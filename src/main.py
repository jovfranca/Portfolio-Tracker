# main.py - Investments Portfolio Tracker

import pandas as pd
from db.transactions import TransactionRecords
from gui.forms import create_transaction_form

def main():
    create_transaction_form()
    

if __name__ == "__main__":
    main()