import yfinance as yf

ticker = yf.Ticker("AAPL")

# get all stock info
ticker.info

# get historical market data
hist = ticker.history(period="1mo")

print(hist)