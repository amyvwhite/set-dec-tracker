import os
import subprocess
from datetime import datetime
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QLineEdit, QPushButton, QMessageBox, 
                               QFileDialog, QWidget, QGridLayout)
from PySide6.QtCore import Qt
from core.settings import load_settings, save_settings
from services.rental_agreement_service import generate_rental_agreement, format_date_with_ordinal

class RentalAgreementDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Rental Agreement")
        self.setFixedSize(640, 600)
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
                color: #ffffff;
            }
            QLabel {
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                color: #00ff88;
                margin-top: 6px;
            }
            QLineEdit {
                background-color: #222222;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #333333;
                border-radius: 6px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #00ff88;
            }
            QPushButton#btn_browse {
                background-color: #222222;
                border: 1px solid #00ff88;
                border-radius: 6px;
                color: #00ff88;
                font-weight: bold;
                font-size: 11px;
                padding: 6px 14px;
            }
            QPushButton#btn_browse:hover {
                background-color: rgba(0, 255, 136, 0.2);
            }
            QPushButton#btn_generate {
                background-color: rgba(0, 255, 136, 0.15);
                border: 2px solid #00ff88;
                border-radius: 10px;
                color: #00ff88;
                font-weight: bold;
                font-size: 13px;
                letter-spacing: 2px;
                padding: 12px;
                margin-top: 15px;
            }
            QPushButton#btn_generate:hover {
                background-color: #00ff88;
                color: #000000;
            }
            QPushButton#btn_cancel {
                background-color: transparent;
                border: 1px solid #444444;
                border-radius: 10px;
                color: #888888;
                font-size: 11px;
                padding: 10px;
                margin-top: 15px;
            }
            QPushButton#btn_cancel:hover {
                border-color: #888888;
                color: #ffffff;
            }
        """)

        settings = load_settings()
        now = datetime.now()
        today_formatted = format_date_with_ordinal(now)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)

        title_label = QLabel("CREATE RENTAL AGREEMENT")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; letter-spacing: 3px; margin-bottom: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        grid = QGridLayout()
        grid.setSpacing(10)

        # 1. Vendor / Company Name
        grid.addWidget(QLabel("COMPANY / VENDOR NAME:"), 0, 0, 1, 2)
        self.vendor_input = QLineEdit()
        self.vendor_input.setPlaceholderText("e.g. Divine Furniture Rental")
        grid.addWidget(self.vendor_input, 1, 0, 1, 2)

        # 2. Dated As Of
        grid.addWidget(QLabel("DATED AS OF:"), 2, 0)
        self.dated_input = QLineEdit(today_formatted)
        grid.addWidget(self.dated_input, 3, 0)

        # 3. Rental Dates (Start & End)
        grid.addWidget(QLabel("RENTAL START DATE (Default: Today):"), 2, 1)
        self.start_date_input = QLineEdit(today_formatted)
        grid.addWidget(self.start_date_input, 3, 1)

        grid.addWidget(QLabel("RENTAL END DATE (Default: Dec 16th):"), 4, 0, 1, 2)
        self.end_date_input = QLineEdit("Dec 16th")
        grid.addWidget(self.end_date_input, 5, 0, 1, 2)

        # 4. Template PDF Path
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
        fallback_template = os.path.join(show_dir, "CH REQS", "MK - Rental Agmt - Set Dec, Props.pdf")
        grid.addWidget(QLabel("RENTAL AGREEMENT TEMPLATE (For New Show):"), 6, 0, 1, 2)
        template_row = QHBoxLayout()
        default_template = settings.get("rental_template_path", fallback_template)
        self.template_input = QLineEdit(default_template)
        template_row.addWidget(self.template_input)

        self.btn_browse_template = QPushButton("BROWSE...")
        self.btn_browse_template.setObjectName("btn_browse")
        self.btn_browse_template.clicked.connect(self.browse_template)
        template_row.addWidget(self.btn_browse_template)
        grid.addLayout(template_row, 7, 0, 1, 2)

        # 5. Output Directory
        grid.addWidget(QLabel("OUTPUT DIRECTORY:"), 8, 0, 1, 2)
        output_row = QHBoxLayout()
        fallback_output = os.path.join(show_dir, "Rental Agreements")
        default_output = settings.get("rental_output_dir", fallback_output)
        self.output_input = QLineEdit(default_output)
        output_row.addWidget(self.output_input)

        self.btn_browse_output = QPushButton("BROWSE...")
        self.btn_browse_output.setObjectName("btn_browse")
        self.btn_browse_output.clicked.connect(self.browse_output)
        output_row.addWidget(self.btn_browse_output)
        grid.addLayout(output_row, 9, 0, 1, 2)

        # 6. Rental Agreement Tracker Sheet URL (For New Show)
        grid.addWidget(QLabel("RENTAL AGREEMENT TRACKER SHEET URL (For New Show):"), 10, 0, 1, 2)
        default_ra_sheet = settings.get("rental_agreements_sheet_url", "")
        self.ra_sheet_input = QLineEdit(default_ra_sheet)
        self.ra_sheet_input.setPlaceholderText("https://docs.google.com/spreadsheets/d/... (Rental Agreements tracking sheet)")
        grid.addWidget(self.ra_sheet_input, 11, 0, 1, 2)

        layout.addLayout(grid)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_generate = QPushButton("⚡ GENERATE RENTAL AGREEMENT")
        self.btn_generate.setObjectName("btn_generate")
        self.btn_generate.clicked.connect(self.generate_agreement)
        btn_layout.addWidget(self.btn_generate)

        layout.addLayout(btn_layout)

    def browse_template(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Rental Agreement Template PDF", 
            self.template_input.text(), "PDF Files (*.pdf)"
        )
        if file_path:
            self.template_input.setText(file_path)

    def browse_output(self):
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder for Rental Agreements",
            self.output_input.text()
        )
        if folder_path:
            self.output_input.setText(folder_path)

    def generate_agreement(self):
        vendor_name = self.vendor_input.text().strip()
        if not vendor_name:
            QMessageBox.warning(self, "Missing Name", "Please enter the Company / Vendor Name.")
            self.vendor_input.setFocus()
            return

        dated_as_of = self.dated_input.text().strip()
        start_date = self.start_date_input.text().strip()
        end_date = self.end_date_input.text().strip()
        template_path = self.template_input.text().strip()
        output_dir = self.output_input.text().strip()

        if not os.path.exists(template_path):
            QMessageBox.critical(self, "Template Missing", f"Template PDF not found:\n{template_path}")
            return

        try:
            # Save settings for future runs
            settings = load_settings()
            settings["rental_template_path"] = template_path
            settings["rental_output_dir"] = output_dir
            if hasattr(self, 'ra_sheet_input') and self.ra_sheet_input.text().strip():
                settings["rental_agreements_sheet_url"] = self.ra_sheet_input.text().strip()
            save_settings(settings)

            # Generate PDF
            pdf_path = generate_rental_agreement(
                vendor_name=vendor_name,
                start_date=start_date,
                end_date=end_date,
                dated_as_of=dated_as_of,
                template_path=template_path,
                output_dir=output_dir
            )

            msg = QMessageBox(self)
            msg.setWindowTitle("Agreement Generated")
            msg.setText(f"Successfully generated Rental Agreement for:\n<b>{vendor_name}</b>")
            msg.setInformativeText(f"File saved to:\n{pdf_path}")
            msg.setIcon(QMessageBox.Information)

            btn_open_file = msg.addButton("Open PDF", QMessageBox.ActionRole)
            btn_open_folder = msg.addButton("Open Folder", QMessageBox.ActionRole)
            btn_ok = msg.addButton("OK", QMessageBox.AcceptRole)

            msg.exec()

            clicked = msg.clickedButton()
            if clicked == btn_open_file:
                if os.name == 'nt':
                    os.startfile(pdf_path)
                else:
                    subprocess.run(['open' if os.name == 'posix' else 'xdg-open', pdf_path])
            elif clicked == btn_open_folder:
                if os.name == 'nt':
                    subprocess.run(['explorer', '/select,', os.path.normpath(pdf_path)])
                else:
                    subprocess.run(['open', output_dir])

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate agreement:\n{str(e)}")
