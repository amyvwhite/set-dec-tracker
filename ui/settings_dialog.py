from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QWidget
from core.settings import load_settings, save_settings

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(600, 150)
        self.setStyleSheet("background-color: #1e1e1e; color: #ffffff;")
        
        layout = QVBoxLayout(self)
        
        label = QLabel("Google Sheets Tracker URL:")
        label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(label)
        
        self.url_input = QLineEdit()
        self.url_input.setStyleSheet("padding: 8px; background-color: #252526; border: 1px solid #444; font-size: 14px;")
        layout.addWidget(self.url_input)

        label_key = QLabel("Gemini AI API Key (Free):")
        label_key.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px;")
        layout.addWidget(label_key)

        self.key_input = QLineEdit()
        self.key_input.setStyleSheet("padding: 8px; background-color: #252526; border: 1px solid #444; font-size: 14px;")
        layout.addWidget(self.key_input)
        
        # Load current settings
        self.current_settings = load_settings()
        self.url_input.setText(self.current_settings.get("spreadsheet_url", ""))
        self.key_input.setText(self.current_settings.get("gemini_api_key", ""))

        # Vendor List & Production Resources Section
        label_res = QLabel("PRODUCTION SHEETS AND RESOURCE LINKS")
        label_res.setStyleSheet("font-size: 15px; font-weight: bold; margin-top: 15px; color: #66ccff; letter-spacing: 1px; background-color: #2b333a; padding: 6px; border-radius: 4px;")
        layout.addWidget(label_res)

        lbl_vendor_sheet = QLabel("Show Vendor Master List URL (Auto-syncs new vendors):")
        lbl_vendor_sheet.setStyleSheet("font-size: 13px; font-weight: bold; margin-top: 6px;")
        layout.addWidget(lbl_vendor_sheet)
        self.vendor_url_input = QLineEdit()
        self.vendor_url_input.setPlaceholderText("https://docs.google.com/spreadsheets/d/... (Paste link for new show)")
        self.vendor_url_input.setText(self.current_settings.get("vendor_list_url", ""))
        self.vendor_url_input.setStyleSheet("padding: 7px; background-color: #252526; border: 1px solid #444; font-size: 13px;")
        layout.addWidget(self.vendor_url_input)

        lbl_ra_sheet = QLabel("Rental Agreements Tracker Sheet URL (Auto-syncs signed/sent status):")
        lbl_ra_sheet.setStyleSheet("font-size: 13px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(lbl_ra_sheet)
        self.ra_sheet_url_input = QLineEdit()
        self.ra_sheet_url_input.setPlaceholderText("https://docs.google.com/spreadsheets/d/... (Rental Agreements list)")
        self.ra_sheet_url_input.setText(self.current_settings.get("rental_agreements_sheet_url", ""))
        self.ra_sheet_url_input.setStyleSheet("padding: 7px; background-color: #252526; border: 1px solid #444; font-size: 13px;")
        layout.addWidget(self.ra_sheet_url_input)

        lbl_budget_sheet = QLabel("Budget & Cost Report Sheet URL (Optional):")
        lbl_budget_sheet.setStyleSheet("font-size: 13px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(lbl_budget_sheet)
        self.budget_url_input = QLineEdit()
        self.budget_url_input.setPlaceholderText("https://docs.google.com/spreadsheets/d/... (Future show budget / cost tracker)")
        self.budget_url_input.setText(self.current_settings.get("budget_sheet_url", ""))
        self.budget_url_input.setStyleSheet("padding: 7px; background-color: #252526; border: 1px solid #444; font-size: 13px;")
        layout.addWidget(self.budget_url_input)

        lbl_drive_folder = QLabel("Production Drive / Asset Folder URL (Optional):")
        lbl_drive_folder.setStyleSheet("font-size: 13px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(lbl_drive_folder)
        self.drive_url_input = QLineEdit()
        self.drive_url_input.setPlaceholderText("https://drive.google.com/drive/folders/... (Production Shared Drive / Assets)")
        self.drive_url_input.setText(self.current_settings.get("production_drive_folder_url", ""))
        self.drive_url_input.setStyleSheet("padding: 7px; background-color: #252526; border: 1px solid #444; font-size: 13px;")
        layout.addWidget(self.drive_url_input)

        lbl_props_inv = QLabel("Props & Furniture Inventory Sheet URL (Optional):")
        lbl_props_inv.setStyleSheet("font-size: 13px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(lbl_props_inv)
        self.props_inv_input = QLineEdit()
        self.props_inv_input.setPlaceholderText("https://docs.google.com/spreadsheets/d/... (Props & Lockup inventory tracking)")
        self.props_inv_input.setText(self.current_settings.get("props_inventory_url", ""))
        self.props_inv_input.setStyleSheet("padding: 7px; background-color: #252526; border: 1px solid #444; font-size: 13px;")
        layout.addWidget(self.props_inv_input)
        
        # Scroll Area for many settings
        from PySide6.QtWidgets import QScrollArea, QFrame
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background-color: #1e1e1e;")
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Expense Defaults Section (The Cheat Sheet)
        label_expense = QLabel("EXPENSE ACCOUNTING CHEAT SHEET")
        label_expense.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 20px; color: #ccff00; letter-spacing: 2px; background-color: #333; padding: 5px;")
        scroll_layout.addWidget(label_expense)

        self.expense_inputs = {}
        
        # 0. Login Credentials
        scroll_layout.addWidget(QLabel("<br><b>0. Login Credentials</b>"))
        
        row_email = QHBoxLayout()
        lbl_email = QLabel("Expense Email:")
        lbl_email.setFixedWidth(150)
        row_email.addWidget(lbl_email)
        inp_email = QLineEdit()
        inp_email.setText(self.current_settings.get("expense_email", ""))
        self.expense_inputs["expense_email"] = inp_email
        row_email.addWidget(inp_email)
        scroll_layout.addLayout(row_email)
        
        row_pass = QHBoxLayout()
        lbl_pass = QLabel("Expense Password:")
        lbl_pass.setFixedWidth(150)
        row_pass.addWidget(lbl_pass)
        inp_pass = QLineEdit()
        inp_pass.setEchoMode(QLineEdit.Password)
        inp_pass.setText(self.current_settings.get("expense_password", ""))
        self.expense_inputs["expense_password"] = inp_pass
        row_pass.addWidget(inp_pass)
        scroll_layout.addLayout(row_pass)
        
        # 0. Global Defaults
        scroll_layout.addWidget(QLabel("<b>General Defaults</b>"))
        from PySide6.QtWidgets import QComboBox
        self.country_combo = QComboBox()
        self.country_combo.addItems(["CANADA (Default)", "USA"])
        self.country_combo.setCurrentIndex(0 if self.current_settings.get("default_country", "CA") == "CA" else 1)
        self.country_combo.setStyleSheet("padding: 5px; background-color: #252526;")
        
        row_country = QHBoxLayout()
        row_country.addWidget(QLabel("Default Region:"))
        row_country.addWidget(self.country_combo)
        scroll_layout.addLayout(row_country)
        
        row_ep = QHBoxLayout()
        row_ep.addWidget(QLabel("Default Episode Code:"))
        self.episode_input = QLineEdit()
        self.episode_input.setText(self.current_settings.get("expense_episode_code", "EP01"))
        self.episode_input.setStyleSheet("padding: 5px; background-color: #252526;")
        self.expense_inputs["expense_episode_code"] = self.episode_input
        row_ep.addWidget(self.episode_input)
        scroll_layout.addLayout(row_ep)

        row_cutoff = QHBoxLayout()
        row_cutoff.addWidget(QLabel("Expense Cutoff Days (e.g. 14):"))
        self.cutoff_input = QLineEdit()
        self.cutoff_input.setText(str(self.current_settings.get("expense_cutoff_days", "14")))
        self.cutoff_input.setStyleSheet("padding: 5px; background-color: #252526;")
        self.expense_inputs["expense_cutoff_days"] = self.cutoff_input
        row_cutoff.addWidget(self.cutoff_input)
        scroll_layout.addLayout(row_cutoff)

        # Date Mapping Section
        import json
        scroll_layout.addWidget(QLabel("<br><b>1. Episode Date Mapping</b>"))
        self.date_ranges_container = QWidget()
        self.date_ranges_layout = QVBoxLayout(self.date_ranges_container)
        self.date_ranges_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addWidget(self.date_ranges_container)
        
        self.date_range_widgets = []
        
        add_date_btn = QPushButton("+ Add Date Range")
        add_date_btn.setStyleSheet("background-color: #444; color: #fff; padding: 5px;")
        add_date_btn.clicked.connect(lambda: self.add_date_range_row("", "", ""))
        scroll_layout.addWidget(add_date_btn)
        
        # Load existing date ranges
        saved_dates_str = self.current_settings.get("episode_date_mappings", "[]")
        try:
            saved_dates = json.loads(saved_dates_str)
            for item in saved_dates:
                self.add_date_range_row(item.get("start", ""), item.get("end", ""), item.get("code", ""))
        except:
            pass
            
        # 1.5. Episode Prefix Mapping
        scroll_layout.addWidget(QLabel("<br><b>1.5. Episode Prefix Mapping</b>"))
        self.prefix_mappings_container = QWidget()
        self.prefix_mappings_layout = QVBoxLayout(self.prefix_mappings_container)
        self.prefix_mappings_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addWidget(self.prefix_mappings_container)
        
        self.prefix_mapping_widgets = []
        
        add_prefix_btn = QPushButton("+ Add Prefix Mapping")
        add_prefix_btn.setStyleSheet("background-color: #444; color: #fff; padding: 5px;")
        add_prefix_btn.clicked.connect(lambda: self.add_prefix_mapping_row("", ""))
        scroll_layout.addWidget(add_prefix_btn)
        
        # Load existing prefix mappings
        saved_prefixes_str = self.current_settings.get("episode_prefix_mappings", "[]")
        try:
            saved_prefixes = json.loads(saved_prefixes_str)
            for item in saved_prefixes:
                self.add_prefix_mapping_row(item.get("prefix", ""), item.get("code", ""))
        except:
            pass
            
        if not self.prefix_mapping_widgets:
            self.add_prefix_mapping_row("A", "251")
            self.add_prefix_mapping_row("X", "297")


        # 2. Account Codes
        scroll_layout.addWidget(QLabel("<br><b>2. GL Account Codes</b>"))
        account_fields = [
            ("Purchase Account", "expense_acc_purchase", "2716"),
            ("Rental Account", "expense_acc_rental", "2718"),
            ("Greens Account", "expense_acc_greens", "2358"),
            ("Craft/Food Account", "expense_acc_craft", "3622"),
            ("Gas/Oil Account", "expense_acc_gas", "3544"),
            ("Parking Account", "expense_acc_parking", "3547")
        ]
        for label_text, key, default in account_fields:
            row = QHBoxLayout()
            lbl = QLabel(label_text + ":")
            lbl.setFixedWidth(150)
            row.addWidget(lbl)
            inp = QLineEdit()
            inp.setText(self.current_settings.get(key, default))
            self.expense_inputs[key] = inp
            row.addWidget(inp)
            scroll_layout.addLayout(row)

        # 2.5 Tax Credit INS Flags
        scroll_layout.addWidget(QLabel("<br><b>2.5 Tax Credit INS Flags</b>"))
        ins_fields = [
            ("Default CAD INS Flag", "expense_ins_cad", "40"),
            ("Craft INS Flag", "expense_ins_craft", "46")
        ]
        for label_text, key, default in ins_fields:
            row = QHBoxLayout()
            lbl = QLabel(label_text + ":")
            lbl.setFixedWidth(150)
            row.addWidget(lbl)
            inp = QLineEdit()
            inp.setText(self.current_settings.get(key, default))
            self.expense_inputs[key] = inp
            row.addWidget(inp)
            scroll_layout.addLayout(row)

        # 3. Monthly HST Coding (Row 2 Account)
        scroll_layout.addWidget(QLabel("<br><b>3. Monthly HST Coding (Row 2 Account)</b>"))
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for i, month in enumerate(months):
            row = QHBoxLayout()
            lbl = QLabel(f"{month} HST Code:")
            lbl.setFixedWidth(150)
            row.addWidget(lbl)
            inp = QLineEdit()
            
            # Default to 7501 for Jan, 7502 for Feb... 7512 for Dec
            month_code = 7500 + i + 1
            inp.setText(self.current_settings.get(f"hst_month_{i+1}", str(month_code)))
            self.expense_inputs[f"hst_month_{i+1}"] = inp
            row.addWidget(inp)
            scroll_layout.addLayout(row)

        # Buyers & Aliases Management Section
        label_buyers = QLabel("DEPARTMENT BUYER NAMES & ALIASES")
        label_buyers.setStyleSheet("font-size: 15px; font-weight: bold; margin-top: 15px; color: #ccff66; letter-spacing: 1px; background-color: #2b3a2b; padding: 6px; border-radius: 4px;")
        layout.addWidget(label_buyers)

        lbl_buyers_sub = QLabel("Configure department buyers and aliases (comma-separated). Used for receipt recognition:")
        lbl_buyers_sub.setStyleSheet("font-size: 11px; color: #aaa; margin-bottom: 5px;")
        layout.addWidget(lbl_buyers_sub)

        def_buyer_layout = QHBoxLayout()
        def_buyer_lbl = QLabel("Default Buyer (when unassigned):")
        def_buyer_lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.default_buyer_input = QLineEdit()
        from core.settings import get_default_buyer, get_buyers, get_buyer_aliases
        self.default_buyer_input.setText(get_default_buyer())
        self.default_buyer_input.setStyleSheet("padding: 5px; background-color: #252526; border: 1px solid #444;")
        def_buyer_layout.addWidget(def_buyer_lbl)
        def_buyer_layout.addWidget(self.default_buyer_input)
        layout.addLayout(def_buyer_layout)

        self.buyers_layout = QVBoxLayout()
        layout.addLayout(self.buyers_layout)
        self.buyer_widgets = []

        buyers_list = get_buyers()
        aliases_map = get_buyer_aliases()
        for b in buyers_list:
            aliases_str = ", ".join(aliases_map.get(b, [b]))
            self.add_buyer_row(b, aliases_str)

        add_buyer_btn = QPushButton("+ Add Buyer")
        add_buyer_btn.setStyleSheet("background-color: #334d33; color: #ccff66; padding: 6px; font-weight: bold; border-radius: 4px; margin-top: 5px; margin-bottom: 10px;")
        add_buyer_btn.clicked.connect(lambda: self.add_buyer_row("", ""))
        layout.addWidget(add_buyer_btn)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("SAVE CHEAT SHEET & SETTINGS")
        save_btn.setFixedHeight(45)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #ccff00; 
                color: #000; 
                font-weight: bold; 
                border-radius: 5px;
                font-size: 13px;
                letter-spacing: 1px;
            }
            QPushButton:hover { background-color: #e6ff80; }
        """)
        save_btn.clicked.connect(self.save_and_close)
        
        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(45)
        cancel_btn.setStyleSheet("background-color: #333; color: #fff; border-radius: 5px;")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        
        self.resize(500, 700)
        
    def save_and_close(self):
        self.current_settings["spreadsheet_url"] = self.url_input.text().strip()
        self.current_settings["gemini_api_key"] = self.key_input.text().strip()
        self.current_settings["vendor_list_url"] = self.vendor_url_input.text().strip()
        self.current_settings["rental_agreements_sheet_url"] = self.ra_sheet_url_input.text().strip()
        self.current_settings["budget_sheet_url"] = self.budget_url_input.text().strip()
        self.current_settings["production_drive_folder_url"] = self.drive_url_input.text().strip()
        self.current_settings["props_inventory_url"] = self.props_inv_input.text().strip()
        self.current_settings["default_country"] = "US" if self.country_combo.currentIndex() == 1 else "CA"
        
        for key, inp in self.expense_inputs.items():
            self.current_settings[key] = inp.text()
            
        # Save date ranges
        import json
        ranges = []
        for start_input, end_input, code_input in self.date_range_widgets:
            ranges.append({
                "start": start_input.text(),
                "end": end_input.text(),
                "code": code_input.text()
            })
        self.current_settings["episode_date_mappings"] = json.dumps(ranges)
        
        # Save prefix mappings
        prefixes = []
        for prefix_input, code_input in self.prefix_mapping_widgets:
            pref = prefix_input.text().strip().upper()
            code = code_input.text().strip()
            if pref and code:
                prefixes.append({
                    "prefix": pref,
                    "code": code
                })
        self.current_settings["episode_prefix_mappings"] = json.dumps(prefixes)
            
        # Save buyers & aliases
        new_buyers = []
        new_aliases = {}
        for name_input, alias_input in self.buyer_widgets:
            b_name = name_input.text().strip().upper()
            if b_name:
                new_buyers.append(b_name)
                raw_aliases = [a.strip().upper() for a in alias_input.text().split(',') if a.strip()]
                if b_name not in raw_aliases:
                    raw_aliases.insert(0, b_name)
                new_aliases[b_name] = raw_aliases
        
        from core.settings import save_buyer_settings
        def_buyer = self.default_buyer_input.text().strip().upper() or "JORDAN"
        save_buyer_settings(buyers=new_buyers, aliases=new_aliases, default_buyer=def_buyer)

        save_settings(self.current_settings)
        self.accept()

    def add_date_range_row(self, start_val, end_val, code_val):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        
        start_input = QLineEdit()
        start_input.setPlaceholderText("Start (YYYY-MM-DD)")
        start_input.setText(start_val)
        start_input.setStyleSheet("padding: 5px; background-color: #252526;")
        
        end_input = QLineEdit()
        end_input.setPlaceholderText("End (YYYY-MM-DD)")
        end_input.setText(end_val)
        end_input.setStyleSheet("padding: 5px; background-color: #252526;")
        
        code_input = QLineEdit()
        code_input.setPlaceholderText("Code (e.g. 296)")
        code_input.setText(code_val)
        code_input.setStyleSheet("padding: 5px; background-color: #252526;")
        
        del_btn = QPushButton("X")
        del_btn.setFixedWidth(30)
        del_btn.setStyleSheet("background-color: #6699ff; color: #fff;")
        del_btn.clicked.connect(lambda: self.remove_date_range_row(row_widget, start_input, end_input, code_input))
        
        row_layout.addWidget(start_input)
        row_layout.addWidget(end_input)
        row_layout.addWidget(code_input)
        row_layout.addWidget(del_btn)
        
        self.date_ranges_layout.addWidget(row_widget)
        self.date_range_widgets.append((start_input, end_input, code_input))

    def remove_date_range_row(self, widget, start_input, end_input, code_input):
        widget.deleteLater()
        if (start_input, end_input, code_input) in self.date_range_widgets:
            self.date_range_widgets.remove((start_input, end_input, code_input))

    def add_prefix_mapping_row(self, prefix_val, code_val):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        
        prefix_input = QLineEdit()
        prefix_input.setPlaceholderText("Prefix (e.g. A)")
        prefix_input.setText(prefix_val)
        prefix_input.setStyleSheet("padding: 5px; background-color: #252526;")
        
        code_input = QLineEdit()
        code_input.setPlaceholderText("Code (e.g. 251)")
        code_input.setText(code_val)
        code_input.setStyleSheet("padding: 5px; background-color: #252526;")
        
        del_btn = QPushButton("X")
        del_btn.setFixedWidth(30)
        del_btn.setStyleSheet("background-color: #6699ff; color: #fff;")
        del_btn.clicked.connect(lambda: self.remove_prefix_mapping_row(row_widget, prefix_input, code_input))
        
        row_layout.addWidget(prefix_input)
        row_layout.addWidget(code_input)
        row_layout.addWidget(del_btn)
        
        self.prefix_mappings_layout.addWidget(row_widget)
        self.prefix_mapping_widgets.append((prefix_input, code_input))

    def remove_prefix_mapping_row(self, widget, prefix_input, code_input):
        widget.deleteLater()
        if (prefix_input, code_input) in self.prefix_mapping_widgets:
            self.prefix_mapping_widgets.remove((prefix_input, code_input))

    def add_buyer_row(self, buyer_name, aliases_str):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 2)
        
        name_input = QLineEdit()
        name_input.setPlaceholderText("Buyer Name")
        name_input.setText(buyer_name)
        name_input.setFixedWidth(140)
        name_input.setStyleSheet("padding: 5px; background-color: #252526; border: 1px solid #444;")
        
        alias_input = QLineEdit()
        alias_input.setPlaceholderText("Aliases, comma-separated")
        alias_input.setText(aliases_str)
        alias_input.setStyleSheet("padding: 5px; background-color: #252526; border: 1px solid #444;")
        
        del_btn = QPushButton("✕")
        del_btn.setFixedWidth(30)
        del_btn.setStyleSheet("background-color: #552222; color: #fff; border-radius: 3px; font-weight: bold;")
        del_btn.clicked.connect(lambda: self.remove_buyer_row(row_widget, name_input, alias_input))
        
        row_layout.addWidget(name_input)
        row_layout.addWidget(alias_input)
        row_layout.addWidget(del_btn)
        
        self.buyers_layout.addWidget(row_widget)
        self.buyer_widgets.append((name_input, alias_input))

    def remove_buyer_row(self, widget, name_input, alias_input):
        widget.deleteLater()
        if (name_input, alias_input) in self.buyer_widgets:
            self.buyer_widgets.remove((name_input, alias_input))
