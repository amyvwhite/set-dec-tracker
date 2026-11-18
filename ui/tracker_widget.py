from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, QThread, Signal
from services.sheets import get_spreadsheet
from core.settings import load_settings
import os

class TrackerLoaderThread(QThread):
    data_loaded = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            sh = get_spreadsheet(self.url)
            worksheets = sh.worksheets()
            worksheet = None
            
            # 1. Look for exact match
            for ws in worksheets:
                if ws.title.upper() == "TRACKER TOP SHEET":
                    worksheet = ws
                    break
            
            # 2. Look for keywords
            if not worksheet:
                for ws in worksheets:
                    if "TRACKER" in ws.title.upper() and "TOP" in ws.title.upper():
                        worksheet = ws
                        break
            
            # 3. Fallback to first sheet
            if not worksheet:
                worksheet = worksheets[0]
            
            data = worksheet.get_all_values()
            self.data_loaded.emit(data)
        except Exception as e:
            self.error_occurred.emit(str(e))

class TrackerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        self.title = QLabel("Tracker Top Sheet Simulation")
        self.title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ecf0f1;")
        header_layout.addWidget(self.title)
        
        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setStyleSheet("padding: 8px; background-color: #3498db; color: white; font-weight: bold;")
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
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 8px 6px;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: #ffffff;
                padding: 10px 8px;
                border: 1px solid #111;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.table)
        
    def load_data(self):
        settings = load_settings()
        url = settings.get("spreadsheet_url")
        if not url:
            self.title.setText("Tracker Top Sheet (No URL configured)")
            return
            
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("⏳ Loading Tracker...")
        
        self.thread = TrackerLoaderThread(url)
        self.thread.data_loaded.connect(self.on_data_loaded)
        self.thread.error_occurred.connect(self.on_error)
        self.thread.start()
        
    def on_data_loaded(self, data):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("🔄 Refresh Tracker")
        
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
