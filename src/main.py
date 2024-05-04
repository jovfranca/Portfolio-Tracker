# main.py - Investments Portfolio Tracker

import pandas as pd
import os
import sys

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
# # Get the path to the root directory by navigating 2 levels up
root_path = os.path.abspath(os.path.join(current_dir, '..'))
# # Add the root directory to sys.path
sys.path.append(root_path)

from src.gui.forms import create_transaction_form

def main():
    create_transaction_form()
    
if __name__ == "__main__":
    main()