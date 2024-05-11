import pandas as pd
from datetime import datetime

from django.db import models

class Position(models.Model):
    """
    A class used to represent an investment position. An investment position is defined by unique assets, brokers and allocation classes.

    Attributes:
    ----------
    allocation_class (str): The allocation class of the position.
    asset (str): The asset associated with the position.
    broker (str): The broker through which the position is held.
    average_cost (float): The average cost per unit of the asset.
    quantity (int): The quantity of the asset held.
    total_value (float): The total value of the position.
    profitability_data (pd.DataFrame): DataFrame to store historical profitability data.
    current_total_gain (float): The current total gain of the position.
    current_accumulated_profitability (float): The current accumulated profitability percentage.

    Methods:
    -------
    update_average_cost(portfolio): Updates the average cost based on transactions in the portfolio.
    update_quantity(portfolio): Updates the quantity based on transactions in the portfolio.
    update_total_value(portfolio): Calculates the total value of the position.
    update_historical_profitability(portfolio): Calculates historical profitability data.
    update_current_profitability(): Updates the current profitability based on the updated historical profitability data.

    """

    def __init__(self, allocation_class, asset, broker):
        self.allocation_class = allocation_class
        self.asset = asset
        self.broker = broker
        self.average_cost = 0.0
        self.quantity = 0
        self.total_value = 0.0
        self.profitability_data = pd.DataFrame(columns=['Unrealized Gain', 'Realized Gain', 'Total Gain', 'Accumulated Profitability %', 'Daily Profitability %'])
        self.current_total_gain = 0
        self.current_accumulated_profitability = 0

    def __str__(self):
        # return f"Position(Allocation Class: {self.allocation_class}, Asset: {self.asset}, Broker: {self.broker}, Average Cost: {self.average_cost}, Quantity: {self.quantity}, Total Value: {self.total_value})"
        return f"{self.allocation_class}\t\t {self.asset}\t {self.broker}\t\t {self.average_cost:.2f}\t\t {self.quantity}\t\t {self.total_value:.2f}\t {self.current_total_gain:.2f}\t\t {self.current_accumulated_profitability:.2f}\%"


    def update_average_cost(self, portfolio):
        average_cost = 0.0
        total_quantity = 0

        # Iterate over the transactions and update the total cost and quantity
        for transaction in portfolio.transactions_list:
            if transaction.asset == self.asset and transaction.allocation_class == self.allocation_class and transaction.broker == self.broker:
                if transaction.type == 'Buy':
                    average_cost = (average_cost*total_quantity + transaction.price*transaction.quantity)/(total_quantity + transaction.quantity)
                    total_quantity += transaction.quantity
                    # total_cost += transaction.price * transaction.quantity
                    # total_quantity += transaction.quantity
                elif transaction.type == 'Sell' and total_quantity > 0:
                    total_quantity -= transaction.quantity  

        # Update the average cost if there are any holdings
        if total_quantity > 0:
            self.average_cost = average_cost
            # self.average_cost = total_cost / total_quantity
        else:
            self.average_cost = 0.0
        pass

    def update_quantity(self, portfolio):
        self.quantity = 0

        # Iterate over the transactions and update the quantity
        for transaction in portfolio.transactions_list:
            if transaction.asset == self.asset and transaction.allocation_class == self.allocation_class and transaction.broker == self.broker:
                if transaction.type == 'Buy':
                    self.quantity += transaction.quantity
                elif transaction.type == 'Sell':
                    self.quantity -= transaction.quantity
                    # Ensure quantity doesn't go negative
                    self.quantity = max(self.quantity, 0)
        pass

    def update_total_value(self, portfolio):
        # Calculate the total value of the position
        for asset in portfolio.assets_list:
            if asset.ticker == self.asset:
                self.total_value = asset.current_price * self.quantity

    def update_historical_profitability(self, portfolio):
        # Initialize a DataFrame to store daily profitability
        asset = next((a for a in portfolio.assets_list if a.ticker == self.asset), None)

        self.profitability_data = pd.DataFrame(index=asset.history.index, columns=['Unrealized Gain', 'Realized Gain', 'Total Gain', 'Accumulated Profitability %', 'Daily Profitability %'], dtype=float)

        # Initialize variables to track the state of the position
        total_quantity = 0
        average_cost = 0
        realized_gain = 0
        initial_investment = 0


        # Iterate over each day in the asset's history
        for date in asset.history.index:
            # Get the closing price for the day
            closing_price = asset.history.loc[date, 'Close']

            # Convert the current date in the loop to string format
            current_date_str = date.strftime("%Y-%m-%d")

            # Process transactions up to the current date
            for transaction in portfolio.transactions_list:
                
                # Convert the transaction date to string format
                transaction_date_str = datetime.strptime(transaction.date_time, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")

                if transaction_date_str == current_date_str and transaction.asset == asset.ticker and transaction.allocation_class == self.allocation_class and transaction.broker == self.broker:
                    if transaction.type == 'Buy':
                        average_cost = (average_cost*total_quantity + transaction.price*transaction.quantity)/(total_quantity + transaction.quantity)
                        total_quantity += transaction.quantity
                        initial_investment += transaction.quantity * transaction.price
                    elif transaction.type == 'Sell':
                        # Calculate realized gain
                        realized_gain += (transaction.price - average_cost) * transaction.quantity
                        # Update the cost basis and quantity held
                        total_quantity -= transaction.quantity
                        
            # Calculate unrealized gain for the day
            unrealized_gain = (closing_price - average_cost)*total_quantity 
            
            # Update the daily profitability DataFrame
            self.profitability_data.loc[date, 'Unrealized Gain'] = unrealized_gain
            self.profitability_data.loc[date, 'Realized Gain'] = realized_gain
            self.profitability_data.loc[date, 'Total Gain'] = unrealized_gain + realized_gain

            # Calculate the accumulated percentage profitability
            if initial_investment > 0:
                self.profitability_data.loc[date, 'Accumulated Profitability %'] = ((unrealized_gain + realized_gain) / initial_investment) * 100

            # Calculate the daily percentage profitability
            if date != asset.history.index[0]:  # Skip the first day as there's no previous day to compare
                previous_dates = asset.history.index[asset.history.index < date]
                if not previous_dates.empty:
                    previous_date = previous_dates.max()
                    previous_total_value = self.profitability_data.loc[previous_date, 'Total Gain']
                    if previous_total_value != 0:  # Check to avoid division by zero
                        daily_profitability_percent = ((self.profitability_data.loc[date, 'Total Gain'] - previous_total_value) / previous_total_value) * 100
                        self.profitability_data.loc[date, 'Daily Profitability %'] = daily_profitability_percent
                    else:
                        self.profitability_data.loc[date, 'Daily Profitability %'] = 0  # or NaN, or some other appropriate value
                else:
                    self.profitability_data.loc[date, 'Daily Profitability %'] = 0  # or NaN, or some other appropriate value

    def update_current_profitability(self):
        # Get the last 'Total Gain' and 'Accumulated Profitability %' value from the profitability DataFrame
        self.current_total_gain = self.profitability_data['Total Gain'].iloc[-1]
        self.current_accumulated_profitability = self.profitability_data['Accumulated Profitability %'].iloc[-1]
