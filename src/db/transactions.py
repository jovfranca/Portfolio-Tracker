import pandas as pd

class TransactionRecords:
    def __init__(self, filename="src/db/transactions.pkl"):
        self.filename = filename
        self.transactions_df = self.load_transactions()

    def load_transactions(self):
        try:
            return pd.read_pickle(self.filename)
        except FileNotFoundError:
            return pd.DataFrame(columns=[
                "Date-Time", "Transaction Type", "Asset Class", "Asset",
                "Broker", "Amount", "Price", "Brokerage Fee", "Other Fees"
            ])

    def add_transaction(self, date_time, transaction_type, asset_class, asset, broker, amount, price, brokerage_fee, other_fees):
        new_row = {
            "Date-Time": date_time,
            "Transaction Type": transaction_type,
            "Asset Class": asset_class,
            "Asset": asset,
            "Broker": broker,
            "Amount": amount,
            "Price": price,
            "Brokerage Fee": brokerage_fee,
            "Other Fees": other_fees
        }
        self.transactions_df = pd.concat([self.transactions_df, pd.DataFrame([new_row])], ignore_index=True)
        self.transactions_df.sort_values(by="Date-Time", inplace=True)

    def save_transactions(self):
        self.transactions_df.to_pickle(self.filename)