import pandas as pd
import pickle
from datetime import datetime
from src.models.asset import Asset

class Portfolio:
    """
    A class used to represent an investment portfolio, which includes methods for managing transactions and assets.

    Attributes:
    ----------
    transactions_data_filename : str
        The file path for storing transaction data in pickle format.
    transactions_list : list
        A list of transaction objects loaded from the pickle file.
    assets_data_filename : str
        The file path for storing asset data in pickle format.
    assets_list : list
        A list of asset objects loaded from the pickle file.

    Methods:
    -------
    load_transactions()
        Loads the list of transaction objects from the pickle file.
    load_assets()
        Loads the list of asset objects from the pickle file.
    add_transaction(transaction)
        Adds a new transaction to the transactions list and updates the pickle file.
    list_assets()
        Iterates over the transactions to update the assets list and serializes it to the pickle file.
    update_asset_list(updated_asset)
        Updates a specific asset in the assets list and serializes the updated list to the pickle file.
    """


    def __init__(self):
        self.transactions_data_filename="src/db/transactions.pkl"
        self.transactions_list = self.load_transactions()

        self.assets_data_filename="src/db/assets.pkl"
        self.assets_list = self.load_assets()

    def load_transactions(self):
        try:
            with open(self.transactions_data_filename, 'rb') as file:
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

        # Print dataframe
        for t in self.transactions_list:
            print(t)
        print("\n")

    def list_assets(self):
        # Load the existing assets list
        self.assets_list = self.load_assets()

        # Iterate over the transactions to update the assets
        for transaction in self.transactions_list:
            # Check if the asset already exists in the assets list
            asset = next((a for a in self.assets_list if a.ticker == transaction.asset), None)
            
            if asset is None:
                # If the asset does not exist, create a new Asset instance
                asset = Asset("", transaction.asset, "", "")
                self.assets_list.append(asset)

        # Serialize the updated assets list to the pickle file
        with open(self.assets_data_filename, 'wb') as file:
            pickle.dump(self.assets_list, file)

        # Print the updated list of assets
        for asset in self.assets_list:
            print(asset)
        print("\n\n")

    def update_asset_list(self, updated_asset):
        # Load the existing assets list
        assets_list = self.load_assets()

        # Find the index of the asset to update
        asset_index = next((index for index, asset in enumerate(assets_list) if asset.ticker == updated_asset.ticker), None)

        # If the asset is found, update it in the list
        if asset_index is not None:
            assets_list[asset_index] = updated_asset

            # Serialize the updated assets list to the pickle file
            with open(self.assets_data_filename, 'wb') as file:
                pickle.dump(assets_list, file)
            return True
        else:
            # Asset not found in the list
            return False

    def calculate_total_value(self):
        # Calculate the total value of the portfolio (sum of asset values)
        # Implement your logic here
        pass