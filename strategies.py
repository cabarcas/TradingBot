import logging
from typing import *

import pandas as pd

from models import *

logger = logging.getLogger()

TF_EQUIV = {"1m": 60, "5m": 300, "15m": 900, "30m": 900, "1h": 3600, "4h": 14400}


class Strategy:
    def __init__(self, contract: Contract, exchange: str, timeframe: str, balance_pct: float, take_profit: float,
                 stop_loss: float):
        self.contract = contract
        self.exchange = exchange
        self.tf = timeframe
        self.tf_equiv = TF_EQUIV[timeframe] * 1000
        self.balance_pct = balance_pct
        self.take_profit = take_profit
        self.stop_loss = stop_loss

        self.candles: List[Candle] = []

    # 3 cases: update same current candle, new candle, new candle + missing candles
    # by comparing the timestamp of the new trade with the timestamp of the most recent candle we have recorded
    def parse_trades(self, price: float, size: float, timestamp: int) -> str:

        last_candle = self.candles[-1]

        # Same Candle: update same current candle
        if timestamp < last_candle.timestamp + self.tf_equiv:

            last_candle.close = price
            last_candle.volume += size

            if price > last_candle.high:
                last_candle.high = price
            elif price < last_candle.low:
                last_candle.low = price

            return "same_candle"

        # Missing Candle(s)
        elif timestamp >= last_candle.timestamp + 2 * self.tf_equiv:

            missing_candles = int((timestamp - last_candle.timestamp) / self.tf_equiv) - 1

            logger.info("%s missing %s candles for %s %s (%s %s)", self.exchange, missing_candles, self.contract.symbol,
                        self.tf, timestamp, last_candle.timestamp)
            # adding number of missing candles to the candle list
            for missing in range(missing_candles):
                new_ts = last_candle.timestamp + self.tf_equiv
                candle_info = {'ts': new_ts, 'open': last_candle.close, 'high': last_candle.close,
                               'low': last_candle.close, 'close': last_candle.close, 'volume': 0}
                new_candle = Candle(candle_info, self.tf, "parse_trade")

                self.candles.append(new_candle)

                last_candle = new_candle

            new_ts = last_candle.timestamp + self.tf_equiv
            candle_info = {'ts': new_ts, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': size}
            new_candle = Candle(candle_info, self.tf, "parse_trade")

            self.candles.append(new_candle)

            return "new_candle"

        # New Candle
        elif timestamp >= last_candle.timestamp + self.tf_equiv:
            new_ts = last_candle.timestamp + self.tf_equiv
            candle_info = {'ts': new_ts, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': size}
            new_candle = Candle(candle_info, self.tf, "parse_trade")

            self.candles.append(new_candle)

            logger.info("%s New candle for %s %s", self.exchange, self.contract.symbol, self.tf)

            return "new_candle"


# we will use candlesticks to calculate indicators: macd and rsi
class TechnicalStrategy(Strategy):
    def __init__(self, contract: Contract, exchange: str, timeframe: str, balance_pct: float, take_profit: float,
                 stop_loss: float, other_params: Dict):
        super().__init__(contract, exchange, timeframe, balance_pct, take_profit, stop_loss)

        self._ema_fast = other_params['ema_fast']
        self._ema_slow = other_params['ema_slow']
        self._ema_signal = other_params['ema_signal']

        # print("Activated strategy for ", contract.symbol)
        self._rsi_length = other_params['rsi_length']

    # relative strength index
    def _rsi(self):
        close_list = []
        for candle in self.candles:
            close_list.append(candle.close)
        # we'll need RSI periods or number of candles used to calculate the RSI.
        closes = pd.Series(close_list)

        # we need to calculate average gain and loss over the period.
        # 42 07:42 formula & calculation
        return

    # moving average convergence-divergence in 4 steps:
    # 1. Fast EMA calculation
    # 2. Slow EMA calculation
    # 3. Fast EMA - Slow EMA
    # 4. EMA on the result of step 3
    # we'll need a list of EMAS, each corresponding to each candlestick recorded
    # we only need to compute the EMA based on the close price of each candle
    # also we will provide a list of close prices of our candles
    def _macd(self) -> Tuple[float, float]:
        close_list = []
        for candle in self.candles:
            close_list.append(candle.close)
        # we use pandas to work with Dataframes or time series since candles can be represented as time series
        # each row is a new timestamp and columns represent open, high, low and close price
        # we convert the list of close prices to a pandas series object
        closes = pd.Series(close_list)
        # we calculate the EMA of a series using ewm (Exponential Weighted Functions) then the mean with mean method
        # span is the period chosen
        ema_fast = closes.ewm(span=self._ema_fast).mean()
        ema_slow = closes.ewm(span=self._ema_slow).mean()

        macd_line = ema_fast - ema_slow
        # we will calculate when there is a new candle, since we're interested in the last finished candle
        # the signal will depend on whether the macd line is above or below the macd signal line.
        # a long signal when the macd line goes above the signal line
        # returning a tuple of 2 elements: macd line  and macd signal of the previous candle
        macd_signal = macd_line.ewm(span=self._ema_signal).mean()

        return macd_line[-2], macd_signal[-2]

    def _check_signal(self):

        macd_line, macd_signal = self._macd()

class BreakoutStrategy(Strategy):
    def __init__(self, contract: Contract, exchange: str, timeframe: str, balance_pct: float, take_profit: float,
                 stop_loss: float, other_params: Dict):
        super().__init__(contract, exchange, timeframe, balance_pct, take_profit, stop_loss)

        self._min_volume = other_params['min_volume']

    # check signal to enter long or short trade or do nothing, returning 1 = long, -1 = short and 0 no signal
    def _check_signal(self) -> int:

        # current candle volume must be more than the minimun volumen parameter input
        if self.candles[-1].close > self.candles[-2].high and self.candles[-1].volume > self._min_volume:
            return 1
        if self.candles[-1].close < self.candles[-2].low and self.candles[-1].volume > self._min_volume:
            return -1
        else:
            return 0
        # logic useful for implementing inside bar or outside bar patterns
