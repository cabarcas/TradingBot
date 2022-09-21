import logging
import time
from typing import *

# allows call delay without block open_position execution
from threading import Timer

import pandas as pd

from models import *

if TYPE_CHECKING:
    from connectors.bitmex import BitmexClient
    from connectors.binance_futures import BinanceFuturesClient

logger = logging.getLogger()

TF_EQUIV = {"1m": 60, "5m": 300, "15m": 900, "30m": 900, "1h": 3600, "4h": 14400}


class Strategy:
    def __init__(self, client: Union["BitmexClient", "BinanceFuturesClient"], contract: Contract, exchange: str,
                timeframe: str, balance_pct: float, take_profit: float, stop_loss: float, strat_name):

        self.client = client

        self.contract = contract
        self.exchange = exchange
        self.tf = timeframe
        self.tf_equiv = TF_EQUIV[timeframe] * 1000
        self.balance_pct = balance_pct
        self.take_profit = take_profit
        self.stop_loss = stop_loss

        self.strat_name = strat_name

        self.ongoing_position = False

        self.candles: List[Candle] = []
        self.trades: List[Trade] = []
        self.logs = []

    # add a log message to the log list while showing the same message on the terminal
    def _add_log(self, msg: str):
        logger.info("%s", msg)
        self.logs.append({"log": msg, "displayed": False})

    # 3 cases: update same current candle, new candle, new candle + missing candles
    # by comparing the timestamp of the new trade with the timestamp of the most recent candle we have recorded
    def parse_trades(self, price: float, size: float, timestamp: int) -> str:

        timestamp_diff = int(time.time() * 1000) - timestamp
        if timestamp_diff >= 2000:
            logger.warning("%s %s: %s milliseconds of difference between the current time and the trade time",
                        self.exchange, self.contract.symbol, timestamp_diff)
            # if you see this msg to often means there is something wrong with check_signal that slows websocket updates

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

    def _check_order_status(self, order_id):

        order_status = self.client.get_order_status(self.contract, order_id)

        # request is successful
        if order_status is not None:
            logger.info("%s order status: %s", self.exchange, order_status.status)

        if order_status.status == "filled":
            for trade in self.trades:
                if trade.entry_id == order_id:
                    trade.entry_price = order_status.avg_price
                    break
            return

        t = Timer(2.0, lambda: self._check_order_status(order_id))
        t.start()

    # we write open_position to further our signal processing

    def _open_position(self, signal_result: int):

        # pass the contract, current price, balance percentage parameter
        trade_size = self.client.get_trade_size(self.contract, self.candles[-1].close, self.balance_pct)
        if trade_size is None:
            return

        # we don't log directly instead we make a list of logs and update_ui put them to the logging frame
        order_side = "buy" if signal_result == 1 else "sell"
        position_side = "long" if signal_result == 1 else "short"

        self._add_log(f"{position_side.capitalize()} signal on {self.contract.symbol}{self.tf}")

        order_status = self.client.place_order(self.contract, "MARKET", trade_size, order_side)

        # if condition true the request was successful so the order is placed
        if order_status is not None:
            self._add_log(f"{order_side.capitalize()} order placed on {self.exchange} | {order_status.status}")

            self.ongoing_position = True

            avg_fill_price = None

            # 2 cases: order is immediately executed returning order_status "filled" depending on the exchange
            if order_status.status == "filled":
                avg_fill_price = order_status.avg_price
            # execute get_order_status every to 2 seconds until we get the execution price
            else:
                t = Timer(2.0, lambda: self._check_order_status(order_status.order_id))
                t.start()

            new_trade = Trade({"time": int(time.time() * 1000), "entry_price": avg_fill_price,
                               "contract": self.contract, "strategy": self.strat_name, "side": position_side,
                               "status": "open", "pnl": 0, "quantity": trade_size, "entry_id": order_status.order_id})
            self.trades.append(new_trade)


# we have almost all the info to send a buy or sell order, the signal side.
# we are going to place a market order -so no bid/ask price required at this point.
# if you need bid/ask price you can create an argument in check_signal e.g. bid: float
# the only element still miss is trade size based on a percentage of the account balance
# trade size is calculated differently on each exchange due to the nature of the contract on these platforms
# in each connector we create a get_trade_size() method

