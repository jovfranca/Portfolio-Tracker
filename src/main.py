# main.py - Investments Portfolio Tracker

import pandas as pd
from db.transactions import add_transaction

def main():
    # Initialize an empty DataFrame to store transactions
    transactions_df = pd.DataFrame(columns=[
        "Date-Time", "Transaction Type", "Asset Class", "Asset",
        "Broker", "Amount", "Price", "Brokerage Fee", "Other Fees"
    ])

    # Example usage: Add a transaction
    transactions_df = add_transaction(
        transactions_df,
        date_time="2024-05-10 14:30:00",
        transaction_type="buy",
        asset_class="stock",
        asset="AAPL",
        broker="XYZ Brokers",
        amount=100,
        price=150.0,
        brokerage_fee=10.0,
        other_fees=5.0
    )

    transactions_df = add_transaction(
        transactions_df,
        date_time="2024-05-10 14:40:00",
        transaction_type="buy",
        asset_class="stock",
        asset="AAPL",
        broker="XYZ Brokers",
        amount=100,
        price=155.0,
        brokerage_fee=10.0,
        other_fees=5.0
    )

    # Display the updated DataFrame
    print(transactions_df)

if __name__ == "__main__":
    main()