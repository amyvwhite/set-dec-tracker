from PySide6.QtCore import QThread, Signal
import os
import shutil
import re
from datetime import datetime
from services.petty_cash_bot import (
    process_file,
    save_envelope_state,
    load_envelope_state,
    append_to_sheet,
    append_to_set_dec_tracker,
    get_template_receipt_count,
    BASE_DIR,
    get_short_owner_name
)

class ProcessPettyCashThread(QThread):
    progress_update = Signal(str)
    finished_processing = Signal()
    needs_set_number = Signal(str, str, dict) # receipt_name, default_set, data
    error = Signal(str)

    def __init__(self, input_dir, owner_name, env_num, today_str):
        super().__init__()
        self.input_dir = input_dir
        self.owner_name = owner_name
        self.env_num = str(env_num)
        self.today_str = today_str
        self.pending_data = None
        self.pending_file = None
        self._is_paused = False
        self._is_running = True
        self.buyer_tracker_rows = []
        self.current_receipt_count = 0

    def stop(self):
        self._is_running = False
        self._is_paused = False
        self.requestInterruption()

    def run(self):
        try:
            if not os.path.exists(self.input_dir):
                self.error.emit(f"Input directory does not exist: {self.input_dir}")
                return

            files = [
                f for f in os.listdir(self.input_dir)
                if os.path.isfile(os.path.join(self.input_dir, f))
                and not f.startswith(".")
                and f.lower() != "desktop.ini"
            ]
            if not files:
                self.error.emit("No files found in the petty cash input directory.")
                return

            # Check capacity: strictly 20 receipts per envelope
            self.current_receipt_count = get_template_receipt_count(self.owner_name)
            if self.current_receipt_count >= 20:
                self.error.emit(
                    f"Envelope #{self.env_num} for {self.owner_name} already has 20 receipts (maximum capacity)!\n\n"
                    "Please mark this envelope as complete and start a new envelope before adding more receipts."
                )
                return

            state = load_envelope_state()
            if self.owner_name not in state:
                state[self.owner_name] = {}
            if self.env_num not in state[self.owner_name]:
                state[self.owner_name][self.env_num] = {
                    "grand_total": 0.0,
                    "e_transfers": {}
                }
            
            env_state = state[self.owner_name][self.env_num]

            for i, f in enumerate(files):
                if self.isInterruptionRequested() or not self._is_running:
                    break
                if self.current_receipt_count >= 20:
                    self.progress_update.emit(f"Envelope #{self.env_num} has reached the 20-receipt limit! Stopping.")
                    break
                
                self.progress_update.emit(f"Processing ({i+1}/{len(files)}): {f} [Receipt {self.current_receipt_count + 1}/20]")
                file_path = os.path.join(self.input_dir, f)
                data = process_file(file_path)

                if not data:
                    self.progress_update.emit(f"Failed to process {f}. Skipping.")
                    continue

                if self.isInterruptionRequested() or not self._is_running:
                    break

                # Pause and emit signal to review receipt
                self._is_paused = True
                self.pending_file = file_path
                self.pending_data = data
                data["owner_name"] = self.owner_name
                self.needs_set_number.emit(f, "", data)
                
                # Wait until resumed or interrupted
                while self._is_paused:
                    self.msleep(100)
                    if self.isInterruptionRequested() or not self._is_running:
                        return
                        
            # Save final state
            state[self.owner_name][self.env_num] = env_state
            save_envelope_state(state)
            
            if self.current_receipt_count >= 20:
                self.progress_update.emit(f"Envelope #{self.env_num} reached maximum of 20 receipts.")
            self.finished_processing.emit()
            
        except Exception as e:
            import traceback
            self.error.emit(f"Error processing petty cash: {str(e)}\n{traceback.format_exc()}")

    def resume_with_set_number(self, results):
        if self.pending_data and self.pending_file:
            self.pending_data["set_num"] = results.get("set_num", "")
            self.pending_data["set_number"] = results.get("set_num", "")
            self.pending_data["is_craft"] = results.get("is_craft", False)
            self.pending_data["craft_quantity"] = results.get("craft_quantity", 1)
            self.pending_data["craft_type"] = results.get("craft_type", "")
            self.pending_data["date_range"] = results.get("date_range", "")
            
            if "vendor" in results and results["vendor"]:
                self.pending_data["vendor"] = results["vendor"]
            if "total" in results and results["total"] is not None:
                self.pending_data["total"] = float(results["total"])
            if "subtotal" in results and results["subtotal"] is not None:
                self.pending_data["subtotal"] = float(results["subtotal"])
            if "tax" in results and results["tax"] is not None:
                self.pending_data["tax"] = float(results["tax"])

            if "buyer_name" in results:
                self.pending_data["buyer_name"] = results["buyer_name"]
            
            state = load_envelope_state()
            env_state = state[self.owner_name][self.env_num]
            
            self.process_receipt_data(self.pending_file, self.pending_data, env_state)
            self.current_receipt_count += 1
            
            state[self.owner_name][self.env_num] = env_state
            save_envelope_state(state)

            if self.current_receipt_count >= 20:
                self._is_running = False
                self.progress_update.emit(f"Envelope #{self.env_num} has reached 20 receipts (full)!")
            
        self.pending_file = None
        self.pending_data = None
        self._is_paused = False

    def process_receipt_data(self, file_path, data, env_state):
        vendor = str(data.get("vendor", "")).upper()
        purchased = str(data.get("purchased_items", data.get("description", ""))).upper()
        gas_terms = ["PETRO", "SHELL", "ESSO", "PIONEER", "ULTRAMAR", "HUSKY", "CHEVRON", "MOBIL", "IRVING", "GAS", "FUEL"]
        parking_terms = ["PARKING", "PARK", "PRK", "TORPRK", "TORPRKAUT", "TPA", "GREEN P", "IMPARK", "INDIGO", "PRESTO", "METER", "PAYBYPHONE", "HONK", "CITY OF TORONTO"]
        toll_terms = ["TOLL", "TOLLS", "407", "407 ETR", "ETR", "HIGHWAY 407", "BRIDGE", "TUNNEL"]
        etransfer_terms = ["CASH PAYMENT FORM", "E-TRANSFER", "ETRANSFER", "ETF", "TRANSFER"]
        
        is_craft = data.get("is_craft", False)
        craft_quantity = int(data.get("craft_quantity", 1))
        is_gas = data.get("is_gas", False) or any(k in vendor or k in purchased for k in gas_terms)
        is_parking = data.get("is_parking", False) or any(k in vendor or k in purchased for k in parking_terms)
        is_toll = data.get("is_toll", False) or any(k in vendor or k in purchased for k in toll_terms)
        is_etransfer = any(k in vendor or k in purchased for k in etransfer_terms)

        if is_gas or is_parking or is_toll or is_etransfer:
            data["is_gas"] = is_gas
            data["is_parking"] = is_parking
            data["is_toll"] = is_toll
            data["is_craft"] = False
            is_craft = False
        else:
            # Treat BREAK and CRAFT identically
            craft_type_str = str(data.get("craft_type", "")).strip().upper()
            notes_str = str(data.get("notes", "")).strip().upper()
            all_text = f"{purchased} {craft_type_str} {notes_str}"
            if "BREAK" in all_text:
                is_craft = True
                data["is_craft"] = True
                m = re.search(r'BREAK\s*X\s*(\d+)', all_text)
                if m:
                    craft_quantity = int(m.group(1))
                    data["craft_quantity"] = craft_quantity
                elif not data.get("craft_quantity") or int(data.get("craft_quantity", 0)) <= 0:
                    craft_quantity = 1
                    data["craft_quantity"] = 1

        subtotal = float(data.get("subtotal", 0.0) or 0.0)
        tax = float(data.get("tax", 0.0) or 0.0)
        total = float(data.get("total", 0.0) or 0.0)

        # Handle Gas / Fuel / Parking / Tolls (Full Amount + 13% HST and Subtotal, NOT Craft)
        if is_gas or is_parking or is_toll:
            if total != 0.0 and (tax == 0.0 or subtotal == total or subtotal == 0.0):
                sign = -1.0 if total < 0 else 1.0
                abs_tot = abs(total)
                abs_sub = round(abs_tot / 1.13, 2)
                abs_tax = round(abs_tot - abs_sub, 2)
                subtotal = sign * abs_sub
                tax = sign * abs_tax
                data["subtotal"] = subtotal
                data["tax"] = tax

        # Handle Craft Limits
        elif is_craft:
            craft_type = str(data.get("craft_type", "")).strip().upper()
            if "LOCK UP" not in craft_type and "OFFICE" not in craft_type:
                craft_quantity = int(data.get("craft_quantity", 1))
                limit = 7.00 * craft_quantity
                if subtotal > limit:
                    subtotal = limit
                tax = round(subtotal * 0.13, 2)
                total = round(subtotal + tax, 2)
        
        # Only Amy reimburses people. Force clear buyer_name for others.
        if self.owner_name.upper() not in ["AMY WHITE", "AMY"]:
            buyer_name = ""
            data["buyer_name"] = ""
        else:
            from core.settings import normalize_buyer_name
            buyer_name = normalize_buyer_name(data.get("buyer_name", ""), default="")

        if is_craft:
            data["set_number"] = ""
            data["set_num"] = ""

        if buyer_name:
            try:
                from services.petty_cash_bot import save_remembered_buyer
                save_remembered_buyer(buyer_name)
            except Exception:
                pass

            env_state.setdefault("e_transfers", {})
            env_state["e_transfers"][buyer_name] = round(env_state["e_transfers"].get(buyer_name, 0.0) + total, 2)

            date_str = str(data.get("date", ""))
            craft_type = str(data.get("craft_type", "")).strip().upper()
            date_range = str(data.get("date_range", "")).strip()
            date_prefix = f"{date_range} " if date_range else ""
            
            if is_craft:
                if craft_type in ["LOCK UP CRAFT", "OFFICE CRAFT", "SET DEC CRAFT LOCK UP", "SET DEC CRAFT OFFICE"]:
                    desc = f"{date_prefix}{craft_type} REIMBURSEMENT"
                else:
                    desc = f"CRAFT X {craft_quantity} REIMBURSEMENT"
            elif any(word in vendor for word in ["SHELL", "PETRO", "ESSO", "PIONEER", "ULTRAMAR", "HUSKY", "CHEVRON", "MOBIL", "IRVING", "GAS", "FUEL"]):
                desc = f"{vendor} GAS REIMBURSEMENT"
            else:
                purchased_items = str(data.get("purchased_items", "")).strip().upper()
                if purchased_items:
                    desc = purchased_items
                else:
                    desc = f"{vendor} REIMBURSEMENT"
            
            row = [
                date_str,
                f"ENV #{self.env_num}",
                buyer_name,
                vendor,
                f"{total:.2f}",
                desc
            ]
            self.buyer_tracker_rows.append(row)
            env_state.setdefault("buyer_tracker_rows", []).append(row)
            
        env_state["grand_total"] += total

        # 2. Add to Expense Template sheet
        date_str = str(data.get("date", ""))
        vendor_str = str(data.get("vendor", "")).upper()
        
        is_cash_payment = "CASH PAYMENT FORM" in vendor_str
        is_gas = any(word in vendor_str for word in ["SHELL", "PETRO", "ESSO", "PIONEER", "ULTRAMAR", "HUSKY"])
        
        if is_cash_payment:
            purpose = f"{date_str} {str(data.get('purchased_items', '')).strip().upper()}"
        elif is_gas:
            purpose = f"{date_str} FUEL SET DEC"
        elif is_craft:
            if craft_type in ["LOCK UP CRAFT", "OFFICE CRAFT", "SET DEC CRAFT LOCK UP", "SET DEC CRAFT OFFICE"]:
                purpose = f"{date_str} {date_prefix}{craft_type}"
            else:
                purpose = f"{date_str} CRAFT X {craft_quantity}"
        else:
            # Purchases for sets: DO NOT put date in front of description!
            purchased_items_str = str(data.get("purchased_items", "")).strip().upper()
            if purchased_items_str:
                purpose = purchased_items_str
            else:
                purpose = vendor_str

        data["purpose"] = purpose

        if is_cash_payment:
            to_whom = str(data.get("buyer_name", "")).strip().upper()
        else:
            to_whom = vendor_str

        # Columns map to indices starting from B:
        # 0=B(Date), 1=C(Vendor/To Whom), 2=D(Purpose), 3-6=E-H(merged with D),
        # 7=I(Accounting), 8=J(Set#), 9=K(Inv. Item),
        # 10=L(Net Amount), 11=M(HST), 12=N(Total)
        row_data = [""] * 13
        row_data[0] = date_str
        row_data[1] = to_whom
        row_data[2] = purpose
        
        set_str = str(data.get("set_number", data.get("set_num", ""))).strip().upper()
        if set_str == "NA":
            row_data[8] = ""
        else:
            row_data[8] = set_str
            
        row_data[10] = round(subtotal, 2)
        row_data[11] = round(tax, 2)
        row_data[12] = round(total, 2)

        try:
            append_to_sheet(row_data, self.owner_name)
        except Exception as e:
            self.error.emit(f"Error appending to sheet: {e}")
            raise

        # 3. If NOT craft and NOT parking, add to set dec tracker app database (Google Sheet)
        if not is_craft and not data.get("is_parking", False) and set_str != "NA":
            try:
                data["set_number"] = set_str
                append_to_set_dec_tracker(data, self.env_num, self.owner_name)
            except Exception as e:
                self.error.emit(f"Error appending to set dec tracker: {e}")

        # 4. Move file to organized folder
        short_name = get_short_owner_name(self.owner_name)
        output_dir = os.path.join(BASE_DIR, f"{self.env_num} {short_name} {self.today_str}")
        os.makedirs(output_dir, exist_ok=True)
        
        filename = os.path.basename(file_path)
        try:
            ext = os.path.splitext(filename)[1]
            display_name = buyer_name if buyer_name else "UNKNOWN"
            safe_date = date_str.replace('/', '-') if date_str else self.today_str
            new_filename = f"{safe_date} - {vendor} - {display_name}{ext}"
            new_filename = re.sub(r'[<>:"/\\|?*]', '', new_filename)
            
            counter = 1
            base_new_name = new_filename
            while os.path.exists(os.path.join(output_dir, new_filename)):
                new_filename = f"{os.path.splitext(base_new_name)[0]} ({counter}){ext}"
                counter += 1
            
            dest_path = os.path.join(output_dir, new_filename)
            shutil.move(file_path, dest_path)
        except Exception as e:
            self.error.emit(f"Error renaming/moving file: {e}")
