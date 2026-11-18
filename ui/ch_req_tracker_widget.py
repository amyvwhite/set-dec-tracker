import os
import re
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit,
    QMessageBox, QProgressBar, QFrame, QSplitter, QCheckBox, QAbstractItemView, QComboBox,
    QMenu, QDialog, QFormLayout, QDialogButtonBox, QDateEdit, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QDate, QTimer

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
CALENDAR_ICON_PATH = os.path.join(ASSETS_DIR, "calendar_icon.png").replace("\\", "/")
from PySide6.QtGui import QColor, QFont, QGuiApplication
from core.database import (
    get_pending_cheque_requests, get_all_cheque_requests,
    delete_cheque_request, get_connection, parse_date_key
)
from services.ch_req_sheet_helper import (
    complete_cheque_and_update_tracker,
    complete_cheques_batch_and_update_tracker,
    parse_ach_batch_text,
    normalize_pasted_text,
    match_ach_items_to_sets,
    apply_ach_payments_to_tracker,
    update_cheque_request_details,
    normalize_rental_period,
    update_pdf_payment_type,
    sync_cheque_request_from_pdf,
    toggle_cheque_request_payment_type,
    toggle_cheque_received_status,
    find_actual_ch_req_pdf
)
from .ch_req_dialog import CHReqDialog

class CompleteChequeThread(QThread):
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, req_ids, cheque_number, delivery_notes):
        super().__init__()
        if isinstance(req_ids, (list, tuple, set)):
            self.req_ids = list(req_ids)
        else:
            self.req_ids = [req_ids]
        self.cheque_number = cheque_number
        self.delivery_notes = delivery_notes

    def run(self):
        try:
            if len(self.req_ids) == 1:
                res = complete_cheque_and_update_tracker(self.req_ids[0], self.cheque_number, self.delivery_notes)
            else:
                res = complete_cheques_batch_and_update_tracker(self.req_ids, self.cheque_number, self.delivery_notes)
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))


class UpdateChReqDetailsThread(QThread):
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, req_id, updates):
        super().__init__()
        self.req_id = req_id
        self.updates = updates

    def run(self):
        try:
            res = update_cheque_request_details(self.req_id, self.updates)
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))


class TogglePaymentTypeThread(QThread):
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, req_id):
        super().__init__()
        self.req_id = req_id

    def run(self):
        try:
            res = toggle_cheque_request_payment_type(self.req_id)
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))

class SyncFromPdfThread(QThread):
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, req_id):
        super().__init__()
        self.req_id = req_id

    def run(self):
        try:
            res = sync_cheque_request_from_pdf(self.req_id)
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))


class ToggleChequeReceivedThread(QThread):
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, req_ids, target_status=None):
        super().__init__()
        if isinstance(req_ids, (list, tuple, set)):
            self.req_ids = list(req_ids)
        else:
            self.req_ids = [req_ids]
        self.target_status = target_status

    def run(self):
        try:
            if len(self.req_ids) == 1:
                res = toggle_cheque_received_status(self.req_ids[0], self.target_status)
            else:
                updated_count = 0
                for r_id in self.req_ids:
                    toggle_cheque_received_status(r_id, self.target_status)
                    updated_count += 1
                status_label = "📬 IN HAND (Cheque Received)" if self.target_status == "RECEIVED" else "⏳ AWAITING CHEQUE (Pending)"
                res = {
                    "status": "success",
                    "message": f"Updated {updated_count} requisitions to: {status_label}",
                    "new_status": self.target_status
                }
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))

class EditChReqDialog(QDialog):
    def __init__(self, item_data, parent=None):
        super().__init__(parent)
        self.item_data = item_data
        self.setWindowTitle(f"✏️ Edit Requisition #{item_data.get('id', '')}")
        self.setMinimumWidth(450)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1622;
                color: #eee;
            }
            QLabel {
                color: #e8d7f1;
                font-weight: bold;
                font-size: 11px;
            }
            QLineEdit, QComboBox, QDateEdit {
                background-color: #25202e;
                border: 1px solid #4a3d5c;
                border-radius: 4px;
                color: white;
                padding: 6px;
                font-size: 11px;
            }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus {
                border: 1px solid #00f2ff;
            }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 26px;
                border-left: 1px solid #4a3d5c;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                background-color: #2e263a;
            }
            QDateEdit::drop-down:hover {
                background-color: #3f3252;
            }
            QDateEdit::down-arrow {
                image: url("C:/Users/amywh/Desktop/SAMPLE SHOW S1/BOT APP FILES/SET DEC TRACKING APP/assets/calendar_icon.png");
                width: 14px;
                height: 14px;
            }
            QPushButton {
                font-weight: bold;
                font-size: 11px;
                padding: 8px 16px;
                border-radius: 6px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        form = QFormLayout()
        form.setSpacing(10)
        
        # Status (Pending vs In Hand)
        self.cb_status = QComboBox()
        self.cb_status.addItems(["PENDING", "RECEIVED"])
        curr_status = str(item_data.get("status", "PENDING")).upper()
        if curr_status not in ("PENDING", "RECEIVED"): curr_status = "PENDING"
        idx_st = self.cb_status.findText(curr_status)
        if idx_st >= 0: self.cb_status.setCurrentIndex(idx_st)
        form.addRow("Status:", self.cb_status)

        # Payment Type
        self.cb_type = QComboBox()
        self.cb_type.addItems(["CHQ", "ACH", "PO"])
        curr_type = str(item_data.get("payment_type", "REQ")).upper()
        if curr_type == "CH REQ": curr_type = "REQ"
        idx = self.cb_type.findText(curr_type)
        if idx >= 0: self.cb_type.setCurrentIndex(idx)
        form.addRow("Payment Type:", self.cb_type)
        
        # Date Required with Calendar Dropdown
        self.dt_date_req = QDateEdit()
        self.dt_date_req.setCalendarPopup(True)
        self.dt_date_req.setDisplayFormat("MM/dd/yyyy")
        cal = self.dt_date_req.calendarWidget()
        if cal:
            cal.setStyleSheet("""
                QCalendarWidget { background-color: #1a1622; }
                QCalendarWidget QWidget { alternate-background-color: #201a2b; color: #e8d7f1; }
                QCalendarWidget QAbstractItemView:enabled { color: #eee; background-color: #25202e; selection-background-color: #795793; selection-color: white; font-size: 11px; }
                QCalendarWidget QToolButton { color: #e8d7f1; background-color: #1a1622; font-weight: bold; font-size: 11px; border: none; border-radius: 4px; padding: 4px; }
                QCalendarWidget QToolButton:hover { background-color: #382c47; }
                QCalendarWidget QSpinBox { background-color: #25202e; color: white; border: 1px solid #4a3d5c; border-radius: 4px; padding: 2px; }
                QCalendarWidget QMenu { background-color: #1a1622; color: white; border: 1px solid #4a3d5c; }
            """)
        raw_date = str(item_data.get("date_required", "")).strip()
        from core.database import parse_date_key
        parsed_dt = parse_date_key(raw_date) if raw_date else None
        if parsed_dt and parsed_dt.year < 9000:
            self.dt_date_req.setDate(QDate(parsed_dt.year, parsed_dt.month, parsed_dt.day))
        else:
            self.dt_date_req.setDate(QDate.currentDate())
        form.addRow("Date Required:", self.dt_date_req)
        
        # Rental Dates
        self.txt_rental = QLineEdit(str(item_data.get("rental_period", "")))
        self.txt_rental.setPlaceholderText("e.g. Sept 10 - Oct 14")
        form.addRow("Rental Dates:", self.txt_rental)
        
        # Vendor
        self.txt_vendor = QLineEdit(str(item_data.get("vendor", "")))
        form.addRow("Vendor:", self.txt_vendor)
        
        # Set #
        self.txt_set = QLineEdit(str(item_data.get("set_number", "")))
        form.addRow("Set #:", self.txt_set)
        
        # Reference #
        self.txt_ref = QLineEdit(str(item_data.get("reference_number", "")))
        form.addRow("Inv / Ref #:", self.txt_ref)
        
        # Description
        self.txt_desc = QLineEdit(str(item_data.get("description", "")))
        form.addRow("Description:", self.txt_desc)
        
        layout.addLayout(form)
        
        # Buttons
        btns = QHBoxLayout()
        btns.addStretch()
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("background: #333; color: #ccc; border: 1px solid #555;")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_cancel)
        
        self.btn_save = QPushButton("💾 Save & Update Tracker")
        self.btn_save.setStyleSheet("background: #00f2ff; color: #000; border: none;")
        self.btn_save.clicked.connect(self.accept)
        btns.addWidget(self.btn_save)
        
        layout.addLayout(btns)

    def get_updates(self):
        return {
            "status": self.cb_status.currentText(),
            "payment_type": self.cb_type.currentText(),
            "date_required": self.dt_date_req.date().toString("MM/dd/yyyy"),
            "rental_period": self.txt_rental.text().strip(),
            "vendor": self.txt_vendor.text().strip(),
            "set_number": self.txt_set.text().strip(),
            "reference_number": self.txt_ref.text().strip(),
            "description": self.txt_desc.text().strip()
        }

class OverdueListDialog(QDialog):
    def __init__(self, chq_items, ach_items, parent=None):
        super().__init__(parent)
        self.chq_items = chq_items
        self.ach_items = ach_items
        self.setWindowTitle("🚨 Past-Due Requisitions for Accounting")
        self.setMinimumSize(640, 520)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1622;
                color: #eee;
            }
            QLabel {
                color: #e8d7f1;
            }
        """)
        self.setup_ui()

    def format_line(self, item):
        vendor = str(item.get("vendor", "")).strip().upper()
        ref = str(item.get("reference_number", "")).strip()
        if not ref:
            inv_str = "INV # N/A"
        elif ref.upper().startswith("INV #"):
            inv_str = f"INV # {ref[5:].strip()}"
        elif ref.upper().startswith("INV#"):
            inv_str = f"INV # {ref[4:].strip()}"
        elif ref.upper().startswith("INV"):
            clean = ref[3:].strip().lstrip('#').strip()
            inv_str = f"INV # {clean}" if clean else "INV # N/A"
        else:
            inv_str = f"INV # {ref}"
            
        return f"{vendor} - {inv_str}"

    def get_ach_text(self):
        lines = ["ACHs OVERDUE:"]
        if self.ach_items:
            for it in self.ach_items:
                lines.append(self.format_line(it))
        else:
            lines.append("None")
        return "\n".join(lines)

    def get_chq_text(self):
        lines = ["CH REQs OVERDUE:"]
        if self.chq_items:
            for it in self.chq_items:
                lines.append(self.format_line(it))
        else:
            lines.append("None")
        return "\n".join(lines)

    def get_full_text(self):
        return f"{self.get_chq_text()}\n\n{self.get_ach_text()}"

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Header Title
        title_box = QHBoxLayout()
        icon_lbl = QLabel("🚨")
        icon_lbl.setStyleSheet("font-size: 24px;")
        title_box.addWidget(icon_lbl)

        header_vbox = QVBoxLayout()
        total_overdue = len(self.ach_items) + len(self.chq_items)
        if total_overdue == 0:
            lbl_title = QLabel("Past-Due Requisitions (0 Overdue)")
            lbl_title.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 16px;")
            lbl_sub = QLabel("Great news! There are no past-due requisitions at this time.")
            lbl_sub.setStyleSheet("color: #aaa; font-size: 11px;")
        else:
            lbl_title = QLabel(f"Past-Due Requisitions ({total_overdue} Total)")
            lbl_title.setStyleSheet("color: #ff9999; font-weight: bold; font-size: 16px;")
            lbl_sub = QLabel(f"{len(self.chq_items)} CH REQs and {len(self.ach_items)} ACHs require payment. Formatted to paste directly to accounting.")
            lbl_sub.setStyleSheet("color: #aaa; font-size: 11px;")

        header_vbox.addWidget(lbl_title)
        header_vbox.addWidget(lbl_sub)
        title_box.addLayout(header_vbox)
        title_box.addStretch()
        layout.addLayout(title_box)

        # Text Area
        self.txt_display = QTextEdit()
        self.txt_display.setPlainText(self.get_full_text())
        self.txt_display.setStyleSheet("""
            QTextEdit {
                background-color: #121017;
                color: #f0edf5;
                border: 1px solid #4a385c;
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                line-height: 1.4;
                padding: 10px;
            }
            QTextEdit:focus {
                border: 1px solid #00f2ff;
            }
        """)
        layout.addWidget(self.txt_display, stretch=1)

        # Status Label for Copy Feedback
        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 11px;")
        layout.addWidget(self.lbl_feedback)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_copy_all = QPushButton("📋 COPY ALL TO CLIPBOARD")
        self.btn_copy_all.setStyleSheet("""
            QPushButton {
                background-color: #00f2ff;
                color: #000;
                font-weight: bold;
                font-size: 11px;
                padding: 9px 18px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #33f5ff;
            }
        """)
        self.btn_copy_all.clicked.connect(self.copy_all)
        btn_layout.addWidget(self.btn_copy_all)

        self.btn_copy_chq = QPushButton("💵 Copy CH REQs Only")
        self.btn_copy_chq.setStyleSheet("""
            QPushButton {
                background-color: #2b2336;
                color: #e8d7f1;
                font-weight: bold;
                font-size: 11px;
                padding: 9px 14px;
                border-radius: 6px;
                border: 1px solid #5a426e;
            }
            QPushButton:hover {
                background-color: #3d304d;
                color: #fff;
            }
        """)
        self.btn_copy_chq.clicked.connect(self.copy_chqs)
        btn_layout.addWidget(self.btn_copy_chq)

        self.btn_copy_ach = QPushButton("⚡ Copy ACHs Only")
        self.btn_copy_ach.setStyleSheet("""
            QPushButton {
                background-color: #2b2336;
                color: #e8d7f1;
                font-weight: bold;
                font-size: 11px;
                padding: 9px 14px;
                border-radius: 6px;
                border: 1px solid #5a426e;
            }
            QPushButton:hover {
                background-color: #3d304d;
                color: #fff;
            }
        """)
        self.btn_copy_ach.clicked.connect(self.copy_achs)
        btn_layout.addWidget(self.btn_copy_ach)

        btn_layout.addStretch()

        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #222;
                color: #ccc;
                font-weight: bold;
                font-size: 11px;
                padding: 9px 18px;
                border-radius: 6px;
                border: 1px solid #444;
            }
            QPushButton:hover {
                background-color: #333;
                color: #fff;
            }
        """)
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def copy_all(self):
        text = self.txt_display.toPlainText()
        QGuiApplication.clipboard().setText(text)
        self.lbl_feedback.setText("✅ Copied all overdue items to clipboard! Ready to paste to accounting.")
        self.btn_copy_all.setText("✅ COPIED ALL!")
        QTimer.singleShot(2500, lambda: self.btn_copy_all.setText("📋 COPY ALL TO CLIPBOARD"))

    def copy_achs(self):
        text = self.get_ach_text()
        QGuiApplication.clipboard().setText(text)
        self.lbl_feedback.setText("✅ Copied ACHs list to clipboard!")
        self.btn_copy_ach.setText("✅ COPIED ACHs!")
        QTimer.singleShot(2500, lambda: self.btn_copy_ach.setText("⚡ Copy ACHs Only"))

    def copy_chqs(self):
        text = self.get_chq_text()
        QGuiApplication.clipboard().setText(text)
        self.lbl_feedback.setText("✅ Copied CH REQs list to clipboard!")
        self.btn_copy_chq.setText("✅ COPIED CH REQs!")
        QTimer.singleShot(2500, lambda: self.btn_copy_chq.setText("💵 Copy CH REQs Only"))


