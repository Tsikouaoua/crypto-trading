# crypto-trading

We are having the strategy of crowd short, which means we are basically expecting the market to go against the majority of traders and liquidated them and we are betting on that outcome.

The first line of filters are from Binance futures: top Trader long/short (accounts), top trader long/short(positions), long/short ratio 
We want the middle on to be at least above long 45% and the corners to be above 62% short, the OI should be bigger than 4 mill
We also draw volume the 24h and the 2h candle per draw

Next step is to check the risk of the trade 
