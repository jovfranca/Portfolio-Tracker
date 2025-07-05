# main.py - Investments Portfolio Tracker

import os
import sys
import pandas as pd
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QLineEdit, QComboBox, QPushButton, QVBoxLayout, QHBoxLayout, QTextEdit, QDateTimeEdit, QTableWidget, QTableWidgetItem)
from PyQt5.QtCore import QDateTime
from datetime import datetime

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
# # Get the path to the root directory by navigating 2 levels up
root_path = os.path.abspath(os.path.join(current_dir, '..', '..'))
# # Add the root directory to sys.path
sys.path.append(root_path)

from portfolioengine.models import Transaction, Position, Asset, Broker, AllocationClass, Portfolio, Country
from django.utils import timezone
from django.db import transaction as db_transaction

def GUI(portfolio):
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Transaction Input")
    window.resize(1200, 700)
    main_layout = QHBoxLayout()

    from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QSizePolicy
    table = QTableWidget()
    table.setColumnCount(10)
    table.setHorizontalHeaderLabels([
        "Date-Time", "Type", "Asset", "Broker", "Allocation Class", "Quantity", "Price", "Brokerage Fee", "Other Fees", "Notes"
    ])
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_layout.addWidget(table, stretch=3)

    right_panel = QWidget()
    right_layout = QVBoxLayout()
    right_panel.setLayout(right_layout)
    right_panel.setMaximumWidth(350)

    # Date-Time
    date_time_label = QLabel("Date-Time")
    date_time_edit = QDateTimeEdit(QDateTime.currentDateTime())
    date_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    right_layout.addWidget(date_time_label)
    right_layout.addWidget(date_time_edit)

    # Type
    type_label = QLabel("Type")
    type_combo = QComboBox()
    type_combo.addItems(["Buy", "Sell"])
    right_layout.addWidget(type_label)
    right_layout.addWidget(type_combo)

    # Asset
    asset_label = QLabel("Asset")
    asset_input = QLineEdit("AAPL")
    right_layout.addWidget(asset_label)
    right_layout.addWidget(asset_input)

    # Broker
    broker_label = QLabel("Broker")
    broker_input = QLineEdit("Inter")
    right_layout.addWidget(broker_label)
    right_layout.addWidget(broker_input)

    # Allocation Class
    allocation_label = QLabel("Allocation Class")
    allocation_combo = QComboBox()
    allocation_combo.addItems(["Oportunity Reserve", "Value Reserve", "Businesses"])
    allocation_combo.setCurrentText("Businesses")
    right_layout.addWidget(allocation_label)
    right_layout.addWidget(allocation_combo)

    # Quantity
    quantity_label = QLabel("Quantity")
    quantity_input = QLineEdit("10")
    right_layout.addWidget(quantity_label)
    right_layout.addWidget(quantity_input)

    # Price
    price_label = QLabel("Price")
    price_input = QLineEdit("100")
    right_layout.addWidget(price_label)
    right_layout.addWidget(price_input)

    # Brokerage Fee
    brokerage_label = QLabel("Brokerage Fee")
    brokerage_input = QLineEdit("0")
    right_layout.addWidget(brokerage_label)
    right_layout.addWidget(brokerage_input)

    # Other Fees
    other_fees_label = QLabel("Other Fees")
    other_fees_input = QLineEdit("0")
    right_layout.addWidget(other_fees_label)
    right_layout.addWidget(other_fees_input)

    # Notes
    notes_label = QLabel("Notes")
    notes_input = QLineEdit()
    right_layout.addWidget(notes_label)
    right_layout.addWidget(notes_input)

    # Buttons
    add_button = QPushButton("Add Transaction")
    update_button = QPushButton("Update")
    right_layout.addWidget(add_button)
    right_layout.addWidget(update_button)
    right_layout.addStretch(1)

    main_layout.addWidget(right_panel, stretch=1)

    # Helper: get or create related objects
    def get_or_create_country():
        country, _ = Country.objects.get_or_create(name="Default Country")
        return country

    def get_or_create_asset(ticker):
        country = get_or_create_country()
        asset, _ = Asset.objects.get_or_create(ticker=ticker, defaults={"description": ticker, "country": country})
        return asset
    def get_or_create_broker(name):
        broker, _ = Broker.objects.get_or_create(name=name, defaults={"registration_number": 0})
        return broker
    def get_or_create_allocation_class(description):
        ac, _ = AllocationClass.objects.get_or_create(description=description)
        return ac
    def get_or_create_position(asset, broker, allocation_class, portfolio):
        pos, _ = Position.objects.get_or_create(asset=asset, broker=broker, allocation_class=allocation_class, portfolio=portfolio)
        return pos

    # Load transactions from DB
    def load_transactions():
        if not portfolio:
            return []
        positions = Position.objects.filter(portfolio=portfolio)
        txs = Transaction.objects.filter(position__in=positions).order_by('date_time')
        return txs

    def refresh_table():
        txs = load_transactions()
        table.setRowCount(len(txs))
        for row, t in enumerate(txs):
            table.setItem(row, 0, QTableWidgetItem(str(t.date_time)))
            table.setItem(row, 1, QTableWidgetItem(t.type))
            table.setItem(row, 2, QTableWidgetItem(t.position.asset.ticker))
            table.setItem(row, 3, QTableWidgetItem(t.position.broker.name))
            table.setItem(row, 4, QTableWidgetItem(t.position.allocation_class.description))
            table.setItem(row, 5, QTableWidgetItem(str(t.quantity)))
            table.setItem(row, 6, QTableWidgetItem(str(t.price)))
            table.setItem(row, 7, QTableWidgetItem(str(t.brokerage_fee)))
            table.setItem(row, 8, QTableWidgetItem(str(t.other_fees)))
            table.setItem(row, 9, QTableWidgetItem(t.notes))

    def on_add_transaction():
        date_time = date_time_edit.dateTime().toPyDateTime()
        type_val = type_combo.currentText()
        asset = get_or_create_asset(asset_input.text())
        broker = get_or_create_broker(broker_input.text())
        allocation_class = get_or_create_allocation_class(allocation_combo.currentText())
        quantity = float(quantity_input.text())
        price = float(price_input.text())
        brokerage_fee = float(brokerage_input.text())
        other_fees = float(other_fees_input.text())
        notes = notes_input.text()
        pos = get_or_create_position(asset, broker, allocation_class, portfolio)
        with db_transaction.atomic():
            Transaction.objects.create(
                date_time=date_time,
                type=type_val,
                position=pos,
                quantity=quantity,
                price=price,
                brokerage_fee=brokerage_fee,
                other_fees=other_fees,
                notes=notes
            )
        refresh_table()

    def on_update():
        refresh_table()

    add_button.clicked.connect(on_add_transaction)
    update_button.clicked.connect(on_update)

    window.setLayout(main_layout)
    window.show()
    refresh_table()
    app.exec_()