from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QFileDialog, QMessageBox, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from services.schedule_parser import update_schedule_dates
from core.settings import load_settings
import os

class GenerateScheduleDatesThread(QThread):
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, url, text):
        super().__init__()
        self.url = url
        self.text = text

    def run(self):
        try:
            res = update_schedule_dates(self.url, self.text)
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))

class ScheduleImporterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Schedule & Update Shoot Dates")
        self.setMinimumSize(600, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #0d0d0d;
                color: white;
            }
            QLabel {
                color: #ccc;
                font-size: 12px;
            }
            QTextEdit {
                background-color: #1a1a1a;
                border: 1px solid #333;
                color: white;
                padding: 6px;
                font-size: 12px;
            }
            QPushButton {
                background-color: #1e1e1e;
                border: 1px solid #00f2ff;
                color: #00f2ff;
                font-weight: bold;
                padding: 8px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #00f2ff;
                color: black;
            }
            QPushButton:disabled {
                border-color: #444;
                color: #666;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header Title
        title_lbl = QLabel("📅 SCHEDULE IMPORTER")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #00f2ff; letter-spacing: 1px;")
        layout.addWidget(title_lbl)
        
        info_lbl = QLabel("Upload a One-Line Schedule PDF or paste the text below. Existing dates will be preserved.")
        layout.addWidget(info_lbl)

        # File Upload Option
        file_layout = QHBoxLayout()
        self.file_btn = QPushButton("📁 Upload Schedule File (PDF / TXT)")
        self.file_btn.clicked.connect(self.select_file)
        self.file_label = QLabel("No file selected")
        self.file_label.setStyleSheet("color: #888; font-style: italic;")
        file_layout.addWidget(self.file_btn)
        file_layout.addWidget(self.file_label, stretch=1)
        layout.addLayout(file_layout)

        # Direct Text Input Option
        txt_lbl = QLabel("Or Paste Schedule Text:")
        layout.addWidget(txt_lbl)

        self.text_area = QTextEdit()
        self.text_area.setPlaceholderText(
            "Paste One-Line Schedule here, e.g.:\n"
            "DAY 1 - Tuesday September 1 - Approx Call: 930 am\n"
            "204. 14 INT CAFE ROMA - MAX'S OFFICE"
        )
        layout.addWidget(self.text_area, stretch=1)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.generate_btn = QPushButton("🚀 PARSE SCHEDULE & UPDATE DATES")
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #00f2ff;
                color: black;
                font-weight: bold;
                font-size: 13px;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #00c8d4;
            }
        """)
        self.generate_btn.clicked.connect(self.start_generation)

        close_btn = QPushButton("Cancel")
        close_btn.setStyleSheet("border-color: #555; color: #aaa;")
        close_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addWidget(self.generate_btn)
        layout.addLayout(btn_layout)

        self.selected_file_path = None
        
        # Enable Drag and Drop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.selected_file_path = file_path
                self.file_label.setText(os.path.basename(file_path))
                self.parse_and_fill_from_file(file_path)
                break  # Only process the first file

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Schedule File", "", "Supported Files (*.pdf *.txt *.csv);;PDF Files (*.pdf);;Text (*.txt *.csv)"
        )
        if file_path:
            self.selected_file_path = file_path
            self.file_label.setText(os.path.basename(file_path))
            self.parse_and_fill_from_file(file_path)

    def parse_and_fill_from_file(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        extracted_text = ""
        if ext == '.pdf':
            try:
                import fitz
                doc = fitz.open(file_path)
                for page in doc:
                    extracted_text += page.get_text() + "\n"
                doc.close()
            except Exception as e:
                QMessageBox.warning(self, "PDF Read Error", f"Could not read PDF text: {e}")
        elif ext in ['.txt', '.csv']:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    extracted_text = f.read()
            except Exception as e:
                QMessageBox.warning(self, "File Read Error", f"Could not read text file: {e}")
        
        if extracted_text:
            self.text_area.setPlainText(extracted_text)

    def start_generation(self):
        settings = load_settings()
        url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
        if not url:
            QMessageBox.critical(self, "Configuration Error", "Google Sheets URL is missing in Settings!")
            return

        text = self.text_area.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No Schedule Found", "No text found! Please paste schedule or upload a file.")
            return

        self.generate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)

        self.gen_thread = GenerateScheduleDatesThread(url, text)
        self.gen_thread.finished_signal.connect(self.on_generation_finished)
        self.gen_thread.error_signal.connect(self.on_generation_error)
        self.gen_thread.start()

    def on_generation_finished(self, result):
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        status = result.get("status")
        if status == "success":
            msg = f"🎉 SUCCESS!\n\n{result.get('message')}"
            QMessageBox.information(self, "Dates Updated", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "Update Error", result.get("message", "Unknown error"))

    def on_generation_error(self, err_msg):
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Update Error", f"An error occurred: {err_msg}")
