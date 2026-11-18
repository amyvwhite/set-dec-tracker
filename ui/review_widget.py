from datetime import datetime
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QFormLayout, QPushButton, QGraphicsView, QGraphicsScene, QMessageBox, QTextEdit, QCheckBox, QScrollArea, QFrame, QComboBox, QFileDialog
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from core.database import get_pending_receipts, update_receipt, check_for_duplicate, get_connection, get_receipt_by_path
from services.sheets import append_receipt_to_sheet
from core.file_manager import move_and_rename_receipt, move_to_checkme
from core.logic import process_receipt_splits
from services.sheets import delete_receipt_from_sheet
from core.settings import load_settings
import sys
import os
import json
import subprocess
import fitz
import sqlite3
import re

class ReceiptImageViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        
    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.scale(1.05, 1.05)
        else:
            self.scale(1.0 / 1.05, 1.0 / 1.05)

class ReviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.current_receipt = None
        self.pending_receipts = []
        self.skip_offset = 0
        
        layout = QHBoxLayout(self)
        
        # Left side - Image Viewer
        left_layout = QVBoxLayout()
        self.image_view = ReceiptImageViewer()
        self.image_scene = QGraphicsScene()
        self.image_view.setScene(self.image_scene)
        self.image_view.setStyleSheet("border: 1px solid #444; background-color: #1e1e1e;")
        
        title_label = QLabel("Receipt Image Viewer (Scroll/Trackpad to Zoom, Click & Drag to Pan)")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        left_layout.addWidget(title_label)
        left_layout.addWidget(self.image_view)
        
        btn_layout = QHBoxLayout()
        self.rotate_btn = QPushButton("Rotate Image")
        self.rotate_btn.setStyleSheet("padding: 8px; background-color: #444; font-weight: bold;")
        self.rotate_btn.clicked.connect(self.rotate_image)
        btn_layout.addWidget(self.rotate_btn)
        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)
        
        layout.addLayout(left_layout, stretch=2)
        
        # Right side - Editable Form
        right_panel = QWidget()
        right_panel_layout = QVBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(5, 5, 5, 5)
        right_panel_layout.setSpacing(5)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("border: none; background-color: #0a0a0a;")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: #0a0a0a;")
        right_layout = QVBoxLayout(scroll_content)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(6)
        self.scroll_area.setWidget(scroll_content)
        
        form_title = QLabel("DATA EXTRACTION")
        form_title.setStyleSheet("font-size: 13px; font-weight: bold; letter-spacing: 2px; color: #888; margin-bottom: 2px;")
        right_layout.addWidget(form_title)

        self.duplicate_warning = QLabel("⚠️ DUPLICATE DETECTED")
        self.duplicate_warning.setStyleSheet("color: #80dfff; font-weight: bold; background-color: #002233; padding: 6px; border: 1px solid #80dfff; font-size: 11px;")
        self.duplicate_warning.setVisible(False)
        right_layout.addWidget(self.duplicate_warning)

        # Helper to create styled LineEdits and Labels
        self.fields = {}

        def make_field(name):
            le = QLineEdit()
            le.setStyleSheet("""
                QLineEdit {
                    padding: 4px 6px; 
                    background-color: #1a1a1a; 
                    border: 1px solid #333; 
                    color: white; 
                    font-size: 12px;
                }
                QLineEdit:focus { border-color: #00f2ff; }
            """)
            if name == "Episode Code":
                orig_focus = le.focusInEvent
                def ep_focus(event):
                    orig_focus(event)
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, le.selectAll)
                le.focusInEvent = ep_focus
            self.fields[name] = le
            return le

        def make_label(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #bbb; font-size: 10px; font-weight: bold; text-transform: uppercase;")
            return lbl

        # Create all field widgets
        field_names = [
            "Episode Code", "Set #", "Buyer Name", "Vendor", 
            "Subtotal", "Shipping", "Import Fees", "Tax", "Total", "Payment Method", 
            "Date", "Ref #", "PO #", "# of People", "Rental End Date", "Notes"
        ]
        for name in field_names:
            make_field(name)

        # Special Tab combobox
        from PySide6.QtWidgets import QComboBox
        special_cb = QComboBox()
        special_cb.setEditable(True)
        special_cb.addItems(["", "203-T", "ELECT", "EQUIP", "EXT", "L&D", "PROD", "SECT", "SHIP", "TRANS"])
        special_cb.setStyleSheet("""
            QComboBox {
                padding: 4px 6px; 
                background-color: #1a1a1a; 
                border: 1px solid #333; 
                color: white; 
                font-size: 12px;
            }
            QComboBox:focus { border-color: #00f2ff; }
        """)
        self.fields["Special Tab"] = special_cb

        # Compact Multi-Column Form Layouts
        # Row 1: Episode Code, Set #, Special Tab
        r1 = QHBoxLayout()
        v1 = QVBoxLayout(); v1.setSpacing(2); v1.addWidget(make_label("Episode Code:")); v1.addWidget(self.fields["Episode Code"])
        v2 = QVBoxLayout(); v2.setSpacing(2); v2.addWidget(make_label("Set #:")); v2.addWidget(self.fields["Set #"])
        v3 = QVBoxLayout(); v3.setSpacing(2); v3.addWidget(make_label("Special Tab:")); v3.addWidget(self.fields["Special Tab"])
        r1.addLayout(v1, 1); r1.addLayout(v2, 1); r1.addLayout(v3, 1)
        right_layout.addLayout(r1)

        # Row 2: Buyer Name, Vendor
        r2 = QHBoxLayout()
        v4 = QVBoxLayout(); v4.setSpacing(2); v4.addWidget(make_label("Buyer Name:")); v4.addWidget(self.fields["Buyer Name"])
        v5 = QVBoxLayout(); v5.setSpacing(2); v5.addWidget(make_label("Vendor:")); v5.addWidget(self.fields["Vendor"])
        r2.addLayout(v4, 1); r2.addLayout(v5, 1)
        right_layout.addLayout(r2)

        # Row 3: Subtotal, Shipping, Import Fees, Tax, Total
        r3 = QHBoxLayout()
        v6 = QVBoxLayout(); v6.setSpacing(2); v6.addWidget(make_label("Subtotal:")); v6.addWidget(self.fields["Subtotal"])
        v7 = QVBoxLayout(); v7.setSpacing(2); v7.addWidget(make_label("Shipping:")); v7.addWidget(self.fields["Shipping"])
        v8 = QVBoxLayout(); v8.setSpacing(2); v8.addWidget(make_label("Import Fees:")); v8.addWidget(self.fields["Import Fees"])
        v9 = QVBoxLayout(); v9.setSpacing(2); v9.addWidget(make_label("Tax:")); v9.addWidget(self.fields["Tax"])
        v10 = QVBoxLayout(); v10.setSpacing(2); v10.addWidget(make_label("Total:")); v10.addWidget(self.fields["Total"])
        r3.addLayout(v6, 1); r3.addLayout(v7, 1); r3.addLayout(v8, 1); r3.addLayout(v9, 1); r3.addLayout(v10, 1)
        right_layout.addLayout(r3)

        # Row 4: Payment Method, Date, Rental End Date, # of People
        r4 = QHBoxLayout()
        v11 = QVBoxLayout(); v11.setSpacing(2); v11.addWidget(make_label("Payment Method:")); v11.addWidget(self.fields["Payment Method"])
        v12 = QVBoxLayout(); v12.setSpacing(2); v12.addWidget(make_label("Date:")); v12.addWidget(self.fields["Date"])
        v13 = QVBoxLayout(); v13.setSpacing(2); v13.addWidget(make_label("Rental End Date:")); v13.addWidget(self.fields["Rental End Date"])
        v14 = QVBoxLayout(); v14.setSpacing(2); v14.addWidget(make_label("# of People:")); v14.addWidget(self.fields["# of People"])
        r4.addLayout(v11, 1); r4.addLayout(v12, 1); r4.addLayout(v13, 1); r4.addLayout(v14, 1)
        right_layout.addLayout(r4)

        # Row 5: Ref #, PO #, Notes
        r5 = QHBoxLayout()
        v15 = QVBoxLayout(); v15.setSpacing(2); v15.addWidget(make_label("Ref #:")); v15.addWidget(self.fields["Ref #"])
        v16 = QVBoxLayout(); v16.setSpacing(2); v16.addWidget(make_label("PO #:")); v16.addWidget(self.fields["PO #"])
        v17 = QVBoxLayout(); v17.setSpacing(2); v17.addWidget(make_label("Notes:")); v17.addWidget(self.fields["Notes"])
        r5.addLayout(v15, 1); r5.addLayout(v16, 1); r5.addLayout(v17, 1)
        right_layout.addLayout(r5)

        # Checkboxes Section - 3-Column Grid
        from PySide6.QtWidgets import QCheckBox, QGridLayout
        
        self.rental_checkbox = QCheckBox("Is Rental?")
        self.rental_checkbox.setStyleSheet("color: white; font-size: 12px; font-weight: bold;")
        
        self.greens_checkbox = QCheckBox("GREENS?")
        self.greens_checkbox.setStyleSheet("color: #4CAF50; font-size: 12px; font-weight: bold;")
        
        self.craft_checkbox = QCheckBox("CRAFT?")
        self.craft_checkbox.setStyleSheet("color: #d2b3ff; font-size: 12px; font-weight: bold;")
        
        self.gas_checkbox = QCheckBox("GAS?")
        self.gas_checkbox.setStyleSheet("color: #ffd9b3; font-size: 12px; font-weight: bold;")
        
        self.parking_checkbox = QCheckBox("PARKING?")
        self.parking_checkbox.setStyleSheet("color: #aa00ff; font-size: 12px; font-weight: bold;")
        
        self.ch_req_checkbox = QCheckBox("CH REQ?")
        self.ch_req_checkbox.setStyleSheet("color: #c2c2d6; font-size: 12px; font-weight: bold;")
        
        self.po_rev_checkbox = QCheckBox("PO REVISION?")
        self.po_rev_checkbox.setStyleSheet("color: #ffd9b3; font-size: 12px; font-weight: bold;")
        
        self.asset_checkbox = QCheckBox("ASSET (>$1000)?")
        self.asset_checkbox.setStyleSheet("color: #ffd9b3; font-size: 12px; font-weight: bold;")
        
        self.usd_checkbox = QCheckBox("USD?")
        self.usd_checkbox.setStyleSheet("color: #00ff99; font-size: 12px; font-weight: bold;")
        
        self.fields["Exchange Rate"] = QLineEdit("1.41")
        self.fields["Exchange Rate"].setFixedWidth(50)
        self.fields["Exchange Rate"].setStyleSheet("padding: 2px 4px; background-color: #1a1a1a; border: 1px solid #333; color: white; font-size: 11px;")
        self.fields["Exchange Rate"].setVisible(False)
        self.rate_label = QLabel("Rate:")
        self.rate_label.setStyleSheet("color: #bbb; font-size: 10px;")
        self.rate_label.setVisible(False)
        
        cb_grid = QGridLayout()
        cb_grid.setSpacing(6)
        cb_grid.addWidget(self.rental_checkbox, 0, 0)
        cb_grid.addWidget(self.greens_checkbox, 0, 1)
        cb_grid.addWidget(self.craft_checkbox, 0, 2)
        
        cb_grid.addWidget(self.gas_checkbox, 1, 0)
        cb_grid.addWidget(self.parking_checkbox, 1, 1)
        cb_grid.addWidget(self.asset_checkbox, 1, 2)
        
        cb_grid.addWidget(self.ch_req_checkbox, 2, 0)
        cb_grid.addWidget(self.po_rev_checkbox, 2, 1)
        
        usd_box = QHBoxLayout()
        usd_box.addWidget(self.usd_checkbox)
        usd_box.addWidget(self.rate_label)
        usd_box.addWidget(self.fields["Exchange Rate"])
        usd_box.addStretch()
        cb_grid.addLayout(usd_box, 3, 0, 1, 3)

        right_layout.addLayout(cb_grid)

        # Connect signals once at initialization
        self.rental_checkbox.toggled.connect(self.on_rental_toggled)
        self.greens_checkbox.toggled.connect(self.on_greens_toggled)
        self.craft_checkbox.toggled.connect(self.on_craft_toggled)
        self.gas_checkbox.toggled.connect(self.on_gas_toggled)
        self.parking_checkbox.toggled.connect(self.on_parking_toggled)
        self.ch_req_checkbox.toggled.connect(self.on_ch_req_toggled)
        self.asset_checkbox.toggled.connect(self.on_asset_toggled)
        self.usd_checkbox.toggled.connect(self.on_usd_toggled)
        
        self.fields["# of People"].textChanged.connect(self.update_craft_description)
        self.fields["Date"].textChanged.connect(self.update_craft_description)
        self.fields["Date"].textChanged.connect(self.update_parking_description)
        self.fields["Date"].textChanged.connect(self.populate_form_dynamic_only)
        
        # Live Duplicate Checking
        self.fields["Vendor"].textChanged.connect(self.recheck_duplicates)
        self.fields["Vendor"].textChanged.connect(self.update_parking_description)
        self.fields["Date"].textChanged.connect(self.recheck_duplicates)
        self.fields["Total"].textChanged.connect(self.recheck_duplicates)
        self.fields["Ref #"].textChanged.connect(self.recheck_duplicates)
        self.fields["PO #"].textChanged.connect(self.recheck_duplicates)
        self.fields["Special Tab"].currentTextChanged.connect(self.on_special_tab_changed)
        self.fields["Set #"].textChanged.connect(self.on_set_number_changed)

        # Description as TextEdit (compact)
        desc_layout = QVBoxLayout()
        desc_layout.setSpacing(2)
        desc_layout.addWidget(make_label("Description:"))
        self.fields["Description"] = QTextEdit()
        self.fields["Description"].setStyleSheet("""
            QTextEdit {
                padding: 4px 6px; 
                background-color: #1a1a1a; 
                border: 1px solid #333; 
                color: white; 
                font-size: 12px;
            }
            QTextEdit:focus { border-color: #00f2ff; }
        """)
        self.fields["Description"].setMaximumHeight(50)
        desc_layout.addWidget(self.fields["Description"])
        right_layout.addLayout(desc_layout)

        # Expense Accounting Section
        expense_title = QLabel("EXPENSE ACCOUNTING (FOR BOT)")
        expense_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #00f2ff; margin-top: 4px; margin-bottom: 2px;")
        right_layout.addWidget(expense_title)

        expense_row = QHBoxLayout()
        
        # ACCOUNT
        v_acc = QVBoxLayout(); v_acc.setSpacing(2); v_acc.addWidget(make_label("ACCOUNT:"))
        le_acc = QLineEdit(); le_acc.setStyleSheet("padding: 4px; background-color: #1a1a1a; border: 1px solid #333; color: #00f2ff; font-size: 12px;")
        self.fields["account_code"] = le_acc
        v_acc.addWidget(le_acc)
        expense_row.addLayout(v_acc, 1)

        # INS
        v_ins = QVBoxLayout(); v_ins.setSpacing(2); v_ins.addWidget(make_label("INS (Tax Credit):"))
        cb_ins = QComboBox(); cb_ins.addItems(["", "40", "41", "42", "44", "45", "46", "99"])
        cb_ins.setStyleSheet("padding: 4px; background-color: #1a1a1a; border: 1px solid #333; color: #00f2ff; font-size: 12px;")
        self.fields["tax_code"] = cb_ins
        v_ins.addWidget(cb_ins)
        expense_row.addLayout(v_ins, 1)

        # Row 2 ACCOUNT (HST)
        v_hst = QVBoxLayout(); v_hst.setSpacing(2); v_hst.addWidget(make_label("Row 2 ACCOUNT (HST):"))
        le_hst = QLineEdit(); le_hst.setStyleSheet("padding: 4px; background-color: #1a1a1a; border: 1px solid #333; color: #00f2ff; font-size: 12px;")
        self.fields["hst_account"] = le_hst
        v_hst.addWidget(le_hst)
        expense_row.addLayout(v_hst, 1)

        right_layout.addLayout(expense_row)

        right_panel_layout.addWidget(self.scroll_area, stretch=1)

        # Action Buttons Fixed Bar (at bottom of Right Panel, outside ScrollArea!)
        action_bar = QWidget()
        action_bar.setStyleSheet("background-color: #0d0d0d; border-top: 1px solid #222; padding-top: 4px;")
        action_bar_layout = QVBoxLayout(action_bar)
        action_bar_layout.setContentsMargins(4, 4, 4, 4)
        action_bar_layout.setSpacing(4)

        self.skip_btn = QPushButton("SKIP")
        self.skip_btn.setFixedHeight(34)
        self.skip_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: 1px solid #80dfff; color: #80dfff; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #80dfff; color: black; }
        """)
        self.skip_btn.clicked.connect(self.skip_receipt)
        
        self.approve_btn = QPushButton("APPROVE")
        self.approve_btn.setFixedHeight(34)
        self.approve_btn.setStyleSheet("""
            QPushButton { background-color: #00f2ff; border: 1px solid #00f2ff; color: black; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #80f9ff; }
        """)
        self.approve_btn.clicked.connect(self.approve_receipt)
        
        self.retry_btn = QPushButton("RE-TRY AI")
        self.retry_btn.setFixedHeight(34)
        self.retry_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: 1px solid #ffffb3; color: #ffffb3; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #ffffb3; color: black; }
        """)
        self.retry_btn.clicked.connect(self.retry_ai_extraction)
        
        self.delete_btn = QPushButton("DELETE")
        self.delete_btn.setFixedHeight(34)
        self.delete_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: 1px solid #888; color: #888; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: white; color: black; }
        """)
        self.delete_btn.clicked.connect(self.delete_current_receipt)

        self.replace_btn = QPushButton("REPLACE ORIGINAL")
        self.replace_btn.setFixedHeight(34)
        self.replace_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: 1px solid #ffd9b3; color: #ffd9b3; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #ffd9b3; color: black; }
        """)
        self.replace_btn.clicked.connect(self.replace_original_receipt)

        action_layout1 = QHBoxLayout()
        action_layout1.setSpacing(6)
        action_layout1.addWidget(self.skip_btn)
        action_layout1.addWidget(self.retry_btn)
        action_layout1.addWidget(self.replace_btn)
        
        action_layout2 = QHBoxLayout()
        action_layout2.setSpacing(6)
        action_layout2.addWidget(self.delete_btn)
        action_layout2.addWidget(self.approve_btn)
        
        action_bar_layout.addLayout(action_layout1)
        action_bar_layout.addLayout(action_layout2)

        right_panel_layout.addWidget(action_bar, stretch=0)

        layout.addWidget(right_panel, stretch=1)

    def load_next_receipt(self):
        while True:
            self.pending_receipts = get_pending_receipts()
            if not self.pending_receipts:
                # QMessageBox.information(self, "Done", "No more receipts to review!")
                if self.parent_window:
                    self.parent_window.home_widget.update_review_btn()
                    self.parent_window.switch_view(0)
                return
                
            if not hasattr(self, 'skip_offset'):
                self.skip_offset = 0
            if self.skip_offset >= len(self.pending_receipts):
                self.skip_offset = 0
                
            self.current_receipt = self.pending_receipts[self.skip_offset]
            if os.path.exists(self.current_receipt.file_path):
                break
            else:
                # Ghost entry! File was deleted manually. Clean it up from DB.
                from core.database import get_connection
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute('DELETE FROM receipts WHERE id = ?', (self.current_receipt.id,))
                conn.commit()
                conn.close()
                
        self.populate_form()
        self.load_image()
        self.scroll_area.verticalScrollBar().setValue(0)

    def retry_ai_extraction(self):
        if not self.current_receipt: return
        self.retry_btn.setText("⏳ ...")
        self.retry_btn.setEnabled(False)
        
        from core.threads import ProcessFolderThread
        # We reuse the existing logic by creating a thread for just this one file
        self.retry_thread = ProcessFolderThread(os.path.dirname(self.current_receipt.file_path))
        self.retry_thread.files_to_process = [self.current_receipt.file_path]
        self.retry_thread.force_reprocess = True
        
        def on_done():
            self.retry_btn.setText("RE-TRY AI")
            self.retry_btn.setEnabled(True)
            # Re-fetch the receipt from DB to get updated fields
            from core.database import get_connection
            from core.models import Receipt
            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM receipts WHERE id = ?', (self.current_receipt.id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                self.current_receipt = Receipt(
                    id=row['id'], file_path=row['file_path'], file_hash=row['file_hash'], set_number=row['set_number'],
                    buyer_name=row['buyer_name'], description=row['description'], vendor=row['vendor'], subtotal=row['subtotal'],
                    tax=row['tax'], total=row['total'], payment_method=row['payment_method'], date=row['date'],
                    reference_number=row['reference_number'], po_number=row['po_number'], is_rental=bool(row['is_rental']),
                    rental_end_date=row['rental_end_date'], notes=row['notes'], status=row['status'], created_at=row['created_at'],
                    is_greens=bool(row['is_greens']), is_craft=bool(row['is_craft']), is_gas=bool(row['is_gas']), is_parking=bool(row['is_parking']),
                    craft_people=row['craft_people'], episode_code=row['episode_code'], co_code=row['co_code'], loc_code=row['loc_code'], 
                    account_code=row['account_code'], tax_code=row['tax_code'], hst_account=row['hst_account'], expense_only=bool(row['expense_only']),
                    is_usd=bool(row['is_usd']) if 'is_usd' in row.keys() else False, 
                    exchange_rate=row['exchange_rate'] if 'exchange_rate' in row.keys() else None
                )
                self.populate_form()
                
        self.retry_thread.finished_processing.connect(on_done)
        self.retry_thread.start()
        
    def recheck_duplicates(self):
        if not hasattr(self, 'current_receipt') or not self.current_receipt:
            return
            
        # Get live values from UI
        vendor = self.fields["Vendor"].text().strip()
        date = self.fields["Date"].text().strip()
        
        try:
            total_val = float(self.fields["Total"].text().replace('$', '').replace(',', '').strip() or 0)
        except:
            total_val = self.current_receipt.total
            
        ref_num = self.fields["Ref #"].text().strip()
        po_num = self.fields["PO #"].text().strip()
        
        dup = check_for_duplicate(
            vendor, date, total_val,
            ref_num=ref_num,
            po_num=po_num,
            exclude_id=self.current_receipt.id
        )
        
        if dup:
            import os
            folder = os.path.basename(os.path.dirname(dup.file_path))
            filename = os.path.basename(dup.file_path)
            self.duplicate_warning.setText(f"?? DUPLICATE DETECTED!\nORIGINAL FOUND IN: {folder.upper()}\nFILE: {filename}\nAPPROVED ON: {dup.created_at}")
            self.duplicate_warning.setVisible(True)
            self.delete_btn.setStyleSheet("""
                QPushButton { background-color: #80dfff; border: 2px solid #80dfff; color: black; font-weight: bold; font-size: 11px; }
                QPushButton:hover { background-color: #33ccff; }
            """)
            self.delete_btn.setText("DELETE DUPLICATE")
        else:
            self.duplicate_warning.setVisible(False)
            self.delete_btn.setStyleSheet("""
                QPushButton { background-color: transparent; border: 1px solid #888; color: #888; font-weight: bold; font-size: 11px; }
                QPushButton:hover { background-color: white; color: black; }
            """)
            self.delete_btn.setText("DELETE")
            
    def set_form_signals_blocked(self, blocked: bool):
        for widget in self.fields.values():
            widget.blockSignals(blocked)
        self.rental_checkbox.blockSignals(blocked)
        self.greens_checkbox.blockSignals(blocked)
        self.craft_checkbox.blockSignals(blocked)
        self.gas_checkbox.blockSignals(blocked)
        self.parking_checkbox.blockSignals(blocked)
        self.ch_req_checkbox.blockSignals(blocked)
        self.asset_checkbox.blockSignals(blocked)
        self.usd_checkbox.blockSignals(blocked)

    def populate_form(self):
        r = self.current_receipt
        if not r:
            return

        self.set_form_signals_blocked(True)
        try:
            settings = load_settings()
            # 1. Reset & Set Checkboxes explicitly based on current receipt r
            is_rent = bool(r.is_rental)
            self.rental_checkbox.setChecked(is_rent)
            self.craft_checkbox.setChecked(bool(r.is_craft))
            self.gas_checkbox.setChecked(bool(getattr(r, 'is_gas', False)))
            self.parking_checkbox.setChecked(bool(getattr(r, 'is_parking', False)))
            self.ch_req_checkbox.setChecked(False)  # Reset CH REQ to False for every new receipt!
            if is_rent:
                self.asset_checkbox.setChecked(False)
            else:
                self.asset_checkbox.setChecked(bool(getattr(r, 'is_asset', False)) or (r.total is not None and r.total > 1000))
            self.usd_checkbox.setChecked(bool(getattr(r, 'is_usd', False)))

            # Auto-detect GREENS strictly if buyer is JAN/MILO, card ends in 7519/3385, or GREENS is written
            buyer_u = str(r.buyer_name or "").upper()
            notes_u = str(r.notes or "").upper()
            ref_u = str(r.reference_number or "").upper()
            pm_u = str(r.payment_method or "").upper()
            set_u = str(r.set_number or "").upper()
            desc_u = str(r.description or "").upper()
            v_u = str(r.vendor or "").upper()

            from core.settings import is_greens_buyer
            is_greens = False
            if is_greens_buyer(buyer_u):
                is_greens = True
            elif any(card in notes_u or card in ref_u or card in set_u or card in pm_u for card in ["7519", "3385"]):
                is_greens = True
            elif "GREENS" in set_u or "GREENS" in notes_u or "GREENS" in ref_u or "GREENS" in desc_u or "GREENS" in v_u:
                is_greens = True
            elif bool(r.is_greens) and set_u == "GREENS":
                is_greens = True

            self.greens_checkbox.setChecked(is_greens)

            # Auto-detect GAS if vendor/desc contains gas keywords or is_gas is set
            is_gas = bool(getattr(r, 'is_gas', False))
            gas_keywords = ["PETRO", "SHELL", "ESSO", "PIONEER", "ULTRAMAR", "HUSKY", "CHEVRON", "MOBIL", "IRVING", "GAS", "FUEL"]
            v_upper = str(r.vendor or "").upper()
            d_upper = str(r.description or "").upper()
            s_upper = str(r.set_number or "").upper()
            if not is_gas and any(k in v_upper or k in d_upper for k in gas_keywords):
                is_gas = True

            if is_gas:
                r.is_gas = True
                r.is_craft = False
                self.gas_checkbox.setChecked(True)
                self.craft_checkbox.setChecked(False)
                if r.total is not None and r.total != 0.0:
                    if r.tax is None or r.tax == 0.0 or r.subtotal == r.total or r.subtotal == 0.0:
                        sign = -1.0 if r.total < 0 else 1.0
                        abs_tot = abs(r.total)
                        abs_sub = round(abs_tot / 1.13, 2)
                        abs_tax = round(abs_tot - abs_sub, 2)
                        r.subtotal = sign * abs_sub
                        r.tax = sign * abs_tax

            # Auto-detect PARKING if vendor/desc/set contains parking keywords or is_parking is set
            is_parking = bool(r.is_parking)
            parking_keywords = ["PARKING", "PARK", "PRK", "TORPRK", "TORPRKAUT", "TPA", "GREEN P", "IMPARK", "INDIGO", "PRESTO", "METER", "PAYBYPHONE", "HONK", "CITY OF TORONTO"]
            if not is_parking and any(k in v_upper or k in d_upper or k in s_upper for k in parking_keywords):
                is_parking = True
            self.parking_checkbox.setChecked(is_parking)

            if is_parking and r.total is not None and r.total != 0.0:
                if r.tax is None or r.tax == 0.0 or r.subtotal == r.total or r.subtotal == 0.0:
                    sign = -1.0 if r.total < 0 else 1.0
                    abs_tot = abs(r.total)
                    abs_sub = round(abs_tot / 1.13, 2)
                    abs_tax = round(abs_tot - abs_sub, 2)
                    r.subtotal = sign * abs_sub
                    r.tax = sign * abs_tax

            # 2. Populate Standard Line Edit Fields
            if is_parking or self.craft_checkbox.isChecked():
                self.fields["Episode Code"].setText("297")
            else:
                self.fields["Episode Code"].setText(str(r.episode_code or ""))
            
            # Set # preservation: Keep actual written set number if present
            set_val = str(r.set_number or "").strip()
            if self.craft_checkbox.isChecked() or is_parking:
                set_val = ""
            elif not set_val and is_greens:
                set_val = "GREENS"
            self.fields["Set #"].setText(set_val)

            # Auto-detect 203-T (203 Tandem & 2nd Unit)
            is_203_t = False
            sp_tab_val = str(r.special_tab or "").strip().upper()
            if sp_tab_val == "203-T":
                is_203_t = True
            elif any(k in set_u or k in notes_u or k in desc_u for k in ["203-T", "203 TANDEM", "203T"]):
                is_203_t = True

            if is_203_t:
                self.fields["Special Tab"].setCurrentText("203-T")
                self.fields["Episode Code"].setText("253")
                self.fields["account_code"].setText("4004")
                self.fields["Set #"].setText("")
                set_val = ""
                # Detect tandem set name if present
                combined_t = f"{set_u} {notes_u} {desc_u}".upper()
                detected_tandem = ""
                if "FANCY" in combined_t or "RESTAURANT" in combined_t or "C26" in combined_t:
                    detected_tandem = "FANCY RESTAURANT"
                elif "DITTY" in combined_t:
                    detected_tandem = "EXT DITTY LANE"
                elif "POLICE" in combined_t:
                    detected_tandem = "EXT POLICE STATION"
                if detected_tandem:
                    cur_notes = self.fields["Notes"].text().strip()
                    if not cur_notes:
                        self.fields["Notes"].setText(detected_tandem)
                    elif detected_tandem not in cur_notes.upper():
                        self.fields["Notes"].setText(f"{detected_tandem} {cur_notes}".strip())
            else:
                self.fields["Special Tab"].setCurrentText(str(r.special_tab or ""))
            self.fields["Buyer Name"].setText(str(r.buyer_name or ""))
            self.fields["# of People"].setText(str(r.craft_people or ""))
            self.fields["Vendor"].setText(str(r.vendor or ""))
            self.fields["Subtotal"].setText(f"{r.subtotal:.2f}" if r.subtotal else "")
            self.fields["Shipping"].setText(f"{r.shipping:.2f}" if r.shipping else "")
            self.fields["Import Fees"].setText(f"{r.import_fees:.2f}" if getattr(r, 'import_fees', None) else "")
            self.fields["Tax"].setText(f"{r.tax:.2f}" if r.tax else "")
            self.fields["Total"].setText(str(r.total or ""))
            self.fields["Payment Method"].setText(str(r.payment_method or ""))
            clean_date = str(r.date or "").strip()
            if clean_date:
                from dateutil import parser
                try:
                    parsed_date = parser.parse(clean_date, fuzzy=True)
                    clean_date = parsed_date.strftime("%b %d").upper().replace("SEP ", "SEPT ")
                except:
                    pass
            self.fields["Date"].setText(clean_date)
            self.fields["Ref #"].setText(str(r.reference_number or ""))
            self.fields["PO #"].setText(str(r.po_number or ""))
            
            clean_rental = str(r.rental_end_date or "").strip()
            if clean_rental:
                try:
                    from dateutil import parser
                    parsed_rental = parser.parse(clean_rental, fuzzy=True)
                    # Use str(day) to avoid zero padding (e.g. '2' instead of '02')
                    clean_rental = f"{parsed_rental.day}-{parsed_rental.strftime('%b').capitalize()}"
                except:
                    pass
            self.fields["Rental End Date"].setText(clean_rental)
            
            self.fields["Notes"].setText(str(r.notes or ""))

            if getattr(r, 'exchange_rate', None):
                self.fields["Exchange Rate"].setText(str(r.exchange_rate))
            else:
                default_rate = settings.get("default_usd_exchange_rate", "1.41")
                self.fields["Exchange Rate"].setText(str(default_rate))
            self.fields["Exchange Rate"].setVisible(self.usd_checkbox.isChecked())
            self.rate_label.setVisible(self.usd_checkbox.isChecked())

            # 3. Populate Description (craft / parking format vs actual receipt description)
            if self.craft_checkbox.isChecked():
                self.update_craft_description()
            elif is_parking or self.parking_checkbox.isChecked():
                self.update_parking_description()
            else:
                self.fields["Description"].setPlainText(str(r.description or ""))

            # 4. Episode Code Mapping
            from core.set_list import derive_episode_code
            epi_derived = derive_episode_code(
                set_input=str(set_val or r.set_number or ""),
                special_tab=str(self.fields["Special Tab"].currentText() or r.special_tab or "")
            )
            if epi_derived:
                self.fields["Episode Code"].setText(epi_derived)
                if is_203_t:
                    self.fields["Set #"].setText("")
                has_mapped = True
            else:
                set_num_upper = str(set_val).strip().upper()
                has_mapped = False
                try:
                    import json
                    mappings_str = settings.get("episode_prefix_mappings", "[]")
                    prefix_mappings = json.loads(mappings_str)
                    prefix_mappings.sort(key=lambda x: len(x.get("prefix", "")), reverse=True)
                    for m in prefix_mappings:
                        prefix = str(m.get("prefix", "")).strip().upper()
                        if prefix and set_num_upper.startswith(prefix):
                            self.fields["Episode Code"].setText(m.get("code", ""))
                            has_mapped = True
                            break
                except Exception as e:
                    print("Error matching episode code from prefix mappings:", e)

            if not has_mapped and r.date:
                try:
                    from dateutil import parser as date_parser
                    mappings_str = load_settings().get("episode_date_mappings", "[]")
                    mappings = json.loads(mappings_str)
                    r_date = date_parser.parse(r.date, fuzzy=True)
                    for m in mappings:
                        if m.get("start") and m.get("end") and m.get("code"):
                            try:
                                s_date = date_parser.parse(m["start"], fuzzy=True)
                                e_date = date_parser.parse(m["end"], fuzzy=True)
                                if s_date <= r_date <= e_date:
                                    self.fields["Episode Code"].setText(m["code"])
                                    has_mapped = True
                                    break
                            except ValueError:
                                pass
                except Exception as e:
                    print("Error calculating episode code from date:", e)

            if not has_mapped:
                self.fields["Episode Code"].setText(load_settings().get("expense_episode_code", "EP01"))

            # 5. Populate Acc/Tax fields dynamically
            self.populate_form_dynamic_only()

            is_special_acc = (is_greens or self.craft_checkbox.isChecked() or self.gas_checkbox.isChecked() or self.parking_checkbox.isChecked() or self.rental_checkbox.isChecked() or is_203_t)
            if not is_special_acc and r.account_code and r.account_code.strip():
                clean_acc = r.account_code.strip().split('-')[0]
                if clean_acc and clean_acc not in ["2493", "2493-000"]:
                    self.fields["account_code"].setText(clean_acc)

            if r.tax_code and r.tax_code.strip():
                idx = self.fields["tax_code"].findText(r.tax_code.strip())
                if idx >= 0:
                    self.fields["tax_code"].setCurrentIndex(idx)

            # Only use saved r.hst_account if dynamic lookup from date was empty
            if not self.fields["hst_account"].text().strip() and r.hst_account and r.hst_account.strip() and not r.hst_account.upper().startswith("A"):
                clean_hst = r.hst_account.strip().split('-')[0]
                if clean_hst:
                    self.fields["hst_account"].setText(clean_hst)

            # 6. Check for semantic duplicates
            dup = check_for_duplicate(
                r.vendor, r.date, r.total,
                ref_num=r.reference_number,
                po_num=r.po_number,
                exclude_id=r.id
            )
            if dup:
                folder = os.path.basename(os.path.dirname(dup.file_path))
                filename = os.path.basename(dup.file_path)
                self.duplicate_warning.setText(f"⚠️ DUPLICATE DETECTED!\nORIGINAL FOUND IN: {folder.upper()}\nFILE: {filename}\nAPPROVED ON: {dup.created_at}")
                self.duplicate_warning.setVisible(True)
                self.delete_btn.setStyleSheet("""
                    QPushButton { background-color: #80dfff; border: 2px solid #80dfff; color: black; font-weight: bold; font-size: 11px; }
                    QPushButton:hover { background-color: #33ccff; }
                """)
                self.delete_btn.setText("DELETE DUPLICATE")
            else:
                self.duplicate_warning.setVisible(False)
                self.delete_btn.setStyleSheet("""
                    QPushButton { background-color: transparent; border: 1px solid #888; color: #888; font-weight: bold; font-size: 11px; }
                    QPushButton:hover { background-color: white; color: black; }
                """)
                self.delete_btn.setText("DELETE")
        finally:
            self.set_form_signals_blocked(False)

    def populate_form_dynamic_only(self):
        """Minimal version of populate_form to refresh Expense fields without reloading everything."""
        if not self.current_receipt: return
        r = self.current_receipt
        settings = load_settings()
        
        acc = settings.get("expense_acc_purchase", "2716")
        if "Special Tab" in self.fields and self.fields["Special Tab"].currentText().strip().upper() == "203-T":
            acc = "4004"
            self.fields["Episode Code"].setText("253")
            self.fields["Set #"].setText("")
        elif self.craft_checkbox.isChecked():
            acc = settings.get("expense_acc_craft", "3622")
        elif self.gas_checkbox.isChecked():
            acc = settings.get("expense_acc_gas", "3544")
        elif self.parking_checkbox.isChecked():
            acc = settings.get("expense_acc_parking", "3547")
        elif self.greens_checkbox.isChecked():
            acc = settings.get("expense_acc_greens", "2358")
        elif self.rental_checkbox.isChecked():
            acc = settings.get("expense_acc_rental", "2718")
        acc = str(acc).strip().split('-')[0]

        current_date = self.fields["Date"].text().strip() if "Date" in self.fields else r.date
        if not current_date:
            current_date = r.date
            
        hst = ""
        if current_date:
            try:
                from dateutil import parser
                # Clean up "SEPT" back to "SEP" for the parser
                parseable_date = current_date.replace("SEPT", "SEP")
                parsed_date = parser.parse(parseable_date, fuzzy=True)
                month_idx = parsed_date.month
                key = f"hst_month_{month_idx}"
                if key in settings:
                    hst = settings[key]
                else:
                    hst = str(7500 + month_idx)
            except:
                pass

        if self.craft_checkbox.isChecked():
            ins_code = settings.get("expense_ins_craft", "46")
        else:
            is_us = self.usd_checkbox.isChecked()
            ins_code = "" if is_us else settings.get("expense_ins_cad", "40")
        
        idx = self.fields["tax_code"].findText(ins_code)
        if idx >= 0:
            self.fields["tax_code"].setCurrentIndex(idx)
        else:
            self.fields["tax_code"].setCurrentIndex(0)

        self.fields["account_code"].setText(acc)
        self.fields["hst_account"].setText(hst)

    def on_usd_toggled(self, checked):
        self.fields["Exchange Rate"].setVisible(checked)
        self.rate_label.setVisible(checked)
        self.populate_form_dynamic_only()

    def on_parking_toggled(self, checked):
        if checked:
            self.craft_checkbox.setChecked(False)
            self.gas_checkbox.setChecked(False)
            self.fields["Episode Code"].setText("297")
            self.fields["Set #"].setText("")
            try:
                tot_text = self.fields["Total"].text().strip()
                if tot_text:
                    tot = float(tot_text.replace('$', '').replace(',', ''))
                    if tot != 0.0:
                        tax_text = self.fields["Tax"].text().strip()
                        sub_text = self.fields["Subtotal"].text().strip()
                        if not tax_text or tax_text in ["0", "0.00", "0.0"] or sub_text == tot_text:
                            sign = -1.0 if tot < 0 else 1.0
                            abs_tot = abs(tot)
                            abs_sub = round(abs_tot / 1.13, 2)
                            abs_tax = round(abs_tot - abs_sub, 2)
                            sub_val = sign * abs_sub
                            tax_val = sign * abs_tax
                            self.fields["Subtotal"].setText(f"{sub_val:.2f}")
                            self.fields["Tax"].setText(f"{tax_val:.2f}")
            except Exception as e:
                print("Error calculating parking tax on toggle:", e)
        self.populate_form_dynamic_only()
        self.update_parking_description()

    def update_parking_description(self):
        if not self.parking_checkbox.isChecked():
            return
            
        full_text = " ".join([
            self.fields["Notes"].text().strip(),
            self.fields["Ref #"].text().strip(),
            self.fields["Date"].text().strip(),
            self.fields["Description"].toPlainText().strip()
        ]).upper()
        
        vendor_text = self.fields["Vendor"].text().strip().upper()
        
        import re

        m_range = re.search(r'(\d{2}/?\d{2})\s*(?:to|[-–])\s*(\d{2}/?\d{2})', full_text, re.IGNORECASE)
        if m_range:
            d1 = m_range.group(1).replace('/', '')
            d2 = m_range.group(2).replace('/', '')
            range_str = f"{d1}-{d2}"
        else:
            months = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06","JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}
            month_pattern = r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d{1,2})'
            found_dates = re.findall(month_pattern, full_text)
            if len(found_dates) >= 2:
                m1, d1 = found_dates[0]
                m2, d2 = found_dates[1]
                mmdd1 = f"{months[m1]}{int(d1):02d}"
                mmdd2 = f"{months[m2]}{int(d2):02d}"
                range_str = f"{mmdd1}-{mmdd2}"
            elif len(found_dates) == 1:
                m1, d1 = found_dates[0]
                mmdd1 = f"{months[m1]}{int(d1):02d}"
                range_str = mmdd1
            else:
                date_val = self.fields["Date"].text().strip()
                if date_val:
                    from dateutil import parser
                    try:
                        p_date = parser.parse(date_val.replace("SEPT", "SEP"), fuzzy=True)
                        range_str = p_date.strftime("%m%d")
                    except:
                        range_str = ""
                else:
                    range_str = ""

        combined_vendor = f"{vendor_text} {full_text}"
        is_tpa = any(k in combined_vendor for k in ["TORONTO PARKING", "TORPRKAUT", "GREEN P", "TPA", "T.P.A", "TP PARKING", "CITY OF TORONTO", "TORONTO"])
        is_permit = ("-" in range_str) or any(k in combined_vendor for k in ["PERMIT", "PRMIT", "TEMP"])
        
        if is_permit and "-" in range_str:
            # Format from user image: 0723-0730 TPA PRKG PRMIT: SETS
            permit_suffix = "GREENS" if self.greens_checkbox.isChecked() else "SETS"
            desc_prefix = f"{range_str} TPA PRKG PRMIT:".strip() if is_tpa else f"{range_str} PRKG PRMIT:".strip()
            clean_desc = f"{desc_prefix} {permit_suffix}".strip()
        else:
            suffix = "GREENS" if self.greens_checkbox.isChecked() else "SET DEC"
            if is_tpa:
                desc_prefix = f"{range_str} TPA PRKG:".strip()
            else:
                desc_prefix = f"{range_str} PRKG:".strip()
            clean_desc = f"{desc_prefix} {suffix}".strip()
            
        self.fields["Description"].setPlainText(clean_desc)

    def on_gas_toggled(self, checked):
        if checked:
            self.craft_checkbox.setChecked(False)
            self.parking_checkbox.setChecked(False)
            try:
                tot_text = self.fields["Total"].text().strip()
                if tot_text:
                    tot = float(tot_text.replace('$', '').replace(',', ''))
                    if tot != 0.0:
                        tax_text = self.fields["Tax"].text().strip()
                        sub_text = self.fields["Subtotal"].text().strip()
                        if not tax_text or tax_text in ["0", "0.00", "0.0"] or sub_text == tot_text:
                            sign = -1.0 if tot < 0 else 1.0
                            abs_tot = abs(tot)
                            abs_sub = round(abs_tot / 1.13, 2)
                            abs_tax = round(abs_tot - abs_sub, 2)
                            sub_val = sign * abs_sub
                            tax_val = sign * abs_tax
                            self.fields["Subtotal"].setText(f"{sub_val:.2f}")
                            self.fields["Tax"].setText(f"{tax_val:.2f}")
            except Exception as e:
                print("Error calculating gas tax on toggle:", e)
        self.populate_form_dynamic_only()

    def on_rental_toggled(self, checked):
        if checked:
            self.asset_checkbox.setChecked(False)
        self.populate_form_dynamic_only()

    def on_asset_toggled(self, checked):
        if checked and self.rental_checkbox.isChecked():
            self.rental_checkbox.setChecked(False)
        self.populate_form_dynamic_only()

    def on_greens_toggled(self, checked):
        self.populate_form_dynamic_only()
        if self.craft_checkbox.isChecked():
            self.update_craft_description()
        elif self.parking_checkbox.isChecked():
            self.update_parking_description()

    def on_set_number_changed(self, text):
        t = str(text).strip().upper()
        if t in ["203-T", "203 TANDEM", "203T"]:
            self.fields["Set #"].blockSignals(True)
            self.fields["Set #"].setText("")
            self.fields["Set #"].blockSignals(False)
            self.fields["Special Tab"].setCurrentText("203-T")
            self.fields["Episode Code"].setText("253")
            self.fields["account_code"].setText("4004")
            return

        sp_tab = self.fields["Special Tab"].currentText().strip().upper() if "Special Tab" in self.fields else ""
        from core.set_list import derive_episode_code
        epi = derive_episode_code(t, special_tab=sp_tab)
        if epi:
            self.fields["Episode Code"].setText(epi)

    def on_special_tab_changed(self, text):
        sp_val = str(text).strip().upper()
        if sp_val == "203-T":
            self.fields["Episode Code"].setText("253")
            self.fields["Set #"].setText("")
            self.fields["account_code"].setText("4004")
            return

        set_val = self.fields["Set #"].text().strip().upper() if "Set #" in self.fields else ""
        from core.set_list import derive_episode_code
        epi = derive_episode_code(set_val, special_tab=sp_val)
        if epi:
            self.fields["Episode Code"].setText(epi)

    def on_craft_toggled(self, checked):
        if checked:
            self.fields["Episode Code"].setText("297")
            self.fields["Set #"].setText("")
            self.gas_checkbox.setChecked(False)
            self.parking_checkbox.setChecked(False)
        self.populate_form_dynamic_only()
        self.update_craft_description()

    def on_ch_req_toggled(self, checked: bool):
        if checked:
            self.fields["Payment Method"].setText("CH REQ")
        else:
            if self.fields["Payment Method"].text().strip().upper() == "CH REQ":
                self.fields["Payment Method"].clear()
        self.populate_form_dynamic_only()

    def update_craft_description(self):
        if not self.craft_checkbox.isChecked():
            return
            
        full_text = " ".join([
            self.fields["Notes"].text().strip(),
            self.fields["Ref #"].text().strip(),
            self.fields["Date"].text().strip(),
            self.fields["Description"].toPlainText().strip()
        ]).upper()
        
        import re

        m_range = re.search(r'(\d{4})\s*[-–to]+\s*(\d{4})', full_text)
        if m_range:
            range_str = f"{m_range.group(1)}-{m_range.group(2)}"
        else:
            date_val = self.fields["Date"].text().strip()
            if date_val:
                from dateutil import parser
                try:
                    p_date = parser.parse(date_val, fuzzy=True)
                    range_str = p_date.strftime("%m%d")
                except:
                    range_str = ""
            else:
                range_str = ""

        people = self.fields["# of People"].text().strip().upper()
        if not people:
            m_people = re.search(r'CRAFT\s*X\s*(\d+)|CRAFT\s*(\d+)|X\s*(\d+)|(OFFICE|LOCK\s*UP|LOCK-UP)', full_text)
            if m_people:
                if m_people.group(4):
                    people = m_people.group(4)
                else:
                    digits = m_people.group(1) or m_people.group(2) or m_people.group(3)
                    people = f"X{digits}"
        
        m_digit = re.search(r'\d+', people)
        if m_digit and (people.startswith("X") or people.isdigit() or "X" in people):
            people_type = f"X{m_digit.group(0)}"
        elif people in ["OFFICE", "LOCK UP", "LOCKUP", "LOCK-UP"]:
            people_type = people
        else:
            people_type = people

        suffix = "GREENS" if self.greens_checkbox.isChecked() else "SET DEC"
        
        if people_type in ["LOCK UP", "LOCKUP", "LOCK-UP"] or ("LOCK" in full_text and not (people_type and people_type.startswith("X"))):
            # Format from user image: 0724 CRAFT:SET DEC LOCK-UP
            clean_desc = f"{range_str} CRAFT:{suffix} LOCK-UP".strip()
        elif people_type == "OFFICE" or ("OFFICE" in full_text and not (people_type and people_type.startswith("X"))):
            clean_desc = f"{range_str} CRAFT:{suffix} OFFICE".strip()
        elif people_type and people_type.startswith("X"):
            # Format from user image: 0617 CRAFT X9: SET DEC
            clean_desc = f"{range_str} CRAFT {people_type}: {suffix}".strip()
        elif people_type:
            clean_desc = f"{range_str} CRAFT: {suffix} {people_type}".strip()
        else:
            clean_desc = f"{range_str} CRAFT: {suffix}".strip()
            
        self.fields["Description"].setPlainText(clean_desc)

    def load_image(self):
        self.current_rotation = 0
        self.image_scene.clear()
        if not self.current_receipt or not os.path.exists(self.current_receipt.file_path):
            return
            
        if self.current_receipt.file_path.lower().endswith('.pdf'):
            try:
                doc = fitz.open(self.current_receipt.file_path)
                zoom_matrix = fitz.Matrix(2.0, 2.0)
                y_offset = 0
                max_w = 0
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    pix = page.get_pixmap(matrix=zoom_matrix)
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                    pm = QPixmap.fromImage(img)
                    if not pm.isNull():
                        item = self.image_scene.addPixmap(pm)
                        item.setPos(0, y_offset)
                        y_offset += pm.height() + 25  # 25px gap between pages
                        if pm.width() > max_w:
                            max_w = pm.width()
                doc.close()

                if max_w > 0:
                    self.image_view.resetTransform()
                    self.image_scene.setSceneRect(0, 0, max_w, max(y_offset - 25, 100))
                    self.image_view.fitInView(self.image_scene.itemsBoundingRect(), Qt.KeepAspectRatio)
                    self.image_view.scale(1.8, 1.8)
                    self.image_view.verticalScrollBar().setValue(0)
                    self.image_view.horizontalScrollBar().setValue(0)
                return
            except Exception as e:
                print(f"DEBUG: Error rendering PDF pages in viewer: {e}")

        pixmap = QPixmap(self.current_receipt.file_path)
        if not pixmap.isNull():
            # Initial zoom setup: fit to view, then scale 1.8x closer so header text is clear and legible immediately!
            self.image_view.resetTransform()
            self.image_scene.addPixmap(pixmap)
            self.image_scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
            self.image_view.fitInView(self.image_scene.itemsBoundingRect(), Qt.KeepAspectRatio)
            self.image_view.scale(1.8, 1.8)
            self.image_view.verticalScrollBar().setValue(0)
            self.image_view.horizontalScrollBar().setValue(0)
        
    def rotate_image(self):
        self.image_view.rotate(90)
        self.current_rotation = (getattr(self, 'current_rotation', 0) + 90) % 360
        
    def skip_receipt(self):
        if not self.current_receipt: return
        self.current_receipt.status = 'SKIPPED'
        update_receipt(self.current_receipt)
        if not hasattr(self, 'skip_offset'):
            self.skip_offset = 0
        self.skip_offset += 1
        self.load_next_receipt()

    def delete_current_receipt(self):
        if not self.current_receipt: return
        reply = QMessageBox.question(self, 'Confirm Delete', 
                                    "Are you sure you want to delete this receipt file and entry? This cannot be undone.",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            # Delete file
            if os.path.exists(self.current_receipt.file_path):
                os.remove(self.current_receipt.file_path)
            
            # Delete from DB
            from core.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM receipts WHERE id = ?", (self.current_receipt.id,))
            conn.commit()
            conn.close()
            
            self.load_next_receipt()
        else:
            print("DB Deletion failed or aborted")

    def replace_original_receipt(self):
        if not self.current_receipt: return
        
        # 1. Ask user to pick the old receipt image
        from core.file_manager import RECEIPTS_DIR
        receipts_dir = RECEIPTS_DIR
        old_file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Original Receipt to Replace",
            receipts_dir,
            "Images/PDFs (*.jpg *.jpeg *.png *.pdf);;All Files (*)"
        )
        
        if not old_file_path:
            return
            
        old_file_path = os.path.normpath(old_file_path)
        
        # 2. Look it up in DB
        old_receipt = get_receipt_by_path(old_file_path)
        if not old_receipt:
            QMessageBox.warning(self, "Not Found", "Could not find that file in the database! Make sure you selected a receipt that was previously approved.")
            return
            
        # 3. Confirm
        reply = QMessageBox.question(
            self,
            "Confirm Replace",
            f"Are you sure you want to replace this original receipt?\n\nVendor: {old_receipt.vendor}\nTotal: ${old_receipt.total}\n\nThis will permanently delete the old receipt from Google Sheets and your local folder!",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
            
        # 4. Delete from Sheets
        url = None
        settings = load_settings()
        if settings.get("google_sheets_url"):
            url = settings["google_sheets_url"]
            
        if url:
            try:
                delete_receipt_from_sheet(url, old_receipt)
            except Exception as e:
                print(f"Error deleting from sheets: {e}")
                
        # 5. Delete from disk
        if os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
            except Exception as e:
                print(f"Error deleting file {old_file_path}: {e}")
                
        # 6. Delete from DB
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM receipts WHERE id = ?", (old_receipt.id,))
        conn.commit()
        conn.close()
        
        QMessageBox.information(self, "Deleted", "Original receipt deleted successfully! Now approving the new replacement receipt...")
        
        # 7. Approve the current one!
        self.approve_receipt()

    def approve_receipt(self):
        try:
            if not self.current_receipt: return
            
            # Apply rotation to file if needed
            rot = getattr(self, 'current_rotation', 0)
            if rot != 0 and os.path.exists(self.current_receipt.file_path):
                fp = self.current_receipt.file_path
                if fp.lower().endswith('.pdf'):
                    import fitz
                    doc = fitz.open(fp)
                    for page in doc:
                        page.set_rotation((page.rotation + rot) % 360)
                    doc.saveIncr()
                    doc.close()
                else:
                    from PIL import Image
                    with Image.open(fp) as img:
                        # PIL rotates counter-clockwise; QGraphicsView rotates clockwise
                        img_rotated = img.rotate(-rot, expand=True)
                        img_rotated.save(fp)
                self.current_rotation = 0
            
            self.current_receipt.set_number = self.fields["Set #"].text()
            self.current_receipt.special_tab = self.fields["Special Tab"].currentText().strip()
            from core.settings import normalize_buyer_name
            self.current_receipt.buyer_name = normalize_buyer_name(self.fields["Buyer Name"].text())

            self.current_receipt.description = self.fields["Description"].toPlainText()
            self.current_receipt.vendor = self.fields["Vendor"].text()
            
            try:
                def clean_num(text):
                    if not text: return None
                    cleaned = text.replace('$', '').replace(',', '').strip()
                    if not cleaned: return None
                    return float(cleaned)
                    
                self.current_receipt.subtotal = clean_num(self.fields["Subtotal"].text())
                self.current_receipt.shipping = clean_num(self.fields["Shipping"].text())
                self.current_receipt.import_fees = clean_num(self.fields["Import Fees"].text())
                self.current_receipt.tax = clean_num(self.fields["Tax"].text())
                self.current_receipt.total = clean_num(self.fields["Total"].text())

                # Validate & reconcile math on approval
                tot = self.current_receipt.total or 0.0
                sub = self.current_receipt.subtotal or 0.0
                ship = self.current_receipt.shipping or 0.0
                fees = self.current_receipt.import_fees or 0.0
                tax = self.current_receipt.tax or 0.0

                if tax == 0.0 and ship > 0.0 and sub > 0.0:
                    if abs(round(sub * 0.13, 2) - ship) <= 0.05 and abs(sub + ship - tot) <= 0.05:
                        tax = ship
                        ship = 0.0
                        self.current_receipt.tax = tax
                        self.current_receipt.shipping = ship

                if abs(tot) > 0.0 and abs(tax) > 0.0:
                    if sub == tot or abs((sub + ship + fees + tax) - tot) > 0.05:
                        sub = round(tot - tax - ship - fees, 2)
                        self.current_receipt.subtotal = sub
            except ValueError:
                QMessageBox.warning(self, "Validation Error", "Subtotal, Tax, and Total must be valid numbers (e.g. 12.34).")
                return
    
            pm = self.fields["Payment Method"].text().strip().upper()
            if pm in ["VISA", "VISA CREDIT", "VISA DEBIT"]:
                pm = "CREDIT"
            self.current_receipt.payment_method = pm
            date_text = self.fields["Date"].text()
            if date_text:
                try:
                    from dateutil import parser
                    parseable_date = date_text.replace("SEPT", "SEP")
                    parsed_ui_date = parser.parse(parseable_date, fuzzy=True)
                    orig_year = parsed_ui_date.year
                    if self.current_receipt.date:
                        try:
                            orig_date = parser.parse(str(self.current_receipt.date).replace("SEPT", "SEP"), fuzzy=True)
                            orig_year = orig_date.year
                        except:
                            pass
                    final_date = parsed_ui_date.replace(year=orig_year)
                    # Use %m/%d/%Y as requested by user
                    date_text = final_date.strftime("%m/%d/%Y")
                except:
                    pass
            self.current_receipt.date = date_text
            self.current_receipt.reference_number = self.fields["Ref #"].text()
            self.current_receipt.po_number = self.fields["PO #"].text()
            rental_date_text = self.fields["Rental End Date"].text()
            if rental_date_text:
                try:
                    from dateutil import parser
                    parsed_rental = parser.parse(rental_date_text, fuzzy=True)
                    rental_date_text = f"{parsed_rental.day}-{parsed_rental.strftime('%b').capitalize()}"
                except:
                    pass
            self.current_receipt.rental_end_date = rental_date_text
            
            self.current_receipt.notes = self.fields["Notes"].text()
            import re
            raw_epi = str(self.fields["Episode Code"].text() or "").strip().upper()
            m_concat = re.match(r'^297(2[56]\d|20\d|210|\d{1,2})$', raw_epi)
            if m_concat:
                raw_epi = m_concat.group(1)
            self.current_receipt.episode_code = raw_epi
            
            try:
                self.current_receipt.craft_people = int(self.fields["# of People"].text()) if self.fields["# of People"].text() else None
            except ValueError:
                self.current_receipt.craft_people = None
                
            self.current_receipt.is_rental = self.rental_checkbox.isChecked()
            self.current_receipt.is_greens = self.greens_checkbox.isChecked()
            self.current_receipt.is_craft = self.craft_checkbox.isChecked()
            self.current_receipt.is_gas = self.gas_checkbox.isChecked()
            self.current_receipt.is_parking = self.parking_checkbox.isChecked()
            self.current_receipt.is_asset = False if self.current_receipt.is_rental else self.asset_checkbox.isChecked()
            self.current_receipt.notes = self.fields["Notes"].text()
            
            # AUTOMATIC EXPENSE ONLY RULE:
            # Parking, Craft, and Fuel (Gas) receipts are ALWAYS Expense Only!
            is_parking_craft_fuel = (
                self.current_receipt.is_craft or
                self.current_receipt.is_parking or
                self.current_receipt.is_gas or
                any(k in (self.current_receipt.set_number or "").upper() for k in ["PARKING", "CRAFT", "GAS"]) or
                any(k in (self.current_receipt.vendor or "").upper() for k in ["PARK", "PRK", "TORPRK", "TPA", "METER", "CITY OF TORONTO", "PETRO", "SHELL", "ESSO", "PIONEER", "ULTRAMAR", "MOBIL", "HUSKY", "IRVING"])
            )
            self.current_receipt.expense_only = is_parking_craft_fuel
            if self.current_receipt.special_tab and self.current_receipt.special_tab.strip() != "":
                self.current_receipt.expense_only = False
            
            # Expense fields
            self.current_receipt.co_code = ""
            self.current_receipt.loc_code = ""
            self.current_receipt.account_code = self.fields["account_code"].text()
            self.current_receipt.tax_code = self.fields["tax_code"].currentText()
            self.current_receipt.hst_account = self.fields["hst_account"].text().strip()
            self.current_receipt.is_usd = self.usd_checkbox.isChecked()
            try:
                self.current_receipt.exchange_rate = float(self.fields["Exchange Rate"].text().strip())
            except ValueError:
                self.current_receipt.exchange_rate = float(settings.get("default_usd_exchange_rate", 1.41))
            
            self.current_receipt.status = 'APPROVED'
            
            # Move and rename the file first
            new_path = move_and_rename_receipt(self.current_receipt)
            self.current_receipt.file_path = new_path
            
            # Now update the database with the NEW path and APPROVED status
            update_receipt(self.current_receipt)
            
            if self.ch_req_checkbox.isChecked():
                import subprocess
                import json
                app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
                bot_path = os.path.join(show_dir, 'CH REQS', 'ch_req_bot.py')
                if os.path.exists(bot_path):
                    pm = str(self.current_receipt.payment_method or "").upper()
                    
                    # Resolve special set rule (e.g. B18 + G98 -> SetLocation = "G98 - INT DR. HALL'S OFFICE")
                    from core.set_list import resolve_special_and_initial_set
                    sp_tab = str(self.current_receipt.special_tab or "").strip().upper()
                    raw_set = str(self.current_receipt.set_number or "").strip()
                    sp_info = resolve_special_and_initial_set(
                        set_input=raw_set,
                        special_tab=sp_tab,
                        notes=self.current_receipt.notes
                    )
                    if sp_info.get("is_special_98"):
                        set_loc_val = sp_info.get("display_pdf_set")
                    else:
                        set_loc_val = raw_set

                    # Subtotal sent to CH REQ Bot MUST match the full expenditure before HST in the app (including shipping, packaging, handling, import fees)
                    app_subtotal = (self.current_receipt.subtotal or 0.0) + (self.current_receipt.shipping or 0.0) + (self.current_receipt.import_fees or 0.0)
                    app_tax = self.current_receipt.tax
                    if self.current_receipt.total is not None:
                        try:
                            tot_val = float(self.current_receipt.total)
                            # If tax was missing or placed in shipping, auto-detect 13% HST
                            if (app_tax is None or float(app_tax or 0.0) == 0.0) and self.current_receipt.subtotal:
                                sub_raw = float(self.current_receipt.subtotal)
                                if sub_raw < tot_val and abs(round(sub_raw * 1.13, 2) - tot_val) <= 0.05:
                                    app_subtotal = sub_raw
                                    app_tax = round(tot_val - sub_raw, 2)
                            elif app_tax is not None:
                                tax_val = float(app_tax)
                                calc_net = round(tot_val - tax_val, 2)
                                if abs(calc_net - app_subtotal) <= 0.05 or app_subtotal == 0.0 or app_subtotal == tot_val:
                                    app_subtotal = calc_net
                        except Exception:
                            pass

                    tracker_data = {
                        "Payee": self.current_receipt.vendor,
                        "Date": self.current_receipt.date,
                        "TotalAmount": f"{float(self.current_receipt.total):.2f}" if self.current_receipt.total is not None else "",
                        "AmountBeforeHST": f"{app_subtotal:.2f}",
                        "HSTAmount": f"{float(app_tax):.2f}" if app_tax is not None else "",
                        "Details": self.current_receipt.description,
                        "SetLocation": set_loc_val,
                        "special_tab": sp_tab,
                        "InitialSet": sp_info.get("initial_set", raw_set),
                        "Episode": self.current_receipt.episode_code,
                        "RequestedBy": self.current_receipt.buyer_name,
                        "PurchaseType": "Rental" if self.current_receipt.is_rental else "Purchase",
                        "ReferenceNumber": self.current_receipt.reference_number or "",
                        "PaymentType": "ACH" if "ACH" in pm else "CH REQ"
                    }
                    pythonw_path = sys.executable.replace("python.exe", "pythonw.exe")
                    creation_flags = 0x08000000 if os.name == 'nt' else 0
                    subprocess.Popen([pythonw_path, bot_path, '--file', new_path, '--data', json.dumps(tracker_data)],
                                     creationflags=creation_flags)
                else:
                    QMessageBox.warning(self, "Warning", "CH REQ Bot script not found at expected location.")
    
            if self.po_rev_checkbox.isChecked():
                import subprocess
                import json
                app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
                bot_path = os.path.join(show_dir, 'PO REVISIONS', 'po_rev_bot.py')
                if os.path.exists(bot_path):
                    tracker_data = {
                        "Vendor Name": self.current_receipt.vendor,
                        "PO Number": self.current_receipt.po_number,
                        "TotalAmount": str(self.current_receipt.total) if self.current_receipt.total is not None else "",
                        "Details": self.current_receipt.description,
                        "SetLocation": self.current_receipt.set_number
                    }
                    pythonw_path = sys.executable.replace("python.exe", "pythonw.exe")
                    creation_flags = 0x08000000 if os.name == 'nt' else 0
                    subprocess.Popen([pythonw_path, bot_path, '--file', new_path, '--data', json.dumps(tracker_data)],
                                     creationflags=creation_flags)
                else:
                    QMessageBox.warning(self, "Warning", "PO REVISION Bot script not found at expected location.")
            elif (not self.ch_req_checkbox.isChecked() and
                  str(self.current_receipt.payment_method or "").strip().upper() in ("PO", "P.O.") and
                  self.current_receipt.po_number and str(self.current_receipt.po_number).strip()):
                # Only record regular PO if user explicitly selected PO as payment method and entered a valid PO #
                try:
                    po_val = str(self.current_receipt.po_number).strip()
                    po_upper = po_val.upper()
                    # Filter out set numbers (e.g. B16, J14), show names, or pending
                    is_invalid_po = (
                        po_upper in ("PENDING", "NONE", "N/A", "TBD") or
                        "SAMPLE SHOW" in po_upper or
                        "SAMPLE" in po_upper or
                        (len(po_val) <= 4 and po_val[0].isalpha() and po_val[1:].isdigit())
                    )
                    if not is_invalid_po:
                        from services.ch_req_sheet_helper import record_cheque_request
                        record_data = {
                            "vendor": self.current_receipt.vendor or "",
                            "date_submitted": datetime.now().strftime("%m/%d/%Y"),
                            "date_required": "",
                            "payment_type": "PO",
                            "set_number": self.current_receipt.set_number or "",
                            "description": self.current_receipt.description or "",
                            "reference_number": f"PO #{po_val}" if not po_upper.startswith("PO") else po_val,
                            "invoice_date": self.current_receipt.date or "",
                            "subtotal": (self.current_receipt.subtotal or 0.0) + (self.current_receipt.shipping or 0.0) + (self.current_receipt.import_fees or 0.0),
                            "tax": self.current_receipt.tax or 0.0,
                            "total": self.current_receipt.total or 0.0,
                            "rental_period": self.current_receipt.rental_end_date or "",
                            "buyer_name": self.current_receipt.buyer_name or "",
                            "pdf_path": new_path
                        }
                        record_cheque_request(record_data)
                except Exception as ex_po:
                    print(f"DEBUG: Could not record PO to tracker list: {ex_po}")

            settings = load_settings()
            url = settings.get("spreadsheet_url", "")
            
            if not self.current_receipt.expense_only:
                from services.sheets import revise_po_in_sheet, append_receipt_to_sheet
                try:
                    if self.po_rev_checkbox.isChecked():
                        revise_po_in_sheet(url, self.current_receipt)
                    else:
                        splits = process_receipt_splits(self.current_receipt)
                        for split in splits:
                            append_receipt_to_sheet(url, split)
                except Exception as ex_sync:
                    err_str = str(ex_sync).lower()
                    is_net = any(w in err_str for w in ["oauth2", "getaddrinfo", "nameresolutionerror", "connection", "max retries", "timeout", "socket", "network", "failed to resolve"])
                    from core.database import queue_offline_receipt
                    queue_offline_receipt(self.current_receipt.id, action='REVISE' if self.po_rev_checkbox.isChecked() else 'APPEND', error_message=str(ex_sync))
                    try:
                        if hasattr(self.parent_window, 'home_widget') and hasattr(self.parent_window.home_widget, 'update_offline_queue_badge'):
                            self.parent_window.home_widget.update_offline_queue_badge()
                    except Exception:
                        pass
                    if is_net:
                        QMessageBox.information(
                            self,
                            "Saved Locally (Offline)",
                            f"Receipt successfully approved and saved locally!\n\n"
                            f"Google Sheets could not be reached right now because of a network connection or DNS issue:\n{ex_sync}\n\n"
                            f"The receipt has been safely queued and will automatically sync to Google Sheets as soon as internet connection is restored."
                        )
                    else:
                        QMessageBox.warning(
                            self,
                            "Saved Locally (Sync Warning)",
                            f"Receipt saved locally, but Google Sheets returned an error:\n{ex_sync}\n\n"
                            f"It has been queued in Offline Sync so you can retry syncing later."
                        )
            else:
                print(f"DEBUG: Skipping Google Sheets for Expense Only receipt: {self.current_receipt.vendor}")
                
            self.load_next_receipt()
        except Exception as e:
            import traceback
            err_str = str(e).lower()
            is_net = any(w in err_str for w in ["oauth2", "getaddrinfo", "nameresolutionerror", "connection", "max retries", "timeout", "socket", "network", "failed to resolve", "11004"])
            if is_net and hasattr(self, 'current_receipt') and self.current_receipt and self.current_receipt.id:
                try:
                    from core.database import queue_offline_receipt
                    queue_offline_receipt(self.current_receipt.id, action='APPEND', error_message=str(e))
                except Exception:
                    pass
                QMessageBox.information(
                    self,
                    "Saved Locally (Offline)",
                    f"Receipt approved and saved locally!\n\n"
                    f"Google Sheets could not be reached right now because of a network connection or DNS issue:\n{e}\n\n"
                    f"The receipt has been safely queued in Offline Sync and will automatically sync once your connection is restored."
                )
                try:
                    self.load_next_receipt()
                except Exception:
                    pass
                return

            error_msg = f"Error during approval:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            print(error_msg)
            QMessageBox.critical(self, "Approval Error", error_msg)