class TechnicalStrategy(Strategy):
    def __init__(self, client, contract: Contract, exchange: str, timeframe: str, balance_pct: float,
                 take_profit: float, stop_loss: float, other_params: Dict):
        super().__init__(client, contract, exchange, timeframe, balance_pct, take_profit, stop_loss, "Technical")

        self._ema_fast = other_params['ema_fast']
        self._ema_slow = other_params['ema_slow']
        self._ema_signal = other_params['ema_signal']

        # print("Activated strategy for ", contract.symbol)
        self._rsi_length = other_params['rsi_length']

        # using candlesticks to calculate indicators with 2 indicators rsi and macd

    # relative strength index, formulas:
    # 100 - (100/1 + RS); RS = Relative Strength RS = Average Gain / Average Loss
    def _rsi(self):
        close_list = []
        for candle in self.candles:
            close_list.append(candle.close)
        # we'll need RSI periods or number of candles used to calculate the RSI.
        closes = pd.Series(close_list)
        # we need to calculate average gain and loss over the period to get a pandas series representing the variations,
        # the gains and the losses between each close price, using diff() method.
        # we create two delta series to separate the gains form the losses
        delta = closes.diff().dropna()

        up, down = delta.copy(), delta.copy()
        # filters rows under 0 and keeps the gains only
        up[up < 0] = 0
        # filter rows higher than 0 set them to 0
        down[down > 0] = 0

        # use moving average to calculate the average gains
        avg_gain = up.ewm(com=(self._rsi_length - 1), min_periods=self._rsi_length).mean()
        avg_loss = down.abs().ewm(com=(self._rsi_length - 1), min_periods=self._rsi_length).mean()

        rs = avg_gain / avg_loss

        rsi = 100 - 100 / (1 + rs)
        rsi = rsi.round(2)

        # iloc select data in row number
        return rsi.iloc[-2]

    # moving average convergence-divergence in 4 steps: (EMA = exponential moving average)
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

        return macd_line.iloc[-2], macd_signal.iloc[-2]

    def _check_signal(self):

        macd_line, macd_signal = self._macd()
        rsi = self._rsi()

        # print(rsi, macd_line, macd_signal)

        # if rsi is below 30 (contract is oversold) we have a long signal
        if rsi < 30 and macd_line > macd_signal:
            return 1
        # if rsi is above 70 (contract is overbought) is a short signal
        elif rsi > 70 and macd_line < macd_signal:
            return -1
        else:
            return 0

    # now we're able to calculate if we have a long or short signal for each strategy
    # the questions are: How and When we call check_signal methods.
    # "When" depends on you, want to call it everytime we have a live price update ? is it useful to do so ?
    # want to call it once per candle ? there can be many answers, or you could call it only at some specific time of the day
    # e.g. you noticed that the macd of 8 is a good indicator por the rest of the daily trend

    def check_trade(self, tick_type: str):
        # we compute the indicators and check for a new trade only when there is a new candle
        if tick_type == "new_candle" and not self.ongoing_position:
            signal_result = self._check_signal()

            if signal_result in [-1, 1]:
                self._open_position(signal_result)


class BreakoutStrategy(Strategy):
    def __init__(self, client, contract: Contract, exchange: str, timeframe: str, balance_pct: float,
                 take_profit: float, stop_loss: float, other_params: Dict):
        super().__init__(client, contract, exchange, timeframe, balance_pct, take_profit, stop_loss, "Breakout")

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

    # 43 Adding more conditions for entering a Trade or not 00:03
    # we are able to know if we have long or short signal for each strategy,
    # we need to know who and when are we going a check_signal method

    def check_trade(self, tick_type: str):
        # we compute the indicators and check for a new trade only when there is a new candle
        if not self.ongoing_position:
            signal_result = self._check_signal()

            if signal_result in [-1, 1]:
                self._open_position(signal_result)

    # if check_signal at every trade if the calculations in it are too heavy and there are many trade updates
    # coming through the websocket the updates may start to delay. to fix this we calculate the difference between
    # the current Unix timestamp and the timestamp of the trade when we parse this trade in parse_trades
