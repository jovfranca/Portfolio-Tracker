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

from src.models.transaction import Transaction
from src.models.portfolio import Portfolio
from datetime import datetime

def GUI(portfolio):
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    layout = [
        [sg.Text("Date-Time"), sg.InputText(key="date_time", default_text=current_datetime)],
        [sg.CalendarButton("Select Date", target="date_time", format="%Y-%m-%d %H:%M:%S", key="calendar")],
        [sg.Text("Type"), sg.Combo(["Buy", "Sell"], key="type", default_value="Buy")],
        [sg.Text("Asset"), sg.InputText(key="asset", default_text="AAPL")],
        [sg.Text("Broker"), sg.InputText(key="broker",default_text="Inter")],
        [sg.Text("Allocation Class"), sg.Combo(["Oportunity Reserve", "Value Reserve", "Businesses"], key="allocation_class", default_value="Businesses")],
        [sg.Text("Quantity"), sg.InputText(key="quantity", default_text="10")],
        [sg.Text("Price"), sg.InputText(key="price",default_text="100")],
        [sg.Text("Brokerage Fee"), sg.InputText(key="brokerage_fee",default_text="0")],
        [sg.Text("Other Fees"), sg.InputText(key="other_fees",default_text="0")],
        [sg.Text("Notes"), sg.InputText(key="notes")],
        [sg.Button("Add Transaction")],
        [sg.Button("Update")]
    ]

    window = sg.Window("Transaction Input", layout)

    while True:
        event, values = window.read()
        if event == sg.WINDOW_CLOSED:
            break
        elif event == "Add Transaction":
            # Extract input values
            date_time = values["date_time"]
            type = values["type"]
            asset = values["asset"]
            broker = values["broker"]
            allocation_class = values["allocation_class"]
            quantity = float(values["quantity"])  # Convert to float
            price = float(values["price"])  # Convert to float
            brokerage_fee = float(values["brokerage_fee"])  # Convert to float
            other_fees = float(values["other_fees"])  # Convert to float
            notes = values["notes"]

            # Add the transaction using your TransactionRecords class

        #     transaction = Transaction(0, date_time, type, asset, broker, allocation_class, quantity, price, brokerage_fee, other_fees, notes)
        #     portfolio.add_transaction(transaction)
        #     portfolio.print_transactions()
        #     portfolio.update_assets()
        #     portfolio.update_positions()
        # elif event == "Update":
        #     portfolio.print_transactions()
        #     portfolio.update_assets()
        #     portfolio.update_positions()

    window.close()