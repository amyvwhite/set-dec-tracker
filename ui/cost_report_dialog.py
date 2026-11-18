from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QMessageBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

class CostReportReviewDialog(QDialog):
    def __init__(self, report_rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Projected Final Amounts")
        self.resize(850, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: white;
            }
            QLabel {
                color: white;
                font-weight: bold;
                margin-bottom: 5px;
            }
            QTableWidget {
                background-color: #2b2b2b;
                color: white;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #333;
                color: white;
                font-weight: bold;
                border: 1px solid #444;
            }
            QPushButton {
                background-color: #0d47a1;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
        """)
        self.report_rows = report_rows
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        info_label = QLabel("Check 'Closed?' to finalize a set's budget (adjusts projection to actual spend).")
        info_label.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        layout.addWidget(info_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Include?", "Episode", "Budget", "Total Spent", "Closed?", "Projected Final Amount", "Variance (Savings)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setRowCount(len(self.report_rows))
        
        for i, r in enumerate(self.report_rows):
            inc_item = QTableWidgetItem()
            inc_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            inc_item.setCheckState(Qt.Checked)
            
            ep_title = r["Episode"]
            if r.get("breakdowns"):
                tooltip_lines = [f"{b.get('code', '')} {b.get('desc', '')}: ${b.get('spent', 0.0):,.2f}".strip() for b in r["breakdowns"]]
                ep_item = QTableWidgetItem(f"{ep_title}*")
                ep_item.setToolTip("Includes:\n" + "\n".join(tooltip_lines))
            else:
                ep_item = QTableWidgetItem(ep_title)
            ep_item.setFlags(ep_item.flags() & ~Qt.ItemIsEditable)
            
            bgt_item = QTableWidgetItem(f"${r['Budget']:,.2f}")
            bgt_item.setFlags(bgt_item.flags() & ~Qt.ItemIsEditable)
            
            act_item = QTableWidgetItem(f"${r['Total Spent']:,.2f}")
            act_item.setFlags(act_item.flags() & ~Qt.ItemIsEditable)
            
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Unchecked)
            
            efc_item = QTableWidgetItem(str(r["Projected Final Amount"]))
            
            var_item = QTableWidgetItem(f"${(r['Budget'] - r['Projected Final Amount']):,.2f}")
            var_item.setFlags(var_item.flags() & ~Qt.ItemIsEditable)
            
            self.table.setItem(i, 0, inc_item)
            self.table.setItem(i, 1, ep_item)
            self.table.setItem(i, 2, bgt_item)
            self.table.setItem(i, 3, act_item)
            self.table.setItem(i, 4, chk_item)
            self.table.setItem(i, 5, efc_item)
            self.table.setItem(i, 6, var_item)
            
            self.update_row_colors(i)
            
        self.table.itemChanged.connect(self.on_item_changed)
            
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet("background-color: #444;")
        btn_cancel.clicked.connect(self.reject)
        
        btn_generate = QPushButton("Generate PDF")
        btn_generate.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_generate)
        layout.addLayout(btn_layout)

    def on_item_changed(self, item):
        row = item.row()
        col = item.column()
        
        if col == 0:  # Include? checkbox toggled
            self.update_row_colors(row)
        elif col == 4:  # Closed checkbox toggled
            is_closed = (item.checkState() == Qt.Checked)
            if is_closed:
                # Update EFC to actuals
                act_str = self.table.item(row, 3).text().replace("$", "").replace(",", "")
                # Temporarily disconnect to avoid loop
                self.table.itemChanged.disconnect(self.on_item_changed)
                self.table.item(row, 5).setText(act_str)
                self.table.itemChanged.connect(self.on_item_changed)
            else:
                # Restore original EFC from data
                orig_efc = self.report_rows[row]["Projected Final Amount"]
                self.table.itemChanged.disconnect(self.on_item_changed)
                self.table.item(row, 5).setText(str(orig_efc))
                self.table.itemChanged.connect(self.on_item_changed)
                
            self.update_row_colors(row)
            self.update_variance(row)
        elif col == 5:
            self.update_row_colors(row)
            self.update_variance(row)
            
    def update_variance(self, row):
        bgt_str = self.table.item(row, 2).text().replace("$", "").replace(",", "")
        efc_str = self.table.item(row, 5).text().replace("$", "").replace(",", "")
        try:
            bgt = float(bgt_str)
            efc = float(efc_str)
            variance = bgt - efc
            self.table.itemChanged.disconnect(self.on_item_changed)
            self.table.item(row, 6).setText(f"${variance:,.2f}")
            self.table.itemChanged.connect(self.on_item_changed)
        except:
            pass

    def update_row_colors(self, row):
        bgt_str = self.table.item(row, 2).text().replace("$", "").replace(",", "")
        efc_str = self.table.item(row, 5).text().replace("$", "").replace(",", "")
        try:
            bgt = float(bgt_str)
            efc = float(efc_str)
            
            # Keep EFC default styling
            self.table.item(row, 5).setBackground(QColor("#004466"))
            self.table.item(row, 5).setForeground(QColor("white"))
            
            if efc < bgt:
                self.table.item(row, 6).setBackground(QColor("#2e7d32")) # Green for savings
                self.table.item(row, 6).setForeground(QColor("white"))
            else:
                self.table.item(row, 6).setBackground(QColor("#2b2b2b")) # Default table color
                self.table.item(row, 6).setForeground(QColor("white"))
        except:
            pass

    def get_updated_rows(self):
        # Also persist cache for all rows
        try:
            import os, json
            cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "efc_cache.json")
            cache_data = {}
            if os.path.exists(cache_file):
                with open(cache_file, "r") as f:
                    cache_data = json.load(f)
            for i, r in enumerate(self.report_rows):
                efc_val = self.table.item(i, 5).text().replace("$", "").replace(",", "").strip()
                try:
                    cache_data[r["Episode"]] = float(efc_val)
                except ValueError:
                    pass
            with open(cache_file, "w") as f:
                json.dump(cache_data, f, indent=4)
        except Exception as e:
            print(f"Failed to cache EFC from dialog: {e}")

        # Return only included rows for the report
        included_rows = []
        for i, r in enumerate(self.report_rows):
            inc_item = self.table.item(i, 0)
            if inc_item and inc_item.checkState() == Qt.Checked:
                efc_str = self.table.item(i, 5).text().replace("$", "").replace(",", "").strip()
                var_str = self.table.item(i, 6).text().replace("$", "").replace(",", "").strip()
                try:
                    r["Projected Final Amount"] = float(efc_str)
                    r["Variance (Savings)"] = float(var_str)
                except ValueError:
                    pass
                included_rows.append(r)
        return included_rows
