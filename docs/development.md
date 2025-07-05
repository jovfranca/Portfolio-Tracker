# Development & Maintenance

## Adding Features
- Create new Django models in `portfolioengine/models/` and run migrations.
- Update or add PyQt code in `src/gui/` for new GUI features.
- Place test scripts in `tests/` for automated testing.
- Reference old model logic in `archive/` if needed, but do not use in production.

## How It Works
1. **Startup**: `src/main.py` sets up Django, then launches the PyQt login window.
2. **Login/Sign Up**: Users can log in or register. After login, the app fetches or creates a portfolio for the user.
3. **Main GUI**: The main window displays a table of transactions and a form to add new ones. All changes are saved to the database.
4. **Data Integrity**: All relationships (user, portfolio, asset, broker, etc.) are enforced by Django’s ORM and database constraints.

## Extending the App
- Add new models to `portfolioengine/models/` and run migrations.
- Add new business logic or analytics in `views/` or as model methods.
- Register new models in `admin.py` for Django admin access.

---

For more details, see the codebase and the Django documentation.
