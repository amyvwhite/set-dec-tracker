from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton, QMessageBox, QApplication, QProgressDialog
from PySide6.QtCore import Qt, Signal, QThread
from services.petty_cash_bot import load_envelope_state, complete_envelope, save_envelope_state, BASE_DIR
from datetime import datetime
import os

class CompleteEnvelopeWorker(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, owner, env_num, today_str):
        super().__init__()
        self.owner = owner
        self.env_num = env_num
        self.today_str = today_str

    def run(self):
        try:
            complete_envelope(self.owner, self.env_num, self.today_str)

            state = load_envelope_state()
            if self.owner in state and str(self.env_num) in state[self.owner]:
                del state[self.owner][str(self.env_num)]
                save_envelope_state(state)

            self.finished_signal.emit(True, "")
        except Exception as e:
            import traceback
            self.finished_signal.emit(False, f"{str(e)}\n{traceback.format_exc()}")

class EnvelopeMgmtDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Envelope Management")
        self.setFixedSize(500, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #ffd9b3;
            }
            QListWidget {
                background-color: #333;
                color: white;
                font-size: 14px;
                padding: 5px;
                border: 1px solid #ffd9b3;
                border-radius: 5px;
            }
            QPushButton {
                background-color: #000;
                border: 2px solid #ffd9b3;
                border-radius: 10px;
                color: #ffd9b3;
                font-weight: bold;
                font-size: 11px;
                letter-spacing: 1px;
                padding: 10px;
                margin-top: 5px;
            }
            QPushButton:hover {
                background-color: #ffd9b3;
                color: black;
            }
        """)

        layout = QVBoxLayout(self)

        lbl = QLabel("Current Open Envelopes:")
        layout.addWidget(lbl)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.btn_mark_complete = QPushButton("✅ MARK SELECTED AS COMPLETE")
        self.btn_mark_complete.clicked.connect(self.mark_complete)
        layout.addWidget(self.btn_mark_complete)

        self.btn_open_folder = QPushButton("📁 OPEN ENVELOPE FOLDER")
        self.btn_open_folder.clicked.connect(self.open_folder)
        layout.addWidget(self.btn_open_folder)

        self.btn_delete_env = QPushButton("🗑️ DELETE SELECTED ENVELOPE")
        self.btn_delete_env.setStyleSheet("""
            QPushButton {
                border-color: #80dfff;
                color: #80dfff;
            }
            QPushButton:hover {
                background-color: #80dfff;
                color: white;
            }
        """)
        self.btn_delete_env.clicked.connect(self.delete_envelope)
        layout.addWidget(self.btn_delete_env)

        self.load_data()

    def load_data(self):
        self.list_widget.clear()
        state = load_envelope_state()
        for owner, envs in state.items():
            if owner == "_global_env_counter" or not isinstance(envs, dict):
                continue
            for env_num, data in envs.items():
                total = data.get("grand_total", 0.0)
                self.list_widget.addItem(f"{owner} - ENV #{env_num} - Total: ${total:.2f}")

    def mark_complete(self):
        selected = self.list_widget.currentItem()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select an envelope first.")
            return

        text = selected.text()
        parts = text.split(" - ")
        owner = parts[0]
        env_num = parts[1].replace("ENV #", "").strip()

        today_str = datetime.today().strftime("%Y-%m-%d")

        self.progress_dialog = QProgressDialog(f"Completing Envelope #{env_num} for {owner}...\nDownloading PDF and updating Petty Cash Tracker.", None, 0, 0, self)
        self.progress_dialog.setWindowTitle("Processing Envelope")
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.worker = CompleteEnvelopeWorker(owner, env_num, today_str)
        self.worker.finished_signal.connect(lambda success, err, o=owner, e_num=env_num: self._on_complete_finished(success, err, o, e_num))
        self.worker.start()

    def _on_complete_finished(self, success, err_msg, owner, env_num):
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
        
        if success:
            QMessageBox.information(self, "Success", f"Envelope #{env_num} for {owner} marked COMPLETE and uploaded to the Petty Cash Tracker!")
            self.load_data()
        else:
            QMessageBox.critical(self, "Error", f"Failed to complete envelope: {err_msg}")

    def open_folder(self):
        selected = self.list_widget.currentItem()
        if not selected:
            return
        text = selected.text()
        try:
            env_num = text.split(" - ")[1].replace("ENV #", "").strip()
            
            import glob
            import subprocess
            
            search_path = os.path.join(BASE_DIR, f"{env_num} *")
            matching_dirs = glob.glob(search_path)
            
            if matching_dirs:
                target_dir = os.path.normpath(matching_dirs[0])
                subprocess.Popen(f'explorer "{target_dir}"')
            else:
                QMessageBox.information(self, "Not Found", f"Folder for Envelope #{env_num} not found in {BASE_DIR}. It will be created when receipts are added.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not open folder: {e}")

    def delete_envelope(self):
        selected = self.list_widget.currentItem()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select an envelope first.")
            return

        text = selected.text()
        parts = text.split(" - ")
        owner = parts[0]
        env_num = parts[1].replace("ENV #", "").strip()
        
        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete Envelope #{env_num} for {owner}?\n\nThis will remove it from the system so you can restart it. This action cannot be undone.", QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            state = load_envelope_state()
            if owner in state and env_num in state[owner]:
                del state[owner][env_num]
                save_envelope_state(state)
                QMessageBox.information(self, "Deleted", f"Envelope #{env_num} deleted successfully.")
                self.load_data()
