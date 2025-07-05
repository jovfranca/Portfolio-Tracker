# Portfolio Tracker Project Documentation

## Overview
Portfolio Tracker is a cross-platform investment management application built with Django (for data and business logic) and PyQt (for the desktop GUI). It allows users to manage investment portfolios, record transactions, and analyze performance, all backed by a robust relational database.

---

## Project Structure

```
Portfolio-Tracker/
├── db.sqlite3                # Main SQLite database for Django
├── manage.py                 # Django management script
├── requirements.txt          # Python dependencies
├── README.md, LICENSE        # Project info and license
├── assets/                   # Static files/resources
├── data/                     # Data files (e.g., CSVs)
├── docs/                     # Documentation (this folder)
├── portfolioengine/          # Main Django app (models, business logic)
│   ├── models/               # Django ORM models (Asset, Portfolio, etc.)
│   ├── migrations/           # Database migration scripts
│   ├── views/                # Django web views (if used)
│   └── templates/            # HTML templates (if used)
├── portfoliotracker/         # Django project config (settings, URLs, WSGI)
├── src/                      # Desktop app code (PyQt GUI, main logic)
│   ├── gui/                  # PyQt GUI code (GUI.py, login.py)
│   ├── api/                  # API integrations
│   ├── reports/              # Reporting/analytics scripts
│   ├── utils/                # Utility functions
│   └── main.py               # Main entry point for the desktop app
├── archive/                  # Legacy code (old models, not used)
└── tests/                    # Test scripts
```

---

## Key Components

### 1. Django Backend
- **portfolioengine/models/**: Contains all database models (Asset, Portfolio, Transaction, Position, etc.)
- **portfolioengine/views/**: (Optional) Django web views for web interface (not used in desktop app)
- **portfolioengine/migrations/**: Database schema migrations
- **portfoliotracker/settings.py**: Django project settings (database, apps, etc.)

### 2. Desktop Application (src/)
- **src/main.py**: Main entry point. Sets up Django, launches the PyQt GUI, and handles user authentication.
- **src/gui/**: PyQt GUI code for login, transaction entry, and portfolio management.
- **src/api/**: Market data and external API integrations.
- **src/reports/**: Scripts for generating performance and tax reports.
- **src/utils/**: Helper functions and calculations.

### 3. Database
- **db.sqlite3**: SQLite database file. Stores all users, portfolios, transactions, and related data.

### 4. Legacy Code
- **archive/models/**: Old, non-Django model classes. Not used in the current application.

---

## Main Features
- **User Authentication**: Login and registration using Django’s user model.
- **Portfolio Management**: Each user has one or more portfolios.
- **Transaction Recording**: Add, view, and manage buy/sell transactions for assets.
- **Asset, Broker, and Allocation Management**: Assets, brokers, and allocation classes are managed in the database and linked to transactions.
- **GUI**: Modern PyQt interface for all user interactions.
- **Database-Backed**: All data is persistent and managed via Django ORM.

---

## How It Works
1. **Startup**: `src/main.py` sets up Django, then launches the PyQt login window.
2. **Login/Sign Up**: Users can log in or register. After login, the app fetches or creates a portfolio for the user.
3. **Main GUI**: The main window displays a table of transactions and a form to add new ones. All changes are saved to the database.
4. **Data Integrity**: All relationships (user, portfolio, asset, broker, etc.) are enforced by Django’s ORM and database constraints.

---

## Development & Maintenance
- **Add new features**: Create new Django models in `portfolioengine/models/` and run migrations.
- **Update GUI**: Edit or add PyQt code in `src/gui/`.
- **Testing**: Place test scripts in `tests/`.
- **Legacy code**: Reference old model logic in `archive/` if needed, but do not use in production.

---

## Getting Started
1. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
2. Run migrations:
   ```powershell
   python manage.py makemigrations
   python manage.py migrate
   ```
3. Start the desktop app:
   ```powershell
   python src/main.py
   ```

---

## Notes
- The project is designed for extensibility: you can add web views, REST APIs, or more analytics as needed.
- All persistent data is managed by Django’s ORM and stored in `db.sqlite3` by default.
- For production, consider switching to PostgreSQL or another robust database.

---

# Django Module: portfolioengine & portfoliotracker

## Overview
The Django backend is split into two main components:
- **portfolioengine/**: The main Django app containing all business logic, models, and (optionally) views/templates for the portfolio tracker.
- **portfoliotracker/**: The Django project root, containing global configuration, settings, and URL routing.

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
