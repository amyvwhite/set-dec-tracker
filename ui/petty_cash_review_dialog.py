from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout, QCompleter
from PySide6.QtCore import Qt

class PettyCashReviewDialog(QDialog):
    def __init__(self, filename, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Review - Petty Cash")
        self.setMinimumWidth(450)
        
        self.data = data
        self.was_halted = False
        
        layout = QVBoxLayout(self)
        
        info_lbl = QLabel(f"<b>Receipt:</b> {filename}")
        info_lbl.setTextFormat(Qt.RichText)
        layout.addWidget(info_lbl)
        
        form = QFormLayout()

        # Editable Vendor, Total, Subtotal, Tax
        vendor = data.get("vendor", "Unknown")
        amount = float(data.get("total", 0.0) or 0.0)
        subtotal = float(data.get("subtotal", 0.0) or 0.0)
        tax = float(data.get("tax", 0.0) or 0.0)

        if amount != 0.0 and (subtotal == 0.0 or tax == 0.0):
            subtotal = round(amount / 1.13, 2)
            tax = round(amount - subtotal, 2)

        self.vendor_input = QLineEdit(str(vendor))
        self.vendor_input.setPlaceholderText("Vendor Name (e.g. HOME DEPOT)")

        self.total_input = QLineEdit(f"{amount:.2f}" if amount else "0.00")
        self.subtotal_input = QLineEdit(f"{subtotal:.2f}" if subtotal else "0.00")
        self.tax_input = QLineEdit(f"{tax:.2f}" if tax else "0.00")

        self.total_input.textChanged.connect(self._on_total_changed)

        form.addRow("Vendor:", self.vendor_input)
        form.addRow("Total ($):", self.total_input)
        form.addRow("Subtotal ($):", self.subtotal_input)
        form.addRow("HST 13% ($):", self.tax_input)
        
        self.set_input = QLineEdit()
        ai_set = data.get("set_number", data.get("set_num", ""))
        self.set_input.setText(str(ai_set) if ai_set else "")
        self.set_input.setPlaceholderText("Leave empty for CRAFT, 'NA' for NOT CRAFT")
        
        self.people_input = QLineEdit()
        ai_craft_type = data.get("craft_type", "")
        ai_people = data.get("craft_quantity", data.get("craft_people", ""))
        
        if ai_craft_type and str(ai_craft_type).upper() in ["LOCK UP", "OFFICE"]:
            self.people_input.setText(str(ai_craft_type).upper())
        elif ai_people:
            self.people_input.setText(str(ai_people))
            
        self.people_input.setPlaceholderText("Number of people OR 'LOCK UP' / 'OFFICE'")
        
        self.date_range_input = QLineEdit()
        ai_date_range = data.get("date_range", "")
        self.date_range_input.setText(str(ai_date_range))
        self.date_range_input.setPlaceholderText("Date Range (e.g. 0720-0724) [Optional]")
        
        form.addRow("Set #:", self.set_input)
        form.addRow("Craft Info (Qty or Type):", self.people_input)
        form.addRow("Date Range:", self.date_range_input)
        
        self.buyer_input = QLineEdit()
        ai_buyer = data.get("buyer_name", "")
        self.buyer_input.setText(str(ai_buyer))
        self.buyer_input.setPlaceholderText("Reimbursed To (e.g. LIAM COLE) [Leave blank if self]")
        try:
            from services.petty_cash_bot import get_remembered_buyers
            completer = QCompleter(get_remembered_buyers(), self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.buyer_input.setCompleter(completer)
        except Exception:
            pass
        
        owner_name = data.get("owner_name", "").upper()
        if owner_name in ["AMY WHITE", "AMY"]:
            form.addRow("Reimbursed To (Buyer):", self.buyer_input)
            
        layout.addLayout(form)
        
        btn_layout = QHBoxLayout()
        self.halt_btn = QPushButton("🛑 HALT PROCESSING")
        self.halt_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 77, 77, 0.25);
                border: 1px solid #ff4d4d;
                color: #ff9999;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(255, 77, 77, 0.5);
                color: #ffffff;
            }
        """)
        self.halt_btn.clicked.connect(self.on_halt_clicked)
        btn_layout.addWidget(self.halt_btn)

        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.accept)
        self.ok_btn.setDefault(True)
        btn_layout.addStretch()
        btn_layout.addWidget(self.ok_btn)
        
        layout.addLayout(btn_layout)

    def on_halt_clicked(self):
        self.was_halted = True
        self.reject()

    def closeEvent(self, event):
        self.was_halted = True
        super().closeEvent(event)

    def _on_total_changed(self, text):
        try:
            val = float(text.strip())
            sub = round(val / 1.13, 2)
            tx = round(val - sub, 2)
            self.subtotal_input.blockSignals(True)
            self.tax_input.blockSignals(True)
            self.subtotal_input.setText(f"{sub:.2f}")
            self.tax_input.setText(f"{tx:.2f}")
            self.subtotal_input.blockSignals(False)
            self.tax_input.blockSignals(False)
        except ValueError:
            pass
        
    def get_results(self):
        set_val = self.set_input.text().strip().upper()
        people_val = self.people_input.text().strip()
        
        if not set_val:
            is_craft = True
            final_set = "" 
        elif set_val == "NA":
            is_craft = False
            final_set = ""
        else:
            is_craft = False
            final_set = set_val
            
        quantity = 1
        craft_type = ""
        
        if people_val.upper() in ["LOCK UP", "LOCK UP CRAFT", "SET DEC CRAFT LOCK UP"]:
            craft_type = "SET DEC CRAFT LOCK UP"
        elif people_val.upper() in ["OFFICE", "OFFICE CRAFT", "SET DEC CRAFT OFFICE"]:
            craft_type = "SET DEC CRAFT OFFICE"
        elif people_val.upper() in ["BREAK", "CRAFT", "BREAK X 1", "CRAFT X 1"]:
            quantity = 1
        elif people_val.isdigit():
            quantity = int(people_val)
        elif "BREAK X" in people_val.upper() or "CRAFT X" in people_val.upper():
            try:
                clean_str = people_val.upper().replace("BREAK X", "").replace("CRAFT X", "").strip()
                quantity = int(clean_str.split()[0])
            except ValueError:
                quantity = 1
        elif people_val:
            craft_type = people_val.upper()

        try:
            total_val = float(self.total_input.text().strip())
        except ValueError:
            total_val = 0.0

        try:
            subtotal_val = float(self.subtotal_input.text().strip())
        except ValueError:
            subtotal_val = round(total_val / 1.13, 2) if total_val else 0.0

        try:
            tax_val = float(self.tax_input.text().strip())
        except ValueError:
            tax_val = round(total_val - subtotal_val, 2) if total_val else 0.0
            
        buyer_entered = self.buyer_input.text().strip()
        if buyer_entered:
            try:
                from services.petty_cash_bot import save_remembered_buyer
                save_remembered_buyer(buyer_entered)
            except Exception:
                pass

        return {
            "is_craft": is_craft,
            "set_num": final_set,
            "craft_quantity": quantity,
            "craft_type": craft_type,
            "date_range": self.date_range_input.text().strip(),
            "buyer_name": buyer_entered,
            "vendor": self.vendor_input.text().strip().upper(),
            "total": total_val,
            "subtotal": subtotal_val,
            "tax": tax_val
        }
