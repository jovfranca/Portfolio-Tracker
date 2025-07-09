import pandas as pd
import os
import sys

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
# # Get the path to the root directory by navigating 2 levels up
root_path = os.path.abspath(os.path.join(current_dir, '..', '..'))
# # Add the root directory to sys.path
sys.path.append(root_path)

filename="src/db/transactions.pkl"

class Transaction:
    """
    A class used to represent a financial transaction within an investment portfolio.

    Attributes:
    ----------
    id (int): Unique identifier for the transaction.
    date_time (str): The date and time when the transaction occurred, formatted as a string.
    type (str): The type of transaction, typically 'Buy' or 'Sell'.
    asset (str): The asset involved in the transaction.
    broker (str): The broker facilitating the transaction.
    allocation_class (str): The classification of the asset for allocation purposes.
    quantity (int): The quantity of the asset transacted.
    price (float): The price per unit of the asset at the time of the transaction.
    brokerage_fee (float): The fee charged by the broker for the transaction.
    other_fees (float): Any additional fees associated with the transaction.
    notes (str): Additional notes or comments about the transaction.

    """


    def __init__(self, id, date_time, type, asset, broker, allocation_class, quantity, price, brokerage_fee, other_fees, notes):
        self.id = id
        self.date_time = date_time
        self.type = type
        self.asset = asset
        self.broker = broker
        self.allocation_class = allocation_class
        self.quantity = quantity
        self.price = price
        self.brokerage_fee = brokerage_fee
        self.other_fees = other_fees
        self.notes = notes

    def __str__(self):
        return f"{self.id}\t\t{self.date_time}\t{self.type}\t{self.asset}\t{self.broker}\t{self.allocation_class}\t\t{self.quantity}\t\t{self.price}\t{self.brokerage_fee}\t\t{self.other_fees}\t\t{self.notes}"


    def validate_transaction(self):
        # Validate the transaction data (e.g., check if required fields are present)
        # Implement your validation rules here
        pass

    def delete_transaction(self):
        # Remove an existing transaction from the system
        # Implement your logic here
        pass

    def calculate_total_cost(self):
        # Calculate the total cost of the transaction (including fees)
        # Implement your logic here
        pass