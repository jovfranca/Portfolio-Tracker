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

def SignUp():
    login = [
        [sg.Text("Name"), sg.InputText(key="name")],
        [sg.Text("Email"), sg.InputText(key="email")],
        [sg.Text("Password"), sg.InputText(key="password", password_char='*')],
        [sg.Button("Sign Up")]
    ]

    window = sg.Window("Sign Up", login)

    while True:
        event, values = window.read()
        if event == sg.WINDOW_CLOSED:
            break
                        
        elif event == "Sign Up":
            user = User(name= values["name"], email= values["email"], pass_hash=hashlib.sha256(values["password"].encode()).hexdigest())
            user.save()
            sg.Popup('Sign up Successful!', title='Welcome')
            GUI()
            # Extract input values
            break