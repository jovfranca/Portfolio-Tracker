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
    Represents a financial transaction within an investment portfolio.

    This class provides a way to store and retrieve details about a single
    financial transaction, including its unique identifier, date and time,
    type (such as 'Buy' or 'Sell'), associated asset, broker involved,
    allocation class, quantity of the asset transacted, price per unit,
    brokerage fee, other associated fees, and any additional notes.

    The `__str__` method is overridden to provide a human-readable string
    representation of the transaction, which can be used for logging or
    display purposes.
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
        return f"Transaction(ID={self.id}, Date-Time='{self.date_time}', Type='{self.type}', Asset='{self.asset}', Broker='{self.broker}', Allocation Class='{self.allocation_class}', Quantity={self.quantity}, Price={self.price}, Brokerage Fee={self.brokerage_fee}, Other Fees={self.other_fees}, Notes='{self.notes}')"


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