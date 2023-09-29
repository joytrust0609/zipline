# Copyright 2021 QuantRocket LLC - All Rights Reserved
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

from typing import Sequence
from zipline.pipeline.data import DataSet, Column as _Column, BoundColumn

Column: BoundColumn = _Column # re-export and customize docstring
"""
A Pipeline column representing a single field of a database queryable with
`quantrocket.get_prices`.

Notes
-----
Usage Guide:

* Pipeline databases: https://qrok.it/dl/z/pipeline-db
"""

class Database(DataSet):
    """
    A Pipeline DataSet representing a database queryable with
    `quantrocket.get_prices`.

    This class cannot be used directly. Instead, subclass this class,
    specify the database to query using the CODE attribute, and specify
    one or more columns (`zipline.pipeline.data.Column`) to include in the
    Dataset. See the examples below.

    This DataSet is implemented as a wrapper around `quantrocket.get_prices_reindexed_like`,
    with most DataSet attributes being passed directly to that function.

    Attributes
    ----------
    CODE : str, required
        the database code

    SHIFT : int, optional
        number of periods to shift the resulting data forward to avoid lookahead
        bias. Default is 1. Shifting one period implies that data timestamped to
        a particular date is available and actionable on the following date.

    FFILL : bool, optional
        forward-fill values in the pipeline output so that each date reflects
        the latest available value as of that date. If False, values appear only
        on the first date they were available, followed by NaNs. Default True.

    LOOKBACK_WINDOW : int, optional
        how many calendar days of back data prior to the pipeline start date
        should be loaded, to ensure an adequate cushion of data is available before
        shifting. Default is 10. Sparse data such as fundamentals will require a
        higher value.

    TIMES : list of str (HH:MM:SS), optional
        limit to these times, specified in the timezone of the bundle. Only
        applicable to querying intraday databases. See additional information in the
        Notes section of `quantrocket.get_prices`.

    AGG : str or function, optional
        when querying intraday databases, how to aggregate each day's intraday values to
        produce a single value per day. Default is "last", meaning use the last non-null
        value of each day. This parameter is passed directly to the pandas `agg` function.
        Example choices include "last", "first", "min", "max", "mean", "sum", etc. See
        https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.core.groupby.DataFrameGroupBy.aggregate.html
        for more info. Note that aggregation occurs after the `TIMES` filters are applied.

    CONT_FUT : str, optional
        stitch futures into continuous contracts using this method (default is not
        to stitch together). Only applicable to history databases. Possible choices:
        concat

    DATA_FREQUENCY : str, optional
        for Zipline bundles, whether to query minute or daily data. If omitted,
        defaults to minute data for minute bundles and to daily data for daily bundles.
        This parameter only needs to be set to request daily data from a minute bundle.
        Possible choices: daily, minute (or aliases d, m).

    Notes
    -----
    Because numpy has no native support for integers with missing values, users
    are strongly encouraged to use floats for any data that's semantically
    numeric. Doing so enables the use of `NaN` as a natural missing value,
    which has useful propagation semantics.

    Usage Guide:

    * Pipeline databases: https://qrok.it/dl/z/pipeline-db

    Examples
    --------
    Define a Pipeline dataset that points to a database of custom fundamentals::

        from zipline.pipeline.data.db import Database, Column
        class CustomFundamentals(Database):
            CODE = "custom-fundamentals"
            Revenue = Column(float)
            EPS = Column(float)
            Currency = Column(object)
            TotalAssets = Column(float)

    Instantiate a column from the dataset::

        revenues = CustomFundamentals.Revenue.latest

    Columns can have different data types.Use float for semantically-numeric data,
    even if it's always integral valued (see Notes section below). The default
    missing value for floats is NaN::

        Revenue = Column(float)

    Use object for string columns. The default missing value for object-dtype columns
    is an empty string::

        Currency = Column(object)

    Use bool for boolean-valued flags. Note that the default missing value for
    bool-dtype columns is False::

        IsEtf = Column(bool)
    """
    CODE: str = None
    SHIFT: int = 1
    FFILL: bool = True
    LOOKBACK_WINDOW: int = 10
    TIMES: Sequence[str] = None
    AGG: str = "last"
    CONT_FUT: str = None
    DATA_FREQUENCY: str = None
