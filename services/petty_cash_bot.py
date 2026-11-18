import os

import sys

from . import chq_req_generator

import shutil

import json

import re

import fitz  # PyMuPDF

from google import genai

import PIL.Image

import io

from datetime import datetime

import gspread

from gspread.exceptions import WorksheetNotFound



# --- CONFIGURATION ---

app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))

BASE_DIR = os.path.join(show_dir, "PETTY CASH")

INPUT_DIR = os.path.join(BASE_DIR, "petty cash input")

BACKEND_DIR = os.path.join(BASE_DIR, "Bot System Files")

CREDENTIALS_PATH = os.path.join(BACKEND_DIR, 'credentials.json')
if not os.path.exists(CREDENTIALS_PATH):
    CREDENTIALS_PATH = os.path.join(app_dir, 'services', 'credentials.json')

SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit?usp=sharing"

TRACKER_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit?usp=sharing"

SET_DEC_TRACKER_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit?usp=sharing"



# Get Gemini API Key

SETTINGS_PATH = os.path.join(app_dir, "settings.json")

try:

    with open(SETTINGS_PATH, 'r') as f:

        settings = json.load(f)

        GEMINI_API_KEY = settings.get("gemini_api_key", "")

except Exception as e:

    print(f"Could not load Gemini API Key: {e}")

    GEMINI_API_KEY = ""



import json



def load_envelope_state():

    state_file = os.path.join(BACKEND_DIR, "envelope_state.json")

    if os.path.exists(state_file):

        with open(state_file, "r") as f:

            try:

                return json.load(f)

            except:

                return {}

    return {}



def save_envelope_state(state):

    state_file = os.path.join(BACKEND_DIR, "envelope_state.json")

    with open(state_file, "w") as f:

        json.dump(state, f)



REMEMBERED_BUYERS_PATH = os.path.join(BACKEND_DIR, "remembered_buyers.json")



from core.settings import get_petty_cash_buyers

DEFAULT_BUYERS = get_petty_cash_buyers()



def get_remembered_buyers():

    try:

        if os.path.exists(REMEMBERED_BUYERS_PATH):

            with open(REMEMBERED_BUYERS_PATH, "r") as f:

                buyers = json.load(f)

                if isinstance(buyers, list):

                    return buyers

    except Exception as e:

        print(f"Error loading remembered buyers: {e}")

    return list(DEFAULT_BUYERS)



def save_remembered_buyer(name):

    if not name:

        return

    name_clean = str(name).strip().upper()

    if not name_clean or name_clean in ["UNKNOWN", "AMY", "AMY WHITE", "OTHER", "N/A", "NA"]:

        return

    try:

        buyers = get_remembered_buyers()

        if name_clean not in buyers:

            buyers.append(name_clean)

            os.makedirs(os.path.dirname(REMEMBERED_BUYERS_PATH), exist_ok=True)

            with open(REMEMBERED_BUYERS_PATH, "w") as f:

                json.dump(buyers, f, indent=2)

            print(f"Remembered new buyer: {name_clean}")

    except Exception as e:

        print(f"Error saving remembered buyer {name_clean}: {e}")



def get_global_envelope_data():

    env_file = os.path.join(BACKEND_DIR, "envelopes.json")

    if os.path.exists(env_file):

        with open(env_file, "r") as f:

            try:

                data = json.load(f)

                if not isinstance(data, dict):

                    data = {}

                return data

            except:

                return {}

    return {}



def save_global_envelope_data(data):

    env_file = os.path.join(BACKEND_DIR, "envelopes.json")

    with open(env_file, "w") as f:

        json.dump(data, f)



def extract_spreadsheet_id(url):

    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)

    if match:

        return match.group(1)

    return url



def get_template_tab_name(owner_name):

    owner_upper = owner_name.upper()

    if owner_upper in ["ROWENA HALE", "ROWAN HALE", "NICK", "ROWENA", "ROWAN"]:

        return "ROWAN PETTY"

    elif owner_upper in ["JORDAN PRICE", "JORDAN"]:

        return "JORDAN PETTY"

    elif owner_upper in ["RAVI KHAN", "RAVI"]:

        return "RAVI PETTY"

    elif owner_upper in ["SAM RIVERA", "SAMUEL RIVERA", "SAM", "SAMUEL"]:

        return "SAM PETTY"

    else:

        return "AMY PETTY"



def get_short_owner_name(owner_name):

    owner_upper = str(owner_name).upper()

    if owner_upper in ["ROWENA HALE", "ROWAN HALE", "NICK", "ROWENA", "ROWAN"]:

        return "ROWAN"

    elif owner_upper in ["JORDAN PRICE", "JORDAN"]:

        return "JORDAN"

    elif owner_upper in ["RAVI KHAN", "RAVI"]:

        return "RAVI"

    elif owner_upper in ["SAM RIVERA", "SAMUEL RIVERA", "SAM", "SAMUEL"]:

        return "SAM"

    elif owner_upper in ["AMY WHITE", "AMY"]:

        return "AMY"

    elif owner_upper in ["JOHN", "LIAM COLE"]:

        return "LIAM COLE"

    return owner_upper



def init_expense_template(owner_name):

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(SHEET_URL)

        sh = client.open_by_key(spreadsheet_id)

        

        tab_name = get_template_tab_name(owner_name)

        try:

            worksheet = sh.worksheet(tab_name)

        except gspread.exceptions.WorksheetNotFound:

            print(f"Tab '{tab_name}' not found. Duplicating template from 'AMY PETTY'...")

            source_ws = sh.worksheet('AMY PETTY')

            worksheet = sh.duplicate_sheet(source_ws.id, new_sheet_name=tab_name)



        worksheet.update_acell('C5', owner_name.upper())

    except Exception as e:

        print(f"Error updating template owner in {tab_name}: {e}")



def append_to_sheet(data_row, owner_name):

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(SHEET_URL)

        sh = client.open_by_key(spreadsheet_id)

        

        tab_name = get_template_tab_name(owner_name)

        worksheet = sh.worksheet(tab_name)

        

        all_values = worksheet.get_all_values()

        

        target_row = 1

        for i, row in enumerate(all_values):

            if i >= 12:

                if len(row) < 2 or not str(row[1]).strip():

                    target_row = i + 1

                    break

            target_row = i + 2

            

        if target_row < 13:

            target_row = 13



        if target_row > 32:

            msg = f"Cannot append to {tab_name}: maximum capacity of 20 receipts reached (row 32 is full)!"

            print(f"Error: {msg}")

            raise ValueError(msg)



        worksheet.update(values=[data_row], range_name=f"B{target_row}:N{target_row}", value_input_option='USER_ENTERED')

        print(f"Successfully appended receipt to row {target_row} in {tab_name}")

        

    except Exception as e:

        print(f"Error appending to Expense Template ({tab_name}): {e}")

        raise



def get_template_receipt_count(owner_name):

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(SHEET_URL)

        sh = client.open_by_key(spreadsheet_id)

        tab_name = get_template_tab_name(owner_name)

        worksheet = sh.worksheet(tab_name)

        all_values = worksheet.get_all_values()

        count = 0

        for i in range(12, min(32, len(all_values))):

            row = all_values[i]

            date_val = str(row[1]).strip() if len(row) > 1 else ""

            vendor_val = str(row[2]).strip() if len(row) > 2 else ""

            if date_val or vendor_val:

                count += 1

        return count

    except Exception as e:

        print(f"Error checking template receipt count: {e}")

        return 0



