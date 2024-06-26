import yfinance as yf
import pandas as pd
from datetime import timezone
from datetime import datetime

class Asset:
    """
    Represents an asset within an investment portfolio.

    This class encapsulates the details of a financial asset, including its classification,
    ticker symbol, sector, sub-sector, average cost, quantity, and current price. It provides
    methods to update the average cost and quantity of the asset based on transactions.

    Attributes:
    -----------
        asset_class (str): The classification of the asset (e.g., 'Stock', 'Bond').
        ticker (str): The ticker symbol representing the asset.
        sector (str): The sector to which the asset belongs.
        sub_sector (str): The sub-sector within the main sector.
        average_cost (float): The average cost of the asset.
        quantity (int): The quantity of the asset held.
        current_price (float): The current market price of the asset.
        history (df): The historical closing price, dividends and stock splits information.
        total_value(float): The total value owned.

    Methods:
    --------
        update_average_cost(portfolio): Updates the average cost of the asset based on the transactions in the given portfolio.
        update_quantity(portfolio): Updates the quantity of the asset based on the transactions in the given portfolio.
        update_history(oldest_transaction_date): Update the asset historical data for closing price, dividends and stock splits.
        update_current_price(): Update the current asset price based on updated historical data.
        update_total_value(): Update the current total value owned based on current price and quantity held.
    """


    def __init__(self, asset_class, ticker, sector, sub_sector):
        self.asset_class = asset_class
        self.ticker = ticker
        self.sector = sector
        self.sub_sector = sub_sector
        self.average_cost = 0.0
        self.quantity = 0
        self.current_price = 0.0
        self.history = pd.DataFrame(columns=['Close', 'Dividends', 'Stock Splits'])
        self.total_value = 0.0

    def __str__(self):
        return f"{self.ticker}\t{self.quantity}\t\t{self.average_cost:.2f}\t\t{self.current_price:.2f}\t\t{self.total_value:.2f}"

    def update_average_cost(self, portfolio):
        average_cost = 0.0
        total_quantity = 0

        # Iterate over the transactions and update the total cost and quantity
        for transaction in portfolio.transactions_list:
            if transaction.asset == self.ticker:
                if transaction.type == 'Buy':
                    average_cost = (average_cost*total_quantity + transaction.price*transaction.quantity)/(total_quantity + transaction.quantity)
                    total_quantity += transaction.quantity
                elif transaction.type == 'Sell' and total_quantity > 0:
                    total_quantity -= transaction.quantity

        # Update the average cost if there are any holdings
        if total_quantity > 0:
            self.average_cost = average_cost
        else:
            self.average_cost = 0.0
        pass

    def update_quantity(self, portfolio):
        self.quantity = 0

        # Iterate over the transactions and update the quantity
        for transaction in portfolio.transactions_list:
            if transaction.asset == self.ticker:
                if transaction.type == 'Buy':
                    self.quantity += transaction.quantity
                elif transaction.type == 'Sell':
                    self.quantity -= transaction.quantity
                    # Ensure quantity doesn't go negative
                    self.quantity = max(self.quantity, 0)
        pass

    def check_for_income(self):
        # Check if the asset generates income (e.g., dividends)
        # Implement your logic here
        pass



    def update_history(self, oldest_transaction_date):
        # Check if self.history is empty or find the last date with available data
        if self.history.empty:
            # If empty, find the oldest transaction date
            start_date = oldest_transaction_date
            asset_up_to_date = False
        else:
            # If not empty, get the first and last date with data
            first_date = self.history.index.min()
            last_date = self.history.index.max()

            

            # Verify if there was inputed a transaction older than the first available data, if so, it'll request older data
            if oldest_transaction_date.strftime('%Y-%m-%d') < first_date.strftime('%Y-%m-%d'):
                start_date = oldest_transaction_date
                asset_up_to_date = False
            else:
                start_date = last_date + pd.Timedelta(days=1)

                #If there is already data for current day, it won't be requested anymore
                asset_up_to_date = True if last_date.strftime('%Y-%m-%d') == datetime.today().strftime('%Y-%m-%d') else False

            

        if not asset_up_to_date:
            new_data = yf.Ticker(self.ticker).history(start=start_date.strftime('%Y-%m-%d'),interval="1d")
            new_data = new_data[['Close', 'Dividends', 'Stock Splits']]

            # Verify if there was inputed a transaction older than the first available data, if so, proceed to replace the entire data
            if not self.history.empty:
                if oldest_transaction_date.strftime('%Y-%m-%d') < first_date.strftime('%Y-%m-%d'):
                    self.history = new_data
                else:
                    self.history = pd.concat([self.history,new_data])
            else:
                self.history = new_data

            self.history = self.history[~self.history.index.duplicated(keep='first')]

    def update_current_price(self):
        # Check if the history DataFrame is not empty
        if not self.history.empty:
            # Get the last 'Close' value from the history DataFrame
            self.current_price = self.history['Close'].iloc[-1]
        else:
            # If history is empty, fetch the current price from yfinance
            self.current_price = yf.Ticker(self.ticker).info['regularMarketPrice']

    def update_total_value(self):
        # Calculate the total value of the asset
        self.total_value = self.current_price * self.quantity

    def update_profitability(self):
        # Calculate and update the profitability (gain/loss percentage)
        # Implement your logic here
        pass