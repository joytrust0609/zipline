from collections import namedtuple
import errno
import os
import shutil
import warnings

from contextlib2 import ExitStack
import pandas as pd
from zipline.utils.calendar_utils import get_calendar
from toolz import curry, complement, take

from ..adjustments import SQLiteAdjustmentReader, SQLiteAdjustmentWriter
from ..bcolz_daily_bars import BcolzDailyBarReader, BcolzDailyBarWriter
from ..minute_bars import (
    BcolzMinuteBarReader,
    BcolzMinuteBarWriter,
)
from zipline.assets import AssetDBWriter, AssetFinder, ASSET_DB_VERSION
from zipline.utils.cache import (
    dataframe_cache,
    working_dir,
    working_file,
)
from zipline.utils.compat import mappingproxy
from zipline.utils.input_validation import ensure_timestamp, optionally
import zipline.utils.paths as pth
from zipline.utils.preprocess import preprocess

def asset_db_path(bundle_name, timestr, environ=None, db_version=None):
    return pth.data_path(
        asset_db_relative(bundle_name, timestr, db_version),
        environ=environ,
    )


def minute_equity_path(bundle_name, timestr, environ=None):
    return pth.data_path(
        minute_equity_relative(bundle_name, timestr),
        environ=environ,
    )


def daily_equity_path(bundle_name, timestr, environ=None):
    return pth.data_path(
        daily_equity_relative(bundle_name, timestr),
        environ=environ,
    )


def adjustment_db_path(bundle_name, timestr, environ=None):
    return pth.data_path(
        adjustment_db_relative(bundle_name, timestr),
        environ=environ,
    )


def cache_path(bundle_name, environ=None):
    return pth.data_path(
        cache_relative(bundle_name),
        environ=environ,
    )


def adjustment_db_relative(bundle_name, timestr):
    return bundle_name, timestr, 'adjustments.sqlite'


def cache_relative(bundle_name):
    return bundle_name, '.cache'


def daily_equity_relative(bundle_name, timestr):
    return bundle_name, timestr, 'daily_equities.bcolz'


def minute_equity_relative(bundle_name, timestr):
    return bundle_name, timestr, 'minute_equities.bcolz'


def asset_db_relative(bundle_name, timestr, db_version=None):
    db_version = ASSET_DB_VERSION if db_version is None else db_version

    return bundle_name, timestr, 'assets-%d.sqlite' % db_version


def to_bundle_ingest_dirname(ts):
    """Convert a pandas Timestamp into the name of the directory for the
    ingestion.

    Parameters
    ----------
    ts : pandas.Timestamp
        The time of the ingestions

    Returns
    -------
    name : str
        The name of the directory for this ingestion.
    """
    return ts.isoformat().replace(':', ';')


def from_bundle_ingest_dirname(cs):
    """Read a bundle ingestion directory name into a pandas Timestamp.

    Parameters
    ----------
    cs : str
        The name of the directory.

    Returns
    -------
    ts : pandas.Timestamp
        The time when this ingestion happened.
    """
    return pd.Timestamp(cs.replace(';', ':'))


def ingestions_for_bundle(bundle, environ=None):
    return sorted(
        (from_bundle_ingest_dirname(ing)
         for ing in os.listdir(pth.data_path([bundle], environ))
         if not pth.hidden(ing)),
        reverse=True,
    )


RegisteredBundle = namedtuple(
    'RegisteredBundle',
    ['calendar_name',
     'start_session',
     'end_session',
     'minutes_per_day',
     'ingest',
     'create_writers']
)

BundleData = namedtuple(
    'BundleData',
    'asset_finder equity_minute_bar_reader equity_daily_bar_reader '
    'adjustment_reader',
)

BundleCore = namedtuple(
    'BundleCore',
    'bundles register unregister ingest load',
)


class UnknownBundle(LookupError):
    """Raised if no bundle with the given name was registered.
    """
    exit_code = 1

    def __init__(self, name):
        super(UnknownBundle, self).__init__(
            'No bundle registered with the name %r' % name,
        )
        self.name = name

