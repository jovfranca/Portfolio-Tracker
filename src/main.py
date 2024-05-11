# main.py - Investments Portfolio Tracker

import pandas as pd
import os
import sys
import settings
import django



# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
# # Get the path to the root directory by navigating 2 levels up
root_path = os.path.abspath(os.path.join(current_dir, '..'))
# # Add the root directory to sys.path
sys.path.append(root_path)

# Set the DJANGO_SETTINGS_MODULE Environment Variable
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "portfoliotracker.settings")
# Initialize Django Settings
django.setup()

from src.gui.GUI import GUI
from src.gui.login import Login
from src.models.portfolio import Portfolio
from django.utils import timezone

from portfolioengine.models import User
from portfolioengine.models import Portfolio

def main():
    Login()
    # users = User.objects.all()
    # for user in users:
    #     print(user)
    #     if user.name == 'Ciclano Ferreira':
    #         p = user.portfolios.all().first()
    #         print(p)

    #GUI(portfolio)
    pass

if __name__ == "__main__":
    settings.init()
    main()