from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, QThread, Signal
from services.sheets import get_spreadsheet
from core.settings import load_settings
import os

class BudgetLoaderThread(QThread):
    data_loaded = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            sh = get_spreadsheet(self.url)
            worksheet = sh.worksheet("SET DEC BUDGET")
            data = worksheet.get_all_values()
            self.data_loaded.emit(data)
        except Exception as e:
            self.error_occurred.emit(str(e))

class BudgetWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        self.title = QLabel("Set Dec Budget Simulation")
        self.title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ecf0f1;")
        header_layout.addWidget(self.title)
        
        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setStyleSheet("padding: 8px; background-color: #27ae60; color: white; font-weight: bold;")
        self.refresh_btn.clicked.connect(self.load_data)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #121212;
                alternate-background-color: #1e1e1e;
                color: #ecf0f1;
                gridline-color: #333;
                border: 1px solid #444;
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 10px;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: #ffffff;
                padding: 12px;
                border: 1px solid #111;
                font-weight: bold;
                font-size: 14px;
            }
        """)
        layout.addWidget(self.table)
        
    def load_data(self):
        settings = load_settings()
        url = settings.get("spreadsheet_url")
        if not url:
            self.title.setText("Set Dec Budget (No URL configured)")
            return
            
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("⏳ Loading Budget...")
        
        self.thread = BudgetLoaderThread(url)
        self.thread.data_loaded.connect(self.on_data_loaded)
        self.thread.error_occurred.connect(self.on_error)
        self.thread.start()
        
    def on_data_loaded(self, data):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("🔄 Refresh Budget")
        
        if not data: return
        
        # Filter out completely empty rows
        filtered_data = [r for r in data if any(cell.strip() for cell in r)]
        
        self.table.setRowCount(len(filtered_data))
        self.table.setColumnCount(len(filtered_data[0]) if filtered_data else 0)
        
        for r_idx, row in enumerate(filtered_data):
            for c_idx, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                self.table.setItem(r_idx, c_idx, item)
                
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        
    def on_error(self, err):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh Data")
        self.title.setText(f"Error: {err}")