def _make_bundle_core():
    """Create a family of data bundle functions that read from the same
    bundle mapping.

    Returns
    -------
    bundles : mappingproxy
        The mapping of bundles to bundle payloads.
    register : callable
        The function which registers new bundles in the ``bundles`` mapping.
    unregister : callable
        The function which deregisters bundles from the ``bundles`` mapping.
    ingest : callable
        The function which downloads and write data for a given data bundle.
    load : callable
        The function which loads the ingested bundles back into memory.
    """
    _bundles = {}  # the registered bundles
    # Expose _bundles through a proxy so that users cannot mutate this
    # accidentally. Users may go through `register` to update this which will
    # warn when trampling another bundle.
    bundles = mappingproxy(_bundles)

    @curry
    def register(name,
                 f,
                 calendar_name='NYSE',
                 start_session=None,
                 end_session=None,
                 minutes_per_day=390,
                 create_writers=True):
        """Register a data bundle ingest function.

        Parameters
        ----------
        name : str
            The name of the bundle.
        f : callable
            The ingest function. This function will be passed:

              environ : mapping
                  The environment this is being run with.
              asset_db_writer : AssetDBWriter
                  The asset db writer to write into.
              minute_bar_writer : BcolzMinuteBarWriter
                  The minute bar writer to write into.
              daily_bar_writer : BcolzDailyBarWriter
                  The daily bar writer to write into.
              adjustment_writer : SQLiteAdjustmentWriter
                  The adjustment db writer to write into.
              calendar : exchange_calendars.ExchangeCalendar
                  The trading calendar to ingest for.
              start_session : pd.Timestamp
                  The first session of data to ingest.
              end_session : pd.Timestamp
                  The last session of data to ingest.
              cache : DataFrameCache
                  A mapping object to temporarily store dataframes.
                  This should be used to cache intermediates in case the load
                  fails. This will be automatically cleaned up after a
                  successful load.
        calendar_name : str, optional
            The name of a calendar used to align bundle data.
            Default is 'NYSE'.
        start_session : pd.Timestamp, optional
            The first session for which we want data. If not provided,
            or if the date lies outside the range supported by the
            calendar, the first_session of the calendar is used.
        end_session : pd.Timestamp, optional
            The last session for which we want data. If not provided,
            or if the date lies outside the range supported by the
            calendar, the last_session of the calendar is used.
        minutes_per_day : int, optional
            The number of minutes in each normal trading day.
        create_writers : bool, optional
            Should the ingest machinery create the writers for the ingest
            function. This can be disabled as an optimization for cases where
            they are not needed.

        Notes
        -----
        This function my be used as a decorator, for example:

        .. code-block:: python

           @register('quandl')
           def quandl_ingest_function(...):
               ...

        See Also
        --------
        zipline.data.bundles.bundles
        """
        if name in bundles:
            warnings.warn(
                'Overwriting bundle with name %r' % name,
                stacklevel=3,
            )

        # NOTE: We don't eagerly compute calendar values here because
        # `register` is called at module scope in zipline, and creating a
        # calendar currently takes between 0.5 and 1 seconds, which causes a
        # noticeable delay on the zipline CLI.
        _bundles[name] = RegisteredBundle(
            calendar_name=calendar_name,
            start_session=start_session,
            end_session=end_session,
            minutes_per_day=minutes_per_day,
            ingest=f,
            create_writers=create_writers,
        )
        return f

    def unregister(name):
        """Unregister a bundle.

        Parameters
        ----------
        name : str
            The name of the bundle to unregister.

        Raises
        ------
        UnknownBundle
            Raised when no bundle has been registered with the given name.

        See Also
        --------
        zipline.data.bundles.bundles
        """
        try:
            del _bundles[name]
        except KeyError:
            raise UnknownBundle(name)

    def ingest(name,
               environ=os.environ,
               timestamp=None):
        """Ingest data for a given bundle.

        Parameters
        ----------
        name : str
            The name of the bundle.
        environ : mapping, optional
            The environment variables. By default this is os.environ.
        timestamp : datetime, optional
            The timestamp to use for the load.
            By default this is the current time.
        """
        try:
            bundle = bundles[name]
        except KeyError:
            raise UnknownBundle(name)

        calendar = get_calendar(bundle.calendar_name)

        start_session = bundle.start_session
        end_session = bundle.end_session

        if start_session is None or start_session < calendar.first_session:
            start_session = calendar.first_session

        if end_session is None or end_session > calendar.last_session:
            end_session = calendar.last_session

        if timestamp is None:
            timestamp = pd.Timestamp.utcnow()
        timestamp = timestamp.tz_convert('utc').tz_localize(None)

        timestr = to_bundle_ingest_dirname(timestamp)
        cachepath = cache_path(name, environ=environ)
        pth.ensure_directory(pth.data_path([name, timestr], environ=environ))
        pth.ensure_directory(cachepath)
        with dataframe_cache(cachepath, clean_on_failure=False) as cache, \
                ExitStack() as stack:
            # we use `cleanup_on_failure=False` so that we don't purge the
            # cache directory if the load fails in the middle
            if bundle.create_writers:
                wd = stack.enter_context(working_dir(
                    pth.data_path([], environ=environ))
                )
                daily_bars_path = wd.ensure_dir(
                    *daily_equity_relative(name, timestr)
                )
                daily_bar_writer = BcolzDailyBarWriter(
                    daily_bars_path,
                    calendar,
                    start_session,
                    end_session,
                )
                # Do an empty write to ensure that the daily ctables exist
                # when we create the SQLiteAdjustmentWriter below. The
                # SQLiteAdjustmentWriter needs to open the daily ctables so
                # that it can compute the adjustment ratios for the dividends.

                daily_bar_writer.write(())
                minute_bar_writer = BcolzMinuteBarWriter(
                    wd.ensure_dir(*minute_equity_relative(name, timestr)),
                    calendar,
                    start_session,
                    end_session,
                    minutes_per_day=bundle.minutes_per_day,
                )
                assets_db_path = wd.getpath(*asset_db_relative(name, timestr))
                asset_db_writer = AssetDBWriter(assets_db_path)

                adjustment_db_writer = stack.enter_context(
                    SQLiteAdjustmentWriter(
                        wd.getpath(*adjustment_db_relative(name, timestr)),
                        BcolzDailyBarReader(daily_bars_path),
                        overwrite=True,
                    )
                )
            else:
                daily_bar_writer = None
                minute_bar_writer = None
                asset_db_writer = None
                adjustment_db_writer = None

            bundle.ingest(
                environ,
                asset_db_writer,
                minute_bar_writer,
                daily_bar_writer,
                adjustment_db_writer,
                calendar,
                start_session,
                end_session,
                cache,
                pth.data_path([name, timestr], environ=environ),
            )

    def most_recent_data(bundle_name, timestamp, environ=None):
        """Get the path to the most recent data after ``date``for the
        given bundle.

        Parameters
        ----------
        bundle_name : str
            The name of the bundle to lookup.
        timestamp : datetime
            The timestamp to begin searching on or before.
        environ : dict, optional
            An environment dict to forward to zipline_root.
        """
        if bundle_name not in bundles:
            raise UnknownBundle(bundle_name)

        try:
            candidates = os.listdir(
                pth.data_path([bundle_name], environ=environ),
            )
            return pth.data_path(
                [bundle_name,
                 max(
                     filter(complement(pth.hidden), candidates),
                     key=from_bundle_ingest_dirname,
                 )],
                environ=environ,
            )
        except (ValueError, OSError) as e:
            if getattr(e, 'errno', errno.ENOENT) != errno.ENOENT:
                raise
            raise ValueError(
                'no data for bundle {bundle!r} on or before {timestamp}\n'
                'maybe you need to run: $ quantrocket zipline ingest {bundle}'.format(
                    bundle=bundle_name,
                    timestamp=timestamp,
                ),
            )

    def load(name, environ=os.environ, timestamp=None,
            daily_bar_reader_kwargs={}, minute_bar_reader_kwargs={}):
        """Loads a previously ingested bundle.

        Parameters
        ----------
        name : str
            The name of the bundle.
        environ : mapping, optional
            The environment variables. Defaults of os.environ.
        timestamp : datetime, optional
            The timestamp of the data to lookup.
            Defaults to the current time.

        Returns
        -------
        bundle_data : BundleData
            The raw data readers for this bundle.
        """
        if timestamp is None:
            timestamp = pd.Timestamp.utcnow()
        timestr = most_recent_data(name, timestamp, environ=environ)
        return BundleData(
            asset_finder=AssetFinder(
                asset_db_path(name, timestr, environ=environ),
            ),
            equity_minute_bar_reader=BcolzMinuteBarReader(
                minute_equity_path(name, timestr, environ=environ),
                **minute_bar_reader_kwargs
            ),
            equity_daily_bar_reader=BcolzDailyBarReader(
                daily_equity_path(name, timestr, environ=environ),
                **daily_bar_reader_kwargs
            ),
            adjustment_reader=SQLiteAdjustmentReader(
                adjustment_db_path(name, timestr, environ=environ),
            ),
        )

    return BundleCore(bundles, register, unregister, ingest, load)


bundles, register, unregister, ingest, load = _make_bundle_core()

# Help Sphinx autoapi understand these definitions
bundles = bundles
register = register
unregister = unregister
ingest = ingest
load = load