def get_actual_totals_from_sheet(owner_name):

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(SHEET_URL)

        sh = client.open_by_key(spreadsheet_id)

        

        tab_name = get_template_tab_name(owner_name)

        worksheet = sh.worksheet(tab_name)

        

        all_values = worksheet.get_all_values()

        

        # 1. Search for the "TOTAL RECEIPTS" summary row first to get the exact authoritative total

        for row in all_values:

            row_text = " ".join([str(cell).upper() for cell in row])

            if "TOTAL RECEIPTS" in row_text:

                net_val = float(str(row[11]).replace("$", "").replace(",", "").strip()) if len(row) > 11 and str(row[11]).replace("$", "").replace(",", "").strip() else 0.0

                hst_val = float(str(row[12]).replace("$", "").replace(",", "").strip()) if len(row) > 12 and str(row[12]).replace("$", "").replace(",", "").strip() else 0.0

                tot_val = float(str(row[13]).replace("$", "").replace(",", "").strip()) if len(row) > 13 and str(row[13]).replace("$", "").replace(",", "").strip() else 0.0

                

                if tot_val > 0:

                    return {"subtotal": round(net_val, 2), "hst": round(hst_val, 2), "total": round(tot_val, 2)}

        

        # 2. Fallback if TOTAL RECEIPTS row is missing: sum line items from row 13 to row 32

        totals = {"subtotal": 0.0, "hst": 0.0, "total": 0.0}

        for i in range(12, min(32, len(all_values))):

            row = all_values[i]

            if len(row) > 13:

                val_str = str(row[13]).strip().replace("$", "").replace(",", "")

                if val_str:

                    try: totals["total"] += float(val_str)

                    except ValueError: pass

            if len(row) > 11:

                val_str = str(row[11]).strip().replace("$", "").replace(",", "")

                if val_str:

                    try: totals["subtotal"] += float(val_str)

                    except ValueError: pass

            if len(row) > 12:

                val_str = str(row[12]).strip().replace("$", "").replace(",", "")

                if val_str:

                    try: totals["hst"] += float(val_str)

                    except ValueError: pass

                    

        return totals

    except Exception as e:

        print(f"Error fetching totals from sheet: {e}")

        return {"subtotal": 0.0, "hst": 0.0, "total": 0.0}



def append_to_set_dec_tracker(receipt_data, env_num, owner_name=""):

    if not receipt_data.get('set_number') or receipt_data.get('is_parking') or receipt_data.get('is_craft'):

        return

        

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(SET_DEC_TRACKER_URL)

        sh = client.open_by_key(spreadsheet_id)

        

        target_tab = str(receipt_data['set_number']).strip().upper()

        

        try:

            worksheet = sh.worksheet(target_tab)

        except gspread.exceptions.WorksheetNotFound:

            headers = [

                "EXPENDITURE", " ", "VENDOR", "NAME", "DESCRIPTION/ITEMS", 

                "CHQ REQ", "PETTY CASH", "CREDIT CARD", "I/A", "P.O.", "P.O. #", 

                "DATE", "REFERENCE", "RENTAL (Y/N)", "RENTAL END DATE", "CHQ #", "NOTES"

            ]

            worksheet = sh.add_worksheet(title=target_tab, rows="1000", cols=str(len(headers) + 5))

            worksheet.append_row(headers)



        row = [""] * 20

        row[0] = round(float(receipt_data.get('subtotal', 0.0) or 0.0), 2)

        row[1] = ""

        row[2] = str(receipt_data.get('vendor', '')).upper()

        buyer_first = str(receipt_data.get('buyer_name', '')).split()[0].upper() if receipt_data.get('buyer_name') else ""

        if not buyer_first and owner_name:

            buyer_first = str(owner_name).split()[0].upper()

        row[3] = buyer_first

        row[4] = str(receipt_data.get('purpose', '')).upper()

        row[5] = "" 

        row[6] = "X" 

        row[7] = "" 

        row[9] = "" 

        row[10] = "" 

        row[11] = str(receipt_data.get('date', ''))

        row[12] = f"Env #{env_num}"

        row[13] = "N" 

        row[14] = "" 

        row[15] = ""

        row[16] = str(receipt_data.get('reference_number', '')).upper() 



        if target_tab == "GREENS":

            start_row = 18

        elif target_tab == "A02":

            start_row = 7

        else:

            start_row = 9

            

        all_values = worksheet.get_all_values()

        target_row = start_row

        

        data_rows = all_values[start_row-1:] if len(all_values) >= start_row else []

        for i, val_row in enumerate(data_rows, start=start_row):

            if len(val_row) < 3 or not str(val_row[2]).strip():

                target_row = i

                break

            target_row = i + 1

            

        worksheet.update(values=[[row[0]]], range_name=f"A{target_row}", value_input_option='USER_ENTERED')

        worksheet.update(values=[row[2:]], range_name=f"C{target_row}", value_input_option='USER_ENTERED')

        print(f"Successfully appended to Set Dec Tracker ({target_tab})")

        

    except Exception as e:

        print(f"Error appending to Set Dec Tracker: {e}")



def append_to_float_tracker(owner_name, grand_total, env_num, date_str):

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(TRACKER_URL)

        sh = client.open_by_key(spreadsheet_id)

        worksheet = sh.worksheet("ENV Tracker") 

        

        all_values = worksheet.get_all_values()

        row_12 = all_values[11] 

        

        sheet_name = get_short_owner_name(owner_name)

            

        col_index = -1

        for i, val in enumerate(row_12):

            if str(val).strip().upper() == sheet_name:

                col_index = i

                break

                

        if col_index == -1:

            print(f"Warning: Could not find person '{sheet_name}' in the float tracker Sheet1 (row 12).")

            return

            

        float_col_index = col_index + 1

        

        # Find last row that has data in this person's float column, then append below it.

        # Scanning bottom-up is safe — we never risk overwriting an existing entry.

        last_used_row = 12  # row 13 (1-based) is the minimum starting point
        existing_row = None
        for k in range(12, len(all_values)):
            row = all_values[k]
            float_val = str(row[float_col_index]).strip() if len(row) > float_col_index else ""
            env_val   = str(row[float_col_index + 1]).strip() if len(row) > float_col_index + 1 else ""
            if env_val == str(env_num):
                existing_row = k + 1
            if float_val != "" or env_val != "":
                last_used_row = k + 1

        if existing_row:
            worksheet.update_cell(existing_row, float_col_index + 1, f"-{grand_total:.2f}")
            worksheet.update_cell(existing_row, float_col_index + 3, date_str)
            print(f"Successfully updated ENV #{env_num} to -{grand_total:.2f} in {sheet_name}'s float column (row {existing_row})!")
        else:
            target_row = last_used_row + 1
            worksheet.update_cell(target_row, float_col_index + 1, f"-{grand_total:.2f}")
            worksheet.update_cell(target_row, float_col_index + 2, f"{env_num}")
            worksheet.update_cell(target_row, float_col_index + 3, date_str)
            print(f"Successfully logged -{grand_total:.2f} to {sheet_name}'s float column!")

        

    except Exception as e:

        print(f"Error appending to Float Tracker: {e}")



