import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHBoxLayout, QMessageBox, QHeaderView
from PySide6.QtCore import Qt
from core.database import get_connection

class SearchWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("RECEIPT HISTORY & SEARCH")
        title.setStyleSheet("font-size: 20px; font-weight: bold; letter-spacing: 3px; color: #888; margin-bottom: 20px;")
        layout.addWidget(title)
        
        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("SEARCH BY SET #, VENDOR, OR DESCRIPTION...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 12px; 
                font-size: 13px; 
                background-color: #1a1a1a; 
                border: 1px solid #333; 
                color: white; 
                border-radius: 10px;
            }
            QLineEdit:focus {
                border-color: #00f2ff;
            }
        """)
        self.search_input.returnPressed.connect(self.perform_search)
        search_layout.addWidget(self.search_input)
        
        search_btn = QPushButton("SEARCH")
        search_btn.setFixedSize(120, 42)
        search_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #00f2ff;
                color: #00f2ff;
                font-weight: bold;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #00f2ff;
                color: black;
            }
        """)
        search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(search_btn)
        
        layout.addLayout(search_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["DATE", "SET #", "BUYER", "VENDOR", "TOTAL", "DESCRIPTION", "STATUS", "FILE"])
        self.table.setWordWrap(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0a0a0a;
                color: #bbb;
                gridline-color: #222;
                border: 1px solid #222;
                font-size: 12px;
                border-radius: 10px;
            }
            QHeaderView::section {
                background-color: #111;
                color: #888;
                padding: 10px;
                border: none;
                font-weight: bold;
                text-transform: uppercase;
                font-size: 10px;
            }
            QTableWidget::item {
                padding: 8px;
            }
        """)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for c in [0, 1, 2, 3, 4, 6, 7]:
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.cellClicked.connect(self.on_cell_clicked)
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table)
        
        # Initial load
        self.perform_search()
        
    def on_item_changed(self, item):
        col = item.column()
        if col in [0, 1, 2, 3, 4, 5]:
            receipt_id = item.data(Qt.UserRole)
            if not receipt_id: return
            
            from core.database import get_receipt_by_id, update_receipt
            receipt = get_receipt_by_id(receipt_id)
            if not receipt: return
            
            val = item.text().strip()
            
            if col == 1: # Set Number
                new_set = val.upper()
                old_set = receipt.set_number
                if old_set == new_set: return
                
                reply = QMessageBox.question(self, "Confirm Move", f"Move receipt from {old_set} to {new_set}?\n\nThis will physically move the file, update the Expense DB, and migrate the row in Google Sheets.", QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    self.table.blockSignals(True)
                    item.setText(old_set)
                    self.table.blockSignals(False)
                    return
                try:
                    receipt.set_number = new_set
                    from core.file_manager import move_and_rename_receipt
                    new_path = move_and_rename_receipt(receipt)
                    receipt.file_path = new_path
                    update_receipt(receipt)
                    
                    from services.sheets import move_receipt_in_sheet
                    from core.settings import load_settings
                    url = load_settings().get("spreadsheet_url", "")
                    if url:
                        import threading
                        def bg_task():
                            move_receipt_in_sheet(url, receipt, old_set)
                        t = threading.Thread(target=bg_task)
                        t.start()
                    file_item = self.table.item(item.row(), 7)
                    if file_item:
                        file_item.setData(Qt.UserRole, new_path)
                except Exception as e:
                    self.table.blockSignals(True)
                    item.setText(old_set)
                    self.table.blockSignals(False)
                    QMessageBox.warning(self, "Error", f"Failed to move receipt: {e}")
                    return
            else:
                try:
                    if col == 0: receipt.date = val
                    elif col == 2: receipt.buyer_name = val
                    elif col == 3: receipt.vendor = val
                    elif col == 4: receipt.total = float(val.replace('$', '').replace(',', '') or 0)
                    elif col == 5: receipt.description = val
                    update_receipt(receipt)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to update database: {e}")
                    return
        
    def perform_search(self):
        query = self.search_input.text().strip().lower()
        conn = get_connection()
        cursor = conn.cursor()
        
        sql = '''
            SELECT date, set_number, buyer_name, vendor, total, description, status, file_path, id 
            FROM receipts 
        '''
        
        if query:
            # Map month names to numbers for date searching
            months = {
                "jan": "-01-", "feb": "-02-", "mar": "-03-", "apr": "-04-",
                "may": "-05-", "jun": "-06-", "jul": "-07-", "aug": "-08-",
                "sep": "-09-", "oct": "-10-", "nov": "-11-", "dec": "-12-",
                "january": "-01-", "february": "-02-", "march": "-03-", "april": "-04-",
                "june": "-06-", "july": "-07-", "august": "-08-", "september": "-09-",
                "october": "-10-", "november": "-11-", "december": "-12-"
            }
            
            search_term = f"%{query}%"
            if query in months:
                search_term = f"%{months[query]}%"
                
            sql += ' WHERE LOWER(set_number) LIKE ? OR LOWER(vendor) LIKE ? OR LOWER(description) LIKE ? OR LOWER(buyer_name) LIKE ? OR date LIKE ?'
            params = (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", search_term)
            cursor.execute(sql + ' ORDER BY created_at DESC', params)
        else:
            cursor.execute(sql + ' ORDER BY created_at DESC')
            
        rows = cursor.fetchall()
        conn.close()
        
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            receipt_id = row_data[8]
            file_path = row_data[7]
            status_val = row_data[6]

            for col_idx in range(8):
                if col_idx == 6: # Status column
                    val = str(status_val if status_val is not None else "")
                    item = QTableWidgetItem(val)
                    if val == "APPROVED":
                        item.setForeground(Qt.green)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setData(Qt.UserRole, receipt_id)
                elif col_idx == 7: # File path column
                    val = "📄 OPEN"
                    item = QTableWidgetItem(val)
                    item.setForeground(Qt.cyan)
                    item.setData(Qt.UserRole, str(file_path if file_path is not None else ""))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                else:
                    cell_data = row_data[col_idx]
                    val = str(cell_data if cell_data is not None else "")
                    item = QTableWidgetItem(val)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    item.setData(Qt.UserRole, receipt_id)
                
                item.setToolTip(val)
                if col_idx == 5:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)
        
        for c in [0, 1, 2, 3, 4, 6, 7]:
            self.table.resizeColumnToContents(c)
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)

    def on_cell_clicked(self, row, col):
        if col in [6, 7]: # File or Status column clicked
            item = self.table.item(row, 7)
            if not item: return
            file_path = item.data(Qt.UserRole)
            if file_path and os.path.exists(file_path):
                os.startfile(file_path)
                return
            
            # Intelligent fallback search in show Receipts folder
            if file_path:
                filename = os.path.basename(file_path)
                from core.file_manager import RECEIPTS_DIR
                receipts_base = RECEIPTS_DIR
                if os.path.exists(receipts_base):
                    for root, dirs, files in os.walk(receipts_base):
                        if filename in files:
                            actual_path = os.path.join(root, filename)
                            item.setData(Qt.UserRole, actual_path)
                            os.startfile(actual_path)
                            return
            QMessageBox.warning(self, "Error", f"File not found: {file_path}")
