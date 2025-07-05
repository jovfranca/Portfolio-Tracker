from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QApplication, QMessageBox, QHBoxLayout
import sys

class Login(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Login')
        self.username = ''
        self.password = ''
        self.error_label = QLabel('')
        self.error_label.setStyleSheet('color: red')
        layout = QVBoxLayout()
        layout.addWidget(QLabel('Username:'))
        self.username_input = QLineEdit()
        layout.addWidget(self.username_input)
        layout.addWidget(QLabel('Password:'))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)
        layout.addWidget(self.error_label)
        btn_layout = QHBoxLayout()
        self.login_button = QPushButton('Login')
        self.signup_button = QPushButton('Sign Up')
        btn_layout.addWidget(self.login_button)
        btn_layout.addWidget(self.signup_button)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.login_button.clicked.connect(self.handle_login)
        self.signup_button.clicked.connect(self.handle_signup)

    def handle_login(self):
        self.username = self.username_input.text()
        self.password = self.password_input.text()
        from django.contrib.auth import authenticate
        user = authenticate(username=self.username, password=self.password)
        if user is not None:
            self.accept()
        else:
            self.error_label.setText('Invalid username or password.')

    def handle_signup(self):
        signup_dialog = SignupDialog(self)
        if signup_dialog.exec_() == QDialog.Accepted:
            self.error_label.setText('Sign up successful! Please log in.')

class SignupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Sign Up')
        layout = QVBoxLayout()
        layout.addWidget(QLabel('Username:'))
        self.username_input = QLineEdit()
        layout.addWidget(self.username_input)
        layout.addWidget(QLabel('Name:'))
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input)
        layout.addWidget(QLabel('Password:'))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)
        self.error_label = QLabel('')
        self.error_label.setStyleSheet('color: red')
        layout.addWidget(self.error_label)
        self.signup_button = QPushButton('Sign Up')
        layout.addWidget(self.signup_button)
        self.setLayout(layout)
        self.signup_button.clicked.connect(self.handle_signup)

    def handle_signup(self):
        username = self.username_input.text()
        name = self.name_input.text()
        password = self.password_input.text()
        if not username or not name or not password:
            self.error_label.setText('All fields are required.')
            return
        from django.contrib.auth.models import User
        if User.objects.filter(username=username).exists():
            self.error_label.setText('Username already exists.')
            return
        user = User.objects.create_user(username=username, password=password)
        user.first_name = name
        user.save()
        self.accept()

# Example usage for testing
if __name__ == '__main__':
    app = QApplication(sys.argv)
    login = Login()
    if login.exec_() == QDialog.Accepted:
        print(f'Username: {login.username}, Password: {login.password}')
    sys.exit()
