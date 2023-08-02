import six

import pandas as pd

from zipline.errors import UnsupportedPipelineOutput
from zipline.utils.input_validation import (
    expect_element,
    expect_types,
    optional,
)

from .domain import Domain, GENERIC, infer_domain
from .graph import ExecutionPlan, TermGraph, SCREEN_NAME
from .filters import (
    Filter,
    SingleAsset,
    StaticAssets,
    StaticSids,
    StaticUniverse,
    ArrayPredicate,
    NumExprFilter,
    Latest as LatestFilter,
    NullFilter,
    NotNullFilter
)
from .classifiers import Latest as LatestClassifier
from .factors import Latest as LatestFactor
from .term import AssetExists, ComputableTerm, Term

def _term_to_prescreen_fielddef(term):
    """
    Tries to convert a term to a prescreen field definition,
    that is, the "fields" key of the prescreen dict.

    Parameters
    ----------
    term : zipline.pipeline.Term

    Returns
    -------
    fielddef : dict or None
    """
    # check if the term is an ArrayPredicate of a SecuritiesMaster column,
    # e.g. SecuritiesMaster.SecType.latest.eq('STK')
    if (isinstance(term, ArrayPredicate)
        and len(term.inputs) == 1
        and isinstance(term.inputs[0], LatestClassifier)
        and len(term.inputs[0].inputs) == 1
        and hasattr(term.inputs[0].inputs[0], "dataset")
        and term.inputs[0].inputs[0].dataset.qualname == "SecuritiesMaster"
        and term.params['op'].__name__ in (
            "eq",
            "isin",
            "ne",
            "has_substring",
            "startswith",
            "endswith",
            "matches",
            )):
        field = term.inputs[0].inputs[0].name
        if term.params['op'].__name__ == "eq":
            op = "eq"
            negate = False
            values = [term.params['opargs'][0]]
        elif term.params['op'].__name__ == "isin":
            op = "eq"
            negate = False
            values = list(term.params['opargs'][0])
        elif term.params['op'].__name__ == "ne":
            op = "eq"
            negate = True
            values = [term.params['opargs'][0]]
        elif term.params['op'].__name__ == "has_substring":
            op = "contains"
            negate = False
            values = term.params['opargs'][0]
        elif term.params['op'].__name__ == "startswith":
            op = "startswith"
            negate = False
            values = term.params['opargs'][0]
        elif term.params['op'].__name__ == "endswith":
            op = "endswith"
            negate = False
            values = term.params['opargs'][0]
        elif term.params['op'].__name__ == "matches":
            op = "match"
            negate = False
            values = term.params['opargs'][0]

        return {"field": field, "op": op, "negate": negate, "values": values}

    # check if the term is a boolean SecuritiesMaster column, e.g.
    # SecuritiesMaster.Etf.latest
    if (isinstance(term, LatestFilter)
        and hasattr(term.inputs[0], "dataset")
        and term.inputs[0].dataset.qualname == "SecuritiesMaster"
        ):
        field = term.inputs[0].name
        op = "eq"
        negate = False
        values = [True]
        return {"field": field, "op": op, "negate": negate, "values": values}

    # check if the term is a NullFilter or NotNullFilter of a SecuritiesMaster
    # column, e.g. SecuritiesMaster.alpaca_AssetId.latest.isnull()
    if (isinstance(term, (NullFilter, NotNullFilter))
        and isinstance(term.inputs[0], (LatestClassifier, LatestFactor))
        and hasattr(term.inputs[0].inputs[0], "dataset")
        and term.inputs[0].inputs[0].dataset.qualname == "SecuritiesMaster"):
        field = term.inputs[0].inputs[0].name
        op = "isnull"
        negate = True if isinstance(term, NotNullFilter) else False
        values = [True]
        return {"field": field, "op": op, "negate": negate, "values": values}

    # isnull() on float columns are handled with a NumExprFilter
    if (isinstance(term, NumExprFilter)
        and term._expr == 'x_0 != x_0'
        and isinstance(term.bindings["x_0"], LatestFactor)
        and len(term.bindings["x_0"].inputs) == 1
        and hasattr(term.bindings["x_0"].inputs[0], "dataset")
        and term.bindings["x_0"].inputs[0].dataset.qualname == "SecuritiesMaster"):
        field = term.bindings["x_0"].inputs[0].name
        op = "isnull"
        negate = False
        values = [True]
        return {"field": field, "op": op, "negate": negate, "values": values}

    return None

