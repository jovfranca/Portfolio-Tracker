class Asset:
    def __init__(self, asset_class, ticker, sector, sub_sector):
        self.asset_class = asset_class
        self.ticker = ticker
        self.sector = sector
        self.sub_sector = sub_sector
        self.average_cost = 0.0
        self.quantity = 0
        self.current_price = 0.0

    def __str__(self):
        return f"Asset(Ticker: {self.ticker}, Quantity: {self.quantity}, Average Cost: {self.average_cost}, Current Price: {self.current_price})"

    def update_average_cost(self, portfolio):
        total_cost = 0.0
        total_quantity = 0

        # Iterate over the transactions and update the total cost and quantity
        for transaction in portfolio.transactions_list:
            if transaction.asset == self.ticker:
                if transaction.type == 'Buy':
                    total_cost += transaction.price * transaction.quantity
                    total_quantity += transaction.quantity
                elif transaction.type == 'Sell' and total_quantity > 0:
                    total_quantity -= transaction.quantity

        # Update the average cost if there are any holdings
        if total_quantity > 0:
            self.average_cost = total_cost / total_quantity
        else:
            self.average_cost = 0.0
        pass

    def update_quantity(self, portfolio):
        self.quantity = 0

        # Iterate over the transactions and update the quantity
        for transaction in portfolio.transactions_list:
            if transaction.asset == self.ticker:
                if transaction.type == 'Buy':
                    self.quantity += transaction.quantity
                elif transaction.type == 'Sell':
                    self.quantity -= transaction.quantity
                    # Ensure quantity doesn't go negative
                    self.quantity = max(self.quantity, 0)
        pass

    def check_for_income(self):
        # Check if the asset generates income (e.g., dividends)
        # Implement your logic here
        pass



    def update_current_price(self, new_price):
        # Update the current price of the asset
        # Implement your logic here
        pass

    def update_current_total_value(self):
        # Calculate and update the current total value (price * quantity)
        # Implement your logic here
        pass

    def update_profitability(self):
        # Calculate and update the profitability (gain/loss percentage)
        # Implement your logic here
        pass