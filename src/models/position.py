class Position:

    def __init__(self, allocation_class, asset, broker):
        self.allocation_class = allocation_class
        self.asset = asset
        self.broker = broker
        self.average_cost = 0.0
        self.quantity = 0
        self.total_value = 0.0

    def __str__(self):
        return f"Position(Allocation Class: {self.allocation_class}, Asset: {self.asset}, Broker: {self.broker}, Average Cost: {self.average_cost}, Quantity: {self.quantity}, Total Value: {self.total_value})"

    def update_average_cost(self, portfolio):
        total_cost = 0.0
        total_quantity = 0

        # Iterate over the transactions and update the total cost and quantity
        for transaction in portfolio.transactions_list:
            if transaction.asset == self.asset:
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
            if transaction.asset == self.asset:
                if transaction.type == 'Buy':
                    self.quantity += transaction.quantity
                elif transaction.type == 'Sell':
                    self.quantity -= transaction.quantity
                    # Ensure quantity doesn't go negative
                    self.quantity = max(self.quantity, 0)
        pass

    def update_total_value(self, portfolio):
        # Calculate the total value of the asset
        for asset in portfolio.asset_list:
            if asset.tricker == self.asset:
                self.total_value = asset.current_price * self.quantity