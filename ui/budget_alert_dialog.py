import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QCheckBox, QMessageBox, QScrollArea, QWidget)
from PySide6.QtCore import Qt
import generate_alert

class BudgetAlertDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Budget Alert")
        self.setMinimumWidth(300)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: white;
            }
            QLabel {
                color: white;
                font-weight: bold;
                margin-bottom: 5px;
            }
            QCheckBox {
                color: white;
                margin: 2px;
            }
            QPushButton {
                background-color: #0d47a1;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        label = QLabel("Select Episodes to Include:")
        layout.addWidget(label)
        
        # Scroll area for episodes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: 1px solid #333; background-color: #252525;")
        
        scroll_widget = QWidget()
        self.episodes_layout = QVBoxLayout(scroll_widget)
        
        # We will list standard episodes plus AMORT
        self.episodes = ["AMORT", "201", "202", "203", "204", "205", "206", "207", "208", "209", "210"]
        self.checkboxes = []
        
        for ep in self.episodes:
            cb = QCheckBox(ep)
            cb.setChecked(False)
            self.checkboxes.append(cb)
            self.episodes_layout.addWidget(cb)
            
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_all = QPushButton("Select All")
        self.btn_all.setStyleSheet("background-color: #333;")
        self.btn_all.clicked.connect(self.select_all)
        
        self.btn_none = QPushButton("Select None")
        self.btn_none.setStyleSheet("background-color: #333;")
        self.btn_none.clicked.connect(self.select_none)
        
        btn_layout.addWidget(self.btn_all)
        btn_layout.addWidget(self.btn_none)
        layout.addLayout(btn_layout)
        
        self.btn_generate = QPushButton("Generate PDF")
        self.btn_generate.clicked.connect(self.generate)
        layout.addWidget(self.btn_generate)
        
    def select_all(self):
        for cb in self.checkboxes:
            cb.setChecked(True)
            
    def select_none(self):
        for cb in self.checkboxes:
            cb.setChecked(False)
            
    def generate(self):
        selected = [cb.text() for cb in self.checkboxes if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select at least one episode.")
            return
            
        try:
            self.btn_generate.setText("Generating...")
            self.btn_generate.setEnabled(False)
            self.repaint()
            
            pdf_path = generate_alert.generate_report(selected)
            
            QMessageBox.information(self, "Success", f"Budget Alert PDF has been saved to SAMPLE SHOW S1/BUDGET ALERTS!")
            if pdf_path and os.path.exists(pdf_path):
                os.startfile(pdf_path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate alert: {str(e)}")
        finally:
            self.btn_generate.setText("Generate PDF")
            self.btn_generate.setEnabled(True)
