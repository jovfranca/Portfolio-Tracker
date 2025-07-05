# Django Backend Documentation

## Overview
The Django backend is split into two main components:
- **portfolioengine/**: The main Django app containing all business logic, models, and (optionally) views/templates for the portfolio tracker.
- **portfoliotracker/**: The Django project root, containing global configuration, settings, and URL routing.

---

## portfolioengine/
This is the core Django app for all investment and portfolio management logic.

### Key Subfolders & Files
- **models/**: Contains all Django ORM models:
  - `asset.py`: Asset model (e.g., stocks, funds) with fields for ticker, description, country, and historical data.
  - `broker.py`: Broker model, with name and registration number.
  - `country.py`: Country model for asset location.
  - `allocation_class.py`: Asset allocation categories (e.g., Value Reserve).
  - `portfolio.py`: Portfolio model, linked to a user, with description and historical data.
  - `position.py`: Position model, linking asset, broker, allocation class, and portfolio.
  - `transaction.py`: Transaction model, linked to a position, with date, type, quantity, price, fees, and notes.
  - `historical_data.py`: Models for storing historical and analytical data for assets and positions.
  - `user.py`: Imports Django’s built-in User model for authentication.
  - `__init__.py`: Exposes all models for easy import.
- **migrations/**: Auto-generated migration scripts for database schema changes.
- **views/**: (Optional) Contains Django views for web interface (e.g., login, dashboard, signup).
- **templates/**: (Optional) HTML templates for web pages.
- **admin.py**: Django admin interface registration.
- **apps.py**: Django app configuration.

### Model Relationships
- **User** (Django built-in): Authenticates and owns portfolios.
- **Portfolio**: Belongs to a user, contains positions.
- **Position**: Belongs to a portfolio, links to an asset, broker, and allocation class.
- **Transaction**: Belongs to a position, records buy/sell events.
- **Asset**: Represents a security, linked to a country.
- **Broker**: Represents a brokerage firm.
- **AllocationClass**: Categorizes positions/assets.
- **Country**: Used for asset location.
- **HistoricalData/PositionData/AssetData**: Used for analytics and performance tracking.

### Example: How a Transaction is Stored
1. User logs in (Django User).
2. User has a Portfolio (or one is created).
3. Each Position in the portfolio links to an Asset, Broker, and AllocationClass.
4. Each Transaction is linked to a Position and records all trade details.

### Extending the App
- Add new models to `portfolioengine/models/` and run migrations.
- Add new business logic or analytics in `views/` or as model methods.
- Register new models in `admin.py` for Django admin access.

---

## portfoliotracker/
This is the Django project root, containing global configuration.

### Key Files
- **settings.py**: All Django settings (database, installed apps, middleware, etc.).
- **urls.py**: URL routing for the project (web interface, if used).
- **wsgi.py/asgi.py**: Entry points for web servers.
- **__init__.py**: Marks the directory as a Python package.

### How It Works
- `settings.py` lists `portfolioengine` in `INSTALLED_APPS` so Django knows to use its models and migrations.
- All database operations, authentication, and business logic are handled by the models and logic in `portfolioengine`.

---

For more details on each model or to extend the backend, see the code in `portfolioengine/models/` and the Django documentation.
