import pandas as pd
import pickle
from datetime import datetime
from src.models.asset import Asset
from src.models.position import Position

class Portfolio:
    """
    A class used to represent an investment portfolio, which includes methods for managing transactions, positions and assets.

    Attributes:
    ----------
        transactions_data_filename (str): The file path for storing transaction data in pickle format.
        transactions_list (list): A list of transaction objects loaded from the pickle file.
        positions_data_filename (str):  The file path for storing positions data in pickle format.
        positions_list (list): A list of positions objects loaded from the pickle file.
        assets_data_filename (str): The file path for storing asset data in pickle format.
        assets_list (list): A list of asset objects loaded from the pickle file.

    Methods:
    -------
        load_transactions(): Loads the list of transaction objects from the pickle file.
        load_positions(): Loads the list of positions objects from the pickle file.
        load_assets(): Loads the list of asset objects from the pickle file.
        add_transaction(transaction): Adds a new transaction to the transactions list and updates the pickle file.
        update_positions(): Iterates over the transactions to update the positions list and serializes it to the pickle file.
        update_assets(): Iterates over the transactions to update the assets list and serializes it to the pickle file.
        print_transactions(): Output on the terminal the transactions list
        get_oldest_transaction_date(): Get the date of the oldested transaction recorded
    
    """


    def __init__(self):
        self.transactions_data_filename="src/db/transactions.pkl"
        self.transactions_list = self.load_transactions()

        self.positions_data_filename="src/db/positions.pkl"
        self.positions_list = self.load_positions()

        self.assets_data_filename="src/db/assets.pkl"
        self.assets_list = self.load_assets()

    def load_transactions(self):
        try:
            with open(self.transactions_data_filename, 'rb') as file:
                return pickle.load(file)
        except FileNotFoundError:
            return []
        
    def load_positions(self):
        try:
            with open(self.positions_data_filename, 'rb') as file:
                return pickle.load(file)
        except FileNotFoundError:
            return []
        
    def load_assets(self):
        try:
            with open(self.assets_data_filename, 'rb') as file:
                return pickle.load(file)
        except FileNotFoundError:
            return []

    def add_transaction(self, transaction):
        # Load the existing transactions list
        self.transactions_list = self.load_transactions()

        # Append the new transaction to the list
        self.transactions_list.append(transaction)

        # Sort the transactions list by the 'date_time' attribute
        self.transactions_list.sort(key=lambda x: datetime.strptime(x.date_time, "%Y-%m-%d %H:%M:%S"))
        
        with open(self.transactions_data_filename, 'wb') as file:
            pickle.dump(self.transactions_list, file)

    def update_positions(self):
        # Load the existing positions list
        self.positions_list = self.load_positions()

        # Iterate over the transactions to update the positions
        for transaction in self.transactions_list:
            # Check if the position already exists in the positions list
            position = next((p for p in self.positions_list if (p.asset == transaction.asset and p.allocation_class == transaction.allocation_class and p.broker == transaction.broker)), None)
            
            if position is None:
                # If the position does not exist, create a new Position instance
                position = Position(transaction.allocation_class, transaction.asset, transaction.broker)
                self.positions_list.append(position)

        # Sort the positions list by allocation class and ticker
        self.positions_list.sort(key=lambda p: (p.allocation_class, p.asset))

        # Iterate over each position to update them
        for position in self.positions_list:
            position.update_average_cost(self)
            position.update_quantity(self)
            position.update_total_value(self)
            position.update_historical_profitability(self)
            position.update_current_profitability()

        # Serialize the updated positions list to the pickle file
        with open(self.positions_data_filename, 'wb') as file:
            pickle.dump(self.positions_list, file)

        # Print the updated list of positions
        print("\n-------------POSITIONS--------------")
        print("Allocation Class\t Asset \t Broker \t Average Cost \t Quantity \t Total Value \t Total Gain \t Acc. Profit (%)")
        for position in self.positions_list:
            print(position)


    def update_assets(self):
        # Load the existing assets list
        self.assets_list = self.load_assets()

        # Iterate over the transactions to update the assets
        for transaction in self.transactions_list:
            # Check if the asset already exists in the assets list
            asset = next((a for a in self.assets_list if a.ticker == transaction.asset), None)
            
            if asset is None:
                # If the asset does not exist, create a new Asset instance
                asset = Asset("", transaction.asset, "", "")
                asset.update_average_cost(self)
                asset.update_quantity(self)
                asset.update_history(self.get_oldest_transaction_date())
                asset.update_current_price()
                asset.update_total_value()
                self.assets_list.append(asset)
            else:
                asset.update_average_cost(self)
                asset.update_quantity(self)
                asset.update_history(self.get_oldest_transaction_date())
                asset.update_current_price()
                asset.update_total_value()

        # Serialize the updated assets list to the pickle file
        with open(self.assets_data_filename, 'wb') as file:
            pickle.dump(self.assets_list, file)

        # Print the updated list of assets
        print("\n-------------ASSETS--------------")
        print(f"Ticker\tQuantity\tAverage Cost\tCurrent Price\tTotal Value")
        for asset in self.assets_list:
            print(asset)

    def print_transactions(self):
        # Print the updated list of transactions
        print("\n-------------TRANSACTIONS--------------")
        print(f"Transaction\tDate-Time\t\tType\tAsset\tBroker\tAllocation Class\tQuantity\tPrice\tBrokerage Fee\tOther Fees\tNotes")

        for t in self.transactions_list:
            print(t)
        
    def get_oldest_transaction_date(self):

        if not self.transactions_list:
            return None  # No transactions available
        return min(datetime.strptime(transaction.date_time, "%Y-%m-%d %H:%M:%S") for transaction in self.transactions_list)

    def calculate_total_value(self):
        # Calculate the total value of the portfolio (sum of asset values)
        # Implement your logic here
        pass