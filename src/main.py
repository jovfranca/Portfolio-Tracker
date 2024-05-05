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

from src.gui.forms import create_transaction
from src.models.portfolio import Portfolio

def main():
    portfolio = Portfolio()
    create_transaction(portfolio)
    portfolio.list_assets()
    oldest_transaction_date = portfolio.get_oldest_transaction_date()
    for asset in portfolio.assets_list:
        # Calculate the average cost and quantity for each asset
        print(asset.ticker)
        asset.update_average_cost(portfolio)
        asset.update_quantity(portfolio)
        asset.update_history(oldest_transaction_date)
        asset.update_current_price()
        asset.update_total_value()

        # Update the asset in the file
        portfolio.update_asset_list(asset)


    # List assets to verify the updates
    portfolio.list_assets()
    
    

if __name__ == "__main__":
    main()