import pandas as pd

class Portfolio:
    def __init__(self, transactions_data_filename="src/db/transactions.pkl"):
        self.assets = []  # List of Asset instances
        self.transactions = []  # List of Transaction instances
        self.transactions_data_filename=transactions_data_filename
        self.transactions_df = self.load_transactions()

    def load_transactions(self):
        try:
            return pd.read_pickle(self.transactions_data_filename)
        except FileNotFoundError:
            return pd.DataFrame(columns=[
                "ID", "Date-Time", "Type", "Asset",
                "Broker", "Allocation Class", "Quantity", "Price", "Brokerage Fee", "Other Fees", "Notes"
            ])

    def add_transaction(self, transaction):
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

        # Print dataframa
        print(self.transactions_df)

    def save_transactions(self):
        self.transactions_df.to_pickle(self.filename)

    def calculate_total_value(self):
        # Calculate the total value of the portfolio (sum of asset values)
        # Implement your logic here
        pass