import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QLineEdit, QComboBox, QPushButton, QMessageBox, 
                               QFileDialog, QScrollArea, QWidget, QGridLayout)
from PySide6.QtCore import Qt, QThread, Signal
from services.ch_req_bot_service import extract_invoice_data, generate_pdf, add_business_days
from datetime import datetime

class ProcessCHReqThread(QThread):
    finished_extraction = Signal(dict)
    error = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            data = extract_invoice_data(self.file_path)
            if not data:
                self.error.emit("Failed to extract data.")
            else:
                self.finished_extraction.emit(data)
        except Exception as e:
            self.error.emit(str(e))

class CHReqDialog(QDialog):
    def __init__(self, parent=None, prefill_data=None):
        super().__init__(parent)
        self.setWindowTitle("Create Single CH REQ")
        self.setFixedSize(600, 750)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QLabel {
                font-size: 12px;
                font-weight: bold;
                color: #00ffff;
            }
            QLineEdit, QComboBox {
                background-color: #333;
                color: white;
                padding: 5px;
                border: 1px solid #00ffff;
                border-radius: 5px;
            }
            QPushButton {
                background-color: #000;
                border: 2px solid #00ffff;
                border-radius: 10px;
                color: #00ffff;
                font-weight: bold;
                font-size: 11px;
                padding: 10px;
                margin-top: 5px;
            }
            QPushButton:hover {
                background-color: #00ffff;
                color: black;
            }
            QPushButton:disabled {
                border-color: #555;
                color: #555;
            }
        """)

        self.invoice_path = None
        self.entries = {}
        self.build_ui()
        
        if prefill_data:
            self.populate_form(prefill_data)
            self.btn_generate.setEnabled(True)

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        # 1. Upload Section
        lbl1 = QLabel("1. Select Invoice (PDF/Image) [Optional for Envelopes]")
        lbl1.setStyleSheet("font-size: 14px; margin-top: 10px;")
        main_layout.addWidget(lbl1)

        self.btn_upload = QPushButton("UPLOAD INVOICE")
        self.btn_upload.clicked.connect(self.upload_invoice)
        main_layout.addWidget(self.btn_upload)

        self.lbl_file = QLabel("No file selected")
        self.lbl_file.setStyleSheet("color: #888; font-weight: normal;")
        main_layout.addWidget(self.lbl_file)

        # 2. Edit Details
        lbl2 = QLabel("2. Verify & Edit Details")
        lbl2.setStyleSheet("font-size: 14px; margin-top: 20px;")
        main_layout.addWidget(lbl2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        
        form_widget = QWidget()
        form_layout = QGridLayout(form_widget)
        
        fields = [
            ("Payee", "Payee"),
            ("Payment Type", "PaymentType"),
            ("Invoice / Ref #", "ReferenceNumber"),
            ("Date", "Date"),
            ("Address Line 1", "AddressLine1"),
            ("Address Line 2", "AddressLine2"),
            ("Contact", "Contact"),
            ("Tel", "Tel"),
            ("Total Amount", "TotalAmount"),
            ("Amount Before HST", "AmountBeforeHST"),
            ("HST Amount", "HSTAmount"),
            ("HST/SIN Number", "HSTNumber"),
            ("Episode #", "Episode"),
            ("Set /Location", "SetLocation"),
            ("Purchase or Rental", "PurchaseType"), 
            ("Rental Period", "RentalPeriod"),
            ("Details/Invoice #", "Details"),
            ("Requested By", "RequestedBy"),
            ("Date Required", "DateRequired")
        ]

        for i, (label, key) in enumerate(fields):
            lbl = QLabel(label + ":")
            lbl.setStyleSheet("color: white; font-weight: normal;")
            form_layout.addWidget(lbl, i, 0)
            
            if key == "PurchaseType":
                cb = QComboBox()
                cb.addItems(["Purchase", "Rental"])
                form_layout.addWidget(cb, i, 1)
                self.entries[key] = cb
            elif key == "PaymentType":
                cb = QComboBox()
                cb.addItems(["CH REQ", "ACH", "PO"])
                form_layout.addWidget(cb, i, 1)
                self.entries[key] = cb
            else:
                ent = QLineEdit()
                form_layout.addWidget(ent, i, 1)
                self.entries[key] = ent

        # Connect signals for vendor memory and auto-fills
        self.entries["Payee"].textChanged.connect(self._on_payee_changed)
        self.entries["PaymentType"].currentTextChanged.connect(self._on_payment_type_changed)

        # Defaults
        now = datetime.now()
        self.entries["Date"].setText(now.strftime("%d-%b-%Y"))
        date_req = add_business_days(now, 4)
        self.entries["DateRequired"].setText(date_req.strftime("%m/%d/%Y"))
        self.entries["PurchaseType"].setCurrentText("Rental")

        scroll.setWidget(form_widget)
        main_layout.addWidget(scroll)

        # 3. Generate
        self.btn_generate = QPushButton("GENERATE CH REQ")
        self.btn_generate.setEnabled(False) # Remains false until file or prefill
        self.btn_generate.clicked.connect(self.generate_ch_req)
        main_layout.addWidget(self.btn_generate)

    def upload_invoice(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Invoice", "", "PDF/Images (*.pdf *.png *.jpg *.jpeg);;All Files (*.*)")
        if not file_path:
            return

        self.invoice_path = file_path
        self.lbl_file.setText(os.path.basename(file_path))
        
        self.btn_upload.setText("EXTRACTING DATA (PLEASE WAIT)...")
        self.btn_upload.setEnabled(False)
        self.btn_generate.setEnabled(False)

        self.thread = ProcessCHReqThread(file_path)
        self.thread.finished_extraction.connect(self.populate_form)
        self.thread.error.connect(self.on_error)
        self.thread.start()

    def populate_form(self, data):
        self.btn_upload.setText("UPLOAD INVOICE")
        self.btn_upload.setEnabled(True)
        self.btn_generate.setEnabled(True)

        if "Payee" in data and data["Payee"]:
            self.entries["Payee"].setText(data["Payee"])
        if data.get("Date"):
            self.entries["Date"].setText(data.get("Date", ""))
            
        self.entries["AddressLine1"].setText(data.get("AddressLine1", ""))
        self.entries["AddressLine2"].setText(data.get("AddressLine2", ""))
        self.entries["Contact"].setText(data.get("Contact", ""))
        self.entries["Tel"].setText(data.get("Tel", ""))
        def fmt_curr(val):
            if val is None or val == "":
                return ""
            try:
                num = float(str(val).replace('$', '').replace(',', '').strip())
                return f"{num:.2f}"
            except ValueError:
                return str(val)

        tot_val = 0.0
        hst_val = 0.0
        sub_val = 0.0
        if "TotalAmount" in data and data["TotalAmount"]:
            self.entries["TotalAmount"].setText(fmt_curr(data.get("TotalAmount")))
            try:
                tot_val = float(str(data.get("TotalAmount", "")).replace('$', '').replace(',', '').strip())
            except ValueError:
                pass

        if "HSTAmount" in data and data["HSTAmount"]:
            self.entries["HSTAmount"].setText(fmt_curr(data.get("HSTAmount")))
            try:
                hst_val = float(str(data.get("HSTAmount", "")).replace('$', '').replace(',', '').strip())
            except ValueError:
                pass

        # Balance Amount Before HST
        sub_raw = data.get("AmountBeforeHST")
        try:
            sub_val = float(str(sub_raw).replace('$', '').replace(',', '').strip()) if sub_raw else 0.0
        except ValueError:
            sub_val = 0.0

        if tot_val > 0 and hst_val > 0:
            if sub_val == 0.0 or sub_val == tot_val or abs((sub_val + hst_val) - tot_val) > 0.05:
                sub_val = round(tot_val - hst_val, 2)
            self.entries["AmountBeforeHST"].setText(f"{sub_val:.2f}")
        else:
            self.entries["AmountBeforeHST"].setText(fmt_curr(sub_raw))

        self.entries["HSTNumber"].setText(data.get("HSTNumber", ""))
        if "Details" in data and data["Details"]:
            self.entries["Details"].setText(data.get("Details", ""))
        
        # Populate Reference Number (prefer InvoiceNumber or ReferenceNumber; do NOT use show names or set codes)
        ref_candidate = data.get("ReferenceNumber") or data.get("reference_number") or data.get("InvoiceNumber") or ""
        if not ref_candidate:
            po_cand = str(data.get("po_number") or "").strip()
            po_u = po_cand.upper()
            if po_cand and po_u not in ("PENDING", "NONE", "N/A", "TBD") and "SAMPLE SHOW" not in po_u and "SAMPLE" not in po_u:
                if not (len(po_cand) <= 4 and po_cand[0].isalpha() and po_cand[1:].isdigit()):
                    ref_candidate = po_cand
        if ref_candidate:
            self.entries["ReferenceNumber"].setText(str(ref_candidate))
            
        # Check remembered vendor preference (default to CH REQ or ACH, NEVER auto-switch to PO)
        payee = data.get("Payee", "")
        pref = None
        try:
            from core.settings import get_vendor_payment_pref
            pref = get_vendor_payment_pref(payee)
        except Exception:
            pass

        if pref and "ACH" in pref.upper():
            self.entries["PaymentType"].setCurrentText("ACH")
        elif data.get("payment_method") and "ach" in str(data.get("payment_method")).lower():
            self.entries["PaymentType"].setCurrentText("ACH")
        elif str(data.get("PaymentType", "")).upper() == "ACH":
            self.entries["PaymentType"].setCurrentText("ACH")
        else:
            self.entries["PaymentType"].setCurrentText("CH REQ")
        
        if data.get("SetLocation"):
            self.entries["SetLocation"].setText(data.get("SetLocation", ""))
        if data.get("RentalPeriod"):
            from services.ch_req_sheet_helper import normalize_rental_period
            self.entries["RentalPeriod"].setText(normalize_rental_period(data.get("RentalPeriod", "")))
        if data.get("RequestedBy"):
            self.entries["RequestedBy"].setText(data.get("RequestedBy", ""))
        if data.get("Episode"):
            self.entries["Episode"].setText(str(data.get("Episode", "")))
        elif data.get("SetLocation") and not self.entries["Episode"].text().strip():
            from core.set_list import derive_episode_code
            code = derive_episode_code(data.get("SetLocation"), special_tab=data.get("special_tab"))
            if code == "297":
                self.entries["Episode"].setText("AMORT")
            elif code.isdigit() and 251 <= int(code) <= 276:
                self.entries["Episode"].setText(str(int(code) - 50))

    def _on_payee_changed(self, text):
        vendor = text.strip()
        if vendor:
            try:
                from core.settings import get_vendor_profile
                prof = get_vendor_profile(vendor)
                if prof:
                    if not self.entries["AddressLine1"].text().strip() and prof.get("address1"):
                        self.entries["AddressLine1"].setText(prof["address1"])
                    if not self.entries["AddressLine2"].text().strip() and prof.get("address2"):
                        self.entries["AddressLine2"].setText(prof["address2"])
                    if not self.entries["Tel"].text().strip() and prof.get("tel"):
                        self.entries["Tel"].setText(prof["tel"])
                    if not self.entries["HSTNumber"].text().strip() and prof.get("hst_number"):
                        self.entries["HSTNumber"].setText(prof["hst_number"])
                    if not self.entries["Contact"].text().strip() and prof.get("contact"):
                        self.entries["Contact"].setText(prof["contact"])
                    if prof.get("payment_type"):
                        target = "ACH" if "ACH" in prof["payment_type"].upper() else ("PO" if "PO" in prof["payment_type"].upper() else "CH REQ")
                        if self.entries["PaymentType"].currentText() != target:
                            self.entries["PaymentType"].blockSignals(True)
                            self.entries["PaymentType"].setCurrentText(target)
                            self.entries["PaymentType"].blockSignals(False)
            except Exception as e_prof:
                print(f"DEBUG: Error auto-filling vendor profile: {e_prof}")

    def _on_payment_type_changed(self, pt):
        vendor = self.entries["Payee"].text().strip()
        if vendor and pt:
            try:
                from core.settings import set_vendor_payment_pref
                set_vendor_payment_pref(vendor, pt)
            except Exception:
                pass

    def on_error(self, err):
        self.btn_upload.setText("UPLOAD INVOICE")
        self.btn_upload.setEnabled(True)
        self.btn_generate.setEnabled(True) # Still allow manual entry
        QMessageBox.warning(self, "Extraction Failed", f"Could not extract data automatically. You can fill out the form manually.\n\nError: {err}")

    def generate_ch_req(self):
        def get_data(self):
            data = {}
            for key, widget in self.entries.items():
                if isinstance(widget, QComboBox):
                    data[key] = widget.currentText()
                else:
                    data[key] = widget.text()
                    
            if hasattr(self, "prefill_data") and self.prefill_data:
                for k, v in self.prefill_data.items():
                    if k not in self.entries:
                        data[k] = v
            return data

        data = get_data(self)
        from services.ch_req_sheet_helper import normalize_rental_period
        data["RentalPeriod"] = normalize_rental_period(data.get("RentalPeriod", ""))
        data["IsACH"] = (data.get("PaymentType") == "ACH")

        # Mathematical balance check before PDF generation
        try:
            tot_num = float(str(data.get("TotalAmount", "")).replace('$', '').replace(',', '').strip())
            hst_num = float(str(data.get("HSTAmount", "")).replace('$', '').replace(',', '').strip()) if data.get("HSTAmount") else 0.0
            sub_num = float(str(data.get("AmountBeforeHST", "")).replace('$', '').replace(',', '').strip()) if data.get("AmountBeforeHST") else 0.0
            if tot_num > 0 and hst_num > 0:
                if sub_num == tot_num or abs((sub_num + hst_num) - tot_num) > 0.05 or sub_num == 0.0:
                    sub_num = round(tot_num - hst_num, 2)
                    data["AmountBeforeHST"] = f"{sub_num:.2f}"
                    self.entries["AmountBeforeHST"].setText(f"{sub_num:.2f}")
        except Exception:
            pass

        if not data.get("Payee"):
            QMessageBox.warning(self, "Missing Data", "Please enter a Payee.")
            return

        self.btn_generate.setText("GENERATING...")
        self.btn_generate.setEnabled(False)

        try:
            output_path = generate_pdf(self.invoice_path, data)
            
            # --- Remember Vendor Profile (New Address, Name, Tel, HST#, Payment Type) ---
            try:
                from core.settings import save_vendor_profile
                save_vendor_profile(data.get("Payee", ""), {
                    "payee": data.get("Payee", ""),
                    "address1": data.get("AddressLine1", ""),
                    "address2": data.get("AddressLine2", ""),
                    "tel": data.get("Tel", ""),
                    "hst_number": data.get("HSTNumber", ""),
                    "contact": data.get("Contact", ""),
                    "payment_type": data.get("PaymentType", "")
                })
            except Exception as e_save_p:
                print(f"DEBUG: Could not remember vendor profile: {e_save_p}")
            # -----------------------------------------------------------------------------

            # --- Record to Cheque Request Tracker & Google Sheets ---
            try:
                from services.ch_req_sheet_helper import record_cheque_request
                data["pdf_path"] = output_path
                record_cheque_request(data)
            except Exception as ex_record:
                print(f"DEBUG: Error recording cheque request: {ex_record}")
            # --------------------------------------------------------

            os.startfile(output_path) # Pop open the PDF!
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate CH REQ:\n{str(e)}")
        finally:
            self.btn_generate.setText("GENERATE CH REQ")
            self.btn_generate.setEnabled(True)