def append_to_tracker(buyer_rows, grand_total, env_num, date_str):

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(TRACKER_URL)

        sh = client.open_by_key(spreadsheet_id)

        

        tab_name = "Bot Reimbursements"

        try:

            worksheet = sh.worksheet(tab_name)

        except gspread.exceptions.WorksheetNotFound:

            print(f"Creating new tab '{tab_name}' in the Tracker...")

            worksheet = sh.add_worksheet(title=tab_name, rows="1000", cols="6")

            headers = ["Date", "Envelope #", "Person to Pay", "Vendor", "Amount Owed", "Notes"]

            worksheet.append_row(headers)

            worksheet.format("A1:F1", {

                "backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.88},

                "textFormat": {"foregroundColor": {"red": 0.2, "green": 0.2, "blue": 0.3}, "fontFamily": "Nunito", "fontSize": 11, "bold": True},

                "horizontalAlignment": "CENTER",

                "borders": {"bottom": {"style": "SOLID_MEDIUM", "color": {"red": 0.9, "green": 0.6, "blue": 0.7}}}

            })

            

        sum_tab_name = "E-Transfers Summaries"

        try:

            sum_worksheet = sh.worksheet(sum_tab_name)

        except gspread.exceptions.WorksheetNotFound:

            print(f"Creating new tab '{sum_tab_name}' in the Tracker...")

            sum_worksheet = sh.add_worksheet(title=sum_tab_name, rows="1000", cols="5")

            sum_headers = ["Envelope #", "Person to Pay", "Total Amount Owed", "Paid?", "Date Paid"]

            sum_worksheet.append_row(sum_headers)

            sum_worksheet.format("A1:E1", {

                "backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.98},

                "textFormat": {"foregroundColor": {"red": 0.1, "green": 0.3, "blue": 0.4}, "fontFamily": "Nunito", "fontSize": 11, "bold": True},

                "horizontalAlignment": "CENTER",

                "borders": {"bottom": {"style": "SOLID_MEDIUM", "color": {"red": 0.5, "green": 0.8, "blue": 0.9}}}

            })

            

            requests = [{

                'setDataValidation': {

                    'range': {

                        'sheetId': sum_worksheet.id,

                        'startRowIndex': 1,

                        'endRowIndex': 1000,

                        'startColumnIndex': 3, 

                        'endColumnIndex': 4,

                    },

                    'rule': {

                        'condition': {'type': 'BOOLEAN'},

                        'showCustomUi': True,

                    }

                }

            }]

            sh.batch_update({'requests': requests})



        all_rows = []

        for buyer_row in buyer_rows:

            amt_val = str(buyer_row[6]).replace('$', '').strip()

            new_row = [buyer_row[0], buyer_row[1], buyer_row[2], buyer_row[5], amt_val, buyer_row[7]]

            all_rows.append(new_row)

            

        totals = {}

        for row in buyer_rows:

            person = row[2]

            amount_str = row[6].replace('$', '').replace(',', '')

            try:

                amount = float(amount_str)

            except ValueError:

                amount = 0.0

            totals[person] = totals.get(person, 0.0) + amount

        

        sum_rows = []

        for person in totals.keys():

            sum_rows.append([f"ENV #{env_num}", person])



        if all_rows:

            start_row = len(worksheet.get_all_values()) + 1

            worksheet.append_rows(all_rows, value_input_option='USER_ENTERED')

            end_row = start_row + len(all_rows) - 1

            worksheet.format(f"A{start_row}:F{end_row}", {

                "textFormat": {"fontFamily": "Nunito", "fontSize": 10, "foregroundColor": {"red": 0.3, "green": 0.3, "blue": 0.3}},

                "horizontalAlignment": "CENTER"

            })

        

        if sum_rows:

            # Read existing rows to avoid overwriting manually entered "Paid?" dates

            existing = sum_worksheet.get_all_values()

            # Build a lookup: (env_label, person) -> row_index (1-based, accounting for header)

            existing_lookup = {}

            for idx, ex_row in enumerate(existing[1:], start=2):  # skip header

                if len(ex_row) >= 2:

                    key = (str(ex_row[0]).strip().upper(), str(ex_row[1]).strip().upper())

                    existing_lookup[key] = idx



            rows_to_append = []

            start_sum_row = len(existing) + 1

            for sr in sum_rows:

                env_label = str(sr[0]).strip().upper()

                person = str(sr[1]).strip().upper()

                key = (env_label, person)

                if key in existing_lookup:

                    # Update column C with dynamic SUMIFS formula, leave Paid? (col D) untouched

                    row_idx = existing_lookup[key]

                    formula = f"=SUMIFS('Bot Reimbursements'!$E:$E, 'Bot Reimbursements'!$B:$B, A{row_idx}, 'Bot Reimbursements'!$C:$C, B{row_idx})"

                    sum_worksheet.update(values=[[formula]], range_name=f"C{row_idx}", value_input_option='USER_ENTERED')

                else:

                    curr_row = start_sum_row + len(rows_to_append)

                    formula = f"=SUMIFS('Bot Reimbursements'!$E:$E, 'Bot Reimbursements'!$B:$B, A{curr_row}, 'Bot Reimbursements'!$C:$C, B{curr_row})"

                    rows_to_append.append([env_label, person, formula, ""])



            if rows_to_append:

                sum_worksheet.append_rows(rows_to_append, value_input_option='USER_ENTERED')

                end_sum_row = start_sum_row + len(rows_to_append) - 1

                sum_worksheet.format(f"A{start_sum_row}:E{end_sum_row}", {

                    "textFormat": {"fontFamily": "Nunito", "fontSize": 10, "foregroundColor": {"red": 0.3, "green": 0.3, "blue": 0.3}},

                    "horizontalAlignment": "CENTER"

                })


        print(f"Successfully updated Tracker with line items and summaries!")

        

    except Exception as e:

        print(f"Error appending to Tracker Sheet: {e}")



