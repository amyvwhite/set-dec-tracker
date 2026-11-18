import os

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox, QInputDialog, QApplication

from PySide6.QtCore import Qt, QTimer

from services.petty_cash_bot import load_envelope_state, complete_envelope, get_template_tab_name, save_envelope_state, BASE_DIR

from core.petty_cash_thread import ProcessPettyCashThread

from datetime import datetime



class PettyCashDialog(QDialog):

    def __init__(self, parent=None):

        super().__init__(parent)

        self.setWindowTitle("Process Petty Cash")

        self.setFixedSize(400, 300)

        self.setStyleSheet("""

            QDialog {

                background-color: #1a1a1a;

                color: white;

            }

            QLabel {

                font-size: 14px;

                font-weight: bold;

                color: #d2b3ff;

            }

            QComboBox {

                background-color: #333;

                color: white;

                padding: 5px;

                border-radius: 5px;

                font-size: 12px;

            }

            QPushButton {

                background-color: #000;

                border: 2px solid #d2b3ff;

                border-radius: 10px;

                color: #d2b3ff;

                font-weight: bold;

                font-size: 11px;

                letter-spacing: 1px;

                padding: 10px;

                margin-top: 5px;

            }

            QPushButton:hover {

                background-color: #d2b3ff;

                color: black;

            }

        """)



        layout = QVBoxLayout(self)



        self.lbl_buyer = QLabel("Who is this envelope for?")

        layout.addWidget(self.lbl_buyer)



        self.buyer_combo = QComboBox()

        from core.settings import get_petty_cash_envelope_owners
        self.buyer_combo.addItems(get_petty_cash_envelope_owners())

        self.buyer_combo.currentTextChanged.connect(self.update_env_info)

        layout.addWidget(self.buyer_combo)



        self.lbl_env_info = QLabel("")

        self.lbl_env_info.setStyleSheet("color: #ccc; font-size: 12px; font-weight: normal; margin-top: 10px; margin-bottom: 10px;")

        layout.addWidget(self.lbl_env_info)



        self.btn_add_receipts = QPushButton("📥 ADD RECEIPTS TO ENVELOPE")

        self.btn_add_receipts.clicked.connect(self.add_receipts)

        layout.addWidget(self.btn_add_receipts)



        self.btn_mark_complete = QPushButton("✅ MARK AS COMPLETE")

        self.btn_mark_complete.clicked.connect(self.mark_complete)

        layout.addWidget(self.btn_mark_complete)



        self.btn_start_new = QPushButton("🆕 START BRAND NEW ENVELOPE")

        self.btn_start_new.clicked.connect(self.start_new)

        layout.addWidget(self.btn_start_new)



        self.update_env_info()



    def get_current_buyer_and_env(self):

        owner = self.buyer_combo.currentText()

        if owner == "OTHER":

            owner, ok = QInputDialog.getText(self, "Other Buyer", "Enter buyer name:")

            if not ok or not owner.strip():

                return None, None

            owner = owner.strip().upper()

            

        state = load_envelope_state()

        if owner not in state:

            state[owner] = {}

        

        env_keys = list(state[owner].keys())

        env_keys = list(state[owner].keys())

        if not env_keys:

            current_env = None

        else:

            current_env = max([int(k) for k in env_keys])

            

        return owner, current_env



    def update_env_info(self):

        owner = self.buyer_combo.currentText()

        if owner == "OTHER":

            self.lbl_env_info.setText("Enter name when continuing...")

            return

            

        state = load_envelope_state()

        env_keys = list(state.get(owner, {}).keys())

        if not env_keys:

            self.lbl_env_info.setText("Current Envelope: NONE (Please Start New Envelope)")

        else:

            current_env = max([int(k) for k in env_keys])

            self.lbl_env_info.setText(f"Current Envelope: #{current_env}")



    def add_receipts(self):

        owner, env_num = self.get_current_buyer_and_env()

        if not owner: return

        if env_num is None:

            QMessageBox.warning(self, "Warning", "Please start a brand new envelope first before adding receipts!")

            return



        today_str = datetime.today().strftime("%Y-%m-%d")

        input_dir = os.path.join(BASE_DIR, "petty cash input")



        self.parent().progress_label.setText(f"PROCESSING PETTY CASH FOR {owner}...")

        self.parent().progress_label.setVisible(True)

        if hasattr(self.parent(), 'halt_btn'):

            self.parent().halt_btn.setVisible(True)



        self.thread = ProcessPettyCashThread(input_dir, owner, env_num, today_str)

        self.parent().petty_cash_thread = self.thread # Keep alive

        self.thread.progress_update.connect(self.parent().update_progress_ui)

        self.thread.error.connect(self.show_error)

        self.thread.needs_set_number.connect(self.parent().prompt_for_set_number)

        self.thread.finished_processing.connect(self.finished_processing)

        self.thread.start()

        self.accept() # Close dialog



    def mark_complete(self):

        owner, env_num = self.get_current_buyer_and_env()

        if not owner: return



        today_str = datetime.today().strftime("%Y-%m-%d")

        

        progress = QMessageBox(self)

        progress.setWindowTitle("Processing Envelope")

        progress.setText(f"Completing Envelope #{env_num} for {owner}...\nDownloading PDF and updating Petty Cash Tracker. Please wait.")

        progress.setStandardButtons(QMessageBox.NoButton)

        progress.show()

        QApplication.processEvents()



        def do_work():

            try:

                state = load_envelope_state()

                if owner not in state:

                    state[owner] = {}

                    save_envelope_state(state)



                complete_envelope(owner, env_num, today_str)

                

                state = load_envelope_state()

                if owner in state and str(env_num) in state[owner]:

                    del state[owner][str(env_num)]

                    save_envelope_state(state)

                    

                progress.close()

                QMessageBox.information(self.parent(), "Success", f"Envelope #{env_num} for {owner} marked COMPLETE and uploaded to the Petty Cash Tracker!")

                self.update_env_info()

                self.accept()

            except Exception as e:

                progress.close()

                QMessageBox.critical(self, "Error", f"Failed to complete envelope: {e}")



        QTimer.singleShot(100, do_work)



    def start_new(self):

        owner = self.buyer_combo.currentText()

        if owner == "OTHER":

            owner, _ = self.get_current_buyer_and_env()

            if not owner: return



        state = load_envelope_state()

        

        global_max = state.get("_global_env_counter", 3)

        for o, envs in state.items():

            if isinstance(envs, dict):

                for k in envs.keys():

                    if str(k).isdigit() and int(k) > global_max:

                        global_max = int(k)

                        

        new_env = global_max + 1

        

        if owner not in state:

            state[owner] = {}

            

        state[owner][str(new_env)] = {

            "grand_total": 0.0,

            "e_transfers": {}

        }

        state["_global_env_counter"] = new_env

        save_envelope_state(state)

        

        # CLEAR TEMPLATE

        try:

            import gspread

            from services.petty_cash_bot import CREDENTIALS_PATH, SHEET_URL, extract_spreadsheet_id, get_template_tab_name

            client = gspread.service_account(filename=CREDENTIALS_PATH)

            sh = client.open_by_key(extract_spreadsheet_id(SHEET_URL))

            tab_name = get_template_tab_name(owner)

            worksheet = sh.worksheet(tab_name)

            worksheet.batch_clear(["B13:N31"])

            QMessageBox.information(self, "Success", f"Started BRAND NEW Envelope #{new_env} for {owner}!\n\nThe {tab_name} template has been wiped blank and is ready for fresh receipts.")

        except Exception as e:

            QMessageBox.warning(self, "Warning", f"Started new envelope #{new_env}, but failed to wipe the spreadsheet template: {e}")

            

        self.update_env_info()



    def prompt_for_set_number(self, filename, default_set, data):

        # This will be tricky because QThread emitting to QDialog that was closed...

        # We need the parent HomeWidget to handle it

        pass



    def show_error(self, msg):

        if hasattr(self.parent(), 'halt_btn'):

            self.parent().halt_btn.setVisible(False)

        self.parent().progress_label.setVisible(False)

        QMessageBox.critical(self.parent(), "Error", msg)



    def finished_processing(self):

        if hasattr(self.parent(), 'halt_btn'):

            self.parent().halt_btn.setVisible(False)

        self.parent().progress_label.setVisible(False)

        QMessageBox.information(self.parent(), "Petty Cash", "Finished processing Petty Cash receipts!")

