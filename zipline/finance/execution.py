#
# Copyright 2014 Quantopian, Inc.
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
Execution styles (aka order types) for simulations.

Classes
-------
ExecutionStyle
    Base class for order execution styles.

MarketOrder
    Execution style for orders to be filled at current market price.

LimitOrder
    Execution style for orders to be filled at a price equal to or better than
    a specified limit price.

StopOrder
    Execution style representing a market order to be placed if market price
    reaches a threshold.

StopLimitOrder
    Execution style representing a limit order to be placed if market price
    reaches a threshold.

MarketOnOpenOrder
    Execution style for orders to be filled at the open price of the asset's
    first trade on the day the order is filled.

LimitOnOpenOrder
    Execution style for orders to be filled at the open price of the asset's
    first trade on the day the order is filled, at a price equal to or better
    than a specified limit price.

MarketOnCloseOrder
    Execution style for orders to be filled at the close price of the asset's
    last trade on the day the order is filled.

LimitOnCloseOrder
    Execution style for orders to be filled at the close price of the asset's
    last trade on the day the order is filled, at a price equal to or better
    than a specified limit price.

Notes
-----
Usage Guide:

* Placing orders: https://qrok.it/dl/z/zipline-orders
"""
import abc
from typing import Union
from sys import float_info
from six import with_metaclass
from numpy import isfinite
import zipline.utils.math_utils as zp_math
from zipline.errors import BadOrderParameters
from zipline.utils.compat import consistent_round
from zipline.assets import Asset

__all__ = [
    'ExecutionStyle',
    'MarketOrder',
    'LimitOrder',
    'StopOrder',
    'StopLimitOrder',
    'MarketOnOpenOrder',
    'LimitOnOpenOrder',
    'MarketOnCloseOrder',
    'LimitOnCloseOrder',
]

class ExecutionStyle(with_metaclass(abc.ABCMeta)):
    """Base class for order execution styles.
    """

    _exchange = None
    _tif = None

    @abc.abstractmethod
    def get_limit_price(self, is_buy):
        """
        Get the limit price for this order.
        Returns either None or a numerical value >= 0.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_stop_price(self, is_buy):
        """
        Get the stop price for this order.
        Returns either None or a numerical value >= 0.
        """
        raise NotImplementedError

    @property
    def exchange(self):
        """
        The exchange to which this order should be routed.
        """
        return self._exchange

    @property
    def tif(self):
        """
        The time in force for this order.
        """
        return self._tif


class MarketOrder(ExecutionStyle):
    """
    Execution style for orders to be filled at current market price.

    This is the default for orders placed with :func:`~zipline.api.order`.

    Parameters
    ----------
    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.
    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.

    Examples
    --------
    Place a SMART-routed market order using the Adaptive algorithm (Interactive
    Brokers)::

        style = MarketOrder(exchange="SMART", order_params={"AlgoStrategy": "Adaptive"})
        algo.order(asset, 100, style=style)
    """

    def __init__(
        self,
        exchange: str = None,
        order_params: dict[str, Union[str, float, int]] = None
        ):
        self._exchange = exchange
        self.order_params = order_params

    def get_limit_price(self, _is_buy):
        return None

    def get_stop_price(self, _is_buy):
        return None


class LimitOrder(ExecutionStyle):
    """
    Execution style for orders to be filled at a price equal to or better than
    a specified limit price.

    Parameters
    ----------
    limit_price : float
        Maximum price for buys, or minimum price for sells, at which the order
        should be filled.
    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.
    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.

    Examples
    --------
    Place a limit order::

        algo.order(asset, 100, style=LimitOrder(10.0))
    """
    def __init__(
        self,
        limit_price: float,
        asset: Asset = None,
        exchange: str = None,
        order_params: dict[str, Union[str, float, int]] = None
        ):
        check_stoplimit_prices(limit_price, 'limit')

        self.limit_price = limit_price
        self._exchange = exchange
        self.order_params = order_params
        self.asset = asset

    def get_limit_price(self, is_buy):
        return asymmetric_round_price(
            self.limit_price,
            is_buy,
            tick_size=(0.01 if self.asset is None else self.asset.tick_size)
        )

    def get_stop_price(self, _is_buy):
        return None


class StopOrder(ExecutionStyle):
    """
    Execution style representing a market order to be placed if market price
    reaches a threshold.

    Parameters
    ----------
    stop_price : float
        Price threshold at which the order should be placed. For sells, the
        order will be placed if market price falls below this value. For buys,
        the order will be placed if market price rises above this value.
    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.
    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.
    """
    def __init__(
        self,
        stop_price: float,
        asset: Asset = None,
        exchange: str = None,
        order_params: dict[str, Union[str, float, int]] = None
        ):
        check_stoplimit_prices(stop_price, 'stop')

        self.stop_price = stop_price
        self._exchange = exchange
        self.order_params = order_params
        self.asset = asset

    def get_limit_price(self, _is_buy):
        return None

    def get_stop_price(self, is_buy):
        return asymmetric_round_price(
            self.stop_price,
            not is_buy,
            tick_size=(0.01 if self.asset is None else self.asset.tick_size)
        )


