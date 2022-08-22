# 30 Trades Component
# pip install websocket
# pip install websocket-client===0.58.0
# pip install python-dateutil>=2.7.0

# import tkinter as tk
import logging

from connectors.binance_futures import BinanceFuturesClient
from connectors.bitmex import BitmexClient

from interface.root_component import Root


logger = logging.getLogger()

logger.setLevel(logging.INFO)

stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s %(levelname)s :: %(message)s')
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.INFO)

file_handler = logging.FileHandler('info.log')
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)

logger.addHandler(stream_handler)
logger.addHandler(file_handler)

if __name__ == '__main__':
    binance = BinanceFuturesClient("a92e0ce00b1d053bc1e8fdbf6ca9554894084d35f79b859f4e51b26bd4462f99",
                                   "d9eb702c036e07bea81a52bc7f403db0b33fac2c68291cf377ab6bff00ce007a", True)
    bitmex = BitmexClient("NOhUtBbsDMtZkL7nVNdrt7CG", "I8JDSEjDFHQiO30I13pPN4-IdZMJMqTXkRdXZv4_v-Fa0Neg", True)

    # print(bitmex.contracts['XBTUSD'].base_asset, bitmex.contracts['XBTUSD'].price_decimals)
    # Bitmex returns XBt symbol for satoshi instead of XBT symbol for Bitcoin
    # print(bitmex.balances['XBt'].wallet_balance)
    # place an order

    # print(vars(bitmex.place_order(bitmex.contracts['XBTUSD'], "Limit", 100, "Buy", price=20000, tif="GoodTillCancel")))
    # print(vars(bitmex.cancel_order('f7063268-fdff-4764-9dbb-bb36a395e75e')))

    # request historical data for 1 hour example
    # bitmex.get_historical_candles(bitmex.contracts['XBTUSD'],"1h")

    # 21 Solving order price and quantity rounding problems example
    # print(vars(bitmex.place_order(bitmex.contracts['XBTUSD'], "Limit", 100.4, "Buy", price=20000.4939338, tif="GoodTillCancel")))

    # root = tk.Tk()
    root = Root(binance, bitmex)
    root.mainloop()
