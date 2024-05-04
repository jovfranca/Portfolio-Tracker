# Classes

## Assets

### Attributes
- Asset Class
- Ticker
- Sector
- Sub-sector
- Average Cost
- Total Quantity
- Current Price
- Current Total Value
- Profitability

### Methods
- CheckForIncome()
- UpdateAverageCost()
- ValidateAverageCost()
- UpdateQuantity()
- UpdateCurrentPrice()
- UpdateCurrentTotalValue()
- UpdateProfitability()


## Transaction

### Attributes
- ID
- Date-Time
- Broker
- Allocation Class
- Quantity
- Price
- Brokerage Fee
- Other Fees
- Notes

### Methods
- NewTransaction()
- ValidateTransaction()
- DeleteTransaction()
- CalculateTotalCost()

## Broker

### Atributes

- Name
- Registration Number
- Country

### Methods

- CalculateTotalFees()

## Portfolio

### Atributes

- List of assets
- List of transactions

### Methods

- CalculateTotalValue()