class StopLimitOrder(ExecutionStyle):
    """
    Execution style representing a limit order to be placed if market price
    reaches a threshold.

    Parameters
    ----------
    limit_price : float
        Maximum price for buys, or minimum price for sells, at which the order
        should be filled, if placed.
    stop_price : float
        Price threshold at which the order should be placed. For sells, the
        order will be placed if market price falls below this value. For buys,
        the order will be placed if market price rises above this value.
    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.
    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.
    """
    def __init__(
        self,
        limit_price: float,
        stop_price: float,
        asset: Asset = None,
        exchange: str = None,
        order_params: dict[str, Union[str, float, int]] = None
        ):
        check_stoplimit_prices(limit_price, 'limit')
        check_stoplimit_prices(stop_price, 'stop')

        self.limit_price = limit_price
        self.stop_price = stop_price
        self._exchange = exchange
        self.order_params = order_params
        self.asset = asset

    def get_limit_price(self, is_buy):
        return asymmetric_round_price(
            self.limit_price,
            is_buy,
            tick_size=(0.01 if self.asset is None else self.asset.tick_size)
        )

    def get_stop_price(self, is_buy):
        return asymmetric_round_price(
            self.stop_price,
            not is_buy,
            tick_size=(0.01 if self.asset is None else self.asset.tick_size)
        )

class MarketOnOpenOrder(MarketOrder):
    """
    Execution style for orders to be filled at the open price of the asset's
    first trade on the day the order is filled.

    Parameters
    ----------
    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.

    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.

    Examples
    --------
    Place a market-on-open order::

        algo.order(asset, 100, style=MarketOnOpenOrder())
    """

    _tif = "OPG"

class LimitOnOpenOrder(LimitOrder):
    """
    Execution style for orders to be filled at the open price of the asset's
    first trade on the day the order is filled, at a price equal to or better
    than a specified limit price.

    Parameters
    ----------
    limit_price : float
        Maximum price for buys, or minimum price for sells, at which the order
        should be filled.

    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.

    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.

    Examples
    --------
    Place a limit-on-open order::

        algo.order(asset, 100, style=LimitOnOpenOrder(10.0))
    """

    _tif = "OPG"

class MarketOnCloseOrder(MarketOrder):
    """
    Execution style for orders to be filled at the close price of the asset's
    last trade on the day the order is filled.

    Parameters
    ----------
    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.

    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.

    Examples
    --------
    Place a market-on-close order::

        algo.order(asset, 100, style=MarketOnCloseOrder())
    """

    _tif = "CLS"

class LimitOnCloseOrder(LimitOrder):
    """
    Execution style for orders to be filled at the close price of the asset's
    last trade on the day the order is filled, at a price equal to or better
    than a specified limit price.

    Parameters
    ----------
    limit_price : float
        Maximum price for buys, or minimum price for sells, at which the order
        should be filled.

    exchange : str, optional
        The exchange to route the order to. Only applicable to live trading
        and to certain brokers.

    order_params : dict, optional
        Additional broker-specific order parameters to use in live trading.
        Ignored in backtests.

    Examples
    --------
    Place a limit-on-close order::

        algo.order(asset, 100, style=LimitOnCloseOrder(10.0))
    """

    _tif = "CLS"

def asymmetric_round_price(price, prefer_round_down, tick_size, diff=0.95):
    """
    Asymmetric rounding function for adjusting prices to the specified number
    of places in a way that "improves" the price. For limit prices, this means
    preferring to round down on buys and preferring to round up on sells.
    For stop prices, it means the reverse.

    If prefer_round_down == True:
        When .05 below to .95 above a specified decimal place, use it.
    If prefer_round_down == False:
        When .95 below to .05 above a specified decimal place, use it.

    In math-speak:
    If prefer_round_down: [<X-1>.0095, X.0195) -> round to X.01.
    If not prefer_round_down: (<X-1>.0005, X.0105] -> round to X.01.
    """
    precision = zp_math.number_of_decimal_places(tick_size)
    multiplier = int(tick_size * (10 ** precision))
    diff -= 0.5  # shift the difference down
    diff *= (10 ** -precision)  # adjust diff to precision of tick size
    diff *= multiplier  # adjust diff to value of tick_size

    # Subtracting an epsilon from diff to enforce the open-ness of the upper
    # bound on buys and the lower bound on sells.  Using the actual system
    # epsilon doesn't quite get there, so use a slightly less epsilon-ey value.
    epsilon = float_info.epsilon * 10
    diff = diff - epsilon

    # relies on rounding half away from zero, unlike numpy's bankers' rounding
    rounded = tick_size * consistent_round(
        (price - (diff if prefer_round_down else -diff)) / tick_size
    )
    if zp_math.tolerant_equals(rounded, 0.0):
        return 0.0
    return rounded


def check_stoplimit_prices(price, label):
    """
    Check to make sure the stop/limit prices are reasonable and raise
    a BadOrderParameters exception if not.
    """
    try:
        if not isfinite(price):
            raise BadOrderParameters(
                msg="Attempted to place an order with a {} price "
                    "of {}.".format(label, price)
            )
    # This catches arbitrary objects
    except TypeError:
        raise BadOrderParameters(
            msg="Attempted to place an order with a {} price "
                "of {}.".format(label, type(price))
        )

    if price < 0:
        raise BadOrderParameters(
            msg="Can't place a {} order with a negative price.".format(label)
        )
