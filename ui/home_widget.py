from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout, QMessageBox, QGridLayout
from PySide6.QtCore import Qt, QThread, Signal
from core.threads import ProcessFolderThread
from core.database import get_pending_receipts, get_approved_receipts
from core.settings import load_settings
from services.sheets import get_budget_alerts
import os

class AlertsLoaderThread(QThread):
    alerts_loaded = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            alerts = get_budget_alerts(self.url)
            self.alerts_loaded.emit(alerts)
        except Exception as e:
            self.error_occurred.emit(str(e))

class PlaceholdersSyncThread(QThread):
    sync_finished = Signal(dict)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        
    def run(self):
        try:
            import importlib
            import services.sheets
            importlib.reload(services.sheets)
            res = services.sheets.sync_placeholders_tab(self.url)
            self.sync_finished.emit(res)
        except Exception as e:
            self.sync_finished.emit({"status": "error", "message": str(e)})

class AssetsSyncThread(QThread):
    sync_finished = Signal(dict)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        
    def run(self):
        try:
            import importlib
            import services.sheets
            importlib.reload(services.sheets)
            res = services.sheets.sync_assets_tab(self.url)
            self.sync_finished.emit(res)
        except Exception as e:
            self.sync_finished.emit({"status": "error", "message": str(e)})

class HomeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.addStretch() # Top stretch for vertical centering
        
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        
        btn_style = """
            QPushButton {
                background-color: rgba(20, 20, 20, 0.6);
                border: 1px solid #555;
                border-radius: 12px;
                color: #888;
                font-weight: bold;
                font-size: 11px;
                letter-spacing: 1px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid #aaa;
                color: #fff;
            }
        """
        
        self.see_all_btn = QPushButton("SEE ALL OVER BUDGET")
        self.see_all_btn.setStyleSheet(btn_style)
        self.see_all_btn.setCursor(Qt.PointingHandCursor)
        self.see_all_btn.clicked.connect(self.unhide_all_alerts)
        header_layout.addWidget(self.see_all_btn)
        
        self.close_all_btn = QPushButton("CLOSE ALL")
        self.close_all_btn.setStyleSheet(btn_style)
        self.close_all_btn.setCursor(Qt.PointingHandCursor)
        self.close_all_btn.clicked.connect(self.hide_all_alerts)
        header_layout.addWidget(self.close_all_btn)

        self.sync_placeholders_btn = QPushButton("📌 SYNC PLACEHOLDERS")
        self.sync_placeholders_btn.setStyleSheet(btn_style)
        self.sync_placeholders_btn.setCursor(Qt.PointingHandCursor)
        self.sync_placeholders_btn.clicked.connect(self.start_sync_placeholders)
        header_layout.addWidget(self.sync_placeholders_btn)
        self.sync_assets_btn = QPushButton("📦 UPDATE ASSETS")
        self.sync_assets_btn.setStyleSheet(btn_style)
        self.sync_assets_btn.setCursor(Qt.PointingHandCursor)
        self.sync_assets_btn.clicked.connect(self.start_sync_assets)
        header_layout.addWidget(self.sync_assets_btn)

        self.sync_offline_btn = QPushButton("☁ SYNC OFFLINE (0)")
        self.sync_offline_btn.setStyleSheet(btn_style)
        self.sync_offline_btn.setCursor(Qt.PointingHandCursor)
        self.sync_offline_btn.clicked.connect(self.flush_offline_queue)
        header_layout.addWidget(self.sync_offline_btn)

        self.mobile_scanner_btn = QPushButton("📱 PHONE SCANNER")
        self.mobile_scanner_btn.setStyleSheet(btn_style)
        self.mobile_scanner_btn.setCursor(Qt.PointingHandCursor)
        self.mobile_scanner_btn.clicked.connect(self.open_mobile_scanner)
        header_layout.addWidget(self.mobile_scanner_btn)


        from PySide6.QtCore import QTimer
        self.placeholders_timer = QTimer(self)
        self.placeholders_timer.setInterval(10 * 60 * 1000) # 10 mins
        self.placeholders_timer.timeout.connect(self.start_sync_placeholders)
        self.placeholders_timer.start()
        
        # Refresh button removed from header layout to keep interface clean (refresh accessible via F5 or Reports menu)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Alerts section
        self.alerts_container = QVBoxLayout()
        self.alerts_container.setAlignment(Qt.AlignCenter)
        layout.addLayout(self.alerts_container)
        
        self.status_label = QLabel("BUDGET STATUS: SCANNING...")
        self.status_label.setStyleSheet("color: #888; font-family: 'Segoe UI'; font-size: 14px; letter-spacing: 1px; margin-bottom: 20px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.alerts_container.addWidget(self.status_label)
        
        # Action Buttons - Minimalist Glass Theme (Single Centered Flow)
        main_hubs_layout = QVBoxLayout()
        main_hubs_layout.setSpacing(25)
        main_hubs_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        
        def get_glass_style(base_color, hover_rgba):
            return f"""
                QPushButton {{
                    background-color: rgba(20, 20, 20, 0.6);
                    border: 1px solid {base_color}66;
                    border-radius: 12px;
                    color: {base_color};
                    font-weight: bold;
                    font-size: 11px;
                    letter-spacing: 2px;
                }}
                QPushButton:hover {{
                    background-color: {hover_rgba};
                    border: 1px solid {base_color};
                }}
                QPushButton:disabled {{
                    border-color: #333;
                    color: #555;
                }}
            """
        
        # --- 1. General Receipt / Expense Hub ---
        general_hub = QVBoxLayout()
        general_hub.setSpacing(12)
        general_label = QLabel("GENERAL RECEIPTS & EXPENSE")
        general_label.setStyleSheet("color: #888; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        general_label.setAlignment(Qt.AlignCenter)
        general_hub.addWidget(general_label)
        
        general_grid = QGridLayout()
        general_grid.setSpacing(15)
        general_grid.setAlignment(Qt.AlignCenter)
            
        self.process_btn = QPushButton("PROCESS CREDIT CARDS")
        self.process_btn.setFixedSize(240, 48)
        self.process_btn.setStyleSheet(get_glass_style("#80dfff", "rgba(128, 223, 255, 0.15)"))
        self.process_btn.clicked.connect(self.start_processing)
        general_grid.addWidget(self.process_btn, 0, 0)
        
        self.review_btn = QPushButton("REVIEW RECEIPTS")
        self.review_btn.setFixedSize(240, 48)
        self.review_btn.setStyleSheet(get_glass_style("#80dfff", "rgba(128, 223, 255, 0.15)"))
        self.review_btn.clicked.connect(self.go_to_review)
        general_grid.addWidget(self.review_btn, 0, 1)

        self.expense_btn = QPushButton("EXPENSE AUTOMATION")
        self.expense_btn.setFixedSize(240, 48)
        self.expense_btn.setStyleSheet(get_glass_style("#80dfff", "rgba(128, 223, 255, 0.15)"))
        self.expense_btn.clicked.connect(self.run_expense_automation)
        general_grid.addWidget(self.expense_btn, 0, 2)
        
        self.auto_group_btn = QPushButton("AI AUTO-GROUP PHOTOS")
        self.auto_group_btn.setFixedSize(240, 32)
        self.auto_group_btn.setStyleSheet(get_glass_style("#80dfff", "rgba(128, 223, 255, 0.15)").replace("11px", "9px"))
        self.auto_group_btn.clicked.connect(self.start_auto_grouping)
        general_grid.addWidget(self.auto_group_btn, 1, 0, alignment=Qt.AlignTop)

        self.stop_expense_btn = QPushButton("STOP BOT")
        self.stop_expense_btn.setFixedSize(240, 32)
        self.stop_expense_btn.setStyleSheet(get_glass_style("#80dfff", "rgba(128, 223, 255, 0.15)"))
        self.stop_expense_btn.clicked.connect(self.stop_expense_automation)
        self.stop_expense_btn.setEnabled(False)
        general_grid.addWidget(self.stop_expense_btn, 1, 2, alignment=Qt.AlignTop)
        
        general_hub.addLayout(general_grid)
        main_hubs_layout.addLayout(general_hub)
        
        # --- 2. Petty Cash Hub ---
        petty_hub = QVBoxLayout()
        petty_hub.setSpacing(12)
        petty_label = QLabel("PETTY CASH MANAGEMENT")
        petty_label.setStyleSheet("color: #888; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        petty_label.setAlignment(Qt.AlignCenter)
        petty_hub.addWidget(petty_label)
        
        petty_row = QHBoxLayout()
        petty_row.setAlignment(Qt.AlignCenter)
        petty_row.setSpacing(20)
        
        self.process_petty_cash_btn = QPushButton("PROCESS PETTY CASH")
        self.process_petty_cash_btn.setFixedSize(240, 48)
        self.process_petty_cash_btn.setStyleSheet(get_glass_style("#d2b3ff", "rgba(210, 179, 255, 0.15)"))
        self.process_petty_cash_btn.clicked.connect(self.open_petty_cash_menu)
        petty_row.addWidget(self.process_petty_cash_btn)

        self.envelope_mgmt_btn = QPushButton("ENVELOPE MANAGEMENT")
        self.envelope_mgmt_btn.setFixedSize(240, 48)
        self.envelope_mgmt_btn.setStyleSheet(get_glass_style("#d2b3ff", "rgba(210, 179, 255, 0.15)"))
        self.envelope_mgmt_btn.clicked.connect(self.open_envelope_mgmt)
        petty_row.addWidget(self.envelope_mgmt_btn)
        
        petty_hub.addLayout(petty_row)
        main_hubs_layout.addLayout(petty_hub)
        
        # --- 3. Check Requisitions Hub ---
        ch_hub = QVBoxLayout()
        ch_hub.setSpacing(12)
        ch_label = QLabel("CHECK REQUISITIONS")
        ch_label.setStyleSheet("color: #888; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        ch_label.setAlignment(Qt.AlignCenter)
        ch_hub.addWidget(ch_label)
        
        self.btn_single_ch_req = QPushButton("CREATE SINGLE CH REQ")
        self.btn_single_ch_req.setFixedSize(240, 48)
        self.btn_single_ch_req.setStyleSheet(get_glass_style("#ffffb3", "rgba(255, 255, 179, 0.15)"))
        self.btn_single_ch_req.clicked.connect(self.open_single_ch_req)

        self.btn_track_ch_reqs = QPushButton("TRACK CH REQS & ACH")
        self.btn_track_ch_reqs.setFixedSize(240, 48)
        self.btn_track_ch_reqs.setStyleSheet(get_glass_style("#e8d7f1", "rgba(232, 215, 241, 0.15)"))
        self.btn_track_ch_reqs.clicked.connect(self.open_ch_req_tracker)
        
        ch_row = QHBoxLayout()
        ch_row.setAlignment(Qt.AlignCenter)
        ch_row.setSpacing(20)
        ch_row.addWidget(self.btn_single_ch_req)
        ch_row.addWidget(self.btn_track_ch_reqs)
        ch_hub.addLayout(ch_row)
        
        main_hubs_layout.addLayout(ch_hub)

        # --- 4. Rental Agreements Hub ---
        rental_hub = QVBoxLayout()
        rental_hub.setSpacing(12)
        rental_label = QLabel("RENTAL AGREEMENTS")
        rental_label.setStyleSheet("color: #888; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        rental_label.setAlignment(Qt.AlignCenter)
        rental_hub.addWidget(rental_label)

        self.btn_rental_agmt = QPushButton("CREATE RENTAL AGREEMENT")
        self.btn_rental_agmt.setFixedSize(240, 48)
        self.btn_rental_agmt.setStyleSheet(get_glass_style("#b3ffd9", "rgba(179, 255, 217, 0.15)"))
        self.btn_rental_agmt.clicked.connect(self.open_rental_agreement_dialog)

        rental_row = QHBoxLayout()
        rental_row.setAlignment(Qt.AlignCenter)
        rental_row.setSpacing(20)
        rental_row.addWidget(self.btn_rental_agmt)

        from .drop_completed_widget import DropCompletedAgreementsWidget
        self.drop_completed_widget = DropCompletedAgreementsWidget(self)
        rental_row.addWidget(self.drop_completed_widget)

        rental_hub.addLayout(rental_row)
        main_hubs_layout.addLayout(rental_hub)
        
        # --- 5. Timesheet Generation Hub ---
        timesheet_hub = QVBoxLayout()
        timesheet_hub.setSpacing(12)
        timesheet_label = QLabel("TIMESHEET GENERATION")
        timesheet_label.setStyleSheet("color: #888; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        timesheet_label.setAlignment(Qt.AlignCenter)
        timesheet_hub.addWidget(timesheet_label)

        self.btn_timesheets = QPushButton("📄 GENERATE TIMESHEETS")
        self.btn_timesheets.setFixedSize(240, 48)
        self.btn_timesheets.setStyleSheet(get_glass_style("#ffd9b3", "rgba(255, 217, 179, 0.15)"))
        self.btn_timesheets.clicked.connect(self.run_timesheet_generator)

        timesheet_row = QHBoxLayout()
        timesheet_row.setAlignment(Qt.AlignCenter)
        timesheet_row.addWidget(self.btn_timesheets)
        timesheet_hub.addLayout(timesheet_row)

        main_hubs_layout.addLayout(timesheet_hub)
        
        layout.addLayout(main_hubs_layout)
        
        # Progress Indicator & Halt Button for Processing
        progress_container = QHBoxLayout()
        progress_container.setAlignment(Qt.AlignCenter)
        progress_container.setSpacing(15)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #ccff00; font-family: 'Segoe UI'; font-size: 13px; font-weight: bold;")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setVisible(False)
        progress_container.addWidget(self.progress_label)

        self.halt_btn = QPushButton("🛑 HALT PROCESSING")
        self.halt_btn.setFixedSize(170, 36)
        self.halt_btn.setCursor(Qt.PointingHandCursor)
        self.halt_btn.setStyleSheet(get_glass_style("#c2c2d6", "rgba(194, 194, 214, 0.25)"))
        self.halt_btn.setToolTip("Click to immediately stop scanning/processing receipts")
        self.halt_btn.setVisible(False)
        self.halt_btn.clicked.connect(self.halt_processing)
        progress_container.addWidget(self.halt_btn)

        layout.addLayout(progress_container)
        
        layout.addStretch() # Bottom stretch for vertical centering
        
        # Initial check
        self.check_alerts()
        self.update_review_btn()
        # Automatically refresh placeholders every time the app opens
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, self.start_sync_placeholders)

    def refresh_all(self):
        if hasattr(self, 'refresh_ui_btn'):
            self.refresh_ui_btn.setText("⏳")
        self.status_label.setText("REFRESHING DATA...")
        self.status_label.setVisible(True)
        
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self.finish_refresh)
        
    def finish_refresh(self):
        self.check_alerts()
        self.update_review_btn()
        self.start_sync_placeholders()
        try:
            from core.database import get_offline_queue_count
            if get_offline_queue_count() > 0:
                from core.settings import load_settings
                from services.sheets import flush_offline_sync_queue
                url = load_settings().get("spreadsheet_url", "")
                flush_offline_sync_queue(url)
                self.update_review_btn()
        except Exception:
            pass
        if hasattr(self, 'refresh_ui_btn'):
            self.refresh_ui_btn.setText("🔄")
        
    def start_sync_placeholders(self):
        if hasattr(self, 'placeholder_thread') and self.placeholder_thread.isRunning():
            return
        from core.settings import load_settings
        settings = load_settings()
        url = settings.get("spreadsheet_url", "")
        if not url:
            return
        self.sync_placeholders_btn.setEnabled(False)
        self.sync_placeholders_btn.setText("SYNCING...")
        self.placeholder_thread = PlaceholdersSyncThread(url)
        self.placeholder_thread.sync_finished.connect(self.on_placeholders_synced)
        self.placeholder_thread.start()
        
    def on_placeholders_synced(self, result):
        self.sync_placeholders_btn.setEnabled(True)
        self.sync_placeholders_btn.setText("📌 SYNC PLACEHOLDERS")
        if result.get("status") == "success":
            count = result.get("count", 0)
            print(f"Placeholders tab synchronized successfully: {count} placeholders found.")

    def start_sync_assets(self):
        if hasattr(self, 'assets_thread') and self.assets_thread.isRunning():
            return
        from core.settings import load_settings
        settings = load_settings()
        url = settings.get("spreadsheet_url", "")
        if not url:
            return
        self.sync_assets_btn.setEnabled(False)
        self.sync_assets_btn.setText("UPDATING ASSETS...")
        self.assets_thread = AssetsSyncThread(url)
        self.assets_thread.sync_finished.connect(self.on_assets_synced)
        self.assets_thread.start()

    def on_assets_synced(self, result):
        self.sync_assets_btn.setEnabled(True)
        self.sync_assets_btn.setText("📦 UPDATE ASSETS")
        if result.get("status") == "success":
            count = result.get("count", 0)
            amount = result.get("amount", 0.0)
            print(f"Assets tab synchronized successfully: {count} assets found (${amount:,.2f}).")
            if hasattr(self, 'parent_window') and self.parent_window and hasattr(self.parent_window, 'statusBar'):
                self.parent_window.statusBar().showMessage(f"Assets Sheet Updated: {count} assets (${amount:,.2f})", 6000)
        else:
            err = result.get("message", "Unknown error")
            print(f"Error syncing assets tab: {err}")
            if hasattr(self, 'parent_window') and self.parent_window and hasattr(self.parent_window, 'statusBar'):
                self.parent_window.statusBar().showMessage(f"Assets Sync Failed: {err}", 6000)

            
    def check_alerts(self):
        from core.settings import load_settings, save_settings
        settings = load_settings()
        url = settings.get("spreadsheet_url", "")
        if not url:
            self.status_label.setText("⚠ Please configure Google Sheets URL in Settings.")
            self.status_label.setStyleSheet("color: #888; font-family: 'Segoe UI'; font-size: 14px; letter-spacing: 1px; margin-bottom: 20px;")
            self.status_label.setVisible(True)
            return
            
        self.status_label.setText("BUDGET STATUS: SCANNING...")
        self.status_label.setStyleSheet("color: #888; font-family: 'Segoe UI'; font-size: 14px; letter-spacing: 1px; margin-bottom: 20px;")
        self.status_label.setVisible(True)

        # Clear old alerts (including sub-layouts)
        for i in reversed(range(self.alerts_container.count())): 
            item = self.alerts_container.itemAt(i)
            if item.widget() and item.widget() != self.status_label:
                widget = item.widget()
                self.alerts_container.removeWidget(widget)
                widget.deleteLater()
            elif item.layout():
                sub_layout = item.layout()
                while sub_layout.count():
                    sub_item = sub_layout.takeAt(0)
                    if sub_item.widget():
                        sub_item.widget().deleteLater()
                self.alerts_container.removeItem(item)
                sub_layout.deleteLater()

        # Start background thread to load alerts
        self.alerts_thread = AlertsLoaderThread(url)
        self.alerts_thread.alerts_loaded.connect(self.on_alerts_loaded)
        self.alerts_thread.error_occurred.connect(self.on_alerts_error)
        self.alerts_thread.start()

    def on_alerts_loaded(self, alerts):
        from core.settings import load_settings, save_settings
        settings = load_settings()
        self.current_alerts = alerts
        
        if alerts and len(alerts) == 1 and "msg" in alerts[0] and "Set" not in alerts[0]["msg"]:
            self.status_label.setText(alerts[0]["msg"])
            self.status_label.setStyleSheet("color: #80dfff; font-family: 'Segoe UI'; font-size: 14px; letter-spacing: 1px; margin-bottom: 20px;")
            self.status_label.setVisible(True)
            return


        hidden_alerts = settings.get("hidden_alerts", [])
        visible_alerts = []
        hidden_count = 0
        
        if alerts:
            self.status_label.setVisible(False)
            for alert in alerts:
                if alert["set"] in hidden_alerts:
                    hidden_count += 1
                else:
                    visible_alerts.append(alert)
                    
            if visible_alerts:
                for alert in visible_alerts:
                    row = QHBoxLayout()
                    
                    lbl = QLabel(alert["msg"])
                    lbl.setAlignment(Qt.AlignCenter)
                    lbl.setStyleSheet("color: #80dfff; padding: 5px; font-size: 13px; font-weight: bold;")
                    
                    hide_btn = QPushButton("✕")
                    hide_btn.setFixedSize(20, 20)
                    hide_btn.setCursor(Qt.PointingHandCursor)
                    hide_btn.setToolTip("Dismiss alert")
                    hide_btn.setStyleSheet("QPushButton { color: #888; background: transparent; border: none; font-weight: bold; font-size: 14px; } QPushButton:hover { color: #fff; }")
                    
                    # Capture current set in closure
                    def make_hide_func(set_name):
                        def hide_alert():
                            curr_settings = load_settings()
                            hidden = curr_settings.get("hidden_alerts", [])
                            if set_name not in hidden:
                                hidden.append(set_name)
                                curr_settings["hidden_alerts"] = hidden
                                save_settings(curr_settings)
                                self.check_alerts() # reload
                        return hide_alert
                        
                    hide_btn.clicked.connect(make_hide_func(alert["set"]))
                    
                    row.addStretch()
                    row.addWidget(lbl)
                    row.addWidget(hide_btn)
                    row.addStretch()
                    
                    self.alerts_container.addLayout(row)
            else:
                self.status_label.setVisible(True)
                self.status_label.setText(f"✅ ALL {len(alerts)} ALERTS DISMISSED")
                self.status_label.setStyleSheet("color: #888; font-size: 14px; font-weight: bold;")
                
            if hidden_count > 0:
                pass
        else:
            self.status_label.setVisible(True)
            self.status_label.setText("✅ ALL SETS WITHIN BUDGET")
            self.status_label.setStyleSheet("color: #39ff14; font-size: 14px; font-weight: bold;")

    def on_alerts_error(self, err):
        self.status_label.setText(f"⚠ Could not connect to Google Sheets: {err}")
        self.status_label.setStyleSheet("color: #80dfff; font-family: 'Segoe UI'; font-size: 14px; letter-spacing: 1px; margin-bottom: 20px;")
        self.status_label.setVisible(True)

    def show_set_summary(self, set_name):
        from core.settings import load_settings
        settings = load_settings()
        url = settings.get("spreadsheet_url", "")
        
        from services.sheets import get_set_summary
        from .summary_dialog import SummaryDialog
        
        # Show a quick loading message
        loading = QMessageBox(self)
        loading.setWindowTitle("Please Wait")
        loading.setText(f"Fetching expenditure summary for {set_name}...")
        loading.setStandardButtons(QMessageBox.NoButton)
        loading.show()
        
        import PySide6.QtGui as QtGui
        QtGui.QGuiApplication.processEvents()
        
        data = get_set_summary(url, set_name)
        loading.close()
        
        if not data:
            QMessageBox.warning(self, "No Data", f"Could not find any expenditure records for {set_name}.")
            return
            
        dialog = SummaryDialog(set_name, data, self)
        dialog.exec()

    def update_review_btn(self):
        pending = get_pending_receipts()
        self.review_btn.setText(f"REVIEW RECEIPTS ({len(pending)})")
        try:
            from core.database import get_offline_queue_count
            offline_count = get_offline_queue_count()
            if hasattr(self, 'sync_offline_btn'):
                self.sync_offline_btn.setText(f"☁ SYNC OFFLINE ({offline_count})")
                if offline_count > 0:
                    self.sync_offline_btn.setStyleSheet("""
                        QPushButton {
                            background-color: rgba(255, 170, 0, 0.25);
                            border: 1px solid #ffaa00;
                            border-radius: 12px;
                            color: #ffaa00;
                            font-weight: bold;
                            font-size: 11px;
                            letter-spacing: 1px;
                            padding: 8px 15px;
                        }
                        QPushButton:hover {
                            background-color: rgba(255, 170, 0, 0.45);
                            color: #fff;
                        }
                    """)
                else:
                    self.sync_offline_btn.setStyleSheet("""
                        QPushButton {
                            background-color: rgba(20, 20, 20, 0.6);
                            border: 1px solid #555;
                            border-radius: 12px;
                            color: #888;
                            font-weight: bold;
                            font-size: 11px;
                            letter-spacing: 1px;
                            padding: 8px 15px;
                        }
                        QPushButton:hover {
                            background-color: rgba(255, 255, 255, 0.1);
                            border: 1px solid #aaa;
                            color: #fff;
                        }
                    """)
        except Exception:
            pass

    def flush_offline_queue(self):
        from core.settings import load_settings
        from services.sheets import flush_offline_sync_queue
        url = load_settings().get("spreadsheet_url", "")
        self.sync_offline_btn.setEnabled(False)
        self.sync_offline_btn.setText("SYNCING...")
        res = flush_offline_sync_queue(url)
        synced = res.get("synced", 0)
        remaining = res.get("remaining", 0)
        self.sync_offline_btn.setEnabled(True)
        self.update_review_btn()
        if synced > 0 and remaining == 0:
            QMessageBox.information(self, "Offline Sync", f"Success! All {synced} queued receipt(s) were synced to Google Sheets.")
        elif remaining > 0:
            QMessageBox.warning(self, "Offline Sync", f"Synced {synced} receipt(s). {remaining} still pending in queue (check your internet connection).")
        else:
            QMessageBox.information(self, "Offline Sync", "All receipts are up to date! There are no offline receipts in the queue.")

    def open_mobile_scanner(self):
        from .mobile_scanner_dialog import MobileScannerDialog
        dialog = MobileScannerDialog(self)
        dialog.exec()
        self.update_review_btn()


    def start_processing(self):
        self._start_thread_with_action("process", "STARTING AI ENGINE...", "PROCESSING...")

    def start_auto_grouping(self):
        self._start_thread_with_action("group_only", "STARTING AI GROUPING...", "GROUPING...")
        
    def _start_thread_with_action(self, action, progress_msg, btn_text):
        self.process_btn.setEnabled(False)
        self.process_btn.setText(btn_text)
        if hasattr(self, "auto_group_btn"): self.auto_group_btn.setEnabled(False)
        
        # Use dynamic path to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        input_dir = os.path.join(project_root, 'Input')
        
        if not os.path.exists(input_dir):
            os.makedirs(input_dir)
            
        self.thread = ProcessFolderThread(input_dir, action=action)
        self.thread.progress_update.connect(self.update_progress_ui)
        self.thread.finished_processing.connect(self.processing_finished)
        self.progress_label.setText(progress_msg)
        self.progress_label.setVisible(True)
        self.halt_btn.setVisible(True)
        self.thread.start()

    def update_progress_ui(self, msg):
        self.progress_label.setText(msg)
        print(f"DEBUG: {msg}")

    def halt_processing(self):
        halted = False
        if hasattr(self, 'thread') and self.thread and self.thread.isRunning():
            if hasattr(self.thread, 'stop'):
                self.thread.stop()
            else:
                self.thread.requestInterruption()
            halted = True

        if hasattr(self, 'petty_cash_thread') and self.petty_cash_thread and self.petty_cash_thread.isRunning():
            if hasattr(self.petty_cash_thread, 'stop'):
                self.petty_cash_thread.stop()
            else:
                self.petty_cash_thread.requestInterruption()
            halted = True

        if hasattr(self, 'active_review_dialog') and self.active_review_dialog:
            try:
                self.active_review_dialog.reject()
            except Exception:
                pass
            self.active_review_dialog = None

        self.process_btn.setEnabled(True)
        self.process_btn.setText("PROCESS RECEIPTS")
        if hasattr(self, "auto_group_btn"): self.auto_group_btn.setEnabled(True)
        self.progress_label.setVisible(False)
        self.halt_btn.setVisible(False)
        self.update_review_btn()

        if halted:
            QMessageBox.warning(self, "HALTED", "Receipt processing has been halted immediately!")

    def processing_finished(self):
        self.process_btn.setEnabled(True)
        self.process_btn.setText("PROCESS RECEIPTS")
        if hasattr(self, "auto_group_btn"): self.auto_group_btn.setEnabled(True)
        self.progress_label.setVisible(False)
        self.halt_btn.setVisible(False)
        self.update_review_btn()
        
        msg = "FINISHED SCANNING INPUT FOLDER!" if getattr(self.thread, 'action', '') == "process" else "FINISHED AUTO-GROUPING PHOTOS!"
        # QMessageBox.information(self, "SUCCESS", msg)
        
    def go_to_review(self):
        if self.parent_window:
            self.parent_window.review_widget.load_next_receipt()
            self.parent_window.switch_view(1)

    def run_expense_automation(self):
        from services.expense_bot import ExpenseBotThread
        all_receipts = get_approved_receipts()
        
        # Pass all receipts to the bot. The bot will naturally skip any that don't appear on the Expense webpage.
        receipts = all_receipts
                
        if not receipts:
            QMessageBox.warning(self, "No Data", "No approved credit card receipts found to automate.")
            return

        self.expense_btn.setEnabled(False)
        self.expense_btn.setText("⏳ BOT RUNNING...")
        self.stop_expense_btn.setEnabled(True)
        
        if hasattr(self, 'bot_thread') and self.bot_thread and self.bot_thread.isRunning():
            QMessageBox.information(self, "Bot Running", "The Expense browser is already open! Please use the '🤖 Set Dec Bot' floating panel in the bottom right corner of the Expense website to fill in data on any page.")
            return

        self.bot_thread = ExpenseBotThread()
        self.bot_thread.batch_finished.connect(self.on_bot_finished)
        self.bot_thread.error.connect(self.on_bot_error)
        self.bot_thread.start()

    def stop_expense_automation(self):
        if hasattr(self, 'bot_thread') and self.bot_thread and self.bot_thread.isRunning():
            self.bot_thread.stop()
            self.bot_thread.wait(2000) # Give it 2 seconds to close gracefully
            self.bot_thread = None
        self.expense_btn.setEnabled(True)
        self.expense_btn.setText("EXPENSE AUTOMATION")
        self.stop_expense_btn.setEnabled(False)
        QMessageBox.information(self, "Stopped", "The Expense Bot has been completely stopped and its browser is closed.")

    def on_bot_finished(self):
        self.expense_btn.setEnabled(True)
        self.expense_btn.setText("EXPENSE AUTOMATION")
        self.stop_expense_btn.setEnabled(False)
        # QMessageBox.information(self, "Success", "Expense batch finished! The browser will stay open for the next batch. You can close it by clicking STOP BOT.")

    def on_bot_error(self, err):
        self.expense_btn.setEnabled(True)
        self.expense_btn.setText("EXPENSE AUTOMATION")
        self.stop_expense_btn.setEnabled(False)
        QMessageBox.critical(self, "Error", f"Expense Automation failed: {err}")

    def open_petty_cash_menu(self):
        from .petty_cash_dialog import PettyCashDialog
        dialog = PettyCashDialog(self)
        dialog.exec()

    def open_envelope_mgmt(self):
        from .envelope_mgmt_dialog import EnvelopeMgmtDialog
        dialog = EnvelopeMgmtDialog(self)
        dialog.exec()

    def prompt_for_set_number(self, filename, default_set, data):
        from .petty_cash_review_dialog import PettyCashReviewDialog
        
        dialog = PettyCashReviewDialog(filename, data, self)
        self.active_review_dialog = dialog
        ret = dialog.exec()
        self.active_review_dialog = None
        
        if ret and not getattr(dialog, 'was_halted', False):
            results = dialog.get_results()
            if hasattr(self, 'petty_cash_thread') and self.petty_cash_thread:
                self.petty_cash_thread.resume_with_set_number(results)
        else:
            # User clicked HALT or closed the dialog (X) -> STOP IMMEDIATELY!
            if hasattr(self, 'petty_cash_thread') and self.petty_cash_thread:
                self.petty_cash_thread.stop()
            self.halt_btn.setVisible(False)
            self.progress_label.setVisible(False)
            QMessageBox.information(self, "HALTED", "Petty Cash receipt processing has been halted.")

    def open_ch_req_tracker(self):
        main_win = self.window()
        if hasattr(main_win, 'switch_view'):
            main_win.switch_view(5)

    def open_single_ch_req(self):
        from .ch_req_dialog import CHReqDialog
        dialog = CHReqDialog(self)
        dialog.exec()

    def open_set_list_importer(self):
        from .set_list_dialog import SetListImporterDialog
        dialog = SetListImporterDialog(self)
        dialog.exec()
        self.refresh_all()

    def open_schedule_importer(self):
        from .schedule_importer_dialog import ScheduleImporterDialog
        dialog = ScheduleImporterDialog(self)
        dialog.exec()
        self.refresh_all()

    def open_rental_agreement_dialog(self):
        from .rental_agreement_dialog import RentalAgreementDialog
        dialog = RentalAgreementDialog(self)
        dialog.exec()

    def run_timesheet_generator(self):
        try:
            import main, importlib; importlib.reload(main)
            main.generate_timesheets()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to run Timesheet Generator:\n{e}")

    def unhide_all_alerts(self):
        from core.settings import load_settings, save_settings
        curr_settings = load_settings()
        curr_settings["hidden_alerts"] = []
        save_settings(curr_settings)
        self.check_alerts()

    def hide_all_alerts(self):
        if not hasattr(self, 'current_alerts') or not self.current_alerts:
            return
        from core.settings import load_settings, save_settings
        curr_settings = load_settings()
        hidden = curr_settings.get("hidden_alerts", [])
        for alert in self.current_alerts:
            if "set" in alert and alert["set"] not in hidden:
                hidden.append(alert["set"])
        curr_settings["hidden_alerts"] = hidden
        save_settings(curr_settings)
        self.check_alerts()


    def run_cost_report(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from core.settings import load_settings
        import datetime
        import os
        
        settings = load_settings()
        url = settings.get("spreadsheet_url", "")
        if not url:
            QMessageBox.warning(self, "No URL", "Please configure your Google Sheets URL in settings.")
            return
            
        import PySide6.QtGui as QtGui
        from services.sheets import get_cost_report_data, generate_cost_report_pdf, update_cost_report_efc
        from ui.cost_report_dialog import CostReportReviewDialog

        QtGui.QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        QtGui.QGuiApplication.processEvents()
        
        # 1. Fetch data
        res = get_cost_report_data(url)
        QtGui.QGuiApplication.restoreOverrideCursor()
        
        if res.get("status") != "success":
            QMessageBox.critical(self, "Error", res.get("message", "Unknown error fetching data."))
            return
            
        report_rows = res.get("report_rows", [])
        
        # 2. Show Review Dialog
        dialog = CostReportReviewDialog(report_rows, self)
        if dialog.exec():
            updated_rows = dialog.get_updated_rows()
            
            # Sync back to Local Cache (Not Google Sheets)
            try:
                import json
                cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "efc_cache.json")
                cache_data = {}
                if os.path.exists(cache_file):
                    with open(cache_file, "r") as f:
                        cache_data = json.load(f)
                
                for r in updated_rows:
                    cache_data[r["Episode"]] = r["Projected Final Amount"]
                    
                with open(cache_file, "w") as f:
                    json.dump(cache_data, f, indent=4)
            except Exception as e:
                print(f"Failed to cache EFC locally: {e}")
            
            # 3. Ask for save path
            default_name = f"Set_Dec_Cost_Report_{datetime.datetime.now().strftime('%Y-%m-%d')}.pdf"
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            show_reports_dir = os.path.abspath(os.path.join(app_dir, '..', '..', 'COST REPORTS'))
            reports_dir = show_reports_dir if os.path.exists(os.path.dirname(show_reports_dir)) else os.path.join(app_dir, 'COST REPORTS')
            if not os.path.exists(reports_dir):
                os.makedirs(reports_dir, exist_ok=True)
            default_path = os.path.join(reports_dir, default_name)
            
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Cost Report", default_path, "PDF Files (*.pdf)")
            if save_path:
                QtGui.QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                QtGui.QGuiApplication.processEvents()
                
                # Check if target file exists and might be open in a viewer
                if os.path.exists(save_path):
                    # Test if writable
                    try:
                        with open(save_path, "a"):
                            pass
                    except IOError:
                        # File is locked by an open viewer (e.g. Acrobat/browser)
                        QMessageBox.warning(
                            self,
                            "File Currently Open",
                            f"The file '{os.path.basename(save_path)}' is currently open in your PDF viewer or browser.\n\nPlease close the open PDF tab/window and click OK to save.",
                            QMessageBox.Ok
                        )

                pdf_res = generate_cost_report_pdf(updated_rows, save_path)
                
                QtGui.QGuiApplication.restoreOverrideCursor()
                
                if pdf_res.get("status") == "success":
                    # Clean up any older timestamped duplicate files for this same date in the folder
                    try:
                        date_prefix = f"Set_Dec_Cost_Report_{datetime.datetime.now().strftime('%Y-%m-%d')}_"
                        for f in os.listdir(reports_dir):
                            if f.startswith(date_prefix) and f.endswith(".pdf"):
                                old_file = os.path.join(reports_dir, f)
                                try:
                                    os.remove(old_file)
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"Cleanup error: {e}")

                    QMessageBox.information(self, "Success", pdf_res.get("message"))
                    if os.path.exists(save_path):
                        os.startfile(save_path)
                else:
                    QMessageBox.critical(self, "Error", pdf_res.get("message", "Unknown error generating PDF."))