def _term_to_prescreen_dict(term, prescreen=None, negate=False):
    """
    Tries to convert a term to a prescreen dict.

    Parameters
    ----------
    term : zipline.pipeline.Term

    prescreen : dict or None
        Existing prescreen dict to update

    negate : bool
        Whether to negate the term. Applies only to fields, not sids.

    Returns
    -------
    prescreen : dict or None

    Notes
    -----
    If a prescreen dict is passed by the new term cannot be converted to a
    prescreen, None is returned.
    """
    prescreen = prescreen or {}

    if isinstance(term, SingleAsset):
        if "sids" not in prescreen:
            prescreen["sids"] = []
        prescreen["sids"].append(term._asset.sid)
        return prescreen

    if isinstance(term, StaticAssets):
        if "sids" not in prescreen:
            prescreen["sids"] = []
        prescreen["sids"].extend(term.params["sids"])
        return prescreen

    # StaticSids and StaticUniverse store real sids in the sids param
    if isinstance(term, (StaticSids, StaticUniverse)):
        if "real_sids" not in prescreen:
            prescreen["real_sids"] = []
        prescreen["real_sids"].extend(term.params["sids"])
        return prescreen

    # check if the term is a negation of a SecuritiesMaster column, e.g.
    # ~SecuritiesMaster.SecType.latest.eq('STK')
    if (
        isinstance(term, NumExprFilter)
        and term._expr == '~x_0'
        ):
        fielddef = _term_to_prescreen_fielddef(term.bindings["x_0"])
        if fielddef is not None:
            # reverse the negate flag since the term has the unary operator
            fielddef["negate"] = True if fielddef["negate"] == False else False
            # negate it back if requested
            if negate:
                fielddef["negate"] = True if fielddef["negate"] == False else False
            if "fields" not in prescreen:
                prescreen["fields"] = []
            prescreen["fields"].append(fielddef)
            return prescreen

    # check if the term is an ArrayPredicate of a SecuritiesMaster column, e.g.
    # SecuritiesMaster.SecType.latest.eq('STK')
    fielddef = _term_to_prescreen_fielddef(term)
    if fielddef is not None:
        # negate if requested
        if negate:
            fielddef["negate"] = True if fielddef["negate"] == False else False
        if "fields" not in prescreen:
            prescreen["fields"] = []
        prescreen["fields"].append(fielddef)
        return prescreen

    return None