def process_file(file_path):

    print(f"Processing {os.path.basename(file_path)}...")

    if not GEMINI_API_KEY:

        print("ERROR: No Gemini API Key.")

        return None



    client = genai.Client(api_key=GEMINI_API_KEY)

    

    try:

        if file_path.lower().endswith('.pdf'):

            doc = fitz.open(file_path)

            page = doc.load_page(0) 

            pix = page.get_pixmap()

            img_bytes = pix.tobytes("png")

            img = PIL.Image.open(io.BytesIO(img_bytes))

        else:

            img = PIL.Image.open(file_path)



        remembered_str = ", ".join(get_remembered_buyers())

        from core.settings import load_settings

        settings_data = load_settings()

        dynamic_sets = settings_data.get("dynamic_sets", {})

        set_list_str = ""

        if dynamic_sets:

            for ep_name, sets in dynamic_sets.items():

                set_list_str += ", ".join([s['code'] for s in sets]) + ", "

        else:

            set_list_str = "L02, X80, 101, A05"

            

        prompt = f"""

        Extract the following information from the receipt.

        Respond ONLY with a JSON object. No markdown formatting, no backticks, no other text.

        Format MUST BE:

        {{

            "date": "YYYY-MM-DD",

            "vendor": "Vendor Name. IMPORTANT: If this document is a 'CASH PAYMENT FORM', use the 'Recipient Name' as the Vendor.",

            "buyer_name": "Name of the person who bought this (if handwritten on the receipt or obvious). ALWAYS KEEP AN EYE OUT FOR THESE NAMES: {remembered_str}. Default to empty string if not found.",

            "purchased_items": "string (If this is a 'CASH PAYMENT FORM', extract the text under 'Purchased Item(s)'. For all other receipts, briefly describe the main item(s) purchased, e.g. 'GROCERIES', 'COFFEE + SNACKS', 'OFFICE SUPPLIES'. Default to empty string if truly unclear.)",

            "is_craft": true/false (true if receipt is for CRAFT or BREAK. Treat BREAK and CRAFT as the exact same thing. IMPORTANT: When a note or receipt just says 'BREAK' or 'break', that means craft x 1),

            "craft_quantity": integer (default 1 if is_craft is true and no quantity is specified, 0 if not craft. If it just says 'break' or 'craft', craft_quantity MUST be 1. Look for 'craft x 2' or 'break x 2' or similar),

            "craft_type": "string (If the receipt is for a large bulk order like 'LOCK UP CRAFT' or 'OFFICE CRAFT', extract 'LOCK UP' or 'OFFICE'. Otherwise default to empty string)",

            "is_gas": true/false (true if receipt is for GAS or FUEL or from a gas station like Petro Canada, Shell, Esso, Pioneer, Ultramar, Husky, Chevron, Mobil, Irving, etc. IMPORTANT: Gas/fuel is NEVER craft! is_craft MUST be false if is_gas is true),

            "reference_number": "string (Look for an Invoice #. If none, look for an Order #. If none, default to empty string)",

            "set_number": "string (Look for a Set Number, e.g. {set_list_str}. Default to empty string)",

            "subtotal": float,

            "tax": float,

            "total": float

        }}

        IMPORTANT RULE: If this receipt or Hyatt invoice has HIGHLIGHTED or UNDERLINED items (e.g. highlighter or pen/red underlines under line items, prices, or descriptions), ONLY extract and sum the HIGHLIGHTED or UNDERLINED items. Completely ignore unhighlighted/ununderlined lines.

        """

        

        response = client.models.generate_content(

            model="gemini-2.5-flash",

            contents=[prompt, img]

        )

        

        text = response.text.replace('```json', '').replace('```', '').strip()

        data = json.loads(text)

        return data

        

    except Exception as e:

        print(f"Error processing with Gemini: {e}")

        return None



