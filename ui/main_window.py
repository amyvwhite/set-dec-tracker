from PySide6.QtWidgets import QMainWindow, QStackedWidget, QToolBar, QToolButton, QMenu, QScrollArea
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtCore import Qt
from .home_widget import HomeWidget
from .review_widget import ReviewWidget
from .settings_dialog import SettingsDialog
from .search_widget import SearchWidget
from .tracker_widget import TrackerWidget
from .budget_widget import BudgetWidget
from .ch_req_tracker_widget import ChReqTrackerWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SET DEC TRACKER")
        self.resize(1200, 800)
        self.setStyleSheet("background-color: #0a0a0a; color: #ffffff;")
        
        self.central_widget = QStackedWidget()
        self.setCentralWidget(self.central_widget)
        
        self.home_widget = HomeWidget(self)
        self.home_scroll = QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setStyleSheet("""
            QScrollArea { background-color: transparent; border: none; }
            QScrollBar:vertical {
                background: rgba(15, 15, 15, 0.7);
                width: 10px;
                border-radius: 5px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #333;
                min-height: 25px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #555;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.home_scroll.setWidget(self.home_widget)

        self.review_widget = ReviewWidget(self)
        self.search_widget = SearchWidget(self)
        self.tracker_widget = TrackerWidget(self)
        self.budget_widget = BudgetWidget(self)
        self.ch_req_widget = ChReqTrackerWidget(self)
        
        self.central_widget.addWidget(self.home_scroll)       # 0
        self.central_widget.addWidget(self.review_widget)     # 1
        self.central_widget.addWidget(self.search_widget)     # 2
        self.central_widget.addWidget(self.tracker_widget)    # 3
        self.central_widget.addWidget(self.budget_widget)     # 4
        self.central_widget.addWidget(self.ch_req_widget)     # 5
        
        self.setup_toolbar()
        
    def setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #111;
                border-bottom: 1px solid #222;
                padding: 10px;
            }
            QToolButton {
                color: #888;
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
                margin-right: 15px;
                background: transparent;
                border: none;
                padding: 4px 8px;
            }
            QToolButton:hover {
                color: #00f2ff;
            }
            QToolButton::menu-indicator {
                image: none;
            }
        """)
        self.addToolBar(toolbar)
        
        # 1. Home
        home_action = QAction("🏠 Home", self)
        home_action.triggered.connect(lambda: self.switch_view(0))
        toolbar.addAction(home_action)
        
        # 2. Search
        search_action = QAction("🔍 Search", self)
        search_action.triggered.connect(lambda: self.switch_view(2))
        toolbar.addAction(search_action)

        # 3. Tracker Sheet
        tracker_action = QAction("📊 Tracker Sheet", self)
        tracker_action.triggered.connect(lambda: self.switch_view(3))
        toolbar.addAction(tracker_action)

        # 4. Budget Tab
        budget_action = QAction("💰 Budget Tab", self)
        budget_action.triggered.connect(lambda: self.switch_view(4))
        toolbar.addAction(budget_action)

        menu_style = """
            QMenu {
                background-color: #141414;
                color: #eee;
                border: 1px solid #333;
                border-radius: 8px;
                padding: 6px;
                font-size: 12px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(0, 242, 255, 0.15);
                color: #00f2ff;
                font-weight: bold;
            }
        """

        # 3. Imports Dropdown (Combines Import Set List & Import Shooting Schedule)
        imports_btn = QToolButton(self)
        imports_btn.setText("📥 IMPORTS ▾")
        imports_btn.setPopupMode(QToolButton.InstantPopup)
        imports_btn.setCursor(Qt.PointingHandCursor)
        imports_menu = QMenu(imports_btn)
        imports_menu.setStyleSheet(menu_style)
        
        act_import_sets = imports_menu.addAction("📋 Import Set List")
        act_import_sets.triggered.connect(self.open_set_list_importer)
        
        act_import_sched = imports_menu.addAction("📅 Import Shooting Schedule")
        act_import_sched.triggered.connect(self.open_schedule_importer)

        act_combine_pdf = imports_menu.addAction("📄 Combine Files into 1 PDF")
        act_combine_pdf.triggered.connect(self.open_combine_pdf_tool)
        
        imports_btn.setMenu(imports_menu)
        toolbar.addWidget(imports_btn)

        # 4. Reports Dropdown (Combines Budget Alerts, Cost Report, and Refresh)
        reports_btn = QToolButton(self)
        reports_btn.setText("📊 REPORTS ▾")
        reports_btn.setPopupMode(QToolButton.InstantPopup)
        reports_btn.setCursor(Qt.PointingHandCursor)
        reports_menu = QMenu(reports_btn)
        reports_menu.setStyleSheet(menu_style)
        
        act_budget_alert = reports_menu.addAction("🚨 Budget Alerts")
        act_budget_alert.triggered.connect(self.open_budget_alert_dialog)
        
        act_cost_report = reports_menu.addAction("📊 Cost Report")
        act_cost_report.triggered.connect(self.open_cost_report)

        act_refresh = reports_menu.addAction("🔄 Refresh Data (F5)")
        act_refresh.triggered.connect(self.refresh_entire_app)

        act_sync_offline = reports_menu.addAction("☁ Sync Offline Receipts")
        act_sync_offline.triggered.connect(self.sync_offline_now)

        reports_btn.setMenu(reports_menu)
        toolbar.addWidget(reports_btn)

        # 5. Settings
        settings_action = QAction("⚙ Settings", self)
        settings_action.triggered.connect(self.open_settings)
        toolbar.addAction(settings_action)

        # Global Shortcut: F5 to refresh
        self.f5_shortcut = QShortcut(QKeySequence("F5"), self)
        self.f5_shortcut.activated.connect(self.refresh_entire_app)
        
    def open_cost_report(self):
        self.home_widget.run_cost_report()
        
    def switch_view(self, index):
        if index == 2:
            self.search_widget.perform_search()
        elif index == 3:
            self.tracker_widget.load_data()
        elif index == 4:
            self.budget_widget.load_data()
        elif index == 5:
            self.ch_req_widget.load_pending_data()
        self.central_widget.setCurrentIndex(index)
        
    def open_set_list_importer(self):
        from .set_list_dialog import SetListImporterDialog
        dialog = SetListImporterDialog(self)
        dialog.exec()
        self.refresh_entire_app()

    def open_budget_alert_dialog(self):
        from .budget_alert_dialog import BudgetAlertDialog
        dialog = BudgetAlertDialog(self)
        dialog.exec()

    def open_schedule_importer(self):
        from .schedule_importer_dialog import ScheduleImporterDialog
        dialog = ScheduleImporterDialog(self)
        dialog.exec()
        self.refresh_entire_app()

    def open_combine_pdf_tool(self):
        try:
            import subprocess, os, sys
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script_path = os.path.join(app_dir, "tools", "combine_to_pdf.py")
            pythonw_path = sys.executable.replace("python.exe", "pythonw.exe")
            subprocess.Popen([pythonw_path, script_path], cwd=app_dir)
        except Exception as e:
            print("Error launching combine PDF tool:", e)

    def open_timesheets(self):
        try:
            import main, importlib; importlib.reload(main)
            main.generate_timesheets()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to run Timesheet Generator:\n{e}")

    def open_rental_agreements(self):
        from .rental_agreement_dialog import RentalAgreementDialog
        dialog = RentalAgreementDialog(self)
        dialog.exec()

    def open_petty_cash(self):
        self.home_widget.open_petty_cash_menu()

    def sync_offline_now(self):
        from core.settings import load_settings
        from services.sheets import flush_offline_sync_queue
        url = load_settings().get("spreadsheet_url", "")
        res = flush_offline_sync_queue(url)
        synced = res.get("synced", 0)
        remaining = res.get("remaining", 0)
        from PySide6.QtWidgets import QMessageBox
        if synced == 0 and remaining == 0:
            QMessageBox.information(self, "Offline Sync", "All receipts are up to date! There are no offline receipts in the queue.")
        elif remaining == 0:
            QMessageBox.information(self, "Offline Sync", f"Success! All {synced} offline receipt(s) were synced to Google Sheets.")
        else:
            QMessageBox.warning(self, "Offline Sync", f"Synced {synced} receipt(s). {remaining} still pending (Google Sheets connection may still be unavailable).")
        self.refresh_entire_app()


    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()
        self.refresh_entire_app()

    def refresh_entire_app(self):
        self.home_widget.refresh_all()
        self.tracker_widget.load_data()
        self.budget_widget.load_data()
        self.search_widget.perform_search()