class Pipeline(object):
    """
    A Pipeline object represents a collection of named expressions to be
    compiled and executed.

    A Pipeline has two important attributes: 'columns', a dictionary of named
    :class:`~zipline.pipeline.Term` instances, and 'screen', a
    :class:`~zipline.pipeline.Filter` representing criteria for
    including an asset in the results of a Pipeline.

    To compute a pipeline in the context of a TradingAlgorithm, users must call
    ``attach_pipeline`` in their ``initialize`` function to register that the
    pipeline should be computed each trading day. The most recent outputs of an
    attached pipeline can be retrieved by calling ``pipeline_output`` from
    ``handle_data``, ``before_trading_start``, or a scheduled function.

    Parameters
    ----------
    columns : dict, optional
        Initial columns.
    screen : zipline.pipeline.Filter, optional
        Initial screen.

    Notes
    -----
    Usage Guide:

    * Pipeline API: https://qrok.it/dl/z/pipeline
    """
    __slots__ = ('_columns', '_prescreen', '_screen', '_domain', '__weakref__')

    @expect_types(
        columns=optional(dict),
        screen=optional(Filter),
        domain=Domain
    )
    def __init__(
        self,
        columns: dict[str, Term] = None,
        screen: Filter = None,
        domain: Domain = GENERIC
        ):
        if columns is None:
            columns = {}

        validate_column = self.validate_column
        for column_name, term in columns.items():
            validate_column(column_name, term)
            if not isinstance(term, ComputableTerm):
                raise TypeError(
                    "Column {column_name!r} contains an invalid pipeline term "
                    "({term}). Did you mean to append '.latest'?".format(
                        column_name=column_name, term=term,
                    )
                )

        self._columns = columns
        self._prescreen = None
        self._screen = screen
        if screen:
            self._maybe_convert_to_prescreen(screen)
        self._domain = domain

    def _maybe_convert_to_prescreen(self, screen):
        """
        Tries to convert the screen Filter into prescreen parameters.

        Screens filter out rows after the pipeline is computed. As a performance
        optimization, we can alternatively pre-filter the universe before computing
        the pipeline if the screen only includes securities master terms, which
        don't change over time.

        self._prescreen is a dict of asset-level parameters that can be used to
        pre-filter the universe and thus limit the initial workspace size. If
        populated, _prescreen is a dict with the following possible keys:
          - sids: list of zipline sids to include
          - real_sids: list of real sids to include
          - fields: list of dicts with the following keys:
              - field: name of securities master field to filter on
              - op: 'eq', 'contains'
              - negate: whether to negate the filter
              - values: list of values to include or exclude
        """

        # see if the screen contains a single prescreenable term
        prescreen = _term_to_prescreen_dict(screen)
        if prescreen is not None:
            self._prescreen = prescreen
            self._screen = None
            return

        # if the screen is a NumExprFilter, see if it is an ANDed conjunction of
        # prescreenable terms (ORed expressions are not supported)
        elif isinstance(screen, NumExprFilter):

            # ignore parantheses, which don't matter for ANDed expressions
            expr = screen._expr.replace("(", "").replace(")", "")
            # split on AND and see if the resulting terms (possibly ignoring ~)
            # match the screen bindings
            terms = expr.split(" & ")
            if set([term.replace("~", "") for term in terms]) == set(screen.bindings):
                prescreen = {}
                for term in terms:
                    negate = "~" in term
                    term = term.replace("~", "")
                    prescreen = _term_to_prescreen_dict(
                        screen.bindings[term],
                        prescreen=prescreen,
                        negate=negate)
                    # if any term cannot be converted to a prescreen, bail out
                    if not prescreen:
                        break
                else:
                    # didn't break loop, so prescreen is valid
                    self._prescreen = prescreen
                    self._screen = None

    @property
    def columns(self) -> dict[str, Term]:
        """The output columns of this pipeline.

        Returns
        -------
        columns : dict[str, zipline.pipeline.ComputableTerm]
            Map from column name to expression computing that column's output.
        """
        return self._columns

    @property
    def screen(self) -> Filter:
        """
        The screen of this pipeline.

        Returns
        -------
        screen : zipline.pipeline.Filter or None
            Term defining the screen for this pipeline. If ``screen`` is a
            filter, rows that do not pass the filter (i.e., rows for which the
            filter computed ``False``) will be dropped from the output of this
            pipeline before returning results.

        Notes
        -----
        Setting a screen on a Pipeline does not change the values produced for
        any rows: it only affects whether a given row is returned. Computing a
        pipeline with a screen is logically equivalent to computing the
        pipeline without the screen and then, as a post-processing-step,
        filtering out any rows for which the screen computed ``False``.
        """
        return self._screen

    @expect_types(term=Term, name=str)
    def add(
        self,
        term: Term,
        name: str,
        overwrite: bool = False
        ) -> None:
        """Add a column.

        The results of computing ``term`` will show up as a column in the
        DataFrame produced by running this pipeline.

        Parameters
        ----------
        column : zipline.pipeline.Term
            A Filter, Factor, or Classifier to add to the pipeline.
        name : str
            Name of the column to add.
        overwrite : bool
            Whether to overwrite the existing entry if we already have a column
            named `name`.
        """
        self.validate_column(name, term)

        columns = self.columns
        if name in columns:
            if overwrite:
                self.remove(name)
            else:
                raise KeyError("Column '{}' already exists.".format(name))

        if not isinstance(term, ComputableTerm):
            raise TypeError(
                "{term} is not a valid pipeline column. Did you mean to "
                "append '.latest'?".format(term=term)
            )

        self._columns[name] = term

    @expect_types(name=str)
    def remove(self, name: str) -> Term:
        """Remove a column.

        Parameters
        ----------
        name : str
            The name of the column to remove.

        Raises
        ------
        KeyError
            If `name` is not in self.columns.

        Returns
        -------
        removed : zipline.pipeline.Term
            The removed term.
        """
        return self.columns.pop(name)

    @expect_types(screen=Filter, overwrite=(bool, int))
    def set_screen(
        self,
        screen: Filter,
        overwrite: bool = False
        ) -> None:
        """Set a screen on this Pipeline.

        Parameters
        ----------
        filter : zipline.pipeline.Filter
            The filter to apply as a screen.
        overwrite : bool
            Whether to overwrite any existing screen.  If overwrite is False
            and self.screen is not None, we raise an error.
        """
        if (self._screen is not None or self._prescreen is not None) and not overwrite:
            raise ValueError(
                "set_screen() called with overwrite=False and screen already "
                "set.\n"
                "If you want to apply multiple filters as a screen use "
                "set_screen(filter1 & filter2 & ...).\n"
                "If you want to replace the previous screen with a new one, "
                "use set_screen(new_filter, overwrite=True)."
            )
        self._screen = screen
        self._prescreen = None
        self._maybe_convert_to_prescreen(screen)

    def to_execution_plan(
        self,
        domain: Domain,
        default_screen: Filter,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp
        ) -> ExecutionPlan:
        """
        Compile into an ExecutionPlan.

        Parameters
        ----------
        domain : zipline.pipeline.domain.Domain
            Domain on which the pipeline will be executed.
        default_screen : zipline.pipeline.Term
            Term to use as a screen if self.screen is None.
        all_dates : pd.DatetimeIndex
            A calendar of dates to use to calculate starts and ends for each
            term.
        start_date : pd.Timestamp
            The first date of requested output.
        end_date : pd.Timestamp
            The last date of requested output.

        Returns
        -------
        graph : zipline.pipeline.graph.ExecutionPlan
            Graph encoding term dependencies, including metadata about extra
            row requirements.
        """
        if self._domain is not GENERIC and self._domain is not domain:
            raise AssertionError(
                "Attempted to compile Pipeline with domain {} to execution "
                "plan with different domain {}.".format(self._domain, domain)
            )

        return ExecutionPlan(
            domain=domain,
            terms=self._prepare_graph_terms(default_screen),
            start_date=start_date,
            end_date=end_date,
        )

    def to_simple_graph(self, default_screen: Filter) -> TermGraph:
        """
        Compile into a simple TermGraph with no extra row metadata.

        Parameters
        ----------
        default_screen : zipline.pipeline.Term
            Term to use as a screen if self.screen is None.

        Returns
        -------
        graph : zipline.pipeline.graph.TermGraph
            Graph encoding term dependencies.
        """
        return TermGraph(self._prepare_graph_terms(default_screen))

    def _prepare_graph_terms(self, default_screen):
        """Helper for to_graph and to_execution_plan."""
        columns = self.columns.copy()
        screen = self.screen
        if screen is None:
            screen = default_screen
        columns[SCREEN_NAME] = screen
        return columns

    @expect_element(format=('svg', 'png', 'jpeg'))
    def show_graph(self, format: str = 'svg'):
        """
        Render this Pipeline as a DAG.

        Parameters
        ----------
        format : {'svg', 'png', 'jpeg'}
            Image format to render with.  Default is 'svg'.
        """
        g = self.to_simple_graph(AssetExists())
        if format == 'svg':
            return g.svg
        elif format == 'png':
            return g.png
        elif format == 'jpeg':
            return g.jpeg
        else:
            # We should never get here because of the expect_element decorator
            # above.
            raise AssertionError("Unknown graph format %r." % format)

    @staticmethod
    @expect_types(term=Term, column_name=six.string_types)
    def validate_column(column_name, term):
        if term.ndim == 1:
            raise UnsupportedPipelineOutput(column_name=column_name, term=term)

    @property
    def _output_terms(self):
        """
        A list of terms that are outputs of this pipeline.

        Includes all terms registered as data outputs of the pipeline, plus the
        screen, if present.
        """
        terms = list(six.itervalues(self._columns))
        screen = self.screen
        if screen is not None:
            terms.append(screen)
        return terms

    @expect_types(default=Domain)
    def domain(self, default: Domain) -> Domain:
        """
        Get the domain for this pipeline.

        - If an explicit domain was provided at construction time, use it.
        - Otherwise, infer a domain from the registered columns.
        - If no domain can be inferred, return ``default``.

        Parameters
        ----------
        default : zipline.pipeline.domain.Domain
            Domain to use if no domain can be inferred from this pipeline by
            itself.

        Returns
        -------
        domain : zipline.pipeline.domain.Domain
            The domain for the pipeline.

        Raises
        ------
        AmbiguousDomain
        ValueError
            If the terms in ``self`` conflict with self._domain.
        """
        # Always compute our inferred domain to ensure that it's compatible
        # with our explicit domain.
        inferred = infer_domain(self._output_terms)

        if inferred is GENERIC and self._domain is GENERIC:
            # Both generic. Fall back to default.
            return default
        elif inferred is GENERIC and self._domain is not GENERIC:
            # Use the non-generic domain.
            return self._domain
        elif inferred is not GENERIC and self._domain is GENERIC:
            # Use the non-generic domain.
            return inferred
        else:
            # Both non-generic. They have to match.
            if inferred is not self._domain:
                raise ValueError(
                    "Conflicting domains in Pipeline. Inferred {}, but {} was "
                    "passed at construction.".format(inferred, self._domain)
                )
            return inferred
