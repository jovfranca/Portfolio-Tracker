# main.py - Investments Portfolio Tracker

import os
import sys
import pandas as pd
import PySimpleGUI as sg

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
# # Get the path to the root directory by navigating 2 levels up
root_path = os.path.abspath(os.path.join(current_dir, '..', '..'))
# # Add the root directory to sys.path
sys.path.append(root_path)

from src.db.transactions import TransactionRecords
from datetime import datetime

def create_transaction_form():
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    layout = [
        [sg.Text("Date-Time"), sg.InputText(key="date_time", default_text=current_datetime)],
        [sg.CalendarButton("Select Date", target="date_time", format="%Y-%m-%d %H:%M:%S", key="calendar")],
        [sg.Text("Transaction Type"), sg.Combo(["Buy", "Sell"], key="transaction_type")],
        [sg.Text("Asset Class"), sg.Combo(["Stocks, ETFs, REITs, etc.", "Funds", "Fixed Deposit", "Government Bonds", "Corporate Bonds", "Stock Options", "Currencies", "Cryptocurrenies", "Commodities", "Cash", "Generic"], key="asset_class")],
        [sg.Text("Asset"), sg.InputText(key="asset")],
        [sg.Text("Broker"), sg.InputText(key="broker")],
        [sg.Text("Amount"), sg.InputText(key="amount")],
        [sg.Text("Price"), sg.InputText(key="price")],
        [sg.Text("Brokerage Fee"), sg.InputText(key="brokerage_fee")],
        [sg.Text("Other Fees"), sg.InputText(key="other_fees")],
        [sg.Button("Add Transaction")]
    ]

    window = sg.Window("Transaction Input", layout)

    while True:
        event, values = window.read()
        if event == sg.WINDOW_CLOSED:
            break
        elif event == "Add Transaction":
            # Extract input values
            date_time = values["date_time"]
            transaction_type = values["transaction_type"]
            asset_class = values["asset_class"]
            asset = values["asset"]
            broker = values["broker"]
            amount = float(values["amount"])  # Convert to float
            price = float(values["price"])  # Convert to float
            brokerage_fee = float(values["brokerage_fee"])  # Convert to float
            other_fees = float(values["other_fees"])  # Convert to float

            # Add the transaction using your TransactionRecords class
            records = TransactionRecords()
            records.add_transaction(
                date_time=date_time,
                transaction_type=transaction_type,
                asset_class=asset_class,
                asset=asset,
                broker=broker,
                amount=amount,
                price=price,
                brokerage_fee=brokerage_fee,
                other_fees=other_fees
            )
            records.save_transactions()
            print(records.transactions_df)

    window.close()