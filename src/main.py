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
    for asset in portfolio.assets_list:
        # Calculate the average cost and quantity for each asset
        asset.update_average_cost(portfolio)
        asset.update_quantity(portfolio)
        
        # Update the asset in the file
        portfolio.update_asset_list(asset)

    # List assets to verify the updates
    portfolio.list_assets()

    
if __name__ == "__main__":
    main()