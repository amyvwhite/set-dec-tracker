from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt

class SummaryDialog(QDialog):
    def __init__(self, set_name, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"EXPENSE SUMMARY - {set_name.upper()}")
        self.resize(800, 500)
        self.setStyleSheet("background-color: #0a0a0a; color: white;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel(f"RECENT EXPENDITURES FOR {set_name.upper()}")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #00f2ff; margin-bottom: 10px;")
        layout.addWidget(title)
        
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setStyleSheet("""
            QTextEdit {
                background-color: #111;
                color: #bbb;
                border: 1px solid #333;
                font-size: 14px;
                padding: 15px;
                line-height: 1.5;
            }
        """)
        layout.addWidget(self.text_area)
        
        # Get unique descriptions and calculate total
        unique_descriptions = set()
        total_sum = 0.0
        
        for entry in data:
            desc = str(entry.get("items", "")).strip().upper()
            if desc:
                unique_descriptions.add(desc)
            
            amt_str = str(entry.get("amount", "0")).replace('$', '').replace(',', '').strip()
            try:
                total_sum += float(amt_str)
            except: pass
            
        # Build bulleted list
        bullet_text = "<b>ITEMS BOUGHT SO FAR:</b><br><br>"
        for item in sorted(list(unique_descriptions)):
            bullet_text += f"• {item}<br>"
            
        self.text_area.setHtml(bullet_text)
        
        footer_layout = QHBoxLayout()
        total_label = QLabel(f"TOTAL SO FAR: ${total_sum:,.2f}")
        total_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #39ff14;")
        footer_layout.addWidget(total_label)
        footer_layout.addStretch()
        
        close_btn = QPushButton("CLOSE")
        close_btn.setFixedSize(100, 40)
        close_btn.setStyleSheet("""
            QPushButton { background-color: #333; border: none; color: white; border-radius: 5px; }
            QPushButton:hover { background-color: #444; }
        """)
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)
        
        layout.addLayout(footer_layout)