def rebuild_buyer_tracker_rows_from_folder(env_num, owner_name, today_str=""):

    import glob, re

    owner_upper = owner_name.strip().upper()

    

    # 1. For Amy's envelopes, read live rows directly from the AMY PETTY worksheet tab first

    if owner_upper in ["AMY WHITE", "AMY"]:

        try:

            client = gspread.service_account(filename=CREDENTIALS_PATH)

            sh = client.open_by_key(extract_spreadsheet_id(SHEET_URL))

            tab_name = get_template_tab_name(owner_upper)

            ws = sh.worksheet(tab_name)

            vals = ws.get_all_values()

            

            sheet_items = []

            if len(vals) >= 13:

                for r in vals[12:32]:

                    if len(r) >= 14 and r[1].strip() and r[2].strip():

                        date_raw = r[1].strip()

                        vendor = r[2].strip()

                        purpose = r[3].strip()

                        try:

                            total = float(r[13].replace('$', '').replace(',', '').strip())

                        except ValueError:

                            total = 0.0

                        if total > 0 and vendor.upper() != "VENDOR":

                            # When purpose just says 'break', convert to 'craft x 1'

                            p_upper = purpose.strip().upper()

                            if p_upper == "BREAK":

                                purpose = f"{date_raw} CRAFT X 1"

                            elif p_upper.endswith(" BREAK"):

                                d_part = p_upper[:-6].strip()

                                purpose = f"{d_part} CRAFT X 1"

                            sheet_items.append({

                                'date_raw': date_raw,

                                'vendor': vendor,

                                'purpose': purpose,

                                'total': total

                            })

                            

            if sheet_items:

                matching_dirs = glob.glob(os.path.join(BASE_DIR, f"{env_num} *"))

                file_info = []

                if matching_dirs:

                    raw_files = [f for f in os.listdir(matching_dirs[0]) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.pdf')) and 'SPREADSHEET' not in f]

                    # Sort files chronologically by modification time (exact receipt scanning order)

                    raw_files.sort(key=lambda f: os.path.getmtime(os.path.join(matching_dirs[0], f)))

                    for f in raw_files:

                        parts = f.rsplit('.', 1)[0].split(' - ')

                        if len(parts) >= 3:

                            file_date = parts[0].strip()

                            vendor_part = parts[1].strip().upper()

                            buyer_part = parts[2].strip().upper()

                            buyer_part = re.sub(r'\s*\(\d+\)', '', buyer_part)

                            file_info.append({'file_date': file_date, 'vendor': vendor_part, 'buyer': buyer_part})

                                

                tracker_rows = []

                used_files = set()

                for item_idx, item in enumerate(sheet_items):

                    v_upper = item['vendor'].upper()

                    purpose_upper = item['purpose'].upper()



                    # Check if a known buyer is explicitly written in the sheet row (vendor or purpose)
                    explicit_buyer = None
                    for b in get_remembered_buyers():
                        b_up = b.upper()
                        if b_up in v_upper or b_up in purpose_upper:
                            explicit_buyer = b_up
                            break

                    matched_buyer = 'UNKNOWN'
                    if explicit_buyer:
                        matched_buyer = explicit_buyer
                    else:
                        # 1. Best match: vendor match AND file_date in purpose
                        best_match_idx = None
                        for idx, fi in enumerate(file_info):
                            if idx in used_files:
                                continue
                            vendor_match = (fi['vendor'] == v_upper) or (fi['vendor'] in v_upper) or (v_upper in fi['vendor'])
                            if vendor_match and fi['file_date'] in purpose_upper:
                                best_match_idx = idx
                                break

                        # 2. Fallback: vendor match alone
                        if best_match_idx is None:
                            for idx, fi in enumerate(file_info):
                                if idx in used_files:
                                    continue
                                vendor_match = (fi['vendor'] == v_upper) or (fi['vendor'] in v_upper) or (v_upper in fi['vendor'])
                                if vendor_match:
                                    best_match_idx = idx
                                    break

                        # 3. Fallback: match by receipt index if unused
                        if best_match_idx is None and item_idx < len(file_info) and item_idx not in used_files:
                            best_match_idx = item_idx

                        if best_match_idx is not None:
                            used_files.add(best_match_idx)
                            matched_buyer = file_info[best_match_idx]['buyer']

                    if matched_buyer in ["JOHN", "LIAM COLE"]: matched_buyer = "LIAM COLE"

                    elif matched_buyer in ["OSCAR", "OSCAR C"]: matched_buyer = "OSCAR FINCH"

                    elif matched_buyer in ["JR", "TJ MORROW"]: matched_buyer = "TJ MORROW"

                    elif matched_buyer in ["NOAH", "NOAH BELL"]: matched_buyer = "NOAH BELL"

                    elif matched_buyer in ["SAM", "SAM RIVERA", "SAMUEL", "SAMUEL RIVERA"]: matched_buyer = "SAM RIVERA"

                    elif matched_buyer in ["OWEN", "OWEN PARK"]: matched_buyer = "OWEN PARK"

                    elif matched_buyer in ["ELI", "ELI VANCE", "ELIAS", "ELIAS VANCE"]: matched_buyer = "ELI VANCE"

                    elif matched_buyer in ["DAN", "DAN REID"]: matched_buyer = "DAN REID"

                    elif matched_buyer in ["MAYA", "MAYA STONE"]: matched_buyer = "MAYA STONE"

                    elif matched_buyer in ["LEO", "LEO GRANT"]: matched_buyer = "LEO GRANT"

                    elif matched_buyer in ["ZOE", "ZOE LANE"]: matched_buyer = "ZOE LANE"

                    elif matched_buyer in ["IAN", "IAN WEST", "IAN WEST"]: matched_buyer = "IAN WEST"

                    elif matched_buyer.startswith("NICK") and matched_buyer != "ROWAN": matched_buyer = "NICK D"

                    elif matched_buyer in ["JOSH", "JOSH VARCOE", "JOSH VARVOE"]: matched_buyer = "JOSH VARCOE"

                    elif "TAMAS" in matched_buyer: matched_buyer = "TAMAS PAL"

                    elif "GECEK" in matched_buyer or matched_buyer in ["AL", "AL G", "AL GECEKUSU"]: matched_buyer = "AL GECEKUSU"



                    t_val = item['total']

                    date_val = today_str if today_str else datetime.today().strftime("%Y-%m-%d")

                    tracker_rows.append([

                        date_val,

                        f"ENV #{env_num}",

                        matched_buyer,

                        item['vendor'],

                        f"{t_val:.2f}",

                        item['purpose']

                    ])

                print(f"Extracted {len(tracker_rows)} live adjusted rows directly from {tab_name} tab for ENV #{env_num}!")

                return tracker_rows

        except Exception as e:

            print(f"Notice: Could not extract live rows from worksheet tab: {e}. Falling back to folder files...")



    # Fallback to image files in folder if worksheet tab reading unavailable

    matching_dirs = glob.glob(os.path.join(BASE_DIR, f"{env_num} *"))

    if not matching_dirs:

        return []

    

    output_dir = matching_dirs[0]

    image_files = [f for f in os.listdir(output_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

    image_files.sort(key=lambda f: os.path.getmtime(os.path.join(output_dir, f)))

    rows = []

    for f in image_files:

        fp = os.path.join(output_dir, f)

        data = process_file(fp)

        

        parts = f.split(' - ')

        if len(parts) >= 3:

            buyer_from_fn = parts[2].replace('.jpg', '').replace('.png', '').replace('.jpeg', '').strip().upper()

            buyer_from_fn = re.sub(r'\s*\(\d+\)', '', buyer_from_fn)

            if buyer_from_fn and buyer_from_fn not in ["UNKNOWN", ""]:

                data['buyer_name'] = buyer_from_fn

                

        buyer_name = str(data.get("buyer_name", "")).strip().upper()

        if not buyer_name or buyer_name in ["UNKNOWN", "AMY", "AMY WHITE"]:

            continue

            

        if buyer_name in ["JOHN", "LIAM COLE"]: buyer_name = "LIAM COLE"

        elif buyer_name in ["OSCAR", "OSCAR C"]: buyer_name = "OSCAR FINCH"

        elif buyer_name in ["JR", "TJ MORROW"]: buyer_name = "TJ MORROW"

        elif buyer_name in ["NOAH", "NOAH BELL"]: buyer_name = "NOAH BELL"

        elif buyer_name in ["SAM", "SAM RIVERA", "SAMUEL", "SAMUEL RIVERA"]: buyer_name = "SAM RIVERA"

        elif buyer_name in ["OWEN", "OWEN PARK"]: buyer_name = "OWEN PARK"

        elif buyer_name in ["ELI", "ELI VANCE", "ELIAS", "ELIAS VANCE"]: buyer_name = "ELI VANCE"

        elif buyer_name in ["DAN", "DAN REID"]: buyer_name = "DAN REID"

        elif buyer_name in ["MAYA", "MAYA STONE"]: buyer_name = "MAYA STONE"

        elif buyer_name in ["LEO", "LEO GRANT"]: buyer_name = "LEO GRANT"

        elif buyer_name in ["ZOE", "ZOE LANE"]: buyer_name = "ZOE LANE"

        elif buyer_name in ["IAN", "IAN WEST", "IAN WEST"]: buyer_name = "IAN WEST"

        elif buyer_name.startswith("NICK") and buyer_name != "ROWAN": buyer_name = "NICK D"

        elif buyer_name in ["JOSH", "JOSH VARCOE", "JOSH VARVOE"]: buyer_name = "JOSH VARCOE"

        elif "TAMAS" in buyer_name: buyer_name = "TAMAS PAL"

        elif "GECEK" in buyer_name or buyer_name in ["AL", "AL G", "AL GECEKUSU"]: buyer_name = "AL GECEKUSU"



        date_str = str(data.get("date", ""))

        vendor = str(data.get("vendor", "")).strip().upper()

        total = float(data.get("total", 0.0) or 0.0)

        is_craft = data.get("is_craft", False)

        craft_quantity = int(data.get("craft_quantity", 1) or 1)

        craft_type = str(data.get("craft_type", "")).strip().upper()

        purchased_items = str(data.get("purchased_items", "")).strip().upper()

        if "BREAK" in craft_type or "BREAK" in purchased_items:

            is_craft = True

            if not craft_quantity or craft_quantity <= 0:

                craft_quantity = 1

        is_bulk_craft = any(term in craft_type or term in purchased_items or term in vendor for term in ["LOCK UP", "OFFICE", "BULK", "WHOLESALE", "COSTCO"])

        

        if is_craft and not is_bulk_craft:

            limit = 7.00 * craft_quantity

            capped_subtotal = min(total / 1.13, limit) if total > 0 else limit

            capped_tax = round(capped_subtotal * 0.13, 2)

            capped_total = round(capped_subtotal + capped_tax, 2)

            if total > capped_total:

                total = capped_total

            desc = f"CRAFT X {craft_quantity} REIMBURSEMENT"

        elif any(w in vendor for w in ["SHELL", "PETRO", "ESSO", "PIONEER", "ULTRAMAR", "HUSKY", "GAS", "FUEL"]):

            desc = f"{vendor} GAS REIMBURSEMENT"

        else:

            desc = purchased_items if purchased_items else f"{vendor} REIMBURSEMENT"

            

        rows.append([

            date_str,

            f"ENV #{env_num}",

            buyer_name,

            vendor,

            f"{total:.2f}",

            desc

        ])

    return rows



def append_single_receipt_to_bot_reimbursements(row):

    """

    Appends a single itemized receipt row directly to 'Bot Reimbursements' in real time as receipts are approved.

    """

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        sh = client.open_by_key(extract_spreadsheet_id(TRACKER_URL))

        ws = sh.worksheet("Bot Reimbursements")

        ws.append_row(row, value_input_option='USER_ENTERED')

        print(f"Logged receipt to Bot Reimbursements: {row}")

    except Exception as e:

        print(f"Error appending single receipt to Bot Reimbursements: {e}")



def sync_etransfers_from_bot_reimbursements(target_env_num=None, today_str=""):

    """

    Reads all rows from 'Bot Reimbursements' and recalculates/updates 'E-Transfers Summaries'.

    If target_env_num is provided, updates only that envelope's summary rows using dynamic SUMIFS formulas.

    """

    try:

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        sh = client.open_by_key(extract_spreadsheet_id(TRACKER_URL))

        ws_bot = sh.worksheet("Bot Reimbursements")

        ws_sum = sh.worksheet("E-Transfers Summaries")

        

        bot_values = ws_bot.get_all_values()

        if not bot_values or len(bot_values) <= 1:

            return

            

        target_label = f"ENV #{target_env_num}".upper() if target_env_num else None



        # Collect distinct persons for each envelope in the order they appear in Bot Reimbursements

        env_person_order = []

        seen_keys = set()

        for r in bot_values[1:]:

            if len(r) >= 5:

                env_label = str(r[1]).strip().upper()

                person = str(r[2]).strip().upper()

                if not env_label or not person:

                    continue

                if target_label and env_label != target_label:

                    continue

                key = (env_label, person)

                if key not in seen_keys:

                    seen_keys.add(key)

                    env_person_order.append(key)



        if not env_person_order:

            return

            

        existing_sum = ws_sum.get_all_values()

        

        # Save any existing "Paid?" status (column D) so we don't erase user markings

        paid_status_map = {}

        for r in existing_sum[1:]:

            if len(r) >= 2:

                k = (str(r[0]).strip().upper(), str(r[1]).strip().upper())

                paid_val = str(r[3]).strip() if len(r) >= 4 else ""

                if paid_val:

                    paid_status_map[k] = paid_val



        if target_label:

            # Delete existing rows for this envelope so we can write clean rows in order

            indices_to_delete = [i+1 for i, r in enumerate(existing_sum) if len(r) >= 1 and str(r[0]).strip().upper() == target_label]

            for idx in reversed(indices_to_delete):

                ws_sum.delete_rows(idx)

            existing_sum = ws_sum.get_all_values()

            

            # Now append all persons for this envelope with SUMIFS formulas

            start_row = len(existing_sum) + 1

            new_rows = []

            for i, (env_lbl, person) in enumerate(env_person_order):

                row_idx = start_row + i

                formula = f"=SUMIFS('Bot Reimbursements'!$E:$E, 'Bot Reimbursements'!$B:$B, A{row_idx}, 'Bot Reimbursements'!$C:$C, B{row_idx})"

                paid_val = paid_status_map.get((env_lbl, person), "")

                new_rows.append([env_lbl, person, formula, paid_val])



            if new_rows:

                ws_sum.append_rows(new_rows, value_input_option='USER_ENTERED')

                end_row = start_row + len(new_rows) - 1

                ws_sum.format(f"A{start_row}:D{end_row}", {

                    "textFormat": {"fontFamily": "Nunito", "fontSize": 11, "foregroundColor": {"red": 0.1, "green": 0.1, "blue": 0.1}},

                    "horizontalAlignment": "CENTER"

                })

        else:

            # If syncing without target_env_num, update existing or append missing

            existing_lookup = {}

            for idx, ex_row in enumerate(existing_sum[1:], start=2):

                if len(ex_row) >= 2:

                    k = (str(ex_row[0]).strip().upper(), str(ex_row[1]).strip().upper())

                    existing_lookup[k] = idx

            

            new_rows = []

            start_row = len(existing_sum) + 1

            for env_lbl, person in env_person_order:

                k = (env_lbl, person)

                if k in existing_lookup:

                    row_idx = existing_lookup[k]

                    formula = f"=SUMIFS('Bot Reimbursements'!$E:$E, 'Bot Reimbursements'!$B:$B, A{row_idx}, 'Bot Reimbursements'!$C:$C, B{row_idx})"

                    ws_sum.update(values=[[formula]], range_name=f"C{row_idx}", value_input_option='USER_ENTERED')

                else:

                    row_idx = start_row + len(new_rows)

                    formula = f"=SUMIFS('Bot Reimbursements'!$E:$E, 'Bot Reimbursements'!$B:$B, A{row_idx}, 'Bot Reimbursements'!$C:$C, B{row_idx})"

                    paid_val = paid_status_map.get(k, "")

                    new_rows.append([env_lbl, person, formula, paid_val])

            

            if new_rows:

                ws_sum.append_rows(new_rows, value_input_option='USER_ENTERED')

                end_row = start_row + len(new_rows) - 1

                ws_sum.format(f"A{start_row}:D{end_row}", {

                    "textFormat": {"fontFamily": "Nunito", "fontSize": 11, "foregroundColor": {"red": 0.1, "green": 0.1, "blue": 0.1}},

                    "horizontalAlignment": "CENTER"

                })

        print("Successfully synced E-Transfers Summaries from Bot Reimbursements!")

    except Exception as e:

        print(f"Error syncing E-Transfers Summaries: {e}")



def complete_envelope(owner_name, env_num, today_str=""):

    owner_upper = owner_name.strip().upper()

    env_str = str(env_num)

    state = load_envelope_state()

    

    data = state.get(owner_upper, {}).get(env_str, {})

    

    actual_totals = get_actual_totals_from_sheet(owner_upper)

    grand_total = actual_totals["total"]

    

    if grand_total <= 0:

        grand_total = data.get("grand_total", 0.0)

    

    print(f"Total Envelope Amount: ${grand_total:.2f}")

    

    # 1. Download PDF of the envelope tab

    try:

        import requests

        client = gspread.service_account(filename=CREDENTIALS_PATH)

        spreadsheet_id = extract_spreadsheet_id(SHEET_URL)

        sh = client.open_by_key(spreadsheet_id)

        

        tab_name = get_template_tab_name(owner_upper)

        ws = sh.worksheet(tab_name)

        

        url = f"https://docs.google.com/spreadsheets/d/{sh.id}/export?format=pdf&gid={ws.id}&portrait=true&size=letter"

        res = client.http_client.request('GET', url)

        

        import glob

        matching_dirs = glob.glob(os.path.join(BASE_DIR, f"{env_num} *"))

        if matching_dirs:

            output_dir = matching_dirs[0]

        else:

            short_name = get_short_owner_name(owner_upper)

            env_folder_name = f"{env_num} {short_name} {today_str}"

            output_dir = os.path.join(BASE_DIR, env_folder_name)

            os.makedirs(output_dir, exist_ok=True)

        

        safe_owner = "".join([c for c in owner_upper if c.isalnum() or c in ' -_']).strip()

        pdf_path = os.path.join(output_dir, f"{safe_owner}_ENV_{env_num}_SPREADSHEET.pdf")

        

        with open(pdf_path, "wb") as f:

            f.write(res.content)

        print(f"Saved Envelope PDF to {pdf_path}")

    except Exception as e:

        print(f"Error downloading Envelope PDF: {e}")

    

    # 2. Append to float tracker

    append_to_float_tracker(owner_upper, grand_total, env_num, today_str)

    

    # 3. For Amy's envelopes, write final itemized rows to Bot Reimbursements AND calculate E-Transfers Summaries ONLY when completed

    if owner_upper in ["AMY WHITE", "AMY"]:

        try:

            print(f"Rebuilding final itemized rows for ENV #{env_num}...")

            buyer_tracker_rows = rebuild_buyer_tracker_rows_from_folder(env_num, owner_upper, today_str)

            if buyer_tracker_rows:

                client = gspread.service_account(filename=CREDENTIALS_PATH)

                sh = client.open_by_key(extract_spreadsheet_id(TRACKER_URL))

                ws_bot = sh.worksheet("Bot Reimbursements")

                

                existing_bot_rows = ws_bot.get_all_values()

                target_label = f"ENV #{env_num}".upper()

                # Clear any existing rows for this envelope so fresh edits from the Google Sheet tab replace them
                indices_to_delete = [idx+1 for idx, r in enumerate(existing_bot_rows) if len(r) >= 2 and str(r[1]).strip().upper() == target_label]
                for d_idx in reversed(indices_to_delete):
                    ws_bot.delete_rows(d_idx)

                ws_bot.append_rows(buyer_tracker_rows, value_input_option='USER_ENTERED')
                print(f"Successfully synced {len(buyer_tracker_rows)} live adjusted rows from {tab_name} to Bot Reimbursements for ENV #{env_num}!")



            print(f"Syncing E-Transfers Summaries for ENV #{env_num} from Bot Reimbursements...")

            sync_etransfers_from_bot_reimbursements(env_num, today_str)

        except Exception as e:

            print(f"Error logging to Bot Reimbursements / E-Transfers Summaries: {e}")

            

    print("\nEnvelope successfully marked as COMPLETE and logged to Tracker!")

    

    import glob

    matching_dirs = glob.glob(os.path.join(BASE_DIR, f"{env_num} *"))

    if matching_dirs:

        output_dir = matching_dirs[0]

    else:

        short_name = get_short_owner_name(owner_upper)

        output_dir = os.path.join(BASE_DIR, f"{env_num} {short_name} {today_str}")

        os.makedirs(output_dir, exist_ok=True)

        

    # chq_req_generator.generate_chq_req_pdf(owner_upper, grand_total, output_dir, env_num)


def main():

    if not os.path.exists(INPUT_DIR):

        print(f"Input directory does not exist: {INPUT_DIR}")

        return



    files = [f for f in os.listdir(INPUT_DIR) if os.path.isfile(os.path.join(INPUT_DIR, f))]

        

    print("\n--- PETTY CASH BOT ---")

    

    print("\nWho is this envelope for?")

    print("1. AMY WHITE")

    print("2. ROWAN HALE")

    print("3. JORDAN PRICE")

    print("4. Other (Type a name)")

    

    choice = input("\nSelect an option (1-4) [Default 1]: ").strip()

    

    if choice == "2":

        owner_name = "ROWAN HALE"

    elif choice == "3":

        owner_name = "JORDAN PRICE"

    elif choice == "4":

        owner_name = input("Enter the name: ").strip()

        if not owner_name:

            owner_name = "AMY WHITE"

    else:

        owner_name = "AMY WHITE"

        

    owner_upper = owner_name.upper()

    

    from datetime import datetime

    today_str = datetime.now().strftime("%Y-%m-%d")

    

    env_data = get_global_envelope_data()

    global_max = env_data.get("GLOBAL_MAX", 0)

    if global_max == 0:

        global_max = max(env_data.values()) if env_data and any(isinstance(v, int) for v in env_data.values()) else 1

    

    current_owner_env = env_data.get(owner_upper, global_max)

    

    print(f"\nCurrent Envelope for {owner_upper}: #{current_owner_env}")

    print(f"1. Add receipts to {owner_upper} Envelope #{current_owner_env}")

    print(f"2. Mark {owner_upper} Envelope #{current_owner_env} as COMPLETE (Logs totals to Tracker)")

    next_env = global_max + 1

    print(f"3. Start a BRAND NEW Envelope for {owner_upper} (Will be #{next_env})")

    

    env_choice = input("Select an option (1-3) [Default 1]: ").strip()

    

    if env_choice == "3":

        env_num = next_env

        env_data["GLOBAL_MAX"] = next_env

        env_data[owner_upper] = next_env

        save_global_envelope_data(env_data)

        print(f"\nStarting BRAND NEW Envelope #{env_num} for {owner_upper}!")

    elif env_choice == "2":

        env_num = current_owner_env

        print(f"\nMarking Envelope #{env_num} for {owner_upper} as COMPLETE...")

        complete_envelope(owner_upper, env_num, today_str)

        input("Press Enter to exit...")

        return

    else:

        if not files:

            print("No files found in the input directory to process.")

            input("Press Enter to exit...")

            return

            

        env_num = current_owner_env

        env_data["GLOBAL_MAX"] = max(global_max, env_num)

        env_data[owner_upper] = env_num

        save_global_envelope_data(env_data)

        print(f"\nContinuing Envelope #{env_num} for {owner_upper}...")

        

    init_expense_template(owner_name)

    print(f"\nProcessing envelope for {owner_name.upper()}...\n")


    short_name = get_short_owner_name(owner_name)

    output_dir = os.path.join(BASE_DIR, f"{env_num} {short_name} {today_str}")

    os.makedirs(output_dir, exist_ok=True)

    

    # 1. Process all files and collect the data

    receipts_batch = []

    for filename in files:

        file_path = os.path.join(INPUT_DIR, filename)

        data = process_file(file_path)

        if data:

            receipts_batch.append({

                'filename': filename,

                'file_path': file_path,

                'data': data

            })

            

    if not receipts_batch:

        print("No valid data could be extracted from any files.")

        return

        

    # 2. Sort the batch chronologically by date

    def sort_key(item):

        d = item['data'].get('date', '')

        # Basic parsing to ensure "6/5" -> "06/05" for alphabetical sorting

        parts = d.split('/')

        if len(parts) == 2:

            return f"{parts[0].zfill(2)}/{parts[1].zfill(2)}"

        return d

        

    receipts_batch.sort(key=sort_key)

    print("\nAll files processed and sorted by date!")



    # 3. Append to sheets in chronological order

    grand_total = 0.0

    buyer_tracker_rows = []

    

    for item in receipts_batch:

        filename = item['filename']

        file_path = item['file_path']

        data = item['data']

        

        date = data.get("date", "")

        vendor = str(data.get("vendor", "")).upper()

        buyer_name = str(data.get("buyer_name", "")).strip().upper()

        

        if buyer_name in ["JOHN", "LIAM COLE"]:

            buyer_name = "LIAM COLE"

        elif buyer_name in ["OSCAR", "OSCAR C"]:

            buyer_name = "OSCAR FINCH"

        elif buyer_name in ["JR", "TJ MORROW"]:

            buyer_name = "TJ MORROW"

        elif buyer_name in ["NOAH", "NOAH BELL"]:

            buyer_name = "NOAH BELL"

        elif buyer_name in ["SAM", "SAM RIVERA", "SAMUEL", "SAMUEL RIVERA"]:

            buyer_name = "SAM RIVERA"

        elif buyer_name in ["OWEN", "OWEN PARK"]:

            buyer_name = "OWEN PARK"

        elif buyer_name in ["ELI", "ELI VANCE", "ELIAS", "ELIAS VANCE"]:

            buyer_name = "ELI VANCE"

        elif buyer_name in ["DAN", "DAN REID"]:

            buyer_name = "DAN REID"

        elif buyer_name in ["MAYA", "MAYA STONE"]:

            buyer_name = "MAYA STONE"

        elif buyer_name in ["LEO", "LEO GRANT"]:

            buyer_name = "LEO GRANT"

        elif buyer_name in ["ZOE", "ZOE LANE"]:

            buyer_name = "ZOE LANE"

        elif buyer_name in ["IAN", "IAN WEST", "IAN WEST"]:

            buyer_name = "IAN WEST"

        elif buyer_name.startswith("NICK") and buyer_name != "ROWAN":

            buyer_name = "NICK D"

        elif buyer_name in ["JOSH", "JOSH VARCOE", "JOSH VARVOE"]:

            buyer_name = "JOSH VARCOE"

        elif "TAMAS" in buyer_name:

            buyer_name = "TAMAS PAL"

        elif "GECEK" in buyer_name or buyer_name in ["AL", "AL G", "AL GECEKUSU"]:

            buyer_name = "AL GECEKUSU"

            

        purchased_items = str(data.get("purchased_items", "")).strip().upper()

        gas_terms = ["PETRO", "SHELL", "ESSO", "PIONEER", "ULTRAMAR", "HUSKY", "CHEVRON", "MOBIL", "IRVING", "GAS", "FUEL"]

        parking_terms = ["PARKING", "PARK", "PRK", "TORPRK", "TORPRKAUT", "TPA", "GREEN P", "IMPARK", "INDIGO", "PRESTO", "METER", "PAYBYPHONE", "HONK", "CITY OF TORONTO"]

        toll_terms = ["TOLL", "TOLLS", "407", "407 ETR", "ETR", "HIGHWAY 407", "BRIDGE", "TUNNEL"]

        etransfer_terms = ["CASH PAYMENT FORM", "E-TRANSFER", "ETRANSFER", "ETF", "TRANSFER"]



        is_craft = data.get("is_craft", False)

        craft_quantity = int(data.get("craft_quantity", 1))

        is_gas = data.get("is_gas", False) or any(k in vendor or k in purchased_items for k in gas_terms)

        is_parking = data.get("is_parking", False) or any(k in vendor or k in purchased_items for k in parking_terms)

        is_toll = data.get("is_toll", False) or any(k in vendor or k in purchased_items for k in toll_terms)

        is_etransfer = any(k in vendor or k in purchased_items for k in etransfer_terms)



        if is_gas or is_parking or is_toll or is_etransfer:

            data["is_gas"] = is_gas

            data["is_parking"] = is_parking

            data["is_toll"] = is_toll

            data["is_craft"] = False

            is_craft = False



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

        

        purpose = ""

        set_num = str(data.get("set_number", "")).upper()

        

        if is_craft:

            limit = 7.00 * craft_quantity

            if subtotal > limit:

                subtotal = limit

            tax = round(subtotal * 0.13, 2)

            total = round(subtotal + tax, 2)

            purpose = f"{date} CRAFT X {craft_quantity} SET DEC"

            set_num = ""  # Craft NEVER has a set number

            

            if buyer_name:

                buyer_tracker_rows.append([

                    date,

                    f"ENV #{env_num}",

                    buyer_name,

                    "FALSE",

                    "",

                    vendor,

                    f"{total:.2f}",

                    f"CRAFT X {craft_quantity} REIMBURSEMENT"

                ])

        elif is_gas:

            purpose = f"{date} FUEL SET DEC"

            if buyer_name:

                buyer_tracker_rows.append([

                    date,

                    f"ENV #{env_num}",

                    buyer_name,

                    "FALSE",

                    "",

                    vendor,

                    f"{total:.2f}",

                    f"{vendor} GAS REIMBURSEMENT"

                ])

        else:

            # Purchases for sets: DO NOT put date in front of description!

            if purchased_items:

                purpose = purchased_items

            else:

                purpose = vendor

                

            if buyer_name:

                buyer_tracker_rows.append([

                    date,

                    f"ENV #{env_num}",

                    buyer_name,

                    "FALSE",

                    "",

                    vendor,

                    f"{total:.2f}",

                    f"{vendor} REIMBURSEMENT"

                ])

        

        row_data = [""] * 13

        row_data[0] = date           # B

        row_data[1] = vendor         # C (To Whom)

        row_data[2] = purpose        # D (Purpose)

        

        set_str = set_num.strip().upper() if set_num else ""

        if set_str == "NA":

            row_data[8] = ""

        else:

            row_data[8] = set_str  # J (Set#)

            

        row_data[10] = round(subtotal, 2) # L (Net Amount)

        row_data[11] = round(tax, 2)      # M (HST)

        row_data[12] = round(total, 2)    # N (Total)

        

        print(f"Appending: {date} - {vendor} - ${total:.2f}")

        append_to_sheet(row_data, owner_name)

        

        if not is_craft:

            extracted_set = str(data.get("set_number", "")).strip().upper()

            if extracted_set:

                print(f"\nExtracted Set # for {vendor}: {extracted_set}")

                confirm = input("Press Enter to keep this Set #, or type a new one (or type 'skip' to skip): ").strip()

                if confirm.lower() == 'skip':

                    final_set = ""

                elif confirm != "":

                    final_set = confirm.upper()

                else:

                    final_set = extracted_set

            else:

                final_set = input(f"\nNon-craft receipt from {vendor} for ${total:.2f}. What set is this for? (Hit Enter to skip): ").strip().upper()

                

            if final_set:

                receipt_data = {

                    'subtotal': subtotal,

                    'vendor': vendor,

                    'buyer_name': buyer_name,

                    'purpose': purpose,

                    'date': date,

                    'reference_number': data.get('reference_number', ''),

                    'set_number': final_set

                }

                append_to_set_dec_tracker(receipt_data, env_num)

        

        grand_total += total

        

        state = load_envelope_state()

        env_str = str(env_num)

        if owner_upper not in state:

            state[owner_upper] = {}

        if env_str not in state[owner_upper]:

            state[owner_upper][env_str] = {"grand_total": 0.0, "e_transfers": {}}

            

        state[owner_upper][env_str]["grand_total"] += total

        if buyer_name:

            current_e_total = state[owner_upper][env_str]["e_transfers"].get(buyer_name, 0.0)

            state[owner_upper][env_str]["e_transfers"][buyer_name] = current_e_total + total

            

        save_envelope_state(state)

        

        # Move and rename file

        try:

            ext = os.path.splitext(filename)[1]

            display_name = buyer_name if buyer_name else "UNKNOWN"

            safe_date = date.replace('/', '-') if date else today_str

            new_filename = f"{safe_date} - {vendor} - {display_name}{ext}"

            new_filename = re.sub(r'[<>:"/\\|?*]', '', new_filename)

            

            counter = 1

            base_new_name = new_filename

            while os.path.exists(os.path.join(output_dir, new_filename)):

                new_filename = f"{os.path.splitext(base_new_name)[0]} ({counter}){ext}"

                counter += 1

            

            shutil.move(file_path, os.path.join(output_dir, new_filename))

        except Exception as e:

            print(f"Error moving file: {e}")

            

    print(f"\nProcessing complete! Grand Total: ${grand_total:.2f}")

    

    if owner_name.upper() in ["AMY WHITE", "AMY"] and buyer_tracker_rows:

        append_to_tracker(buyer_tracker_rows, grand_total, env_num, today_str)

        

    print("\nAll files processed successfully!")

    input("Press Enter to exit...")



if __name__ == "__main__":

    main()

