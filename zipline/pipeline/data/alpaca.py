# Copyright 2020 QuantRocket LLC - All Rights Reserved
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

from typing import TYPE_CHECKING
from zipline.utils.numpy_utils import bool_dtype
from zipline.pipeline.data import Column, DataSet
from zipline.pipeline.domain import Domain, US_EQUITIES
if TYPE_CHECKING:
    from zipline.pipeline.data.dataset import BoundBooleanColumn

class ETB(DataSet):
    """
    Dataset representing whether securities are easy-to-borrow
    through Alpaca.

    Attributes
    ----------
    etb : bool
        whether the security is easy-to-borrow

    Notes
    -----
    Usage Guide:

    * Alpaca ETB: https://qrok.it/dl/z/pipeline-alpaca-etb

    Examples
    --------
    Create a Filter that computes True for easy-to-borrow securities::

        are_etb = alpaca.ETB.etb.latest
    """
    domain: Domain = US_EQUITIES
    etb: 'BoundBooleanColumn' = Column(bool_dtype)
    """Whether the security is easy-to-borrow"""
