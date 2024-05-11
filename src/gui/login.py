import PySimpleGUI as sg
import hashlib
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
# # Get the path to the root directory by navigating 2 levels up
root_path = os.path.abspath(os.path.join(current_dir, '..'))
# # Add the root directory to sys.path
sys.path.append(root_path)

from portfolioengine.models import User
from src.gui.GUI import GUI
from src.gui.sign_up import SignUp

def Login():
    login = [
        [sg.Text("Email"), sg.InputText(key="email")],
        [sg.Text("Password"), sg.InputText(key="password", password_char='*')],
        [sg.Button("Login")],
        [sg.Button("Sign Up")]
    ]

    window = sg.Window("Login", login)

    while True:
        event, values = window.read()
        if event == sg.WINDOW_CLOSED:
            break
        elif event == "Login":
            # Extract input values
            email = values["email"]
            pass_hash = hashlib.sha256(values["password"].encode()).hexdigest()
            authenticated = False
            wrong_pass = False
            for u in User.objects.all():
                print(u.email)
                if u.email == email:
                    if u.pass_hash == pass_hash:
                        user = u
                        authenticated = True
                        break
                    else:
                        wrong_pass = True
                        sg.Popup('Wrong password, please try again!', title='Login Failed')
            if (not authenticated) and (not wrong_pass):
                sg.Popup('Email not found, please try again!', title='Login Failed')
            if authenticated:
                # Proceed with login
                sg.Popup('Login Successful!', title='Welcome')
                GUI()
                # Add your code here to handle successful login
                break
                        
        elif event == "Sign Up":
            SignUp()
            # Extract input values
            break
