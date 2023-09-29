#
# Copyright 2015 Quantopian, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Zipline: An Algorithmic Trading Library

Packages
--------
zipline.api
    The public API for writing trading algorithms in Zipline.

zipline.pipeline
    An API for filtering and performing computations on large universes
    of securities.

zipline.research
    The public API for working with Zipline in Jupyter notebooks.

Notes
-----
Usage Guide:

* Zipline: https://qrok.it/dl/z/zipline
* Algorithm API: https://qrok.it/dl/z/zipline-algo
* Pipeline API: https://qrok.it/dl/z/pipeline
* Research API: https://qrok.it/dl/z/zipline-research
"""
import os
import numpy as np

# This is *not* a place to dump arbitrary classes/modules for convenience,
# it is a place to expose the public interfaces.
from zipline.utils.calendar_utils import get_calendar

from . import data
from . import finance
from . import gens
from . import utils
from ._version import get_versions

# These need to happen after the other imports.
from . algorithm import TradingAlgorithm
from . import api
from zipline import extensions as ext
from zipline.finance.blotter import Blotter

# PERF: Fire a warning if calendars were instantiated during zipline import.
# Having calendars doesn't break anything per-se, but it makes zipline imports
# noticeably slower, which becomes particularly noticeable in the Zipline CLI.
from exchange_calendars.calendar_utils import global_calendar_dispatcher
if global_calendar_dispatcher._calendars:
    import warnings
    warnings.warn(
        "Found ExchangeCalendar instances after zipline import.\n"
        "Zipline startup will be much slower until this is fixed!",
    )
    del warnings
del global_calendar_dispatcher


__version__ = get_versions()['version']
del get_versions

extension_args = ext.Namespace()


def load_ipython_extension(ipython):
    from .__main__ import zipline_magic
    ipython.register_magic_function(zipline_magic, 'line_cell', 'zipline')


if os.name == 'nt':
    # we need to be able to write to our temp directoy on windows so we
    # create a subdir in %TMP% that has write access and use that as %TMP%
    def _():
        import atexit
        import tempfile

        tempfile.tempdir = tempdir = tempfile.mkdtemp()

        @atexit.register
        def cleanup_tempdir():
            import shutil
            shutil.rmtree(tempdir)
    _()
    del _

__all__ = [
    'api',
    'pipeline',
    'research',
    'data',
    'finance',
]


def setup(self, np=np):
    """Lives in zipline.__init__ for doctests."""

    self.old_opts = np.get_printoptions()
    np.set_printoptions(legacy='1.13')

    self.old_err = np.geterr()
    np.seterr(all='ignore')


def teardown(self, np=np):
    """Lives in zipline.__init__ for doctests."""

    np.seterr(**self.old_err)
    np.set_printoptions(**self.old_opts)


del os
del np
