# Project Overview
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

## Main Features
- **User Authentication**: Login and registration using Django’s user model.
- **Portfolio Management**: Each user has one or more portfolios.
- **Transaction Recording**: Add, view, and manage buy/sell transactions for assets.
- **Asset, Broker, and Allocation Management**: Assets, brokers, and allocation classes are managed in the database and linked to transactions.
- **GUI**: Modern PyQt interface for all user interactions.
- **Database-Backed**: All data is persistent and managed via Django ORM.

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

For more details, see other files in the `docs/` folder.
