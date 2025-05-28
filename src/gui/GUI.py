# main.py - Investments Portfolio Tracker

import os
import sys
import pandas as pd

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
    portfolio.print_transactions()