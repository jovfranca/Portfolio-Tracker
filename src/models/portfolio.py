import pandas as pd

class Portfolio:
    def __init__(self):
        self.transactions_data_filename="src/db/transactions.pkl"
        self.transactions_df = self.load_transactions()

        self.assets_data_filename="src/db/assets.pkl"
        self.assets_df = pd.DataFrame(columns = [
                "Asset Class", "Ticker", "Sector", "Sub-sector", "Average Cost", "Quantity", "Current Price"
            ])

    def load_transactions(self):
        try:
            return pd.read_pickle(self.transactions_data_filename)
        except FileNotFoundError:
            return pd.DataFrame(columns=[
                "ID", "Date-Time", "Type", "Asset",
                "Broker", "Allocation Class", "Quantity", "Price", "Brokerage Fee", "Other Fees", "Notes"
            ])
        
    # def load_assets(self):
    #     try:
    #         return pd.read_pickle(self.assets_data_filename)
    #     except FileNotFoundError:
    #         return pd.DataFrame(columns = [
    #             "Asset Class", "Ticker", "Sector", "Sub-sector", "Average Cost", "Quantity", "Current Price"
    #         ])

    def add_transaction(self, transaction):
        """
        Adds a new transaction to the portfolio's transactions DataFrame and updates the storage file.

        This method takes a transaction object, converts it into a DataFrame row, and appends it to the
        existing transactions DataFrame. It then sorts the DataFrame based on the 'Date-Time' column to
        maintain chronological order. After updating the DataFrame, it saves the new DataFrame to a pickle
        file specified by 'self.transactions_data_filename'. Finally, it prints the updated DataFrame.

        Parameters:
            transaction (Transaction): An object representing a financial transaction, which contains
                                    attributes like ID, date-time, type, asset, broker, allocation class,
                                    quantity, price, brokerage fee, other fees, and notes.

        Raises:
            FileNotFoundError: If the pickle file specified by 'self.transactions_data_filename' does not exist.
            ValueError: If the transaction object has missing or invalid attributes.
        """

        # Convert the transaction instance into a DataFrame
        transaction_data = {
            "ID": [transaction.id],
            "Date-Time": [transaction.date_time],
            "Type": [transaction.type],
            "Asset": [transaction.asset],
            "Broker": [transaction.broker],
            "Allocation Class": [transaction.allocation_class],
            "Quantity": [transaction.quantity],
            "Price": [transaction.price],
            "Brokerage Fee": [transaction.brokerage_fee],
            "Other Fees": [transaction.other_fees],
            "Notes": [transaction.notes]
        }
        transaction_df = pd.DataFrame(transaction_data)
        
        # Append the new transaction DataFrame to the existing transactions DataFrame
        self.transactions_df = pd.concat([self.transactions_df, transaction_df], ignore_index=True)

        # Sort the transactions DataFrame by date-time
        self.transactions_df.sort_values(by="Date-Time", inplace=True)
        
        # Save the updated DataFrame to a file
        self.transactions_df.to_pickle(self.transactions_data_filename)

        # Print dataframe
        print(self.transactions_df)

    def update_assets(self):
        """
        Updates the assets DataFrame with the latest transactions.

        This method iterates over each transaction in the transactions DataFrame. If the asset
        from a transaction does not exist in the assets DataFrame, it adds a new entry with the
        transaction details. If the asset exists, it updates the 'Average Cost' and 'Quantity'
        based on the transaction type ('Buy' or 'Sell'). If the quantity of an asset reaches zero,
        it sets the 'Average Cost' to zero. Finally, it saves the updated assets DataFrame to a
        pickle file and prints it.

        The method assumes that 'self.transactions_df' and 'self.assets_df' are already defined
        Pandas DataFrames with specific columns.

        Raises:
            FileNotFoundError: If the pickle file for assets does not exist.
        """
        self.assets_df = pd.DataFrame(columns = [
                "Asset Class", "Ticker", "Sector", "Sub-sector", "Average Cost", "Quantity", "Current Price"
            ])
        
        for index, transaction in self.transactions_df.iterrows():
            if not self.assets_df["Ticker"].str.contains(transaction["Asset"]).any():
                asset_data = {
                    "Asset Class": [""],
                    "Ticker": [transaction["Asset"]],
                    "Sector": [""],
                    "Sub-sector": [""],
                    "Average Cost": [transaction["Price"]],
                    "Quantity": [transaction["Quantity"]],
                    "Current Price": [""],
                }
                assets_df = pd.DataFrame(asset_data)

                # Append the new asset DataFrame to the existing transactions DataFrame
                if not assets_df.dropna(how='all').empty:
                    self.assets_df = pd.concat([self.assets_df, assets_df], ignore_index=True)

            else:
                # Search for the row that contains the ticker and creates a mask
                mask = self.assets_df["Ticker"].str.contains(transaction["Asset"])

                if transaction["Type"] == "Buy":
                    self.assets_df.loc[mask, "Average Cost"] = (self.assets_df.loc[mask, "Average Cost"]*self.assets_df.loc[mask, "Quantity"] + transaction["Price"]*transaction["Quantity"])/(self.assets_df.loc[mask, "Quantity"] + transaction["Quantity"])
                    self.assets_df.loc[mask, "Quantity"] = self.assets_df.loc[mask, "Quantity"] + transaction["Quantity"]
                elif transaction["Type"] == "Sell":
                    self.assets_df.loc[mask, "Quantity"] = self.assets_df.loc[mask, "Quantity"] - transaction["Quantity"]
                    if self.assets_df.loc[mask, "Quantity"].all() == 0:
                        self.assets_df.loc[mask, "Average Cost"] = 0
        # Save the updated DataFrame to a file
        self.assets_df.to_pickle(self.assets_data_filename)

        # Print dataframe
        print(self.assets_df)


    def calculate_total_value(self):
        # Calculate the total value of the portfolio (sum of asset values)
        # Implement your logic here
        pass