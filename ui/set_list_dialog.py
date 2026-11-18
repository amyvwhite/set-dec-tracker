from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, 
    QTextEdit, QFileDialog, QMessageBox, QComboBox, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from services.sheets import create_tracker_sets_and_tabs
from core.settings import load_settings
import os
import re

class GenerateTrackerTabsThread(QThread):
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, url, episode_name, set_items, default_budget=None):
        super().__init__()
        self.url = url
        self.episode_name = episode_name
        self.set_items = set_items
        self.default_budget = default_budget

    def run(self):
        try:
            res = create_tracker_sets_and_tabs(self.url, self.episode_name, self.set_items, self.default_budget)
            self.finished_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))

class SetListImporterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Set List & Generate Tracker Tabs")
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
            QLineEdit, QComboBox, QTextEdit {
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
        title_lbl = QLabel("📋 SET LIST IMPORTER & TRACKER AUTOMATOR")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #00f2ff; letter-spacing: 1px;")
        layout.addWidget(title_lbl)

        # Episode Selection
        ep_layout = QHBoxLayout()
        ep_lbl = QLabel("Episode Section:")
        self.ep_combo = QComboBox()
        episodes = [f"EPISODE {200 + i}" for i in range(1, 13)] + ["AMORT"]
        self.ep_combo.addItems(episodes)
        self.ep_combo.setEditable(True)
        ep_layout.addWidget(ep_lbl)
        ep_layout.addWidget(self.ep_combo, stretch=1)
        layout.addLayout(ep_layout)

        # File Upload Option
        file_layout = QHBoxLayout()
        self.file_btn = QPushButton("📁 Upload Set List File (PDF / Image / TXT / CSV)")
        self.file_btn.clicked.connect(self.select_file)
        self.file_label = QLabel("No file selected")
        self.file_label.setStyleSheet("color: #888; font-style: italic;")
        file_layout.addWidget(self.file_btn)
        file_layout.addWidget(self.file_label, stretch=1)
        layout.addLayout(file_layout)

        # Direct Text Input Option
        txt_lbl = QLabel("Or Paste Set List Text / Codes (e.g. D10 INT MEMORY CARE FACILITY):")
        layout.addWidget(txt_lbl)

        self.text_area = QTextEdit()
        self.text_area.setPlaceholderText(
            "Paste Set List here, e.g.:\n"
            "D10 INT MEMORY CARE FACILITY - SECRET ROOM\n"
            "D11 EXT REC CENTER - ACROSS STREET\n"
            "D12 INT BRENNAN'S CAR - MOVING\n"
            "D13 INT MAX'S CAR\n"
            "D14 EXT BRONX STREETS - INTERSECTION"
        )
        layout.addWidget(self.text_area, stretch=1)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate spinner
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.generate_btn = QPushButton("🚀 GENERATE TRACKER LINES & SET TABS")
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

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Set List File", "", "All Supported Files (*.pdf *.png *.jpg *.jpeg *.txt *.csv *.json);;PDF Files (*.pdf);;Images (*.png *.jpg *.jpeg);;Text/CSV (*.txt *.csv);;JSON (*.json)"
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

    def parse_set_items(self):
        text = self.text_area.toPlainText().strip()
        items = []
        if not text:
            return items

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        
        i = 0
        while i < len(lines):
            line_str = lines[i]
            
            # 1. Check if set code and set name are on the SAME line (e.g. C10 INT MEMORY CARE)
            match_same_line = re.search(r'^([A-Z]\d{1,3}|\d{3})\s+([A-Z0-9\s\-/’\'—–:]+)', line_str, re.IGNORECASE)
            if match_same_line:
                code = match_same_line.group(1).upper()
                name = match_same_line.group(2).strip().upper()
                items.append({"code": code, "name": name})
                i += 1
                continue
                
            # 2. Check if set code is on its OWN line (e.g. Line 1: C10, Line 2: INT MEMORY CARE)
            match_code_only = re.match(r'^([A-Z]\d{1,3}|\d{3})$', line_str, re.IGNORECASE)
            if match_code_only:
                code = match_code_only.group(1).upper()
                name = ""
                if i + 1 < len(lines) and not re.match(r'^([A-Z]\d{1,3}|\d{3})$', lines[i+1], re.IGNORECASE):
                    name = lines[i+1].strip().upper()
                    i += 1
                items.append({"code": code, "name": name})
                i += 1
                continue

            # 3. Fallback split by tab/comma/bar
            parts = [p.strip() for p in re.split(r'[\t,;|]', line_str) if p.strip()]
            if len(parts) >= 2 and re.match(r'^[A-Z0-9]+$', parts[0], re.IGNORECASE):
                items.append({"code": parts[0].upper(), "name": parts[1].upper()})
            
            i += 1

        return items

    def start_generation(self):
        settings = load_settings()
        url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
        if not url:
            QMessageBox.critical(self, "Configuration Error", "Google Sheets URL is missing in Settings!")
            return

        set_items = self.parse_set_items()
        if not set_items:
            QMessageBox.warning(self, "No Sets Found", "No set codes found in text/file! Please format lines as e.g.:\nD10 INT MEMORY CARE FACILITY")
            return

        ep_name = self.ep_combo.currentText().strip()

        # --- SAVE SET LIST FOR GLOBAL APP USAGE ---
        from core.settings import save_settings
        import json
        
        dynamic_sets = settings.get("dynamic_sets", {})
        
        ep_prefix = ep_name
        if ep_name.startswith("EPISODE "):
            num_str = ep_name.split(" ")[1]
            if len(num_str) == 3:
                pass
        
        dynamic_sets[ep_name] = set_items
        settings["dynamic_sets"] = dynamic_sets
        save_settings(settings)
        
        # Also sync to standalone bot set_list.json files
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
        bot_set_lists = [
            os.path.join(show_dir, "CH REQS", "set_list.json"),
            os.path.join(show_dir, "PO REVISIONS", "set_list.json")
        ]
        updates = {item["code"]: item["name"] for item in set_items}
        for path in bot_set_lists:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        bot_data = json.load(f)
                    bot_data.update(updates)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(bot_data, f, indent=4)
                except Exception as e:
                    print(f"DEBUG: Failed to update bot set list {path}: {e}")
        # -------------------------------------------

        self.generate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)

        self.gen_thread = GenerateTrackerTabsThread(url, ep_name, set_items)
        self.gen_thread.finished_signal.connect(self.on_generation_finished)
        self.gen_thread.error_signal.connect(self.on_generation_error)
        self.gen_thread.start()

    def on_generation_finished(self, result):
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        status = result.get("status")
        if status == "success":
            msg = f"🎉 SUCCESS!\n\n{result.get('message')}\n\nTabs Created: {', '.join(result.get('created_tabs', [])) if result.get('created_tabs') else 'All tabs were already present'}"
            QMessageBox.information(self, "Tracker Generation Complete", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "Generation Error", result.get("message", "Unknown error"))

    def on_generation_error(self, err_msg):
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Generation Error", f"An error occurred: {err_msg}")