class ApplyACHBatchThread(QThread):
    progress_signal = Signal(int, int, str)
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, items):
        super().__init__()
        self.items = items

    def run(self):
        try:
            def on_progress(idx, total, msg):
                self.progress_signal.emit(idx + 1, total, msg)

            res = apply_ach_payments_to_tracker(self.items, progress_callback=on_progress)
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))

class ChReqTrackerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending_items = []
        self.pending_pos = []
        self.selected_item = None
        self.selected_items = []
        self.selected_po = None
        self.parsed_ach_items = []
        
        self.setup_ui()
        self.load_pending_data()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2a2a2a;
                background-color: #121212;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #181818;
                color: #aaa;
                font-weight: bold;
                font-size: 12px;
                padding: 10px 20px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid #222;
            }
            QTabBar::tab:selected {
                background: #242424;
                color: #00f2ff;
                border-bottom: 2px solid #00f2ff;
            }
            QTabBar::tab:hover {
                color: #fff;
            }
        """)

        # Tab 1: Pending Cheques & ACH
        self.tab_pending = QWidget()
        self.setup_pending_tab()
        self.tabs.addTab(self.tab_pending, "📋 PENDING CHEQUES & ACH")

        # Tab 2: Purchase Orders (POs)
        self.tab_pos = QWidget()
        self.setup_po_tab()
        self.tabs.addTab(self.tab_pos, "📌 PURCHASE ORDERS (POs)")

        # Tab 3: Accountant ACH Batch Processor
        self.tab_ach = QWidget()
        self.setup_ach_tab()
        self.tabs.addTab(self.tab_ach, "⚡ ACCOUNTANT ACH BATCH")

        main_layout.addWidget(self.tabs)

    def setup_pending_tab(self):
        layout = QVBoxLayout(self.tab_pending)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Top Filter Bar (Search + Dropdowns + Refresh)
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filter by Vendor, Set #, Invoice #, Buyer...")
        self.search_input.setMinimumWidth(260)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 6px;
                color: white;
                padding: 8px 12px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #00f2ff;
            }
        """)
        self.search_input.textChanged.connect(self.filter_table)
        filter_bar.addWidget(self.search_input, stretch=3)

        self.type_filter = QComboBox()
        self.type_filter.addItems(["ALL CHEQUES & ACH", "💵 CHQ ONLY", "⚡ ACH ONLY"])
        self.type_filter.setStyleSheet("""
            QComboBox {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 6px;
                color: #e8d7f1;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
            }
        """)
        self.type_filter.currentIndexChanged.connect(self.filter_table)
        filter_bar.addWidget(self.type_filter, stretch=1)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["⏳ PENDING (Awaiting Cheque)", "📬 IN HAND (Cheque Received)", "📋 ALL ACTIVE"])
        self.status_filter.setStyleSheet("""
            QComboBox {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 6px;
                color: #ffe599;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
            }
        """)
        self.status_filter.currentIndexChanged.connect(self.filter_table)
        filter_bar.addWidget(self.status_filter, stretch=1)

        self.btn_refresh = QPushButton("🔄 REFRESH")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #222;
                color: #ccc;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 14px;
                border-radius: 6px;
                border: 1px solid #444;
            }
            QPushButton:hover {
                background-color: #333;
                color: #fff;
            }
        """)
        self.btn_refresh.clicked.connect(self.load_pending_data)
        filter_bar.addWidget(self.btn_refresh)

        layout.addLayout(filter_bar)

        # Action Buttons Row
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        self.btn_new = QPushButton("➕ NEW REQ")
        self.btn_new.setStyleSheet("""
            QPushButton {
                background-color: #00f2ff;
                color: #000;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 14px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #33f5ff;
            }
        """)
        self.btn_new.clicked.connect(self.open_new_ch_req)
        action_bar.addWidget(self.btn_new)

        self.btn_toggle_received = QPushButton("📬 CHEQUE RECEIVED")
        self.btn_toggle_received.setToolTip("Mark cheque as received (in hand) or revert back to awaiting cheque")
        self.btn_toggle_received.setStyleSheet("""
            QPushButton {
                background-color: #164e3f;
                color: #6ee7b7;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 14px;
                border-radius: 6px;
                border: 1px solid #2a8069;
            }
            QPushButton:hover {
                background-color: #1f6753;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_toggle_received.clicked.connect(self.toggle_selected_item_received_status)
        self.btn_toggle_received.setEnabled(False)
        action_bar.addWidget(self.btn_toggle_received)

        self.btn_edit = QPushButton("✏️ EDIT ITEM")
        self.btn_edit.setStyleSheet("""
            QPushButton {
                background-color: #2b2336;
                color: #e8d7f1;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 12px;
                border-radius: 6px;
                border: 1px solid #5a426e;
            }
            QPushButton:hover {
                background-color: #3d304d;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_edit.clicked.connect(self.open_edit_dialog_for_selected)
        self.btn_edit.setEnabled(False)
        action_bar.addWidget(self.btn_edit)

        self.btn_toggle_type = QPushButton("☑️ CHQ ↔ ACH")
        self.btn_toggle_type.setToolTip("Toggle checkmark between Cheque and ACH in PDF and Tracker")
        self.btn_toggle_type.setStyleSheet("""
            QPushButton {
                background-color: #1e3a29;
                color: #4ade80;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 12px;
                border-radius: 6px;
                border: 1px solid #2e6640;
            }
            QPushButton:hover {
                background-color: #274d35;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_toggle_type.clicked.connect(self.toggle_selected_item_payment_type)
        self.btn_toggle_type.setEnabled(False)
        action_bar.addWidget(self.btn_toggle_type)

        self.btn_sync_pdf = QPushButton("📄 SYNC FROM PDF")
        self.btn_sync_pdf.setToolTip("Re-read checkmarks, dates, and amounts from the modified PDF into the tracker")
        self.btn_sync_pdf.setStyleSheet("""
            QPushButton {
                background-color: #1b2838;
                color: #66c0f4;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 12px;
                border-radius: 6px;
                border: 1px solid #2a475e;
            }
            QPushButton:hover {
                background-color: #2a475e;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_sync_pdf.clicked.connect(self.sync_selected_item_from_pdf)
        self.btn_sync_pdf.setEnabled(False)
        action_bar.addWidget(self.btn_sync_pdf)

        self.btn_open_pdf = QPushButton("📂 OPEN PDF")
        self.btn_open_pdf.setToolTip("Open the CH REQ PDF in your default PDF viewer / Acrobat")
        self.btn_open_pdf.setStyleSheet("""
            QPushButton {
                background-color: #2b2336;
                color: #e8d7f1;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 12px;
                border-radius: 6px;
                border: 1px solid #5a426e;
            }
            QPushButton:hover {
                background-color: #3d304d;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_open_pdf.clicked.connect(self.open_selected_item_pdf)
        self.btn_open_pdf.setEnabled(False)
        action_bar.addWidget(self.btn_open_pdf)

        self.btn_overdue = QPushButton("🚨 PAST DUE")
        self.btn_overdue.setToolTip("Generate copyable list of past-due ACHs and CH REQs for Accounting")
        self.btn_overdue.setStyleSheet("""
            QPushButton {
                background-color: #3b181e;
                color: #ff9999;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 12px;
                border-radius: 6px;
                border: 1px solid #732631;
            }
            QPushButton:hover {
                background-color: #54222a;
                color: #ffffff;
                border-color: #ff9999;
            }
        """)
        self.btn_overdue.clicked.connect(self.show_overdue_list_dialog)
        action_bar.addWidget(self.btn_overdue)

        action_bar.addStretch()

        self.btn_delete = QPushButton("🗑 DELETE")
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #222;
                color: #ff6b6b;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 12px;
                border-radius: 6px;
                border: 1px solid #552222;
            }
            QPushButton:hover {
                background-color: #441111;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_delete.clicked.connect(self.delete_selected_item)
        self.btn_delete.setEnabled(False)
        action_bar.addWidget(self.btn_delete)

        layout.addLayout(action_bar)

        # Pending Count Banner
        self.lbl_count = QLabel("0 Pending Requisitions")
        self.lbl_count.setStyleSheet("color: #e8d7f1; font-weight: bold; font-size: 12px; margin-bottom: 2px;")
        layout.addWidget(self.lbl_count)

        self.lbl_multi_hint = QLabel("💡 Tip: Hold Ctrl or Shift to select multiple requisitions paid on the same cheque.")
        self.lbl_multi_hint.setStyleSheet("color: #a78bfa; font-size: 11px; margin-bottom: 4px;")
        layout.addWidget(self.lbl_multi_hint)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(14)
        self.table.setHorizontalHeaderLabels([
            "ID", "Date Sub", "Date Req", "Type", "Status", "CH REQ", "Vendor", "Inv / Ref #",
            "Set #", "Description", "Subtotal", "Total", "Rental Dates", "Buyer"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #141414;
                border: 1px solid #262626;
                gridline-color: #222;
                color: #eee;
                font-size: 12px;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 6px 4px;
            }
            QHeaderView::section {
                background-color: #201b24;
                color: #e8d7f1;
                font-weight: bold;
                font-size: 12px;
                padding: 8px 6px;
                border: none;
                border-bottom: 2px solid #cbb2de;
            }
            QTableWidget::item:selected {
                background-color: #2c2538;
                color: #00f2ff;
            }
        """)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch) # Vendor stretches (Col 6)
        self.table.horizontalHeader().setSectionResizeMode(9, QHeaderView.Stretch) # Description stretches (Col 9)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemDoubleClicked.connect(self.on_table_double_clicked)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        layout.addWidget(self.table, stretch=1)

        # Bottom Completion Card
        self.card_complete = QFrame()
        self.card_complete.setStyleSheet("""
            QFrame {
                background-color: #1a1622;
                border: 1px solid #3d314a;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        card_layout = QVBoxLayout(self.card_complete)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        self.lbl_selected_info = QLabel("Select a requisition above to edit type/details or complete payment.")
        self.lbl_selected_info.setTextFormat(Qt.RichText)
        self.lbl_selected_info.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.lbl_selected_info.linkActivated.connect(lambda link: self.open_selected_item_pdf())
        self.lbl_selected_info.setStyleSheet("color: #e8d7f1; font-weight: bold; font-size: 12px;")
        card_layout.addWidget(self.lbl_selected_info)

        # Quick Edit & Change Type Row
        quick_edit_box = QFrame()
        quick_edit_box.setStyleSheet("background-color: #231c2c; border: 1px solid #4a385c; border-radius: 6px; padding: 4px;")
        q_layout = QHBoxLayout(quick_edit_box)
        q_layout.setContentsMargins(8, 4, 8, 4)
        q_layout.setSpacing(10)

        lbl_type = QLabel("Change Type:")
        lbl_type.setStyleSheet("color: #e8d7f1; font-weight: bold; font-size: 11px;")
        self.cb_edit_type = QComboBox()
        self.cb_edit_type.addItems(["💵 CHQ", "⚡ ACH", "📌 PO"])
        self.cb_edit_type.setStyleSheet("""
            QComboBox {
                background-color: #1a1622;
                border: 1px solid #795793;
                border-radius: 4px;
                color: #fff;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 8px;
            }
        """)
        q_layout.addWidget(lbl_type)
        q_layout.addWidget(self.cb_edit_type)

        lbl_date_req = QLabel("Date Req:")
        lbl_date_req.setStyleSheet("color: #ccc; font-size: 11px;")
        self.txt_edit_date_req = QDateEdit()
        self.txt_edit_date_req.setCalendarPopup(True)
        self.txt_edit_date_req.setDisplayFormat("MM/dd/yyyy")
        self.txt_edit_date_req.setFixedWidth(115)
        self.txt_edit_date_req.setStyleSheet("""
            QDateEdit {{
                background: #1a1622;
                border: 1px solid #4a3d5c;
                border-radius: 4px;
                color: white;
                padding: 4px 24px 4px 6px;
                font-size: 11px;
            }}
            QDateEdit:focus {{
                border: 1px solid #00f2ff;
            }}
            QDateEdit::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 22px;
                border-left: 1px solid #4a3d5c;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                background-color: #2e263a;
            }}
            QDateEdit::drop-down:hover {{
                background-color: #3f3252;
            }}
            QDateEdit::down-arrow {{
                image: url("C:/Users/amywh/Desktop/SAMPLE SHOW S1/BOT APP FILES/SET DEC TRACKING APP/assets/calendar_icon.png");
                width: 13px;
                height: 13px;
            }}
        """)
        cal_quick = self.txt_edit_date_req.calendarWidget()
        if cal_quick:
            cal_quick.setStyleSheet("""
                QCalendarWidget {{ background-color: #1a1622; }}
                QCalendarWidget QWidget {{ alternate-background-color: #201a2b; color: #e8d7f1; }}
                QCalendarWidget QAbstractItemView:enabled {{ color: #eee; background-color: #25202e; selection-background-color: #795793; selection-color: white; font-size: 11px; }}
                QCalendarWidget QToolButton {{ color: #e8d7f1; background-color: #1a1622; font-weight: bold; font-size: 11px; border: none; border-radius: 4px; padding: 4px; }}
                QCalendarWidget QToolButton:hover {{ background-color: #382c47; }}
                QCalendarWidget QSpinBox {{ background-color: #25202e; color: white; border: 1px solid #4a3d5c; border-radius: 4px; padding: 2px; }}
                QCalendarWidget QMenu {{ background-color: #1a1622; color: white; border: 1px solid #4a3d5c; }}
            """)
        q_layout.addWidget(lbl_date_req)
        q_layout.addWidget(self.txt_edit_date_req)

        lbl_rental = QLabel("Rental Dates:")
        lbl_rental.setStyleSheet("color: #ccc; font-size: 11px;")
        self.txt_edit_rental = QLineEdit()
        self.txt_edit_rental.setPlaceholderText("e.g. Sept 10 - Oct 14")
        self.txt_edit_rental.setStyleSheet("background: #1a1622; border: 1px solid #4a3d5c; border-radius: 4px; color: white; padding: 4px; font-size: 11px;")
        q_layout.addWidget(lbl_rental)
        q_layout.addWidget(self.txt_edit_rental, stretch=1)

        self.btn_save_edit = QPushButton("💾 SAVE CHANGES TO TRACKER")
        self.btn_save_edit.setStyleSheet("""
            QPushButton {
                background-color: #795793;
                color: white;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 14px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #9368b5;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #666;
            }
        """)
        self.btn_save_edit.clicked.connect(self.save_item_changes)
        self.btn_save_edit.setEnabled(False)
        q_layout.addWidget(self.btn_save_edit)

        self.btn_toggle_card = QPushButton("☑️ TOGGLE CHQ ↔ ACH")
        self.btn_toggle_card.setToolTip("Switches checkmark between Cheque and ACH in PDF & Tracker")
        self.btn_toggle_card.setStyleSheet("""
            QPushButton {
                background-color: #1e3a29;
                color: #4ade80;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 12px;
                border-radius: 4px;
                border: 1px solid #2e6640;
            }
            QPushButton:hover {
                background-color: #274d35;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #222;
                color: #555;
            }
        """)
        self.btn_toggle_card.clicked.connect(self.toggle_selected_item_payment_type)
        self.btn_toggle_card.setEnabled(False)
        q_layout.addWidget(self.btn_toggle_card)

        self.btn_card_received = QPushButton("📬 CHEQUE RECEIVED (IN HAND)")
        self.btn_card_received.setToolTip("Mark cheque as received (in hand) or revert back to awaiting cheque")
        self.btn_card_received.setStyleSheet("""
            QPushButton {
                background-color: #164e3f;
                color: #6ee7b7;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 12px;
                border-radius: 4px;
                border: 1px solid #2a8069;
            }
            QPushButton:hover {
                background-color: #1f6753;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #222;
                color: #555;
            }
        """)
        self.btn_card_received.clicked.connect(self.toggle_selected_item_received_status)
        self.btn_card_received.setEnabled(False)
        q_layout.addWidget(self.btn_card_received)

        self.btn_full_edit = QPushButton("✏️ Full Edit...")
        self.btn_full_edit.setStyleSheet("""
            QPushButton {
                background-color: #2b2336;
                color: #e8d7f1;
                font-size: 11px;
                padding: 6px 10px;
                border: 1px solid #5a426e;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3d304d;
            }
            QPushButton:disabled {
                background-color: #222;
                color: #555;
            }
        """)
        self.btn_full_edit.clicked.connect(self.open_edit_dialog_for_selected)
        self.btn_full_edit.setEnabled(False)
        q_layout.addWidget(self.btn_full_edit)

        self.btn_card_open_pdf = QPushButton("📄 OPEN CH REQ PDF")
        self.btn_card_open_pdf.setToolTip("Open the Cheque Request PDF in your default PDF viewer / Acrobat")
        self.btn_card_open_pdf.setStyleSheet("""
            QPushButton {
                background-color: #102838;
                color: #00f2ff;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 14px;
                border-radius: 4px;
                border: 1px solid #00a8b5;
            }
            QPushButton:hover {
                background-color: #163d56;
                color: #ffffff;
            }
            QPushButton:disabled {
                background-color: #222;
                color: #555;
                border: 1px solid #333;
            }
        """)
        self.btn_card_open_pdf.clicked.connect(lambda: self.open_selected_item_pdf())
        self.btn_card_open_pdf.setEnabled(False)
        q_layout.addWidget(self.btn_card_open_pdf)

        card_layout.addWidget(quick_edit_box)

        inputs_layout = QHBoxLayout()

        lbl_chq = QLabel("Cheque / ACH #:")
        lbl_chq.setStyleSheet("color: #ccc; font-size: 11px;")
        self.txt_chq_num = QLineEdit()
        self.txt_chq_num.setPlaceholderText("e.g. 20568 or ACH200914 10/26")
        self.txt_chq_num.setStyleSheet("background: #25202e; border: 1px solid #4a3d5c; border-radius: 4px; color: white; padding: 6px;")
        inputs_layout.addWidget(lbl_chq)
        inputs_layout.addWidget(self.txt_chq_num, stretch=1)

        lbl_deliv = QLabel("Delivery / Notes:")
        lbl_deliv.setStyleSheet("color: #ccc; font-size: 11px; margin-left: 10px;")
        self.txt_delivery = QLineEdit()
        self.txt_delivery.setPlaceholderText("e.g. truck 10/22 or Nick delivered 10/25")
        self.txt_delivery.setStyleSheet("background: #25202e; border: 1px solid #4a3d5c; border-radius: 4px; color: white; padding: 6px;")
        inputs_layout.addWidget(lbl_deliv)
        inputs_layout.addWidget(self.txt_delivery, stretch=2)

        self.btn_complete = QPushButton("🚀 UPDATE TRACKER & COMPLETE")
        self.btn_complete.setStyleSheet("""
            QPushButton {
                background-color: #d8c5e8;
                color: #20182b;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #ebdff5;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #666;
            }
        """)
        self.btn_complete.clicked.connect(self.complete_selected_cheque)
        self.btn_complete.setEnabled(False)
        inputs_layout.addWidget(self.btn_complete)

        card_layout.addLayout(inputs_layout)

        self.progress_complete = QProgressBar()
        self.progress_complete.setRange(0, 0)
        self.progress_complete.setVisible(False)
        card_layout.addWidget(self.progress_complete)

        layout.addWidget(self.card_complete)


    def setup_po_tab(self):
        layout = QVBoxLayout(self.tab_pos)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Top Bar: Search and Actions
        top_bar = QHBoxLayout()

        self.po_search_input = QLineEdit()
        self.po_search_input.setPlaceholderText("🔍 Filter POs by Vendor, PO #, Set #, Buyer, Description...")
        self.po_search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 6px;
                color: white;
                padding: 8px 12px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #00f2ff;
            }
        """)
        self.po_search_input.textChanged.connect(self.filter_po_table)
        top_bar.addWidget(self.po_search_input, stretch=2)

        self.btn_new_po = QPushButton("➕ NEW PO")
        self.btn_new_po.setStyleSheet("""
            QPushButton {
                background-color: #00f2ff;
                color: #000;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #33f5ff;
            }
        """)
        self.btn_new_po.clicked.connect(self.open_new_po)
        top_bar.addWidget(self.btn_new_po)

        self.btn_edit_po = QPushButton("✏️ EDIT PO")
        self.btn_edit_po.setStyleSheet("""
            QPushButton {
                background-color: #2b2336;
                color: #e8d7f1;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 14px;
                border-radius: 6px;
                border: 1px solid #5a426e;
            }
            QPushButton:hover {
                background-color: #3d304d;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_edit_po.clicked.connect(self.open_edit_dialog_for_selected_po)
        self.btn_edit_po.setEnabled(False)
        top_bar.addWidget(self.btn_edit_po)

        self.btn_open_pdf_po = QPushButton("📂 OPEN PO / RECEIPT")
        self.btn_open_pdf_po.setToolTip("Open the PO PDF or uploaded invoice/receipt")
        self.btn_open_pdf_po.setStyleSheet("""
            QPushButton {
                background-color: #2b2336;
                color: #e8d7f1;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 14px;
                border-radius: 6px;
                border: 1px solid #5a426e;
            }
            QPushButton:hover {
                background-color: #3d304d;
                color: #fff;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_open_pdf_po.clicked.connect(self.open_selected_po_pdf)
        self.btn_open_pdf_po.setEnabled(False)
        top_bar.addWidget(self.btn_open_pdf_po)

        self.btn_refresh_po = QPushButton("🔄 REFRESH")
        self.btn_refresh_po.setStyleSheet("""
            QPushButton {
                background-color: #222;
                color: #ccc;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 14px;
                border-radius: 6px;
                border: 1px solid #444;
            }
            QPushButton:hover {
                background-color: #333;
                color: #fff;
            }
        """)
        self.btn_refresh_po.clicked.connect(self.load_pending_data)
        top_bar.addWidget(self.btn_refresh_po)

        self.btn_import_pos = QPushButton("📥 IMPORT OPEN POs")
        self.btn_import_pos.setToolTip("Scan receipts in database and import any active POs into this list")
        self.btn_import_pos.setStyleSheet("""
            QPushButton {
                background-color: #2b1f14;
                color: #ffa657;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 14px;
                border-radius: 6px;
                border: 1px solid #734018;
            }
            QPushButton:hover {
                background-color: #4a2e16;
            }
        """)
        self.btn_import_pos.clicked.connect(self.import_open_pos_from_db)
        top_bar.addWidget(self.btn_import_pos)

        self.btn_delete_po = QPushButton("🗑 DELETE")
        self.btn_delete_po.setStyleSheet("""
            QPushButton {
                background-color: #222;
                color: #ff6b6b;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 14px;
                border-radius: 6px;
                border: 1px solid #552222;
            }
            QPushButton:hover {
                background-color: #441111;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
                border: 1px solid #33283d;
            }
        """)
        self.btn_delete_po.clicked.connect(self.delete_selected_po)
        self.btn_delete_po.setEnabled(False)
        top_bar.addWidget(self.btn_delete_po)

        layout.addLayout(top_bar)

        # Count / Value Banner
        self.lbl_po_count = QLabel("0 Open Purchase Orders")
        self.lbl_po_count.setStyleSheet("color: #70b5ff; font-weight: bold; font-size: 12px; margin-bottom: 2px;")
        layout.addWidget(self.lbl_po_count)

        # PO Table
        self.po_table = QTableWidget()
        self.po_table.setColumnCount(11)
        self.po_table.setHorizontalHeaderLabels([
            "ID", "Date Issued", "Type", "Vendor", "PO #",
            "Set #", "Description", "Subtotal", "Total", "Rental / Notes", "Buyer"
        ])
        self.po_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.po_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.po_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.po_table.verticalHeader().setVisible(False)
        self.po_table.setStyleSheet("""
            QTableWidget {
                background-color: #141414;
                border: 1px solid #262626;
                gridline-color: #222;
                color: #eee;
                font-size: 12px;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 6px 4px;
            }
            QHeaderView::section {
                background-color: #16202c;
                color: #70b5ff;
                font-weight: bold;
                font-size: 12px;
                padding: 8px 6px;
                border: none;
                border-bottom: 2px solid #388bfd;
            }
            QTableWidget::item:selected {
                background-color: #1a2b42;
                color: #70b5ff;
            }
        """)
        self.po_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.po_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch) # Vendor stretches
        self.po_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch) # Description stretches
        self.po_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.po_table.customContextMenuRequested.connect(self.show_po_context_menu)
        self.po_table.itemDoubleClicked.connect(self.on_po_table_double_clicked)
        self.po_table.itemSelectionChanged.connect(self.on_po_table_selection_changed)
        layout.addWidget(self.po_table, stretch=1)

        # Bottom Completion Card for PO
        self.card_po_complete = QFrame()
        self.card_po_complete.setStyleSheet("""
            QFrame {
                background-color: #141c26;
                border: 1px solid #27384e;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        card_layout = QVBoxLayout(self.card_po_complete)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        self.lbl_po_selected_info = QLabel("Select a purchase order above to view details, update notes, or close / complete.")
        self.lbl_po_selected_info.setStyleSheet("color: #70b5ff; font-weight: bold; font-size: 12px;")
        card_layout.addWidget(self.lbl_po_selected_info)

        inputs_layout = QHBoxLayout()

        lbl_inv = QLabel("Invoice # / Status:")
        lbl_inv.setStyleSheet("color: #ccc; font-size: 11px;")
        self.txt_po_inv_num = QLineEdit()
        self.txt_po_inv_num.setPlaceholderText("PO COMPLETED (or custom Inv #)")
        self.txt_po_inv_num.setStyleSheet("background: #1c2636; border: 1px solid #354a69; border-radius: 4px; color: white; padding: 6px;")
        inputs_layout.addWidget(lbl_inv)
        inputs_layout.addWidget(self.txt_po_inv_num, stretch=1)

        lbl_date = QLabel("Date:")
        lbl_date.setStyleSheet("color: #ccc; font-size: 11px; margin-left: 8px;")
        self.txt_po_date = QLineEdit()
        self.txt_po_date.setPlaceholderText("MM/DD")
        self.txt_po_date.setStyleSheet("background: #1c2636; border: 1px solid #354a69; border-radius: 4px; color: white; padding: 6px; max-width: 65px;")
        inputs_layout.addWidget(lbl_date)
        inputs_layout.addWidget(self.txt_po_date)

        lbl_deliv = QLabel("Delivery / Notes:")
        lbl_deliv.setStyleSheet("color: #ccc; font-size: 11px; margin-left: 8px;")
        self.txt_po_delivery = QLineEdit()
        self.txt_po_delivery.setPlaceholderText("e.g. Received at shop / Nick 10/28")
        self.txt_po_delivery.setStyleSheet("background: #1c2636; border: 1px solid #354a69; border-radius: 4px; color: white; padding: 6px;")
        inputs_layout.addWidget(lbl_deliv)
        inputs_layout.addWidget(self.txt_po_delivery, stretch=2)

        self.btn_po_complete = QPushButton("🚀 CLOSE / COMPLETE PO")
        self.btn_po_complete.setStyleSheet("""
            QPushButton {
                background-color: #388bfd;
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
                padding: 8px 16px;
                border-radius: 6px;
                border: none;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #58a6ff;
            }
            QPushButton:disabled {
                background-color: #222;
                color: #555;
            }
        """)
        self.btn_po_complete.clicked.connect(self.complete_selected_po)
        self.btn_po_complete.setEnabled(False)
        inputs_layout.addWidget(self.btn_po_complete)

        self.btn_po_edit = QPushButton("✏️ Full Edit...")
        self.btn_po_edit.setStyleSheet("""
            QPushButton {
                background-color: #202b3c;
                color: #70b5ff;
                font-size: 11px;
                padding: 8px 12px;
                border: 1px solid #385072;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2b3b52;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
            }
        """)
        self.btn_po_edit.clicked.connect(self.open_edit_dialog_for_selected_po)
        self.btn_po_edit.setEnabled(False)
        inputs_layout.addWidget(self.btn_po_edit)

        self.btn_po_open_pdf = QPushButton("📂 Open PO / PDF")
        self.btn_po_open_pdf.setStyleSheet("""
            QPushButton {
                background-color: #202b3c;
                color: #70b5ff;
                font-size: 11px;
                padding: 8px 12px;
                border: 1px solid #385072;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2b3b52;
            }
            QPushButton:disabled {
                background-color: #1a1622;
                color: #555;
            }
        """)
        self.btn_po_open_pdf.clicked.connect(self.open_selected_po_pdf)
        self.btn_po_open_pdf.setEnabled(False)
        inputs_layout.addWidget(self.btn_po_open_pdf)

        card_layout.addLayout(inputs_layout)

        self.progress_po_complete = QProgressBar()
        self.progress_po_complete.setRange(0, 0)
        self.progress_po_complete.setVisible(False)
        card_layout.addWidget(self.progress_po_complete)

        layout.addWidget(self.card_po_complete)

    def setup_ach_tab(self):
        layout = QVBoxLayout(self.tab_ach)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Header Instructions
        lbl_title = QLabel("⚡ ACCOUNTANT ACH BATCH PROCESSOR")
        lbl_title.setStyleSheet("color: #00f2ff; font-weight: bold; font-size: 14px; letter-spacing: 0.5px;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Paste accountant ACH lines below. The app will auto-match invoices against your Tracker sheets, format the payment text, and update Column P.")
        lbl_desc.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 5px;")
        layout.addWidget(lbl_desc)

        # Input Section
        input_box = QFrame()
        input_box.setStyleSheet("background-color: #161616; border: 1px solid #282828; border-radius: 6px; padding: 10px;")
        box_layout = QVBoxLayout(input_box)
        box_layout.setSpacing(8)

        date_layout = QHBoxLayout()
        lbl_date = QLabel("Payment Date (MM/DD):")
        lbl_date.setStyleSheet("color: #ccc; font-weight: bold; font-size: 11px;")
        self.txt_ach_date = QLineEdit()
        self.txt_ach_date.setText(datetime.now().strftime("%m/%d"))
        self.txt_ach_date.setFixedWidth(80)
        self.txt_ach_date.setStyleSheet("background: #222; border: 1px solid #444; border-radius: 4px; color: white; padding: 4px; font-weight: bold;")
        date_layout.addWidget(lbl_date)
        date_layout.addWidget(self.txt_ach_date)
        date_layout.addStretch()

        self.btn_parse = QPushButton("🔍 PARSE & MATCH INVOICES")
        self.btn_parse.setStyleSheet("""
            QPushButton {
                background-color: #00f2ff;
                color: #000;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 16px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #33f5ff;
            }
        """)
        self.btn_parse.clicked.connect(self.parse_and_match_ach)
        date_layout.addWidget(self.btn_parse)
        box_layout.addLayout(date_layout)

        self.txt_ach_input = QTextEdit()
        self.txt_ach_input.setPlaceholderText(
            "Paste accountant updates here, e.g.:\n"
            "UNITED PROP - INV 9402 PD ACH 200886\n"
            "PICKLE PROPS - INV 53582 PD ACH 200872\n"
            "WISEACRE - INV 319825   PD ACH200888\n"
            "GOOD DOG - INV 26-13903   PD ACH200849\n"
            "SUPA HOLDINGS - INV 7115  PD ACH200914\n"
            "HERCULES MOVNG - INV 019967-D  PD ACH200908\n"
            "PROSOURCE - INV PS015800 NOT ENTERED WHEN DID WE GET IT"
        )
        self.txt_ach_input.setFixedHeight(110)
        self.txt_ach_input.setStyleSheet("background: #111; border: 1px solid #333; border-radius: 4px; color: #eee; font-family: Consolas, monospace; font-size: 11px;")
        box_layout.addWidget(self.txt_ach_input)

        layout.addWidget(input_box)

        # Match Preview Table
        self.table_ach = QTableWidget()
        self.table_ach.setColumnCount(7)
        self.table_ach.setHorizontalHeaderLabels([
            "Apply?", "Vendor (From Text)", "Invoice #", "ACH #",
            "Col P Entry", "Target Set Tab", "Match Status"
        ])
        self.table_ach.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_ach.verticalHeader().setVisible(False)
        self.table_ach.setStyleSheet("""
            QTableWidget {
                background-color: #141414;
                border: 1px solid #262626;
                gridline-color: #222;
                color: #eee;
                font-size: 12px;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 6px 4px;
            }
            QHeaderView::section {
                background-color: #1a2228;
                color: #79c0ff;
                font-weight: bold;
                font-size: 12px;
                padding: 8px 6px;
                border: none;
                border-bottom: 2px solid #388bfd;
            }
        """)
        self.table_ach.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_ach.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table_ach, stretch=1)

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        self.lbl_ach_summary = QLabel("0 items parsed.")
        self.lbl_ach_summary.setStyleSheet("color: #aaa; font-size: 11px;")
        bottom_bar.addWidget(self.lbl_ach_summary)

        bottom_bar.addStretch()

        self.btn_apply_ach = QPushButton("🚀 APPLY ALL MATCHED TO TRACKER (COL P)")
        self.btn_apply_ach.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: white;
                font-weight: bold;
                font-size: 12px;
                padding: 10px 22px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #666;
            }
        """)
        self.btn_apply_ach.clicked.connect(self.apply_ach_payments)
        self.btn_apply_ach.setEnabled(False)
        bottom_bar.addWidget(self.btn_apply_ach)

        layout.addLayout(bottom_bar)

        self.progress_ach = QProgressBar()
        self.progress_ach.setVisible(False)
        self.progress_ach.setStyleSheet("QProgressBar { background: #222; border-radius: 4px; height: 14px; text-align: center; color: white; font-size: 10px; } QProgressBar::chunk { background: #00f2ff; }")
        layout.addWidget(self.progress_ach)

    # --- PENDING TAB METHODS ---

    def load_pending_data(self):
        all_pending = get_pending_cheque_requests()
        self.pending_items = [it for it in all_pending if str(it.get("payment_type", "")).upper() != "PO"]
        self.pending_pos = [it for it in all_pending if str(it.get("payment_type", "")).upper() == "PO"]

        self.filter_table()
        self.filter_po_table()
        
        # Calculate awaiting, in hand, and overdue counts for Tab 0 (CHQ & ACH)
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        overdue_count = 0
        awaiting_count = 0
        in_hand_count = 0

        for it in self.pending_items:
            st = str(it.get("status", "PENDING")).upper()
            if st == "RECEIVED":
                in_hand_count += 1
            else:
                awaiting_count += 1
                raw_d = str(it.get("date_required", "")).strip()
                if raw_d:
                    try:
                        dt_val = parse_date_key(raw_d)
                        if dt_val and dt_val < today_start:
                            overdue_count += 1
                    except Exception:
                        pass

        count_parts = [f"⏳ {awaiting_count} Awaiting Cheque", f"📬 {in_hand_count} Cheques In Hand"]
        if overdue_count > 0:
            count_parts.append(f"<span style='color: #ff9999; font-weight: bold;'>🚨 {overdue_count} Past Due</span>")
            if hasattr(self, "btn_overdue"):
                self.btn_overdue.setText(f"🚨 PAST DUE ({overdue_count})")
        else:
            if hasattr(self, "btn_overdue"):
                self.btn_overdue.setText("🚨 PAST DUE")

        self.lbl_count.setText("  •  ".join(count_parts))

        # Tab 1: Calculate count & value for Open POs
        total_po_val = sum((it.get("total") or 0.0) for it in self.pending_pos)
        po_count = len(self.pending_pos)
        if hasattr(self, "lbl_po_count"):
            self.lbl_po_count.setText(
                f"📌 {po_count} Open Purchase Order{'s' if po_count != 1 else ''}  •  <span style='color: #7ee787; font-weight: bold;'>Total Value: ${total_po_val:,.2f}</span>"
            )

        self.clear_selection()
        if hasattr(self, "clear_po_selection"):
            self.clear_po_selection()

    def filter_table(self):
        query = self.search_input.text().strip().lower()
        type_filter = getattr(self, "type_filter", None)
        selected_type = type_filter.currentText() if type_filter else "ALL CHEQUES & ACH"
        status_filter = getattr(self, "status_filter", None)
        selected_status = status_filter.currentText() if status_filter else "⏳ PENDING (Awaiting Cheque)"
        
        filtered = []
        for item in self.pending_items:
            p_type = str(item.get("payment_type", "CH REQ")).upper()
            item_status = str(item.get("status", "PENDING")).upper()
            
            # Status Filter: Awaiting vs In Hand vs All
            if "PENDING" in selected_status and "ALL" not in selected_status:
                if item_status == "RECEIVED":
                    continue
            elif ("IN HAND" in selected_status or "RECEIVED" in selected_status) and "ALL" not in selected_status:
                if item_status != "RECEIVED":
                    continue

            # Type Filter check (Tab 0 only shows CHQ & ACH)
            if "ACH ONLY" in selected_type:
                if p_type != "ACH":
                    continue
            elif "CHQ ONLY" in selected_type or "REQ ONLY" in selected_type:
                if p_type not in ("CHQ", "REQ", "CH REQ"):
                    continue

            vendor = str(item.get("vendor", "")).lower()
            set_num = str(item.get("set_number", "")).lower()
            ref_num = str(item.get("reference_number", "")).lower()
            desc = str(item.get("description", "")).lower()
            buyer = str(item.get("buyer_name", "")).lower()
            
            if not query or query in vendor or query in set_num or query in ref_num or query in desc or query in buyer:
                filtered.append(item)

        # Sort so lines with sooner date required are at the top
        from core.database import parse_date_key
        filtered.sort(key=lambda x: (parse_date_key(x.get("date_required")), parse_date_key(x.get("date_submitted")), x.get("id", 0)))

        self.table.setRowCount(len(filtered))
        for row_idx, item in enumerate(filtered):
            # ID
            item_id = QTableWidgetItem(str(item.get("id")))
            item_id.setTextAlignment(Qt.AlignCenter)
            item_id.setData(Qt.UserRole, item)
            self.table.setItem(row_idx, 0, item_id)

            # Date Submitted
            it_sub = QTableWidgetItem(str(item.get("date_submitted", "")))
            it_sub.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 1, it_sub)

            # Date Required - Highlighted in warm pastel gold (#ffe599), light red if passed
            raw_req = str(item.get("date_required", "")).strip()
            it_req = QTableWidgetItem(raw_req)
            it_req.setTextAlignment(Qt.AlignCenter)

            is_overdue = False
            item_status = str(item.get("status", "PENDING")).upper()
            if raw_req and item_status != "RECEIVED":
                try:
                    dt_val = parse_date_key(raw_req)
                    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    if dt_val < today_start:
                        is_overdue = True
                except Exception:
                    pass

            if is_overdue:
                it_req.setBackground(QColor("#4a1c1c")) # soft dark red alert background
                it_req.setForeground(QColor("#ff9999")) # light red / coral text
            else:
                it_req.setBackground(QColor("#332612")) # warm dark gold box
                it_req.setForeground(QColor("#ffe599")) # soft warm gold text

            f_req = it_req.font()
            f_req.setBold(True)
            it_req.setFont(f_req)
            self.table.setItem(row_idx, 2, it_req)

            # Type: CH REQ highlighted green, ACH stays white
            p_type = str(item.get("payment_type", "CHQ")).upper()
            if p_type in ("CH REQ", "REQ"):
                p_type = "CHQ"
            if "PO" in p_type:
                display_type = "📌 PO"
                type_color = QColor("#70b5ff") # Distinct vibrant light blue
                type_bg = QColor("#142740")     # Light blue / navy tint box
            elif p_type == "ACH":
                display_type = "⚡ ACH"
                type_color = QColor("#ffffff") # Clean white text
                type_bg = QColor("#1e1e1e")    # Neutral dark / stays white
            else:
                display_type = "💵 CHQ"
                type_color = QColor("#4ade80") # Vibrant green
                type_bg = QColor("#163d24")    # Green highlight box

            it_type = QTableWidgetItem(display_type)
            it_type.setTextAlignment(Qt.AlignCenter)
            it_type.setForeground(type_color)
            it_type.setBackground(type_bg)
            f_bold = it_type.font()
            f_bold.setBold(True)
            it_type.setFont(f_bold)
            self.table.setItem(row_idx, 3, it_type)

            # Status (Column 4): IN HAND highlighted mint green vs AWAITING soft gold
            if item_status == "RECEIVED":
                it_status = QTableWidgetItem("📬 IN HAND")
                it_status.setTextAlignment(Qt.AlignCenter)
                it_status.setForeground(QColor("#4ade80"))
                it_status.setBackground(QColor("#0e382b"))
            else:
                it_status = QTableWidgetItem("⏳ AWAITING")
                it_status.setTextAlignment(Qt.AlignCenter)
                it_status.setForeground(QColor("#ffe599"))
                it_status.setBackground(QColor("#2e2312"))
            f_st = it_status.font()
            f_st.setBold(True)
            it_status.setFont(f_st)
            self.table.setItem(row_idx, 4, it_status)

            # CH REQ PDF Link (Column 5)
            pdf_path = item.get("pdf_path")
            if not pdf_path or not os.path.exists(pdf_path) or "Receipts" in str(pdf_path):
                actual = find_actual_ch_req_pdf(
                    item.get("vendor", ""),
                    item.get("description", ""),
                    item.get("invoice_date", ""),
                    item.get("total", 0.0)
                )
                if actual and os.path.exists(actual):
                    pdf_path = actual
                    item["pdf_path"] = actual

            if pdf_path and os.path.exists(pdf_path):
                it_pdf = QTableWidgetItem("📄 Open PDF")
                it_pdf.setTextAlignment(Qt.AlignCenter)
                it_pdf.setForeground(QColor("#00f2ff"))
                it_pdf.setBackground(QColor("#0e2a38"))
                f_pdf = it_pdf.font()
                f_pdf.setBold(True)
                f_pdf.setUnderline(True)
                it_pdf.setFont(f_pdf)
                it_pdf.setToolTip(f"Click to open Cheque Request PDF:\n{os.path.basename(pdf_path)}")
            else:
                it_pdf = QTableWidgetItem("—")
                it_pdf.setTextAlignment(Qt.AlignCenter)
                it_pdf.setForeground(QColor("#666666"))
                it_pdf.setToolTip("No Cheque Request PDF found on disk")
            self.table.setItem(row_idx, 5, it_pdf)

            # Vendor (Column 6)
            it_vendor = QTableWidgetItem(str(item.get("vendor", "")).upper())
            self.table.setItem(row_idx, 6, it_vendor)

            # Reference # / PO # (Column 7)
            raw_ref = str(item.get("reference_number", ""))
            if p_type == "PO" and raw_ref and not raw_ref.upper().startswith("PO"):
                display_ref = f"PO #{raw_ref}"
            else:
                display_ref = raw_ref
            it_ref = QTableWidgetItem(display_ref)
            it_ref.setTextAlignment(Qt.AlignCenter)
            if "PO" in p_type:
                it_ref.setForeground(QColor("#70b5ff"))
            self.table.setItem(row_idx, 7, it_ref)

            # Set # (Column 8)
            it_set = QTableWidgetItem(str(item.get("set_number", "")).upper())
            it_set.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 8, it_set)

            # Description (Column 9)
            it_desc = QTableWidgetItem(str(item.get("description", "")))
            self.table.setItem(row_idx, 9, it_desc)

            # Subtotal (Column 10, Center aligned)
            sub_val = item.get("subtotal") or 0.0
            it_subtot = QTableWidgetItem(f"${sub_val:,.2f}")
            it_subtot.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 10, it_subtot)

            # Total (Column 11, Center aligned)
            tot_val = item.get("total") or 0.0
            it_tot = QTableWidgetItem(f"${tot_val:,.2f}")
            it_tot.setTextAlignment(Qt.AlignCenter)
            it_tot.setForeground(QColor("#7ee787"))
            self.table.setItem(row_idx, 11, it_tot)

            # Rental Dates (Column 12)
            it_rental = QTableWidgetItem(str(item.get("rental_period", "")))
            it_rental.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 12, it_rental)

            # Buyer (Column 13)
            it_buyer = QTableWidgetItem(str(item.get("buyer_name", "")).upper())
            it_buyer.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 13, it_buyer)

    def on_table_item_clicked(self, item):
        pass

    def on_table_cell_clicked(self, row, col):
        if row >= 0 and row < self.table.rowCount():
            if col == 5:
                item_id_item = self.table.item(row, 0)
                if item_id_item:
                    item_data = item_id_item.data(Qt.UserRole)
                    if item_data:
                        self.open_selected_item_pdf(item_data)

    def on_table_selection_changed(self):
        selected_indexes = self.table.selectionModel().selectedRows()
        rows = sorted(list(set(idx.row() for idx in selected_indexes)))
        if not rows:
            rows = sorted(list(set(idx.row() for idx in self.table.selectedIndexes())))
        if not rows:
            self.clear_selection()
            return

        selected_items = []
        for r in rows:
            item_id_item = self.table.item(r, 0)
            if item_id_item:
                data = item_id_item.data(Qt.UserRole)
                if data:
                    selected_items.append(data)

        if not selected_items:
            self.clear_selection()
            return

        self.selected_items = selected_items
        self.selected_item = selected_items[0]

        if len(selected_items) == 1:
            self.set_selected_requisition(selected_items[0])
        else:
            self.set_multi_selected_requisitions(selected_items)

    def set_selected_requisition(self, item_data):
        if not item_data:
            return

        self.selected_item = item_data
        self.selected_items = [item_data]
        if hasattr(self, "btn_complete"):
            self.btn_complete.setText("🚀 UPDATE TRACKER & COMPLETE")
        
        vendor = item_data.get("vendor", "").upper()
        set_num = item_data.get("set_number", "").upper()
        ref_num = item_data.get("reference_number", "")
        total = item_data.get("total", 0.0)

        p_type = str(item_data.get("payment_type", "CHQ")).upper()
        if p_type in ("CH REQ", "REQ"): p_type = "CHQ"
        st_val = str(item_data.get("status", "PENDING")).upper()
        status_tag = " • [📬 CHEQUE IN HAND - Awaiting # & Notes]" if st_val == "RECEIVED" else " • [⏳ AWAITING CHEQUE]"
        pdf_path = item_data.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path) or "Receipts" in str(pdf_path):
            actual = find_actual_ch_req_pdf(
                item_data.get("vendor", ""),
                item_data.get("description", ""),
                item_data.get("invoice_date", ""),
                item_data.get("total", 0.0)
            )
            if actual and os.path.exists(actual):
                pdf_path = actual
                item_data["pdf_path"] = actual

        pdf_link_html = ""
        if pdf_path and os.path.exists(pdf_path):
            pdf_name = os.path.basename(pdf_path)
            pdf_link_html = f"  |  <a href='open_pdf' style='color: #00f2ff; text-decoration: underline; font-weight: bold;'>📄 {pdf_name}</a>"

        if p_type == "PO":
            po_display = ref_num if ref_num.upper().startswith("PO") else f"PO #{ref_num}"
            self.lbl_selected_info.setText(
                f"📌 Selected Purchase Order: <b>{vendor}</b>  |  {po_display}  |  Set: <b>{set_num}</b>  |  Total: <b>${total:,.2f}</b>{status_tag}{pdf_link_html}"
            )
        else:
            self.lbl_selected_info.setText(
                f"📝 Selected {p_type}: <b>{vendor}</b>  |  Set: <b>{set_num}</b>  |  Inv: <b>{ref_num or 'N/A'}</b>  |  Total: <b>${total:,.2f}</b>{status_tag}{pdf_link_html}"
            )

        if hasattr(self, "btn_card_open_pdf"):
            self.btn_card_open_pdf.setEnabled(True)

        # Update Cheque Received toggle button texts & styles
        if hasattr(self, "btn_toggle_received") and hasattr(self, "btn_card_received"):
            if st_val == "RECEIVED":
                style_recv = """
                    QPushButton {
                        background-color: #3d2b12;
                        color: #fcd34d;
                        font-weight: bold;
                        font-size: 11px;
                        padding: 7px 14px;
                        border-radius: 6px;
                        border: 1px solid #7a5424;
                    }
                    QPushButton:hover {
                        background-color: #523a18;
                        color: #fff;
                    }
                    QPushButton:disabled {
                        background-color: #1a1622;
                        color: #555;
                        border: 1px solid #33283d;
                    }
                """
                self.btn_toggle_received.setText("⏳ REVERT TO PENDING")
                self.btn_toggle_received.setStyleSheet(style_recv)

                style_card_recv = """
                    QPushButton {
                        background-color: #3d2b12;
                        color: #fcd34d;
                        font-weight: bold;
                        font-size: 11px;
                        padding: 6px 12px;
                        border-radius: 4px;
                        border: 1px solid #7a5424;
                    }
                    QPushButton:hover {
                        background-color: #523a18;
                        color: #fff;
                    }
                    QPushButton:disabled {
                        background-color: #222;
                        color: #555;
                    }
                """
                self.btn_card_received.setText("⏳ REVERT TO PENDING")
                self.btn_card_received.setStyleSheet(style_card_recv)
            else:
                style_pend = """
                    QPushButton {
                        background-color: #164e3f;
                        color: #6ee7b7;
                        font-weight: bold;
                        font-size: 11px;
                        padding: 7px 14px;
                        border-radius: 6px;
                        border: 1px solid #2a8069;
                    }
                    QPushButton:hover {
                        background-color: #1f6753;
                        color: #fff;
                    }
                    QPushButton:disabled {
                        background-color: #1a1622;
                        color: #555;
                        border: 1px solid #33283d;
                    }
                """
                self.btn_toggle_received.setText("📬 CHEQUE RECEIVED")
                self.btn_toggle_received.setStyleSheet(style_pend)

                style_card_pend = """
                    QPushButton {
                        background-color: #164e3f;
                        color: #6ee7b7;
                        font-weight: bold;
                        font-size: 11px;
                        padding: 6px 12px;
                        border-radius: 4px;
                        border: 1px solid #2a8069;
                    }
                    QPushButton:hover {
                        background-color: #1f6753;
                        color: #fff;
                    }
                    QPushButton:disabled {
                        background-color: #222;
                        color: #555;
                    }
                """
                self.btn_card_received.setText("📬 CHEQUE RECEIVED (IN HAND)")
                self.btn_card_received.setStyleSheet(style_card_pend)

            self.btn_toggle_received.setEnabled(True)
            self.btn_card_received.setEnabled(True)
        
        # Populate Quick Edit fields
        type_text = f"💵 CHQ" if p_type in ("CHQ", "REQ") else (f"⚡ ACH" if p_type == "ACH" else f"📌 PO")
        t_idx = self.cb_edit_type.findText(type_text)
        if t_idx >= 0:
            self.cb_edit_type.setCurrentIndex(t_idx)
        raw_d = str(item_data.get("date_required", "")).strip()
        p_dt = parse_date_key(raw_d) if raw_d else None
        if p_dt and p_dt.year < 9000:
            self.txt_edit_date_req.setDate(QDate(p_dt.year, p_dt.month, p_dt.day))
        else:
            self.txt_edit_date_req.setDate(QDate.currentDate())
        self.txt_edit_rental.setText(str(item_data.get("rental_period", "")))
        
        # Pre-fill cheque and delivery info only if stored in item and inputs are currently empty
        existing_chq = str(item_data.get("cheque_number", "")).strip()
        if existing_chq and not self.txt_chq_num.text().strip():
            self.txt_chq_num.setText(existing_chq)
        existing_deliv = str(item_data.get("delivery_notes", "")).strip()
        if existing_deliv and not self.txt_delivery.text().strip():
            self.txt_delivery.setText(existing_deliv)

        self.btn_save_edit.setEnabled(True)
        self.btn_full_edit.setEnabled(True)
        self.btn_edit.setEnabled(True)
        self.btn_complete.setEnabled(True)
        self.btn_toggle_type.setEnabled(True)
        self.btn_sync_pdf.setEnabled(True)
        self.btn_open_pdf.setEnabled(True)
        self.btn_delete.setEnabled(True)
        self.btn_toggle_card.setEnabled(True)

    def set_multi_selected_requisitions(self, items):
        if not items:
            return

        self.selected_items = items
        self.selected_item = items[0]

        count = len(items)
        total_sum = sum(float(it.get("total") or 0.0) for it in items)
        vendors = sorted(list(set(str(it.get("vendor", "")).strip().upper() for it in items if it.get("vendor"))))
        sets = sorted(list(set(str(it.get("set_number", "")).strip().upper() for it in items if it.get("set_number"))))
        invoices = [str(it.get("reference_number", "")).strip() for it in items if it.get("reference_number")]

        vendor_str = ", ".join(vendors[:3]) + (f" (+{len(vendors)-3} more)" if len(vendors) > 3 else "")
        set_str = ", ".join(sets[:4]) + (f" (+{len(sets)-4} more)" if len(sets) > 4 else "")
        inv_str = ", ".join(invoices[:4]) + (f" (+{len(invoices)-4} more)" if len(invoices) > 4 else "")

        num_received = sum(1 for it in items if str(it.get("status", "")).upper() == "RECEIVED")
        if num_received == count:
            status_tag = " • [📬 ALL IN HAND]"
            btn_recv_text = "⏳ REVERT ALL TO PENDING"
        elif num_received > 0:
            status_tag = f" • [{num_received}/{count} IN HAND]"
            btn_recv_text = "📬 MARK ALL RECEIVED (IN HAND)"
        else:
            status_tag = " • [⏳ AWAITING CHEQUE]"
            btn_recv_text = "📬 MARK ALL RECEIVED (IN HAND)"

        self.lbl_selected_info.setText(
            f"📦 <b>MULTI-SELECTION ({count} Requisitions)</b>  |  Vendors: <b>{vendor_str}</b>  |  Sets: <b>{set_str}</b>  |  Invs: <b>{inv_str or 'N/A'}</b>  |  Combined Total: <b style='color: #4ade80; font-size: 13px;'>${total_sum:,.2f}</b>{status_tag}"
        )

        if hasattr(self, "btn_complete"):
            self.btn_complete.setEnabled(True)
            self.btn_complete.setText(f"🚀 COMPLETE ALL {count} ON THIS CHEQUE (${total_sum:,.2f})")

        self.btn_delete.setEnabled(True)

        if hasattr(self, "btn_toggle_received") and hasattr(self, "btn_card_received"):
            self.btn_toggle_received.setText(btn_recv_text)
            self.btn_card_received.setText(btn_recv_text)
            self.btn_toggle_received.setEnabled(True)
            self.btn_card_received.setEnabled(True)

        # Disable single-item exclusive actions
        self.btn_edit.setEnabled(False)
        self.btn_full_edit.setEnabled(False)
        self.btn_save_edit.setEnabled(False)
        self.btn_toggle_type.setEnabled(False)
        self.btn_toggle_card.setEnabled(False)
        self.btn_sync_pdf.setEnabled(False)
        self.btn_open_pdf.setEnabled(False)
        if hasattr(self, "btn_card_open_pdf"):
            self.btn_card_open_pdf.setEnabled(False)

    def clear_selection(self):
        self.selected_item = None
        self.selected_items = []
        if hasattr(self, "table"):
            self.table.blockSignals(True)
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.table.blockSignals(False)
        if hasattr(self, "btn_toggle_received"):
            self.btn_toggle_received.setEnabled(False)
            self.btn_toggle_received.setText("📬 CHEQUE RECEIVED")
        if hasattr(self, "btn_card_received"):
            self.btn_card_received.setEnabled(False)
            self.btn_card_received.setText("📬 CHEQUE RECEIVED (IN HAND)")
        self.lbl_selected_info.setText("Select a requisition above to edit type/details or complete payment.")
        self.txt_edit_date_req.setDate(QDate.currentDate())
        self.txt_edit_rental.clear()
        self.btn_save_edit.setEnabled(False)
        self.btn_full_edit.setEnabled(False)
        self.btn_edit.setEnabled(False)
        self.btn_complete.setEnabled(False)
        if hasattr(self, "btn_complete"):
            self.btn_complete.setText("🚀 UPDATE TRACKER & COMPLETE")
        self.btn_toggle_type.setEnabled(False)
        self.btn_sync_pdf.setEnabled(False)
        self.btn_open_pdf.setEnabled(False)
        if hasattr(self, "btn_card_open_pdf"):
            self.btn_card_open_pdf.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.btn_toggle_card.setEnabled(False)

    def toggle_selected_item_received_status(self):
        items = getattr(self, "selected_items", [])
        if not items and self.selected_item:
            items = [self.selected_item]

        if not items:
            QMessageBox.information(self, "No Item", "Please select a requisition from the table first.")
            return

        if hasattr(self, "btn_toggle_received"):
            self.btn_toggle_received.setEnabled(False)
        if hasattr(self, "btn_card_received"):
            self.btn_card_received.setEnabled(False)

        if len(items) == 1:
            req = items[0]
            req_id = req.get("id")
            curr_status = str(req.get("status", "PENDING")).upper()
            target_status = "PENDING" if curr_status == "RECEIVED" else "RECEIVED"
            vendor = req.get("vendor", "")

            action_label = "Marking Cheque as Received (In Hand)" if target_status == "RECEIVED" else "Reverting status to Awaiting Cheque (Pending)"
            self.lbl_count.setText(f"⏳ {action_label} for #{req_id} ({vendor})...")

            self.recv_thread = ToggleChequeReceivedThread(req_id, target_status)
            self.recv_thread.finished_signal.connect(self.on_toggle_received_finished)
            self.recv_thread.error_signal.connect(self.on_toggle_received_error)
            self.recv_thread.start()
        else:
            num_received = sum(1 for it in items if str(it.get("status", "")).upper() == "RECEIVED")
            target_status = "PENDING" if num_received == len(items) else "RECEIVED"
            req_ids = [it.get("id") for it in items]

            action_label = f"Marking {len(items)} cheques as Received (In Hand)" if target_status == "RECEIVED" else f"Reverting {len(items)} cheques to Awaiting Cheque (Pending)"
            self.lbl_count.setText(f"⏳ {action_label}...")

            self.recv_thread = ToggleChequeReceivedThread(req_ids, target_status)
            self.recv_thread.finished_signal.connect(self.on_toggle_received_finished)
            self.recv_thread.error_signal.connect(self.on_toggle_received_error)
            self.recv_thread.start()

    def on_toggle_received_finished(self, res):
        if hasattr(self, "btn_toggle_received"):
            self.btn_toggle_received.setEnabled(True)
        if hasattr(self, "btn_card_received"):
            self.btn_card_received.setEnabled(True)

        msg = res.get("message", "Status updated.")
        self.load_pending_data()
        self.lbl_selected_info.setText(f"✅ {msg}")

    def on_toggle_received_error(self, err):
        if hasattr(self, "btn_toggle_received"):
            self.btn_toggle_received.setEnabled(True)
        if hasattr(self, "btn_card_received"):
            self.btn_card_received.setEnabled(True)
        QMessageBox.critical(self, "Status Update Failed", f"Could not update cheque status: {err}")

    def toggle_selected_item_payment_type(self):
        if not self.selected_item:
            QMessageBox.information(self, "No Item", "Please select a requisition from the table first.")
            return

        req_id = self.selected_item.get("id")
        self.btn_toggle_type.setEnabled(False)
        self.btn_toggle_card.setEnabled(False)
        self.lbl_count.setText(f"⏳ Toggling Cheque / ACH checkmark for Requisition #{req_id}...")

        self.toggle_thread = TogglePaymentTypeThread(req_id)
        self.toggle_thread.finished_signal.connect(self.on_toggle_finished)
        self.toggle_thread.error_signal.connect(self.on_toggle_error)
        self.toggle_thread.start()

    def on_toggle_finished(self, res):
        self.btn_toggle_type.setEnabled(True)
        self.btn_toggle_card.setEnabled(True)
        msg = res.get("message", "Updated payment type.")
        self.load_pending_data()
        self.lbl_selected_info.setText(f"✅ {msg}")

    def on_toggle_error(self, err):
        self.btn_toggle_type.setEnabled(True)
        self.btn_toggle_card.setEnabled(True)
        QMessageBox.critical(self, "Toggle Failed", f"Could not toggle payment type: {err}")

    def sync_selected_item_from_pdf(self):
        if not self.selected_item:
            QMessageBox.information(self, "No Item", "Please select a requisition from the table first.")
            return

        req_id = self.selected_item.get("id")
        self.btn_sync_pdf.setEnabled(False)
        self.lbl_count.setText(f"⏳ Syncing changes from PDF for Requisition #{req_id}...")

        self.sync_thread = SyncFromPdfThread(req_id)
        self.sync_thread.finished_signal.connect(self.on_sync_finished)
        self.sync_thread.error_signal.connect(self.on_sync_error)
        self.sync_thread.start()

    def on_sync_finished(self, res):
        self.btn_sync_pdf.setEnabled(True)
        msg = res.get("message", "Synced data from PDF.")
        self.load_pending_data()
        self.lbl_selected_info.setText(f"✅ {msg}")

    def on_sync_error(self, err):
        self.btn_sync_pdf.setEnabled(True)
        QMessageBox.critical(self, "Sync Failed", f"Could not sync from PDF: {err}")

    def open_selected_item_pdf(self, item_data=None):
        import time
        now = time.time()
        if now - getattr(self, "_last_pdf_open_time", 0) < 0.6:
            return
        self._last_pdf_open_time = now

        target = item_data or self.selected_item
        if not target:
            QMessageBox.information(self, "No Item", "Please select a requisition from the table first.")
            return

        pdf_path = target.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path) or "Receipts" in str(pdf_path):
            actual = find_actual_ch_req_pdf(
                target.get("vendor", ""),
                target.get("description", ""),
                target.get("invoice_date", ""),
                target.get("total", 0.0)
            )
            if actual and os.path.exists(actual):
                pdf_path = actual
                target["pdf_path"] = actual
                try:
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute("UPDATE cheque_requests SET pdf_path = ? WHERE id = ?", (actual, target.get("id")))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

        if pdf_path and os.path.exists(pdf_path):
            try:
                os.startfile(pdf_path)
            except Exception as e:
                QMessageBox.warning(self, "Open Error", f"Could not open PDF file: {e}")
        else:
            QMessageBox.warning(
                self, "PDF Not Found",
                f"Could not locate the Cheque Request PDF file for this requisition.\n\nVendor: {target.get('vendor')}\nInv #: {target.get('reference_number')}"
            )

    def save_item_changes(self):
        if not self.selected_item:
            return

        req_id = self.selected_item.get("id")
        raw_type = self.cb_edit_type.currentText()
        if "ACH" in raw_type:
            new_type = "ACH"
        elif "PO" in raw_type:
            new_type = "PO"
        else:
            new_type = "REQ"

        new_date_req = self.txt_edit_date_req.date().toString("MM/dd/yyyy")
        new_rental = self.txt_edit_rental.text().strip()

        updates = {
            "payment_type": new_type,
            "date_required": new_date_req,
            "rental_period": new_rental
        }
        # Also update PDF checkmark if PDF exists
        pdf_p = self.selected_item.get("pdf_path")
        if not pdf_p or not os.path.exists(pdf_p) or "Receipts" in pdf_p:
            pdf_p = find_actual_ch_req_pdf(self.selected_item.get("vendor", ""), self.selected_item.get("description", ""))
        if pdf_p and os.path.exists(pdf_p):
            update_pdf_payment_type(pdf_p, new_type)

        self.btn_save_edit.setEnabled(False)
        self.btn_save_edit.setText("⏳ SAVING...")

        self.edit_thread = UpdateChReqDetailsThread(req_id, updates)
        self.edit_thread.finished_signal.connect(self.on_edit_finished)
        self.edit_thread.error_signal.connect(self.on_edit_error)
        self.edit_thread.start()

    def quick_change_type(self, req_id: int, new_type: str):
        updates = {"payment_type": new_type}
        # Also update PDF checkmark if available
        if self.selected_item and self.selected_item.get("id") == req_id:
            pdf_p = self.selected_item.get("pdf_path")
            if not pdf_p or not os.path.exists(pdf_p) or "Receipts" in pdf_p:
                pdf_p = find_actual_ch_req_pdf(self.selected_item.get("vendor", ""), self.selected_item.get("description", ""))
            if pdf_p and os.path.exists(pdf_p):
                update_pdf_payment_type(pdf_p, new_type)
        self.lbl_count.setText(f"⏳ Updating Type for Requisition #{req_id} to {new_type}...")
        self.edit_thread = UpdateChReqDetailsThread(req_id, updates)
        self.edit_thread.finished_signal.connect(self.on_edit_finished)
        self.edit_thread.error_signal.connect(self.on_edit_error)
        self.edit_thread.start()

    def show_overdue_list_dialog(self):
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        achs = []
        chqs = []
        
        items = self.pending_items if self.pending_items else get_pending_cheque_requests()
        for it in items:
            if str(it.get("status", "PENDING")).upper() == "RECEIVED":
                continue
            raw_d = str(it.get("date_required", "")).strip()
            if not raw_d:
                continue
            try:
                dt_val = parse_date_key(raw_d)
                if dt_val and dt_val < today_start:
                    p_type = str(it.get("payment_type", "")).upper()
                    if p_type == "ACH":
                        achs.append(it)
                    elif p_type in ("CHQ", "REQ", "CH REQ"):
                        chqs.append(it)
            except Exception:
                pass

        # Sort both lists alphabetically by vendor, then date_required, then ref
        achs.sort(key=lambda x: (str(x.get("vendor", "")).strip().upper(), parse_date_key(x.get("date_required")), str(x.get("reference_number", ""))))
        chqs.sort(key=lambda x: (str(x.get("vendor", "")).strip().upper(), parse_date_key(x.get("date_required")), str(x.get("reference_number", ""))))

        dlg = OverdueListDialog(chqs, achs, self)
        dlg.exec()

    def open_edit_dialog_for_selected(self):
        if not self.selected_item:
            QMessageBox.information(self, "No Item Selected", "Please select a requisition from the table to edit.")
            return
        self.open_edit_dialog_for_data(self.selected_item)

    def open_edit_dialog_for_data(self, item_data):
        dlg = EditChReqDialog(item_data, self)
        if dlg.exec():
            updates = dlg.get_updates()
            req_id = item_data.get("id")
            self.lbl_count.setText(f"⏳ Saving changes for Requisition #{req_id}...")
            self.edit_thread = UpdateChReqDetailsThread(req_id, updates)
            self.edit_thread.finished_signal.connect(self.on_edit_finished)
            self.edit_thread.error_signal.connect(self.on_edit_error)
            self.edit_thread.start()

    def on_table_double_clicked(self, item):
        row = item.row()
        col = item.column()
        id_cell = self.table.item(row, 0)
        if id_cell:
            data = id_cell.data(Qt.UserRole)
            if data:
                if col == 5:
                    self.open_selected_item_pdf(data)
                else:
                    self.open_edit_dialog_for_data(data)

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        id_cell = self.table.item(row, 0)
        if not id_cell:
            return
        data = id_cell.data(Qt.UserRole)
        if not data:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #201a29;
                color: #eee;
                border: 1px solid #4a385c;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                font-size: 11px;
            }
            QMenu::item:selected {
                background-color: #795793;
                color: #fff;
            }
        """)

        # Multi-selection context menu
        if getattr(self, "selected_items", None) and len(self.selected_items) > 1 and any(it.get("id") == data.get("id") for it in self.selected_items):
            count = len(self.selected_items)
            total_sum = sum(float(it.get("total") or 0.0) for it in self.selected_items)
            num_received = sum(1 for it in self.selected_items if str(it.get("status", "")).upper() == "RECEIVED")

            act_batch_comp = menu.addAction(f"🚀 Complete All {count} on This Cheque (${total_sum:,.2f})...")
            if num_received == count:
                act_recv = menu.addAction(f"⏳ Revert All {count} to Awaiting Cheque (Pending)")
            else:
                act_recv = menu.addAction(f"📬 Mark All {count} as Received (In Hand)")
            menu.addSeparator()
            act_del = menu.addAction(f"🗑 Delete All {count} Selected Requisitions")

            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action == act_batch_comp:
                self.complete_selected_cheque()
            elif action == act_recv:
                self.toggle_selected_item_received_status()
            elif action == act_del:
                self.delete_selected_item()
            return

        vendor = str(data.get("vendor", "")).upper()
        curr_status = str(data.get("status", "PENDING")).upper()
        if curr_status == "RECEIVED":
            act_recv = menu.addAction("⏳ Revert Status to Awaiting Cheque (Pending)")
        else:
            act_recv = menu.addAction("📬 Mark Cheque as Received (In Hand)")
        act_toggle = menu.addAction("☑️ Toggle Checkmark (Cheque ↔ ACH)")
        act_sync = menu.addAction("📄 Sync / Re-read Changes from PDF")
        act_open = menu.addAction("📂 Open CH REQ PDF in Acrobat / Viewer")
        menu.addSeparator()
        act_req = menu.addAction(f"💵 Set Type to CHQ (Cheque)")
        act_ach = menu.addAction(f"⚡ Set Type to ACH")
        act_po = menu.addAction(f"📌 Set Type to PO")
        menu.addSeparator()
        act_edit = menu.addAction("✏️ Edit Requisition Details...")
        menu.addSeparator()
        act_overdue = menu.addAction("🚨 Past-Due List for Accounting...")
        menu.addSeparator()
        act_del = menu.addAction("🗑 Delete Requisition")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        req_id = data.get("id")
        if action == act_recv:
            self.toggle_selected_item_received_status()
        elif action == act_overdue:
            self.show_overdue_list_dialog()
        elif action == act_toggle:
            self.toggle_selected_item_payment_type()
        elif action == act_sync:
            self.sync_selected_item_from_pdf()
        elif action == act_open:
            self.open_selected_item_pdf()
        elif action == act_req:
            self.quick_change_type(req_id, "CHQ")
        elif action == act_ach:
            self.quick_change_type(req_id, "ACH")
        elif action == act_po:
            self.quick_change_type(req_id, "PO")
        elif action == act_edit:
            self.open_edit_dialog_for_data(data)
        elif action == act_del:
            self.delete_selected_item()

    def on_edit_finished(self, res):
        self.btn_save_edit.setEnabled(True)
        self.btn_save_edit.setText("💾 SAVE CHANGES TO TRACKER")
        msg = res.get("message", "Updated successfully.")
        self.load_pending_data()
        self.lbl_selected_info.setText(f"✅ {msg}")

    def on_edit_error(self, err):
        self.btn_save_edit.setEnabled(True)
        self.btn_save_edit.setText("💾 SAVE CHANGES TO TRACKER")
        QMessageBox.critical(self, "Update Failed", f"Could not update requisition: {err}")

    def complete_selected_cheque(self):
        items = []
        if getattr(self, "selected_items", None):
            items = list(self.selected_items)
        elif self.selected_item:
            items = [self.selected_item]
        else:
            curr_row = self.table.currentRow()
            if curr_row < 0 and self.table.selectedItems():
                curr_row = self.table.selectedItems()[0].row()
            if curr_row >= 0:
                id_item = self.table.item(curr_row, 0)
                if id_item:
                    d = id_item.data(Qt.UserRole)
                    if d:
                        items = [d]

        if not items:
            QMessageBox.warning(self, "No Requisition Selected", "Please select one or more requisitions from the table first.")
            return

        chq_num = self.txt_chq_num.text().strip()
        delivery = self.txt_delivery.text().strip()

        if not chq_num:
            QMessageBox.warning(self, "Missing Cheque #", "Please enter the Cheque # or ACH # received.")
            self.txt_chq_num.setFocus()
            return

        if len(items) > 1:
            total_sum = sum(float(it.get('total') or 0.0) for it in items)
            item_lines = []
            for it in items:
                v = it.get('vendor', '')
                inv = it.get('reference_number', 'N/A')
                st = it.get('set_number', '')
                amt = float(it.get('total') or 0.0)
                item_lines.append(f"• #{it.get('id')} - {v} (Inv {inv}, Set {st}): ${amt:,.2f}")

            preview_text = "\n".join(item_lines[:8])
            if len(item_lines) > 8:
                preview_text += f"\n... and {len(item_lines) - 8} more"

            reply = QMessageBox.question(
                self,
                "Confirm Batch Cheque Completion",
                f"You are about to complete {len(items)} requisitions on Cheque #{chq_num}:\n\n"
                f"{preview_text}\n\n"
                f"Combined Total: ${total_sum:,.2f}\n"
                f"Delivery / Notes: '{delivery or 'None'}'\n\n"
                f"This will update each requisition's set tab in Google Sheets, remove them from the 'CH REQS' tab, and mark them delivered.\n\n"
                f"Do you want to proceed?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return

        req_ids = [it.get("id") for it in items]

        self.btn_complete.setEnabled(False)
        self.progress_complete.setVisible(True)

        self.comp_thread = CompleteChequeThread(req_ids, chq_num, delivery)
        self.comp_thread.finished_signal.connect(self.on_complete_finished)
        self.comp_thread.error_signal.connect(self.on_complete_error)
        self.comp_thread.start()

    def on_complete_finished(self, res):
        self.progress_complete.setVisible(False)
        self.btn_complete.setEnabled(True)

        if res.get("status") == "success":
            QMessageBox.information(self, "Cheque Completed", res.get("message", "Tracker updated successfully!"))
            self.txt_chq_num.clear()
            self.txt_delivery.clear()
            self.load_pending_data()
        else:
            QMessageBox.warning(self, "Error Updating Tracker", res.get("message", "Failed to update tracker."))

    def on_complete_error(self, err_msg):
        self.progress_complete.setVisible(False)
        self.btn_complete.setEnabled(True)
        QMessageBox.critical(self, "Network / Sheet Error", f"Could not update Google Sheets:\n{err_msg}")

    def delete_selected_item(self):
        items = getattr(self, "selected_items", [])
        if not items and self.selected_item:
            items = [self.selected_item]

        if not items:
            QMessageBox.warning(self, "No Selection", "Please select a requisition to delete.")
            return

        if len(items) > 1:
            confirm = QMessageBox.question(
                self, "Confirm Batch Delete",
                f"Are you sure you want to delete all {len(items)} selected requisitions from the tracker?",
                QMessageBox.Yes | QMessageBox.No
            )
            if confirm == QMessageBox.Yes:
                for it in items:
                    delete_cheque_request(it.get("id"))
                self.load_pending_data()
            return

        vendor = items[0].get("vendor", "")
        req_id = items[0].get("id")

        confirm = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete pending requisition #{req_id} ({vendor})?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            delete_cheque_request(req_id)
            self.load_pending_data()
            delete_cheque_request(req_id)
            self.load_pending_data()

    def open_new_ch_req(self):
        dialog = CHReqDialog(self)
        if dialog.exec():
            self.load_pending_data()


    # --- PURCHASE ORDERS (POs) TAB METHODS ---

    def filter_po_table(self):
        query = ""
        if hasattr(self, "po_search_input"):
            query = self.po_search_input.text().strip().lower()

        filtered = []
        for item in getattr(self, "pending_pos", []):
            vendor = str(item.get("vendor", "")).lower()
            set_num = str(item.get("set_number", "")).lower()
            ref_num = str(item.get("reference_number", "")).lower()
            desc = str(item.get("description", "")).lower()
            buyer = str(item.get("buyer_name", "")).lower()

            if not query or query in vendor or query in set_num or query in ref_num or query in desc or query in buyer:
                filtered.append(item)

        # Sort from oldest to newest (oldest at the top) by date issued and numeric PO number
        from core.database import parse_date_key
        def po_sort_key(item):
            raw_d = str(item.get("invoice_date") or item.get("date_submitted") or "").strip()
            dt_val = parse_date_key(raw_d)
            raw_po = str(item.get("reference_number", "")).strip()
            m = re.search(r'\d+', raw_po)
            po_num = int(m.group()) if m else 999999
            return (dt_val, po_num, item.get("id", 0))

        filtered.sort(key=po_sort_key, reverse=False)

        if not hasattr(self, "po_table"):
            return

        self.po_table.setRowCount(len(filtered))
        for row_idx, item in enumerate(filtered):
            # 0. ID
            item_id = QTableWidgetItem(str(item.get("id")))
            item_id.setTextAlignment(Qt.AlignCenter)
            item_id.setData(Qt.UserRole, item)
            self.po_table.setItem(row_idx, 0, item_id)

            # 1. Date Issued
            dt_issued = str(item.get("invoice_date") or item.get("date_submitted") or "")
            it_date = QTableWidgetItem(dt_issued)
            it_date.setTextAlignment(Qt.AlignCenter)
            self.po_table.setItem(row_idx, 1, it_date)

            # 2. Type: 📌 PO
            it_type = QTableWidgetItem("📌 PO")
            it_type.setTextAlignment(Qt.AlignCenter)
            it_type.setForeground(QColor("#70b5ff"))
            it_type.setBackground(QColor("#142740"))
            f_bold = it_type.font()
            f_bold.setBold(True)
            it_type.setFont(f_bold)
            self.po_table.setItem(row_idx, 2, it_type)

            # 3. Vendor
            it_vendor = QTableWidgetItem(str(item.get("vendor", "")).upper())
            self.po_table.setItem(row_idx, 3, it_vendor)

            # 4. PO #
            raw_ref = str(item.get("reference_number", ""))
            po_display = raw_ref if raw_ref.upper().startswith("PO") else f"PO #{raw_ref}"
            it_po = QTableWidgetItem(po_display)
            it_po.setTextAlignment(Qt.AlignCenter)
            it_po.setForeground(QColor("#70b5ff"))
            f_pobold = it_po.font()
            f_pobold.setBold(True)
            it_po.setFont(f_pobold)
            self.po_table.setItem(row_idx, 4, it_po)

            # 5. Set #
            it_set = QTableWidgetItem(str(item.get("set_number", "")).upper())
            it_set.setTextAlignment(Qt.AlignCenter)
            self.po_table.setItem(row_idx, 5, it_set)

            # 6. Description
            it_desc = QTableWidgetItem(str(item.get("description", "")))
            self.po_table.setItem(row_idx, 6, it_desc)

            # 7. Subtotal
            sub_val = item.get("subtotal") or 0.0
            it_subtot = QTableWidgetItem(f"${sub_val:,.2f}")
            it_subtot.setTextAlignment(Qt.AlignCenter)
            self.po_table.setItem(row_idx, 7, it_subtot)

            # 8. Total
            tot_val = item.get("total") or 0.0
            it_tot = QTableWidgetItem(f"${tot_val:,.2f}")
            it_tot.setTextAlignment(Qt.AlignCenter)
            it_tot.setForeground(QColor("#7ee787"))
            f_totbold = it_tot.font()
            f_totbold.setBold(True)
            it_tot.setFont(f_totbold)
            self.po_table.setItem(row_idx, 8, it_tot)

            # 9. Rental / Notes
            notes_val = str(item.get("rental_period") or item.get("delivery_notes") or "")
            it_notes = QTableWidgetItem(notes_val)
            it_notes.setTextAlignment(Qt.AlignCenter)
            self.po_table.setItem(row_idx, 9, it_notes)

            # 10. Buyer
            it_buyer = QTableWidgetItem(str(item.get("buyer_name", "")).upper())
            it_buyer.setTextAlignment(Qt.AlignCenter)
            self.po_table.setItem(row_idx, 10, it_buyer)

    def on_po_table_selection_changed(self):
        selected_rows = self.po_table.selectedItems()
        if not selected_rows:
            self.clear_po_selection()
            return

        row = selected_rows[0].row()
        item_id_item = self.po_table.item(row, 0)
        if item_id_item:
            item_data = item_id_item.data(Qt.UserRole)
            self.selected_po = item_data

            vendor = item_data.get("vendor", "").upper()
            set_num = item_data.get("set_number", "").upper()
            ref_num = item_data.get("reference_number", "")
            total = item_data.get("total", 0.0)
            buyer = item_data.get("buyer_name", "").upper()
            po_display = ref_num if ref_num.upper().startswith("PO") else f"PO #{ref_num}"

            self.lbl_po_selected_info.setText(
                f"📌 Selected PO: <span style='color: white;'>{vendor}</span>  •  "
                f"<span style='color: #70b5ff; font-weight: bold;'>{po_display}</span>  •  "
                f"Set: <span style='color: #00f2ff;'>{set_num}</span>  •  "
                f"Total: <span style='color: #7ee787;'>${total:,.2f}</span>  •  "
                f"Buyer: {buyer or 'N/A'}"
            )

            self.txt_po_delivery.setText(str(item_data.get("delivery_notes") or ""))
            self.txt_po_inv_num.clear()
            if hasattr(self, "txt_po_date"):
                self.txt_po_date.setText(datetime.now().strftime("%m/%d"))

            self.btn_po_complete.setEnabled(True)
            self.btn_po_edit.setEnabled(True)
            self.btn_po_open_pdf.setEnabled(True)
            self.btn_edit_po.setEnabled(True)
            self.btn_open_pdf_po.setEnabled(True)
            self.btn_delete_po.setEnabled(True)

    def clear_po_selection(self):
        self.selected_po = None
        self.lbl_po_selected_info.setText("Select a purchase order above to view details, update notes, or close / complete.")
        self.txt_po_inv_num.clear()
        if hasattr(self, "txt_po_date"):
            self.txt_po_date.clear()
        self.txt_po_delivery.clear()
        self.btn_po_complete.setEnabled(False)
        self.btn_po_edit.setEnabled(False)
        self.btn_po_open_pdf.setEnabled(False)
        self.btn_edit_po.setEnabled(False)
        self.btn_open_pdf_po.setEnabled(False)
        self.btn_delete_po.setEnabled(False)

    def on_po_table_double_clicked(self, item):
        row = item.row()
        id_cell = self.po_table.item(row, 0)
        if id_cell:
            data = id_cell.data(Qt.UserRole)
            if data:
                self.open_edit_dialog_for_data(data)

    def show_po_context_menu(self, pos):
        item = self.po_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        id_cell = self.po_table.item(row, 0)
        if not id_cell:
            return
        data = id_cell.data(Qt.UserRole)
        if not data:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #181d26;
                color: #eee;
                border: 1px solid #30425c;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                font-size: 11px;
            }
            QMenu::item:selected {
                background-color: #21406d;
                color: #fff;
            }
        """)

        act_open = menu.addAction("📂 Open PO Document / Receipt")
        act_edit = menu.addAction("✏️ Edit PO Details...")
        menu.addSeparator()
        act_complete = menu.addAction("🚀 Close / Complete Purchase Order...")
        menu.addSeparator()
        act_del = menu.addAction("🗑 Delete Purchase Order")

        action = menu.exec(self.po_table.viewport().mapToGlobal(pos))
        if action == act_open:
            self.open_selected_po_pdf()
        elif action == act_edit:
            self.open_edit_dialog_for_data(data)
        elif action == act_complete:
            self.complete_selected_po()
        elif action == act_del:
            self.delete_selected_po()

    def open_selected_po_pdf(self):
        if not self.selected_po:
            QMessageBox.information(self, "No Item", "Please select a purchase order from the table first.")
            return

        pdf_path = self.selected_po.get("pdf_path")
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.startfile(pdf_path)
                return
            except Exception as e:
                pass

        actual = find_actual_ch_req_pdf(
            self.selected_po.get("vendor", ""),
            self.selected_po.get("description", ""),
            self.selected_po.get("invoice_date", ""),
            self.selected_po.get("total", 0.0)
        )
        if actual and os.path.exists(actual):
            try:
                os.startfile(actual)
                return
            except Exception as e:
                pass

        QMessageBox.warning(self, "File Not Found", "Could not locate the PO or receipt document on disk.")

    def complete_selected_po(self):
        if not self.selected_po:
            return

        inv_num = self.txt_po_inv_num.text().strip()
        delivery = self.txt_po_delivery.text().strip()
        date_str = self.txt_po_date.text().strip() if hasattr(self, 'txt_po_date') and self.txt_po_date.text().strip() else datetime.now().strftime("%m/%d")

        # Automatically include the completion / approval date
        if not inv_num:
            inv_num = f"PO COMPLETED {date_str}"
        elif inv_num.upper() in ("PO COMPLETED", "COMPLETED", "APPROVED", "PO APPROVED", "PO CLOSED"):
            inv_num = f"{inv_num.upper()} {date_str}"
        elif not any(char.isdigit() for char in inv_num.split()[-1] if '/' in inv_num or '-' in inv_num):
            if inv_num.upper().startswith("PO COMPLETED") or inv_num.upper().startswith("APPROVED"):
                inv_num = f"{inv_num} {date_str}"

        po_id = self.selected_po.get("id")
        po_ref = self.selected_po.get("reference_number", "")
        vendor = self.selected_po.get("vendor", "")

        confirm = QMessageBox.question(
            self, "Complete Purchase Order",
            f"Are you sure you want to complete and close PO {po_ref} ({vendor})?\n\n"
            f"Tracker Column P will be marked with: '{inv_num}'\n"
            f"Notes Column Q: '{delivery or 'N/A'}'",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        self.btn_po_complete.setEnabled(False)
        self.progress_po_complete.setVisible(True)

        self.po_comp_thread = CompleteChequeThread(po_id, inv_num, delivery)
        self.po_comp_thread.finished_signal.connect(self.on_po_complete_finished)
        self.po_comp_thread.error_signal.connect(self.on_po_complete_error)
        self.po_comp_thread.start()

    def on_po_complete_finished(self, res):
        self.progress_po_complete.setVisible(False)
        self.btn_po_complete.setEnabled(True)

        if res.get("status") == "success":
            QMessageBox.information(self, "PO Completed", res.get("message", "Purchase order closed and tracker updated successfully!"))
            self.load_pending_data()
        else:
            QMessageBox.warning(self, "Error Updating Tracker", res.get("message", "Failed to update tracker."))

    def on_po_complete_error(self, err_msg):
        self.progress_po_complete.setVisible(False)
        self.btn_po_complete.setEnabled(True)
        QMessageBox.critical(self, "Network / Sheet Error", f"Could not update Google Sheets:\n{err_msg}")

    def delete_selected_po(self):
        if not self.selected_po:
            QMessageBox.warning(self, "No Selection", "Please select a purchase order to delete.")
            return

        vendor = self.selected_po.get("vendor", "")
        ref = self.selected_po.get("reference_number", "")
        po_id = self.selected_po.get("id")

        confirm = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete PO #{po_id} ({vendor} - {ref}) from active PO tracking?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            delete_cheque_request(po_id)
            self.load_pending_data()

    def open_edit_dialog_for_selected_po(self):
        if not self.selected_po:
            QMessageBox.warning(self, "No Selection", "Please select a purchase order to edit.")
            return
        self.open_edit_dialog_for_data(self.selected_po)

    def open_new_po(self):
        dialog = CHReqDialog(self, prefill_data={"PaymentType": "PO"})
        if dialog.exec():
            self.load_pending_data()

    # --- ACH BATCH TAB METHODS ---

    def parse_and_match_ach(self):
        raw_text = self.txt_ach_input.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Input Empty", "Please paste the accountant's ACH updates in the text box.")
            return

        p_date = self.txt_ach_date.text().strip() or datetime.now().strftime("%m/%d")

        # Auto-format input text box if items were pasted as a single glued line
        formatted_input = normalize_pasted_text(raw_text)
        if formatted_input and formatted_input != raw_text:
            self.txt_ach_input.setPlainText(formatted_input)

        # Parse text
        parsed = parse_ach_batch_text(raw_text, default_date=p_date)
        if not parsed:
            QMessageBox.warning(self, "No Items", "Could not parse any valid lines from the text.")
            return

        # Match to local database & sets
        self.parsed_ach_items = match_ach_items_to_sets(parsed)

        # Populate table
        self.table_ach.setRowCount(len(self.parsed_ach_items))
        
        matched_count = 0
        unpaid_count = 0

        for r_idx, item in enumerate(self.parsed_ach_items):
            # 0. Checkbox
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk = QCheckBox()
            is_valid = item.get("status") == "PAID" and bool(item.get("ach_number"))
            chk.setChecked(is_valid)
            chk_layout.addWidget(chk)
            self.table_ach.setCellWidget(r_idx, 0, chk_widget)

            # 1. Vendor
            it_vendor = QTableWidgetItem(item.get("vendor", ""))
            self.table_ach.setItem(r_idx, 1, it_vendor)

            # 2. Invoice #
            it_inv = QTableWidgetItem(item.get("invoice", ""))
            it_inv.setTextAlignment(Qt.AlignCenter)
            self.table_ach.setItem(r_idx, 2, it_inv)

            # 3. ACH #
            it_ach = QTableWidgetItem(item.get("ach_number", ""))
            it_ach.setTextAlignment(Qt.AlignCenter)
            it_ach.setForeground(QColor("#7ee787"))
            self.table_ach.setItem(r_idx, 3, it_ach)

            # 4. Col P Entry
            it_col_p = QTableWidgetItem(item.get("formatted_col_p", ""))
            it_col_p.setTextAlignment(Qt.AlignCenter)
            it_col_p.setFont(QFont("Consolas", 10))
            self.table_ach.setItem(r_idx, 4, it_col_p)

            # 5. Target Set Tab
            set_str = item.get("matched_set", "")
            it_set = QTableWidgetItem(set_str)
            it_set.setTextAlignment(Qt.AlignCenter)
            if set_str:
                it_set.setForeground(QColor("#00f2ff"))
                it_set.setFont(QFont("Segoe UI", 10, QFont.Bold))
            self.table_ach.setItem(r_idx, 5, it_set)

            # 6. Match Status
            status_str = item.get("match_status", "")
            it_status = QTableWidgetItem(status_str)
            it_status.setTextAlignment(Qt.AlignCenter)
            if "Found" in status_str:
                it_status.setForeground(QColor("#7ee787"))
                matched_count += 1
            elif "Skipped" in status_str:
                it_status.setForeground(QColor("#d29922"))
                unpaid_count += 1
            else:
                it_status.setForeground(QColor("#ff7b72"))
            self.table_ach.setItem(r_idx, 6, it_status)

        self.lbl_ach_summary.setText(
            f"Parsed {len(self.parsed_ach_items)} lines:  ✅ {matched_count} Matched  |  ⚠️ {unpaid_count} Unpaid/Notes  |  ❌ {len(self.parsed_ach_items) - matched_count - unpaid_count} Not Found"
        )
        self.btn_apply_ach.setEnabled(matched_count > 0 or len(self.parsed_ach_items) > unpaid_count)

    def apply_ach_payments(self):
        items_to_apply = []
        for r_idx in range(self.table_ach.rowCount()):
            chk_widget = self.table_ach.cellWidget(r_idx, 0)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk and chk.isChecked():
                    items_to_apply.append(self.parsed_ach_items[r_idx])

        if not items_to_apply:
            QMessageBox.warning(self, "No Items Selected", "Please select at least one matched ACH item to apply.")
            return

        confirm = QMessageBox.question(
            self, "Apply ACH Payments",
            f"Apply {len(items_to_apply)} ACH payment updates directly to Google Sheets Tracker (Column P)?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        self.btn_apply_ach.setEnabled(False)
        self.progress_ach.setVisible(True)
        self.progress_ach.setRange(0, len(items_to_apply))
        self.progress_ach.setValue(0)

        self.ach_thread = ApplyACHBatchThread(items_to_apply)
        self.ach_thread.progress_signal.connect(self.on_ach_progress)
        self.ach_thread.finished_signal.connect(self.on_ach_finished)
        self.ach_thread.error_signal.connect(self.on_ach_error)
        self.ach_thread.start()

    def on_ach_progress(self, current, total, msg):
        self.progress_ach.setValue(current)
        self.lbl_ach_summary.setText(f"Applying ({current}/{total}): {msg}")

    def on_ach_finished(self, res):
        self.progress_ach.setVisible(False)
        self.btn_apply_ach.setEnabled(True)

        updated = res.get("updated_count", 0)
        failed = res.get("failed_count", 0)
        details = "\n".join(res.get("success_details", []))
        if failed > 0:
            details += "\n\nIssues:\n" + "\n".join(res.get("failed_items", []))

        msg = f"Successfully updated {updated} invoice(s) in Google Sheets Tracker!\n"
        if failed > 0:
            msg += f"{failed} invoice(s) could not be located in sheets.\n\n"
        msg += f"Details:\n{details[:800]}"
        if len(details) > 800:
            msg += "\n...(see sheets for all rows)"

        QMessageBox.information(self, "ACH Batch Applied", msg)
        self.load_pending_data()

    def on_ach_error(self, err_msg):
        self.progress_ach.setVisible(False)
        self.btn_apply_ach.setEnabled(True)
        QMessageBox.critical(self, "ACH Update Error", f"Error updating sheets:\n{err_msg}")

    def import_open_pos_from_db(self):
        """
        Scans SQLite receipts for active POs not yet in the pending list,
        and adds them clearly labeled as POs!
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT vendor, set_number, description, reference_number, po_number,
                   date, subtotal, tax, total, buyer_name, file_path, payment_method
            FROM receipts
            WHERE UPPER(TRIM(payment_method)) IN ('PO', 'P.O.')
              AND po_number IS NOT NULL AND length(trim(po_number)) > 0
            ORDER BY id DESC
            LIMIT 50
        ''')
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            QMessageBox.information(self, "No POs Found", "No receipts with PO payment method were found in the database.")
            return

        from services.ch_req_sheet_helper import record_cheque_request
        existing_refs = {str(item.get("reference_number", "")).upper() for item in (self.pending_items + self.pending_pos)}

        added_count = 0
        for r in rows:
            po_num = str(r["po_number"]).strip()
            po_upper = po_num.upper()
            # Filter out set numbers, show names, pending, or junk
            if (po_upper in ("PENDING", "NONE", "N/A", "TBD") or
                "SAMPLE SHOW" in po_upper or
                "SAMPLE" in po_upper or
                (len(po_num) <= 4 and po_num[0].isalpha() and po_num[1:].isdigit())):
                continue

            po_label = f"PO #{po_num}" if not po_upper.startswith("PO") else po_num
            if po_label.upper() in existing_refs or po_num.upper() in existing_refs:
                continue

            # Also check if this vendor & total already exists in pending_items (as CHQ or ACH)
            vendor_r = (r["vendor"] or "").strip().upper()
            tot_r = float(r["total"] or 0.0)
            is_dupe_of_chq = any(
                (item.get("vendor", "").strip().upper() == vendor_r and
                 abs(float(item.get("total", 0.0) or 0.0) - tot_r) < 0.05)
                for item in self.pending_items
            )
            if is_dupe_of_chq:
                continue

            record_data = {
                "vendor": r["vendor"] or "",
                "date_submitted": datetime.now().strftime("%m/%d/%Y"),
                "date_required": "",
                "payment_type": "PO",
                "set_number": r["set_number"] or "",
                "description": r["description"] or "",
                "reference_number": po_label,
                "invoice_date": r["date"] or "",
                "subtotal": r["subtotal"] or 0.0,
                "tax": r["tax"] or 0.0,
                "total": r["total"] or 0.0,
                "rental_period": "",
                "buyer_name": r["buyer_name"] or "",
                "pdf_path": r["file_path"] or ""
            }
            record_cheque_request(record_data)
            added_count += 1

        self.load_pending_data()
        QMessageBox.information(
            self, "POs Imported",
            f"Successfully imported {added_count} active Purchase Orders into the tracking list, clearly labeled as POs!"
        )
