# Portfolio Tracker
# Investments Portfolio Tracker

## Overview
The Investments Portfolio Tracker is a comprehensive tool designed to manage and analyze your investment portfolio. It provides detailed insights into your investments, featuring profit and allocation calculations.

## Released Features

### Transaction Data
- [x] **Transaction Records**: Track all buy and sell transactions. 
- [x] **Transaction Form**: A form to input transaction details.

### Asset Data

- [x] **Assets List**: List of all assets owned
- [x] **Average Cost**: Calculation of average cost
- [x] **Current Price**: Fetching of current price for asset
- [x] **Historical Data**: Fetching of historical price for asset

There was implemented classes for: assets, brokers, transactions and portfolio.

## Upcoming Features

### Position Data

Each position must have a unique asset, broker and allocation class.

- **Assets List**: List of all positions owned
- **Average Cost**: Calculation of average cost of each position
- **Unrealized Gain**: Calculation of unrealized gain
- **Realized Gain**: Calculation of realized gain
- **Total Gain**: Calculation of total gain
- **Accumulated Profitability %**: Calculation of accumulated profitability
- **Daily Profitability %**: Calculation of Daily Profitability


### Portfolio Data
- **Position Overview**: List positions with details such as average cost, quantity, current value, allocation, dividends, and profitability.
- **Asset Overview**: List assets with details such as average cost, quantity, current value, allocation, dividends, and profitability.
- **Ideal Allocation**: Calculate the ideal asset allocation based on risk indicators.
- **Investment Strategy**: Determine investment amounts based on current and ideal allocations.
- **API Integration**: Fetch historical price and dividend data.
- **Database**: Backend stored time-series data of asset prices and dividends.

### Portfolio Dashboard
- **Visualization**: Graphs to display asset allocations.
- **Filtering**: Options to view data by asset, class, or country.
- **Historical Data**: A graph showing the daily historical value of the portfolio.
- **Performance Analysis**: Compare your portfolio's performance against standard benchmarks to gauge relative success.
- **Correlation Metrics**: Analyze the correlations between different assets to understand their relationships and impact on portfolio risk.

### Taxation Reports
- **Monthly Taxes**: A report detailing monthly tax obligations.
- **Annual Declaration**: A report for the annual income tax declaration.