# main.py - Investments Portfolio Tracker

import os
import sys
# Ensure project root is in sys.path before any other imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.abspath(os.path.join(current_dir, '..'))
if root_path not in sys.path:
    sys.path.insert(0, root_path)

import pandas as pd
import settings
import django
from django.utils import timezone

# Set the DJANGO_SETTINGS_MODULE Environment Variable
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "portfoliotracker.settings")
# Initialize Django Settings
django.setup()

from django.contrib.auth import get_user_model
from portfolioengine.models import Portfolio
from src.gui.GUI import GUI
from src.gui.login import Login

User = get_user_model()

def main():
    import sys
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    login_dialog = Login()
    if login_dialog.exec_() == login_dialog.Accepted:
        username = login_dialog.username
        # Fetch the Django user
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            print(f"User '{username}' does not exist.")
            sys.exit()
        # Fetch or create a portfolio for the user
        portfolio, _ = Portfolio.objects.get_or_create(user=user, defaults={"description": f"Default Portfolio for {username}"})
        # Launch the main GUI with the user's portfolio
        GUI(portfolio)
    else:
        print("Login cancelled.")

    sys.exit()

if __name__ == "__main__":
    settings.init()
    main()