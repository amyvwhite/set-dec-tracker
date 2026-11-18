import gspread
import os
import re
import sys

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.dirname(sys.executable)
else:
    DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CREDENTIALS_PATH = os.path.join(DATA_DIR, 'services', 'credentials.json')
if not os.path.exists(CREDENTIALS_PATH) and getattr(sys, '_MEIPASS', None):
    alt_path = os.path.join(sys._MEIPASS, 'services', 'credentials.json')
    if os.path.exists(alt_path):
        CREDENTIALS_PATH = alt_path

def get_client():
    if not os.path.exists(CREDENTIALS_PATH):
        raise FileNotFoundError("credentials.json is missing in services directory.")
    client = gspread.service_account(filename=CREDENTIALS_PATH)
    
    # Patch request to handle 429 API Quota automatically
    original_request = client.http_client.request
    import time
    def patched_request(*args, **kwargs):
        for attempt in range(7):
            try:
                return original_request(*args, **kwargs)
            except gspread.exceptions.APIError as e:
                # 429 Quota Exceeded
                if getattr(e.response, 'status_code', None) == 429 or '429' in str(e):
                    sleep_time = (2 ** attempt) + 3
                    print(f"API Quota hit! Sleeping for {sleep_time} seconds before retrying (Attempt {attempt+1}/7)...")
                    time.sleep(sleep_time)
                else:
                    raise
        return original_request(*args, **kwargs)
        
    client.http_client.request = patched_request
    return client

def extract_spreadsheet_id(url):
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if match:
        return match.group(1)
    return url

def get_spreadsheet(url):
    client = get_client()
    spreadsheet_id = extract_spreadsheet_id(url)
    return client.open_by_key(spreadsheet_id)

# --- IN-MEMORY SHORT-TERM CACHE & BATCH READ/WRITE UTILITIES ---
import time

_SHEET_DATA_CACHE = {}  # key: (spreadsheet_id, range_key), val: (timestamp, data)
_WORKSHEET_TITLES_CACHE = {}  # key: spreadsheet_id, val: (timestamp, set_of_titles)
CACHE_TTL_SECONDS = 45  # 45-second cache for batch operations

def get_cached_worksheet_titles(sh, max_age: float = CACHE_TTL_SECONDS) -> set:
    """
    Returns a set of all worksheet titles in the spreadsheet, cached for `max_age` seconds.
    Avoids repeated metadata fetch calls across operations.
    """
    now = time.time()
    cached = _WORKSHEET_TITLES_CACHE.get(sh.id)
    if cached and (now - cached[0] < max_age):
        return cached[1]
    
    titles = {w.title for w in sh.worksheets()}
    _WORKSHEET_TITLES_CACHE[sh.id] = (now, titles)
    return titles

def batch_get_worksheets_data(sh, tab_names: list, range_spec: str = "A1:Q120", use_cache: bool = True) -> dict:
    """
    Fetches rows for multiple worksheets in a SINGLE Google Sheets API call
    using values:batchGet. Returns a dictionary mapping tab_name -> list of row lists.
    Prevents hitting the 60 requests/minute Google Sheets read quota.
    """
    if not tab_names:
        return {}

    now = time.time()
    results = {}
    missing_tabs = []

    existing_titles = get_cached_worksheet_titles(sh)
    valid_tabs = [t for t in tab_names if t in existing_titles]

    if use_cache:
        for t in valid_tabs:
            cache_key = (sh.id, f"'{t}'!{range_spec}")
            cached = _SHEET_DATA_CACHE.get(cache_key)
            if cached and (now - cached[0] < CACHE_TTL_SECONDS):
                results[t] = cached[1]
            else:
                missing_tabs.append(t)
    else:
        missing_tabs = valid_tabs

    if missing_tabs:
        chunk_size = 30
        for i in range(0, len(missing_tabs), chunk_size):
            chunk = missing_tabs[i:i + chunk_size]
            ranges = [f"'{t}'!{range_spec}" for t in chunk]
            try:
                batch_res = sh.values_batch_get(ranges)
                value_ranges = batch_res.get('valueRanges', [])
                for idx, vr in enumerate(value_ranges):
                    t_name = chunk[idx]
                    vals = vr.get('values', [])
                    results[t_name] = vals
                    if use_cache:
                        _SHEET_DATA_CACHE[(sh.id, f"'{t_name}'!{range_spec}")] = (now, vals)
            except Exception as e:
                print(f"DEBUG: Error in batch_get_worksheets_data for chunk {chunk}: {e}")
                for t in chunk:
                    try:
                        vals = sh.worksheet(t).get_all_values()
                        results[t] = vals
                        if use_cache:
                            _SHEET_DATA_CACHE[(sh.id, f"'{t}'!{range_spec}")] = (now, vals)
                    except Exception:
                        results[t] = []

    return results

def clear_sheet_cache(spreadsheet_id: str = None):
    """Clears the in-memory cache when new tabs or rows are written."""
    global _SHEET_DATA_CACHE, _WORKSHEET_TITLES_CACHE
    if spreadsheet_id:
        keys_to_del = [k for k in list(_SHEET_DATA_CACHE.keys()) if k[0] == spreadsheet_id]
        for k in keys_to_del:
            _SHEET_DATA_CACHE.pop(k, None)
        _WORKSHEET_TITLES_CACHE.pop(spreadsheet_id, None)
    else:
        _SHEET_DATA_CACHE.clear()
        _WORKSHEET_TITLES_CACHE.clear()


def get_budget_alerts(url):
    """
    Reads the TOPSHEET tab, looks for Set names and % column.
    Returns a list of dicts: {"set": "A01", "pct": 81, "msg": "..."}
    """
    if not url:
        return [{"msg": "⚠ No Google Sheets URL configured."}]
    
    try:
        sh = get_spreadsheet(url)
        try:
            worksheet = sh.worksheet("TRACKER TOPSHEET")
        except:
            worksheet = sh.get_worksheet(1) # Second tab fallback
        data = worksheet.get_all_values()
        
        # Dynamically locate % and cost/budget columns
        pct_col_idx = 7
        cost_col_idx = 4
        bgt_col_idx = 5
        for row in data[:6]:
            for idx, cell in enumerate(row):
                c_upper = str(cell).strip().upper()
                if c_upper == '%':
                    pct_col_idx = idx
                elif 'COST' in c_upper:
                    cost_col_idx = idx
                elif c_upper == 'BUDGET':
                    bgt_col_idx = idx
                    
        alerts = []
        for row in data:
            if len(row) <= max(pct_col_idx, 2):
                continue
                
            # Try columns C or B for the set code (index 2 or 1)
            set_col_1 = str(row[1]).strip().upper() if len(row) > 1 else ""
            set_col_2 = str(row[2]).strip().upper() if len(row) > 2 else ""
            
            set_code = ""
            if set_col_2 and set_col_2 not in ["SET", "CODE", "NAME", "TOTAL"]:
                set_code = set_col_2
            elif set_col_1 and set_col_1 not in ["SET", "CODE", "NAME", "TOTAL"]:
                set_code = set_col_1
            
            if not set_code or set_code in ["SET", "CODE", "NAME", "TOTAL"]:
                continue
            
            pct_str = str(row[pct_col_idx]).strip().replace('%', '') if len(row) > pct_col_idx else ""
            cost_str = str(row[cost_col_idx]).strip().replace('$', '').replace(',', '') if len(row) > cost_col_idx else ""
            bgt_str = str(row[bgt_col_idx]).strip().replace('$', '').replace(',', '') if len(row) > bgt_col_idx else ""
            
            pct_val = 0.0
            try:
                if pct_str:
                    pct_str = pct_str.replace(',', '')
                    pct_val = float(pct_str)
                    if 0 < pct_val < 1.0:
                        pct_val = pct_val * 100
                elif bgt_str and cost_str:
                    b_val = float(bgt_str)
                    c_val = float(cost_str)
                    if b_val > 0:
                        pct_val = (c_val / b_val) * 100
                    else:
                        continue
                else:
                    continue
                    
                if pct_val >= 90.0:
                    alerts.append({
                        "set": set_code,
                        "pct": round(pct_val, 1),
                        "msg": f"⚠ Set {set_code} is at {round(pct_val, 1)}% of budget"
                    })
            except ValueError:
                pass
        return alerts
    except Exception as e:
        print(f"Error fetching budget alerts: {e}")
        if '503' in str(e):
            return [{"msg": "⚠ Google Sheets servers are temporarily down (503). Please try again in a few minutes."}]
        return [{"msg": f"⚠ Could not connect to Google Sheets: {e}"}]

def get_set_summary(url, set_name):
    """
    Reads the tab for set_name and returns a list of recent expenditures.
    """
    try:
        sh = get_spreadsheet(url)
        target_tab = set_name.upper()
        if "GREENS" in target_tab: target_tab = "GREENS"
        
        try:
            worksheet = sh.worksheet(target_tab)
        except:
            return []
            
        data = worksheet.get_all_values()
        summary = []
        # Expenditure rows usually start after row 9
        if target_tab == "203-T":

            start_row = 11

        elif target_tab == "X99":

            start_row = 48

        else:

            start_row = 8
        
        for row in data[start_row-1:]:
            if len(row) >= 5 and row[2].strip(): # Vendor column
                summary.append({
                    "amount": row[0],
                    "vendor": row[2],
                    "buyer": row[3],
                    "items": row[4],
                    "date": row[11]
                })
        return summary
    except Exception as e:
        print(f"Error fetching summary: {e}")
        return []

def format_rental_date(val) -> str:
    """
    Normalizes a rental end date to 'd-mmm' format (e.g. '27-Nov', '16-Nov', '13-Nov', '2-Oct').
    Day has no leading zero, month is 3-letter title case (e.g. Nov, Dec, Jan).
    """
    if not val or not str(val).strip():
        return ""
    s = str(val).strip()
    
    # Check if already in '13-Nov' or '13-NOV' or '13-nov' format
    m = re.match(r'^(\d{1,2})[-/ ]([a-zA-Z]{3,9})(?:[-/ ]\d{2,4})?$', s)
    if m:
        day = int(m.group(1))
        mon = m.group(2)[:3].capitalize()
        return f"{day}-{mon}"
        
    try:
        from dateutil import parser
        clean_s = s.replace("SEPT", "SEP").replace("sept", "sep")
        dt = parser.parse(clean_s, fuzzy=True)
        return f"{dt.day}-{dt.strftime('%b').capitalize()}"
    except Exception:
        return s

def append_receipt_to_sheet(url, receipt):
    """
    Appends receipt data to the correct tab(s) based on set number.
    Handles splits (e.g., "A01 / A05") by dividing the costs.
    """
    if not url:
        return

    if getattr(receipt, 'is_parking', False) or getattr(receipt, 'expense_only', False):
        print(f"DEBUG: Skipping Google Sheets append for Parking / Expense Only receipt: {getattr(receipt, 'vendor', '')}")
        return

    sh = get_spreadsheet(url)
    
    # Clean and split set numbers (e.g., "A01 / A05" or "A01 & A02")
    raw_sets = re.split(r'[/,&]+|\band\b', str(receipt.set_number), flags=re.IGNORECASE)
    sets = [s.strip() for s in raw_sets if s.strip()]
    if not sets:
        sets = ["Unknown"]
        
    num_sets = len(sets)
    
    rate = getattr(receipt, 'exchange_rate', 1.0) if getattr(receipt, 'is_usd', False) else 1.0
    
    # Calculate split amounts if multiple sets are involved
    split_total = ((receipt.total or 0) * rate) / num_sets
    split_subtotal = ((receipt.subtotal or 0) * rate) / num_sets
    split_shipping = ((receipt.shipping or 0) * rate) / num_sets
    split_import_fees = ((getattr(receipt, 'import_fees', 0) or 0) * rate) / num_sets
    split_tax = ((receipt.tax or 0) * rate) / num_sets
    
    if not getattr(receipt, 'is_asset', False):
        split_subtotal += split_shipping
        split_shipping = 0

    # Invariant: Column A on Set Dec budget tabs is net expenditure before tax.
    # If tax is present, split_subtotal MUST be split_total - split_tax so tax is never included.
    if abs(split_total) > 0.0 and abs(split_tax) > 0.0:
        calc_net = round(split_total - split_tax, 2)
        if abs(calc_net - split_subtotal) > 0.05 or split_subtotal == round(split_total, 2):
            split_subtotal = calc_net

    for set_name in sets:
        # Helper to force uppercase
        def to_caps(val):
            if val is None: return ""
            return str(val).upper()

        # Determine if this entry belongs in the GREENS tab
        is_greens_entry = receipt.is_greens or "GREENS" in set_name.upper()
        
        v_upper = str(receipt.vendor or "").upper()
        d_upper = str(receipt.description or "").upper()
        is_pure_shipping_vendor = any(k in v_upper for k in ["FEDEX", "UPS", "PUROLATOR", "DHL", "COURIER"])

        is_custom_special = False
        if getattr(receipt, 'special_tab', None) and str(receipt.special_tab).strip():
            target_tab = str(receipt.special_tab).strip().upper()
            is_custom_special = True
        elif is_pure_shipping_vendor:
            target_tab = "SHIP"
        else:
            target_tab = "GREENS" if is_greens_entry else set_name.upper()

        # CRITICAL USER DIRECTIVE: Any craft, parking, or fuel/gas receipts must NOT be uploaded to the GREENS Google Sheet tracker
        if target_tab == "GREENS" or is_greens_entry:
            is_craft = bool(getattr(receipt, 'is_craft', False))
            is_parking = bool(getattr(receipt, 'is_parking', False))
            is_gas = bool(getattr(receipt, 'is_gas', False))
            if is_craft or is_parking or is_gas:
                print(f"Skipping GREENS Google Sheets append for receipt {getattr(receipt, 'id', '')} ({receipt.vendor}) because it is Craft/Parking/Gas.")
                continue

        # Episode / Notes Logic
        episode = ""
        orig_set = set_name.upper()
        if is_greens_entry:
            match = re.search(r'(\d+)', set_name)
            if match:
                num = int(match.group(1))
                ep_num = num // 100
                episode = f"EP {ep_num}" if ep_num > 0 else "AMORT"
            elif set_name.upper().startswith('A'):
                episode = "AMORT"
            else:
                episode = "AMORT"
        other_sets = [s.upper() for s in sets if s.upper() != set_name.upper()]
        split_note = f"(SPLIT WITH {', '.join(other_sets)})" if other_sets else ""
        if not split_note:
            m_split = re.search(r'\(\s*SPLIT WITH[^)]*\)', str(receipt.notes or ""), re.IGNORECASE)
            if m_split:
                split_note = m_split.group(0).upper()
                
        # Clean description & user_note so (SPLIT WITH ...) is never in Column E / Description
        clean_desc = re.sub(r'\s*\(\s*SPLIT WITH[^)]*\)', '', receipt.description or "", flags=re.IGNORECASE).strip()
        user_note = re.sub(r'\s*\(\s*SPLIT WITH[^)]*\)', '', receipt.notes or "", flags=re.IGNORECASE).strip()
        user_note = to_caps(user_note)

        is_usd_receipt = getattr(receipt, 'is_usd', False) or "USD" in user_note.upper()
        usd_note = f"CONVERTED FROM USD ({getattr(receipt, 'exchange_rate', 1.0)})" if getattr(receipt, 'is_usd', False) else ""
        # Calculate formatted episode for EXT tab
        ext_epi_str = ""
        is_ext_reroute = False
        if target_tab == "EXT":
            is_ext_reroute = True
            ep_str = str(getattr(receipt, 'episode_code', '')).strip().upper()
            if ep_str in ['297', 'AMORT', 'X']:
                ext_epi_str = "AMORT"
            elif ep_str.isdigit() and 251 <= int(ep_str) <= 276:
                ext_epi_str = f"EP {int(ep_str) - 250}"
            elif len(ep_str) > 0 and 'A' <= ep_str[0] <= 'Z':
                ext_epi_str = f"EP {ord(ep_str[0]) - ord('A') + 1}"
            else:
                m = re.search(r'(\d+)', ep_str)
                if m:
                    ext_epi_str = f"EP {int(m.group(1)) % 100}"
                else:
                    ext_epi_str = ep_str
            
            # Map EXT to prefix98
            m_prefix = re.match(r'^([A-Z]+)', set_name.upper())
            prefix = m_prefix.group(1) if m_prefix else "X"
            target_tab = f"{prefix}98"

        # Check special 98 set rule (e.g. X83 - X98 -> target_tab is X98, special_note is X83)
        from core.set_list import resolve_special_and_initial_set
        sp_info = resolve_special_and_initial_set(
            set_input=set_name,
            special_tab=getattr(receipt, 'special_tab', None),
            notes=getattr(receipt, 'notes', None)
        )
        if sp_info.get("is_special_98"):
            target_tab = sp_info.get("special_set")
            special_note = sp_info.get("initial_set")
        elif target_tab in ["SHIP", "EQUIP", "PROD"] or is_ext_reroute or is_custom_special:
            special_note = set_name.upper()
        else:
            special_note = ""

        # Never put the tab's own set code into the notes column of that tab
        if special_note and special_note.strip().upper() == target_tab.strip().upper():
            special_note = ""

        if target_tab == "203-T":
            epi_val = "253"
            comb = f"{set_name} {str(receipt.notes or '')} {str(receipt.description or '')}".upper()
            if "FANCY" in comb or "RESTAURANT" in comb or "RETAURANT" in comb or "C26" in comb or "INDIAN" in comb or "HAVELI" in comb or "JALI" in comb or "SARIS" in comb or "MAHARANI" in comb:
                special_note = "FANCY RESTAURANT"
            elif "DITTY" in comb:
                special_note = "EXT DITTY LANE"
            elif "POLICE" in comb:
                special_note = "EXT POLICE STATION"
            elif special_note == "UNKNOWN":
                special_note = ""

        # Column Q (Col 16) & Column R (Col 17) Placement Rule:
        note_parts_q = []
        if is_usd_receipt and usd_note:
            note_parts_q.append(usd_note)
        elif not is_usd_receipt and split_note:
            note_parts_q.append(split_note)

        if special_note:
            note_parts_q.append(special_note)
        if user_note:
            if not special_note or special_note.upper() not in user_note.upper():
                note_parts_q.append(user_note)
        col_q_note = " ".join(note_parts_q).strip()

        col_r_note = f"{split_note} {ext_epi_str}".strip() if is_usd_receipt else ext_epi_str.strip()

        row = [""] * 20
        row[0] = round(split_subtotal, 2)
        vendor_val = to_caps(receipt.vendor)
        if vendor_val in ["TGV PROPS", "TGV PROPS INC.", "TGV PROPS INC", "THE PROP ROOM", "TGV"]:
            vendor_val = "TGV PROPS INC. (THE PROP ROOM)"
        row[2] = vendor_val
        b_raw = str(receipt.buyer_name or "").strip().upper()
        if "BRANDT" in b_raw:
            buyer_first_name = "BRANDT"
        elif "MACDOUGA" in b_raw or "MCDOUGA" in b_raw:
            buyer_first_name = "MACDOUGALL"
        elif b_raw.startswith("NICK ") or b_raw == "NICK D" or "DIMAS" in b_raw:
            buyer_first_name = "NICK D"
        else:
            buyer_first_name = str(receipt.buyer_name).split()[0] if receipt.buyer_name and str(receipt.buyer_name).strip() else ""
        row[3] = f"USD ({to_caps(buyer_first_name)})" if getattr(receipt, 'is_usd', False) and buyer_first_name else (("USD") if getattr(receipt, 'is_usd', False) else to_caps(buyer_first_name))
        desc_val = to_caps(clean_desc)
        if getattr(receipt, 'is_rental', False):
            if not desc_val.startswith("RENTAL:"):
                desc_val = f"RENTAL: {desc_val}"
        row[4] = desc_val
        row[5] = "X" if "ch req" in str(receipt.payment_method).lower() else ""
        row[6] = "X" if any(x in str(receipt.payment_method).lower() for x in ["petty", "pc"]) else ""
        row[7] = "X" if any(x in str(receipt.payment_method).lower() for x in ["visa", "mastercard", "credit", "cc", "amex", "american express", "expense", "card"]) else ""
        row[8] = "A" if (getattr(receipt, 'is_asset', False) and not getattr(receipt, 'is_rental', False)) else ""
        row[9] = "X" if ("po" in str(receipt.payment_method).lower() or bool(receipt.po_number and str(receipt.po_number).strip())) else ""
        row[10] = to_caps(receipt.po_number)
        row[11] = to_caps(receipt.date)
        row[12] = to_caps(receipt.reference_number)
        row[13] = "Y" if receipt.is_rental else "N"
        row[14] = format_rental_date(receipt.rental_end_date)
        
        is_craft = bool(getattr(receipt, 'is_craft', False)) or "CRAFT" in (receipt.description or "").upper() or "CRAFT" in (receipt.vendor or "").upper()
        is_parking = bool(getattr(receipt, 'is_parking', False)) or any(k in (receipt.vendor or "").upper() for k in ["PARK", "PRK", "TORPRK", "TPA", "METER", "CITY OF TORONTO"])
        epi_val = "297" if (is_parking or is_craft) else (to_caps(receipt.episode_code) if (receipt.episode_code and str(receipt.episode_code).strip()) else to_caps(episode))

        # OVERRIDE: If target_tab belongs to a specific episode (e.g. B98 -> Ep 2, G14 -> Ep 7), 
        # force epi_val to match the tab's letter so it always goes into the correct Topsheet section!
        m_tab_override = re.match(r'^([A-Z])\d+$', target_tab)
        if m_tab_override:
            override_letter = m_tab_override.group(1).upper()
            if override_letter != 'X':
                ep_num_from_tab = ord(override_letter) - ord('A') + 1
                epi_val = str(250 + ep_num_from_tab)

        if is_greens_entry:
            row[16] = to_caps(orig_set)
            row[17] = epi_val
            full_greens_note = f"{col_q_note} {col_r_note}".strip()
            row[18] = to_caps(full_greens_note)
        else:
            row[16] = to_caps(col_q_note)
            row[17] = to_caps(col_r_note)

        if is_pure_shipping_vendor or target_tab == "SHIP":
            append_to_sectioned_tab(sh, row, set_name, epi_val, receipt, split_subtotal if split_subtotal > 0 else split_total, "SHIP", "FREIGHT")
            continue
            
        if target_tab == "L&D":
            try:
                worksheet = sh.worksheet("L&D")
            except gspread.exceptions.WorksheetNotFound:
                headers = ["DAMAGE COST", "VENDOR", "DESCRIPTION OF DAMAGED", "DATE OF L&D REPORT", "INVOICE OR CLAIM NUMBER", "DATE OF INSURANCE", "SETTLEMENT DATE/FILE CLOSED", "CHEQUE NUMBER", "NOTES", "SET #"]
                worksheet = sh.add_worksheet(title="L&D", rows="1000", cols="20")
                worksheet.append_row(headers)
                
            ld_desc = to_caps(clean_desc)
            if not ld_desc.startswith("L&D:"):
                ld_desc = f"L&D: {ld_desc}".strip()
                
            ld_row = [""] * 10
            ld_row[0] = round(split_subtotal if split_subtotal > 0 else split_total, 2)
            ld_row[1] = to_caps(receipt.vendor)
            ld_row[2] = ld_desc
            ld_row[3] = to_caps(receipt.date)
            ld_row[4] = to_caps(receipt.reference_number)
            ld_row[8] = to_caps(f"{col_q_note} {col_r_note}".strip())
            ld_row[9] = to_caps(set_name)
            
            all_vals = worksheet.get_all_values()
            target_row = len(all_vals) + 1
            for idx in range(1, len(all_vals)):
                r_data = all_vals[idx]
                if not r_data or not any(str(cell).strip() for cell in r_data[:5]):
                    target_row = idx + 1
                    break
            worksheet.insert_row(ld_row, index=target_row, value_input_option='USER_ENTERED')
            continue
        
        try:
            worksheet = sh.worksheet(target_tab)
        except gspread.exceptions.WorksheetNotFound:
            # If the tab doesn't exist, use the standard stylistic tab creator
            from core.settings import load_settings
            url = load_settings().get("spreadsheet_url", "")
            create_tracker_sets_and_tabs(url, epi_val, [{"code": target_tab, "name": f"AMORTIZED SET ({target_tab})", "budget": 0}])
            try:
                worksheet = sh.worksheet(target_tab)
            except gspread.exceptions.WorksheetNotFound:
                # Absolute fallback if creation fails
                headers = ["EXPENDITURE", " ", "VENDOR", "NAME", "DESCRIPTION/ITEMS", "CHQ REQ", "PETTY CASH", "CREDIT CARD", "I/A", "P.O.", "P.O. #", "DATE", "REFERENCE", "RENTAL (Y/N)", "RENTAL END DATE", "CHQ #", "NOTES"]
                worksheet = sh.add_worksheet(title=target_tab, rows="1000", cols=str(len(headers) + 5))
                worksheet.append_row(headers)
            
        # If target tab is EQUIP or X99, route to correct episode section
        if target_tab in ["X99"]:
            append_to_sectioned_tab(sh, row, set_name, epi_val, receipt, split_subtotal if split_subtotal > 0 else split_total, target_tab)
            # Make sure we don't ALSO append it via standard logic below
            # But wait, we still need to process shipping below.
            # Actually, standard logic below appends to target_tab! We should just replace the standard logic for X99 and EQUIP.
            pass
        else:
            # Standard Set Tabs: data entries start 2 rows after EXPENDITURE (leaving 1 spacer) or for 203-T after row 11 (leaving rows 9-10 clean)
            all_vals = worksheet.get_all_values()
            if target_tab == "203-T":

                start_row = 11

            else:

                # Absolute invariant: NOTHING in ANY tab should be put before row 8

                start_row = 8

                for idx, r_data in enumerate(all_vals[:12]):

                    if r_data and any("EXPENDITURE" in str(cell).upper() for cell in r_data[:3]):

                        # If EXPENDITURE header is at row 8, data starts at row 9

                        # If EXPENDITURE header is at row 5, data starts at row 8 (leaving rows 6-7 as header border & spacer)

                        start_row = max(8, idx + 2)

                        break

                start_row = max(8, start_row)

            target_row = max(start_row, len(all_vals) + 1)
            for idx in range(start_row - 1, len(all_vals)):
                r_data = all_vals[idx]
                if not r_data or not any(str(cell).strip() for cell in r_data[:5]):
                    target_row = idx + 1
                    break
                    
            # Batch update Column A and Columns C+ in a single API call
            worksheet.batch_update([
                {'range': f"A{target_row}", 'values': [[row[0]]]},
                {'range': f"C{target_row}", 'values': [row[2:]]}
            ], value_input_option='USER_ENTERED')
            clear_sheet_cache(sh.id)

            if getattr(receipt, 'is_usd', False) or is_usd_receipt or "CONVERTED" in str(col_q_note).upper():

                if is_greens_entry:

                    worksheet.format(f"S{target_row}", {"textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}, "bold": True}})

                else:

                    worksheet.format(f"Q{target_row}", {"textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}, "bold": True}})
            if row[14]:
                try:
                    worksheet.format(f"O{target_row}", {
                        "horizontalAlignment": "CENTER",
                        "numberFormat": {
                            "type": "DATE",
                            "pattern": 'd"-"mmm'
                        }
                    })
                except Exception:
                    pass

        has_freight_in_desc = any(k in d_upper for k in ["FREIGHT", "SHIPPING", "DELIVERY", "IMPORT FEES", "CUSTOMS DUTY"])
        if split_shipping > 0 or split_shipping < 0:
            append_to_sectioned_tab(sh, row, set_name, epi_val, receipt, split_shipping, "SHIP", "FREIGHT")
        elif has_freight_in_desc and not is_pure_shipping_vendor:
            append_to_sectioned_tab(sh, row, set_name, epi_val, receipt, split_subtotal, "SHIP", "FREIGHT")
        if split_import_fees > 0 or split_import_fees < 0:
            append_to_sectioned_tab(sh, row, set_name, epi_val, receipt, split_import_fees, "SHIP", "IMPORT FEES")


def append_to_sectioned_tab(sh, base_row, set_name, episode_code, receipt, amount, target_tab, description_prefix=""):
    """
    Appends an entry to a sectioned tab (e.g. SHIP, X99, EQUIP) by finding the correct episode section.
    """
    try:
        try:
            worksheet = sh.worksheet(target_tab)
        except gspread.exceptions.WorksheetNotFound:
            print(f"{target_tab} tab not found in spreadsheet.")
            return

        all_vals = worksheet.get_all_values()
        ep_str = str(episode_code or "").upper().strip()
        set_str = str(set_name or "").upper().strip()

        # Clean concatenated 297 prefix if followed by an episode number (e.g. '297260' -> '260')
        m_concat = re.match(r'^297(2[56]\d|20\d|210|\d{1,2})$', ep_str)
        if m_concat:
            ep_str = m_concat.group(1)

        # Normalize to find the episode number:
        # In SAMPLE SHOW S1: 260 = Ep 10 (EPISODE 210), 251 = Ep 1 (EPISODE 201), 210 = Ep 10, etc.
        search_terms = []
        if ep_str in ['297', 'AMORT', 'X']:
            search_terms = ['AMORT']
        else:
            ep_num = None
            if len(ep_str) == 1 and 'A' <= ep_str <= 'Z':
                ep_num = ord(ep_str) - ord('A') + 1
            else:
                match = re.search(r'(\d+)', ep_str)
                if match:
                    val = int(match.group(1))
                    if 251 <= val <= 276:
                        ep_num = val - 250   # 260 -> 10 (Ep 210), 251 -> 1 (Ep 201)
                    elif 201 <= val <= 226:
                        ep_num = val - 200   # 210 -> 10, 201 -> 1
                    elif 101 <= val <= 126:
                        ep_num = val - 100
                    elif 1 <= val <= 26:
                        ep_num = val

            if ep_num is not None:
                search_terms = [
                    f'EPISODE 2{ep_num:02d}',
                    f'EPISODE {250 + ep_num}',
                    f'EPISODE {ep_num}',
                    f'EPISODE 1{ep_num:02d}',
                    f'EP 2{ep_num:02d}',
                    f'EP {250 + ep_num}',
                    f'EP {ep_num}',
                    f'EP{ep_num}'
                ]
            else:
                search_terms = ['AMORT']
                
        start_row = -1
        for i, row in enumerate(all_vals):
            row_str = ' '.join(row).upper()
            if any(term in row_str for term in search_terms):
                start_row = i + 1
                break
                
        if start_row == -1:
            for i, row in enumerate(all_vals):
                if 'AMORT' in ' '.join(row).upper():
                    start_row = i + 1
                    break
            if start_row == -1:
                start_row = 8
                
        end_row = len(all_vals)
        for i in range(start_row, len(all_vals)):
            row_str = ' '.join(all_vals[i]).upper()
            if 'EPISODE' in row_str or 'AMORT' in row_str:
                end_row = i
                break
                
        target_row = max(8, start_row + 2)
        for i in range(max(7, start_row), end_row):
            if i < len(all_vals):
                row_data = all_vals[i]
                if not row_data or not any(str(cell).strip() for cell in row_data[:5]):
                    target_row = i + 1
                    break
        else:
            target_row = end_row + 1

        target_row = max(8, target_row)
            
        row_copy = list(base_row)
        row_copy[0] = round(amount, 2)
        if description_prefix:
            desc = str(base_row[4])
            if not desc.upper().startswith(description_prefix.upper()):
                row_copy[4] = f"{description_prefix}: {desc}"
        
        # Ensure row_copy has enough elements to index 16
        while len(row_copy) < 18:
            row_copy.append("")
            
        row_copy[16] = set_str.upper() # Column Q: SET #

        # Write Column A and Columns C to Q in a single batch update call
        worksheet.batch_update([
            {'range': f"A{target_row}", 'values': [[row_copy[0]]]},
            {'range': f"C{target_row}", 'values': [row_copy[2:17]]}
        ], value_input_option='USER_ENTERED')
        clear_sheet_cache(sh.id)

        if getattr(receipt, 'is_usd', False) or "CONVERTED" in str(row_copy[16]).upper():

            worksheet.format(f"Q{target_row}", {"textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}, "bold": True}})
        if row_copy[14]:
            try:
                worksheet.format(f"O{target_row}", {
                    "horizontalAlignment": "CENTER",
                    "numberFormat": {
                        "type": "DATE",
                        "pattern": 'd"-"mmm'
                    }
                })
            except Exception:
                pass

        print(f"Appended {description_prefix} (${amount}) to {target_tab} tab under {search_terms[0]} at Row {target_row} (SET {set_str})")
    except Exception as e:
        print(f"Error appending to SHIP tab: {e}")

def delete_receipt_from_sheet(url, receipt, old_set_number=None):
    if not url: return
    sh = get_spreadsheet(url)
    
    if not old_set_number:
        old_set_number = receipt.set_number
        
    old_sets = [s.strip() for s in str(old_set_number).split('/') if s.strip()]
    if not old_sets: old_sets = ["Unknown"]
    
    num_sets = len(old_sets)
    split_subtotal = (receipt.subtotal or 0) / num_sets
    split_shipping = (receipt.shipping or 0) / num_sets
    split_import_fees = (getattr(receipt, 'import_fees', 0) or 0) / num_sets

    for set_name in old_sets:
        is_greens = receipt.is_greens or "GREENS" in set_name.upper()
        target_tab = "GREENS" if is_greens else set_name.upper()
        try:
            worksheet = sh.worksheet(target_tab)
            data = worksheet.get_all_values()
            
            rows_to_delete = []
            vendor_target = str(receipt.vendor).strip().upper()
            
            for i in range(len(data) - 1, 0, -1):
                row = data[i]
                if len(row) >= 5:
                    row_vendor = str(row[2]).strip().upper()
                    if row_vendor == vendor_target:
                        try:
                            row_amt = float(str(row[0]).replace('$', '').replace(',', '').strip())
                            if abs(row_amt - split_subtotal) < 0.05 or abs(row_amt - split_shipping) < 0.05 or abs(row_amt - split_import_fees) < 0.05:
                                rows_to_delete.append(i + 1)
                        except ValueError:
                            pass
            
            expected_deletions = 1
            if split_shipping > 0 or split_shipping < 0: expected_deletions += 1
            if split_import_fees > 0 or split_import_fees < 0: expected_deletions += 1
            deleted = 0
            for row_idx in rows_to_delete:
                if deleted >= expected_deletions: break
                worksheet.delete_rows(row_idx)
                deleted += 1
                
        except gspread.exceptions.WorksheetNotFound:
            print(f"DEBUG: Tab {target_tab} not found, skipping delete.")
        except Exception as e:
            print(f"DEBUG: Error deleting from {target_tab}: {e}")

def move_receipt_in_sheet(url, receipt, old_set_number):
    if not url: return
    
    # 1. Delete from old sets
    delete_receipt_from_sheet(url, receipt, old_set_number)

    # 2. Append to new sets
    append_receipt_to_sheet(url, receipt)

def revise_po_in_sheet(url, receipt):
    if not url: return
    sh = get_spreadsheet(url)
    
    sets = [s.strip() for s in str(receipt.set_number).split('/') if s.strip()]
    if not sets: sets = ["Unknown"]
    
    num_sets = len(sets)
    rate = getattr(receipt, 'exchange_rate', 1.0) if getattr(receipt, 'is_usd', False) else 1.0
    split_subtotal = ((receipt.subtotal or 0) * rate) / num_sets
    if not getattr(receipt, 'is_asset', False):
        split_subtotal += ((receipt.shipping or 0) * rate) / num_sets

    po_target = str(receipt.po_number).strip().upper()
    if not po_target:
        print("DEBUG: Cannot revise PO without a PO Number.")
        return

    import datetime
    today_str = datetime.datetime.now().strftime("%d-%b-%Y").upper()

    for set_name in sets:
        is_greens = receipt.is_greens or "GREENS" in set_name.upper()
        target_tab = "GREENS" if is_greens else set_name.upper()
        try:
            worksheet = sh.worksheet(target_tab)
            data = worksheet.get_all_values()
            
            for i in range(len(data) - 1, 0, -1):
                row = data[i]
                if len(row) >= 11:
                    row_po = str(row[10]).strip().upper() # Column K (index 10) is P.O. #
                    if row_po == po_target:
                        target_row = i + 1
                        
                        # Batch update Amount, Description, Ref, Rental End, and Notes in a single API call
                        desc = str(receipt.description).upper()
                        ref_num = str(receipt.reference_number).upper() if receipt.reference_number else ""
                        rental_end = format_rental_date(receipt.rental_end_date)
                        notes_col = "S" if is_greens else "Q"
                        existing_notes = str(row[18]) if is_greens and len(row) > 18 else (str(row[16]) if len(row) > 16 else "")
                        new_notes = f"REVISED PO {today_str} {existing_notes}".strip()

                        batch_data = [
                            {"range": f"A{target_row}", "values": [[round(split_subtotal, 2)]]},
                            {"range": f"E{target_row}", "values": [[desc]]},
                            {"range": f"M{target_row}", "values": [[ref_num]]},
                            {"range": f"O{target_row}", "values": [[rental_end]]},
                            {"range": f"{notes_col}{target_row}", "values": [[new_notes]]}
                        ]
                        worksheet.batch_update(batch_data, value_input_option='USER_ENTERED')
                        clear_sheet_cache(sh.id)
                        
                        # Set text color to orange for revision
                        worksheet.format(f"{notes_col}{target_row}", {"textFormat": {"foregroundColor": {"red": 1.0, "green": 0.5, "blue": 0.0}}})
                        if rental_end:
                            try:
                                worksheet.format(f"O{target_row}", {
                                    "horizontalAlignment": "CENTER",
                                    "numberFormat": {
                                        "type": "DATE",
                                        "pattern": 'd"-"mmm'
                                    }
                                })
                            except Exception:
                                pass
                        print(f"DEBUG: Revised PO {po_target} in {target_tab} tab.")
                        break # Only revise the first match per tab
        except gspread.exceptions.WorksheetNotFound:
            print(f"DEBUG: Tab {target_tab} not found, skipping revise.")
        except Exception as e:
            print(f"DEBUG: Error revising PO in {target_tab}: {e}")

def flush_offline_sync_queue(url):
    """
    Attempts to sync all receipts currently held in the offline queue to Google Sheets.
    Returns a dict with 'synced' count, 'remaining' count, and any error message.
    """
    from core.database import get_offline_queue, remove_from_offline_queue
    from core.logic import process_receipt_splits
    
    queued_items = get_offline_queue()
    if not queued_items:
        return {"synced": 0, "remaining": 0, "errors": []}
        
    synced = 0
    errors = []
    
    for item in queued_items:
        queue_id = item['queue_id']
        receipt = item['receipt']
        action = item['action']
        
        if not receipt:
            remove_from_offline_queue(queue_id)
            continue
            
        try:
            if action == 'REVISE':
                revise_po_in_sheet(url, receipt)
            else:
                splits = process_receipt_splits(receipt)
                for split in splits:
                    append_receipt_to_sheet(url, split)
            remove_from_offline_queue(queue_id)
            synced += 1
        except Exception as e:
            errors.append(f"{receipt.vendor} (${receipt.total}): {str(e)}")
            err_str = str(e).lower()
            if any(w in err_str for w in ["oauth2", "getaddrinfo", "connection", "max retries", "timeout"]):
                break

    from core.database import get_offline_queue_count
    remaining = get_offline_queue_count()
    return {"synced": synced, "remaining": remaining, "errors": errors}



def create_new_episode_block_on_topsheet(ws_top, ep_target, num_sets=15):
    """
    Creates a brand-new Episode Block on TRACKER TOPSHEET if it doesn't exist yet,
    including the header, blank set rows, EXPENDABLES, ELECT, SHIP, EQUIP rows,
    and TOTAL row with summary formulas!
    """
    all_vals = ws_top.get_all_values(value_render_option='FORMULA')
    start_r = len(all_vals) + 2

    ep_short = ep_target.replace("EPISODE ", "EP ").strip()
    m_ep = re.search(r'\d+', ep_target)
    ep_digit = m_ep.group(0) if m_ep else "1"

    prefix_code = f"E{ep_digit[-1]} -399" if ep_digit else "EXPENDABLES"

    block_rows = []
    # Row 1: Header row (Col A: EPS xxx, Col B: SET, Col C: '', Col D: EPISODE xxx)
    block_rows.append([ep_short, "SET", "", ep_target, "", "", "", "", "", "", "", ""])

    # Row 2: Standard blank separator row beneath header (matching Episode 205, 206, 207)
    block_rows.append([""] * 12)

    first_set_row = start_r + 2
    last_set_row = start_r + 1 + num_sets
    for _ in range(num_sets):
        block_rows.append([""] * 12)

    expendables_r = last_set_row + 1
    elect_r = last_set_row + 2
    ship_r = last_set_row + 3
    equip_r = last_set_row + 4
    total_r = last_set_row + 5

    # Col A: '', Col B: '', Col C: Code, Col D: Desc, Col E: Spent, Col F: Budget, Col G: Diff, Col H: Pct, Col I: '', Col J: ''
    block_rows.append(["", "", "X99", "EXPENDABLES / SUPPLIES", "=INDIRECT('X99'!A5)", "", f"=SUM(F{expendables_r}-E{expendables_r})", f'=IFERROR(E{expendables_r}/F{expendables_r}, "")', "", ""])
    block_rows.append(["", "", "ELECT", "WIREPERSON ", "=INDIRECT('ELECT'!A2)", "", f"=SUM(F{elect_r}-E{elect_r})", f'=IFERROR(E{elect_r}/F{elect_r}, "")', "", ""])
    block_rows.append(["", "", "SHIP", "SHIPPING", "=INDIRECT('SHIP'!A2)", "", f"=SUM(F{ship_r}-E{ship_r})", f'=IFERROR(E{ship_r}/F{ship_r}, "")', "", ""])
    block_rows.append(["", "", "EQUIP", "HEAVY EQUIPMENT", "=INDIRECT('EQUIP'!A2)", "", f"=SUM(F{equip_r}-E{equip_r})", f'=IFERROR(E{equip_r}/F{equip_r}, "")', "", ""])

    tot_spent = f"=SUM(E{first_set_row}:E{equip_r})"
    tot_budget = f"=SUM(F{first_set_row}:F{equip_r})"
    tot_diff = f"=SUM(F{total_r}-E{total_r})"
    tot_pct = f"=IFERROR(E{total_r}/F{total_r}, 0)"

    block_rows.append(["", "TOTAL", "", ep_target, tot_spent, tot_budget, tot_diff, tot_pct, "", ""])

    ws_top.append_rows(block_rows, value_input_option='USER_ENTERED')

    # Format the entire new episode block with Century Gothic 14pt, number formats, and borders
    try:
        sh_obj = ws_top.spreadsheet
        b_solid = {'style': 'SOLID', 'width': 1, 'color': {'red': 0, 'green': 0, 'blue': 0}}
        b_all = {'top': b_solid, 'bottom': b_solid, 'left': b_solid, 'right': b_solid}
        blk_fmt = []
        
        # 1. Set rows & special rows: Col C (Center), Col D (Left), Col E-G (Right, #,##0.00), Col H (Right, 0.00%)
        blk_fmt.append({
            'repeatCell': {
                'range': {'sheetId': ws_top.id, 'startRowIndex': first_set_row - 1, 'endRowIndex': equip_r, 'startColumnIndex': 2, 'endColumnIndex': 3},
                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': True}, 'horizontalAlignment': 'CENTER', 'borders': b_all}},
                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
            }
        })
        blk_fmt.append({
            'repeatCell': {
                'range': {'sheetId': ws_top.id, 'startRowIndex': first_set_row - 1, 'endRowIndex': equip_r, 'startColumnIndex': 3, 'endColumnIndex': 4},
                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': False}, 'numberFormat': {'type': 'TEXT'}, 'horizontalAlignment': 'LEFT', 'borders': b_all}},
                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
            }
        })
        blk_fmt.append({
            'repeatCell': {
                'range': {'sheetId': ws_top.id, 'startRowIndex': first_set_row - 1, 'endRowIndex': equip_r, 'startColumnIndex': 4, 'endColumnIndex': 7},
                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': False}, 'numberFormat': {'type': 'NUMBER', 'pattern': '#,##0.00'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
            }
        })
        blk_fmt.append({
            'repeatCell': {
                'range': {'sheetId': ws_top.id, 'startRowIndex': first_set_row - 1, 'endRowIndex': equip_r, 'startColumnIndex': 7, 'endColumnIndex': 8},
                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': False}, 'numberFormat': {'type': 'PERCENT', 'pattern': '0.00%'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
            }
        })
        # 2. TOTAL row: Century Gothic 14pt Bold
        tot_idx = total_r - 1
        blk_fmt.append({
            'repeatCell': {
                'range': {'sheetId': ws_top.id, 'startRowIndex': tot_idx, 'endRowIndex': tot_idx + 1, 'startColumnIndex': 1, 'endColumnIndex': 4},
                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': True}, 'borders': b_all}},
                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.borders'
            }
        })
        blk_fmt.append({
            'repeatCell': {
                'range': {'sheetId': ws_top.id, 'startRowIndex': tot_idx, 'endRowIndex': tot_idx + 1, 'startColumnIndex': 4, 'endColumnIndex': 7},
                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': True}, 'numberFormat': {'type': 'NUMBER', 'pattern': '#,##0.00'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
            }
        })
        blk_fmt.append({
            'repeatCell': {
                'range': {'sheetId': ws_top.id, 'startRowIndex': tot_idx, 'endRowIndex': tot_idx + 1, 'startColumnIndex': 7, 'endColumnIndex': 8},
                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': True}, 'numberFormat': {'type': 'PERCENT', 'pattern': '0.00%'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
            }
        })
        sh_obj.batch_update({'requests': blk_fmt})
    except Exception as blk_err:
        print(f"DEBUG: Failed to format new episode block: {blk_err}")

    return start_r, expendables_r

def create_tracker_sets_and_tabs(url, episode_name, set_items, default_budget=None):
    """
    Automates creating new set lines on TRACKER TOPSHEET and individual Set Tabs.
    - episode_name: e.g. "EPISODE 204" or "EPISODE 203" or "EPISODE 4"
    - set_items: list of dicts [{"code": "D10", "name": "INT NORTHGATE INDUSTRIES", "budget": 5000}, ...]
    """
    if not url or not set_items:
        return {"status": "error", "message": "Missing spreadsheet URL or set items"}

    sh = get_spreadsheet(url)
    ws_top = sh.worksheet("TRACKER TOPSHEET")
    all_top_vals = ws_top.get_all_values(value_render_option='FORMULA')

    # Normalize episode section name
    ep_target = str(episode_name).upper().strip()
    if "EPISODE" not in ep_target and "EP" not in ep_target and "AMORT" not in ep_target:
        ep_target = f"EPISODE {ep_target}"

    ep_num_match = re.search(r'\d+', ep_target)
    ep_num = ep_num_match.group(0) if ep_num_match else ""
    
    search_terms = []
    if "AMORT" in ep_target or "297" in ep_target or "X" == ep_target.strip():
        search_terms = ["AMORT"]
    elif ep_num:
        raw_num = int(ep_num)
        if 251 <= raw_num <= 276:
            base_num = raw_num - 250
        else:
            base_num = raw_num % 100
        search_terms = [f"EPISODE {base_num}", f"EPISODE 1{base_num:02d}", f"EPISODE 2{base_num:02d}", f"EP {base_num}"]
    else:
        search_terms = [ep_target]

    # Locate Episode section header row
    header_row_idx = None
    expendables_row_idx = None
    
    for i, row in enumerate(all_top_vals):
        row_str = " ".join([str(c).upper() for c in row if str(c).strip()])
        is_match = any(term in row_str for term in search_terms)

        if not header_row_idx and is_match:
            header_row_idx = i + 1
        elif header_row_idx and not expendables_row_idx:
            if "EXPENDABLES" in row_str or "WIREPERSON" in row_str or "TOTAL" in row_str:
                expendables_row_idx = i + 1

    if not header_row_idx:
        # Automatically create the entire new Episode Block at the bottom of TRACKER TOPSHEET
        header_row_idx, expendables_row_idx = create_new_episode_block_on_topsheet(ws_top, ep_target, max(15, len(set_items)))
        # Re-fetch values after block creation
        all_top_vals = ws_top.get_all_values(value_render_option='FORMULA')

    if not expendables_row_idx:
        expendables_row_idx = len(all_top_vals)

    # Available blank rows between header and EXPENDABLES
    # Check if header_row_idx + 1 is a standard blank separator row beneath the header
    has_separator_row = False
    if header_row_idx < len(all_top_vals):
        sep_row_data = all_top_vals[header_row_idx]
        if not any(str(c).strip() for c in sep_row_data):
            has_separator_row = True

    start_search_row = header_row_idx + 2 if has_separator_row else header_row_idx + 1
    end_search_row = expendables_row_idx - 1
    
    blank_row_indices = []
    for r_num in range(start_search_row, end_search_row + 1):
        idx = r_num - 1
        row_data = all_top_vals[idx] if idx < len(all_top_vals) else []
        if not any(str(c).strip() for c in row_data):
            blank_row_indices.append(r_num)

    needed_count = len(set_items)
    available_blank_count = len(blank_row_indices)

    # Insert extra rows if needed right before EXPENDABLES / SUPPLIES
    if needed_count > available_blank_count:
        extra_rows_needed = needed_count - available_blank_count
        insert_at_row = expendables_row_idx
        ws_top.insert_rows([[""] * 15] * extra_rows_needed, row=insert_at_row, value_input_option='USER_ENTERED')
        
        # Explicitly copy formatting from the row ABOVE the insertion to prevent inheriting from below
        # insert_at_row is 1-indexed. The row above is insert_at_row - 1.
        # Its index is insert_at_row - 2.
        copy_fmt_req = [{
            'copyPaste': {
                'source': {
                    'sheetId': ws_top.id,
                    'startRowIndex': insert_at_row - 2,
                    'endRowIndex': insert_at_row - 1,
                    'startColumnIndex': 1,
                    'endColumnIndex': 16
                },
                'destination': {
                    'sheetId': ws_top.id,
                    'startRowIndex': insert_at_row - 1,
                    'endRowIndex': insert_at_row - 1 + extra_rows_needed,
                    'startColumnIndex': 1,
                    'endColumnIndex': 16
                },
                'pasteType': 'PASTE_FORMAT'
            }
        }]
        sh.batch_update({'requests': copy_fmt_req})
        
        # Re-fetch values after row insertion
        all_top_vals = ws_top.get_all_values(value_render_option='FORMULA')
        
        blank_row_indices = []
        for r_num in range(start_search_row, end_search_row + extra_rows_needed + 1):
            idx = r_num - 1
            row_data = all_top_vals[idx] if idx < len(all_top_vals) else []
            if not any(str(c).strip() for c in row_data):
                blank_row_indices.append(r_num)

    import time

    all_ws = sh.worksheets()
    ws_map = {w.title: w.id for w in all_ws}
    all_ws_titles = [w.title for w in all_ws]

    # Find a template set tab (e.g. C31, C32) to copy visual formatting from
    template_sheet_id = None
    for tmpl_name in ['C31', 'C32', 'C10', 'B24', 'A10', 'X80']:
        if tmpl_name in ws_map:
            template_sheet_id = ws_map[tmpl_name]
            break

    PROTECTED_TABS = {"GREENS", "PROD", "SHIP", "ELECT", "TRANS", "EQUIP", "SECURITY DEPOSITS", "L&D", "X99", "X80", "X81", "X82", "X83", "X84", "X85", "X86"}

    created_tabs = []
    
    # Ensure all Set Tabs exist in correct tab order so we have GIDs for hyperlinks
    for idx_item, item in enumerate(set_items):
        set_code = str(item.get("code", "")).strip().upper()
        if not set_code or set_code in PROTECTED_TABS:
            continue
        if set_code not in ws_map:
            insert_idx = None
            for prev_item in reversed(set_items[:idx_item]):
                prev_code = str(prev_item.get("code", "")).strip().upper()
                if prev_code in all_ws_titles:
                    insert_idx = all_ws_titles.index(prev_code) + 1
                    break

            for attempt in range(4):
                try:
                    if insert_idx is not None:
                        ws_set = sh.add_worksheet(title=set_code, rows="28", cols="20", index=insert_idx)
                        all_ws_titles.insert(insert_idx, set_code)
                    else:
                        ws_set = sh.add_worksheet(title=set_code, rows="28", cols="20")
                        all_ws_titles.append(set_code)
                    ws_map[set_code] = ws_set.id
                    created_tabs.append(set_code)
                    
                    # Copy visual formatting & exact column/row dimensions from saved template.json
                    dim_requests = []
                    import os, json
                    template_path = os.path.join(os.path.dirname(__file__), 'template.json')
                    if os.path.exists(template_path):
                        with open(template_path, 'r') as f:
                            template_data = json.load(f)
                        
                        # 1. Apply formatting via updateCells
                        dim_requests.append({
                            'updateCells': {
                                'rows': template_data.get('rowData', []),
                                'fields': 'userEnteredFormat,dataValidation',
                                'start': {
                                    'sheetId': ws_set.id,
                                    'rowIndex': 0,
                                    'columnIndex': 0
                                }
                            }
                        })
                        
                        # 2. Apply column widths
                        for c_idx, col in enumerate(template_data.get('columnMetadata', [])):
                            if 'pixelSize' in col:
                                dim_requests.append({
                                    'updateDimensionProperties': {
                                        'range': {'sheetId': ws_set.id, 'dimension': 'COLUMNS', 'startIndex': c_idx, 'endIndex': c_idx + 1},
                                        'properties': {'pixelSize': col['pixelSize']},
                                        'fields': 'pixelSize'
                                    }
                                })
                                
                        # 3. Apply row heights
                        for r_idx, row in enumerate(template_data.get('rowMetadata', [])):
                            if 'pixelSize' in row:
                                dim_requests.append({
                                    'updateDimensionProperties': {
                                        'range': {'sheetId': ws_set.id, 'dimension': 'ROWS', 'startIndex': r_idx, 'endIndex': r_idx + 1},
                                        'properties': {'pixelSize': row['pixelSize']},
                                        'fields': 'pixelSize'
                                    }
                                })
                                
                        # 4. Apply merges
                        for merge in template_data.get('merges', []):
                            # The sheetId in the saved merge is from the template, we must override it with the new sheetId
                            new_range = merge.copy()
                            new_range['sheetId'] = ws_set.id
                            dim_requests.append({
                                'mergeCells': {
                                    'range': new_range,
                                    'mergeType': 'MERGE_ALL'
                                }
                            })
                            
                        # 5. Apply conditional formatting
                        for rule in template_data.get('conditionalFormats', []):
                            import copy
                            new_rule = copy.deepcopy(rule)
                            for r in new_rule.get('ranges', []):
                                r['sheetId'] = ws_set.id
                            dim_requests.append({
                                'addConditionalFormatRule': {
                                    'rule': new_rule,
                                    'index': 0
                                }
                            })
                    else:
                        print("Warning: template.json not found, skipping visual formatting.")


                    # Explicitly enforce Calibri 18pt Bold for A1:B1 (Set Code & Set Name)
                    dim_requests.append({
                        'repeatCell': {
                            'range': {
                                'sheetId': ws_set.id,
                                'startRowIndex': 0,
                                'endRowIndex': 1,
                                'startColumnIndex': 0,
                                'endColumnIndex': 2
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'textFormat': {
                                        'fontFamily': 'Calibri',
                                        'fontSize': 18,
                                        'bold': True
                                    }
                                }
                            },
                            'fields': 'userEnteredFormat.textFormat'
                        }
                    })

                    # Automatically merge cells B1:E1 for Set Name (excluding SHIP and ELECT)
                    if set_code not in ["SHIP", "ELECT", "SHIPPING", "WIREPERSON"]:
                        dim_requests.append({
                            'mergeCells': {
                                'range': {
                                    'sheetId': ws_set.id,
                                    'startRowIndex': 0,
                                    'endRowIndex': 1,
                                    'startColumnIndex': 1,
                                    'endColumnIndex': 5
                                },
                                'mergeType': 'MERGE_ALL'
                            }
                        })

                    if dim_requests:
                        try:
                            sh.batch_update({'requests': dim_requests})
                        except Exception as fmt_err:
                            print(f"DEBUG: Dimension/format copy error on {set_code}: {fmt_err}")

                    time.sleep(1.0)
                    break
                except gspread.exceptions.APIError as e:
                    if '429' in str(e):
                        time.sleep(5)
                    else:
                        break

    updated_rows = []
    batch_data = []

    # Collect all set codes already present in this section on the topsheet to enforce
    # the invariant: exactly ONE spent number per set number.
    placed_set_codes = set()
    for idx in range(start_search_row - 1, min(end_search_row, len(all_top_vals))):
        row_data = all_top_vals[idx] if idx < len(all_top_vals) else []
        if len(row_data) > 2:
            cell_c = str(row_data[2]).strip().upper()
            m_code = re.search(r'\b([A-Z]\d{1,3}|\d{3})\b', cell_c)
            if m_code:
                placed_set_codes.add(m_code.group(1).upper())


    # Process each set item and prepare batch payload with HYPERLINK formulas for Topsheet
    for i, item in enumerate(set_items):
        set_code = str(item.get("code", "")).strip().upper()
        set_name = str(item.get("name", "")).strip().upper()
        budget_val = item.get("budget", default_budget)
        
        if not set_code:
            continue

        gid = ws_map.get(set_code)

        # Check if set_code already exists on the topsheet to prevent duplicates
        already_exists = False
        for idx in range(start_search_row - 1, min(end_search_row, len(all_top_vals))):
            row_data = all_top_vals[idx] if idx < len(all_top_vals) else []
            if len(row_data) > 2 and set_code in str(row_data[2]).upper():
                already_exists = True
                updated_rows.append((idx + 1, set_code, set_name))
                if gid:
                    batch_data.append({
                        'range': f"C{idx + 1}:C{idx + 1}",
                        'values': [[f'=HYPERLINK("#gid={gid}", "{set_code}")']]
                    })
                break
        
        if already_exists:
            print(f"Skipping Topsheet insertion for {set_code} because it already exists (updating hyperlink & format).")
            continue

        target_row_num = blank_row_indices.pop(0) if blank_row_indices else (start_search_row + len(updated_rows))

        # INVARIANT: Exactly ONE spent number per set number!
        # If this set code was already placed (e.g. multi-scene set like J14 or J17),
        # only add the sub-scene description; NEVER duplicate the spent formula in Column E!
        if set_code in placed_set_codes:
            row_vals = ["", set_name, "", "", "", "", "", ""]
            batch_data.append({
                'range': f"C{target_row_num}:J{target_row_num}",
                'values': [row_vals]
            })
            updated_rows.append((target_row_num, "", set_name))
            continue

        placed_set_codes.add(set_code)

        
        if gid:
            c_entry = f'=HYPERLINK("#gid={gid}", "{set_code}")'
        else:
            c_entry = set_code

        spent_formula = f'=INDIRECT("\'"&"{set_code}"&"\'!A$2")'
        diff_formula = f'=SUM(F{target_row_num}-E{target_row_num})'
        pct_formula = f'=IFERROR(E{target_row_num}/F{target_row_num}, "")'
        b_entry = budget_val if (budget_val is not None and str(budget_val).strip() != "") else ""

        # Col C: Code, Col D: Name, Col E: Spent, Col F: Budget, Col G: Diff, Col H: Pct, Col I: "", Col J: ""
        row_vals = [c_entry, set_name, spent_formula, b_entry, diff_formula, pct_formula, "", ""]
        batch_data.append({
            'range': f"C{target_row_num}:J{target_row_num}",
            'values': [row_vals]
        })
        updated_rows.append((target_row_num, set_code, set_name))

    # Executing 1 single batch call for all Topsheet rows
    if batch_data:
        for attempt in range(5):
            try:
                ws_top.batch_update(batch_data, value_input_option='USER_ENTERED')
                break
            except gspread.exceptions.APIError as e:
                if '429' in str(e):
                    time.sleep(5 * (attempt + 1))
                else:
                    raise
                    
        # Apply comprehensive styling: Century Gothic 14pt across all numbers and cells, solid borders, and proper number formatting
        fmt_requests = []
        b_solid = {'style': 'SOLID', 'width': 1, 'color': {'red': 0, 'green': 0, 'blue': 0}}
        b_all = {'top': b_solid, 'bottom': b_solid, 'left': b_solid, 'right': b_solid}
        
        for r_num, set_c, _ in updated_rows:
            r_idx = r_num - 1
            gid = ws_map.get(set_c) if set_c else None
            
            # 1. Column C (index 2): Set Code
            if set_c and gid:
                fmt_requests.append({
                    'repeatCell': {
                        'range': {'sheetId': ws_top.id, 'startRowIndex': r_idx, 'endRowIndex': r_idx + 1, 'startColumnIndex': 2, 'endColumnIndex': 3},
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'fontFamily': 'Century Gothic',
                                    'fontSize': 14,
                                    'bold': True,
                                    'underline': True,
                                    'foregroundColor': {'red': 0.015686275, 'green': 0.38431373, 'blue': 0.75686276},
                                    'link': {'uri': f'#gid={gid}'}
                                },
                                'horizontalAlignment': 'CENTER',
                                'hyperlinkDisplayType': 'LINKED',
                                'borders': b_all
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat,userEnteredFormat.hyperlinkDisplayType,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                    }
                })
            else:
                fmt_requests.append({
                    'repeatCell': {
                        'range': {'sheetId': ws_top.id, 'startRowIndex': r_idx, 'endRowIndex': r_idx + 1, 'startColumnIndex': 2, 'endColumnIndex': 3},
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'fontFamily': 'Century Gothic',
                                    'fontSize': 14,
                                    'bold': True if set_c else False,
                                    'underline': False,
                                    'foregroundColor': {'red': 0.18, 'green': 0.34, 'blue': 0.58} if set_c else {'red': 0, 'green': 0, 'blue': 0}
                                },
                                'horizontalAlignment': 'CENTER',
                                'borders': b_all
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                    }
                })

            # 2. Column D (index 3): Set Description (Century Gothic 14pt, Left, TEXT)
            fmt_requests.append({
                'repeatCell': {
                    'range': {'sheetId': ws_top.id, 'startRowIndex': r_idx, 'endRowIndex': r_idx + 1, 'startColumnIndex': 3, 'endColumnIndex': 4},
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {
                                'fontFamily': 'Century Gothic',
                                'fontSize': 14,
                                'bold': False,
                                'foregroundColor': {'red': 0.0, 'green': 0.0, 'blue': 0.0}
                            },
                            'numberFormat': {'type': 'TEXT'},
                            'horizontalAlignment': 'LEFT',
                            'borders': b_all
                        }
                    },
                    'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                }
            })

            # 3. Columns E, F, G (indices 4, 5, 6): Numbers (Spent, Budget, Diff) - Century Gothic 14pt Right #,##0.00
            fmt_requests.append({
                'repeatCell': {
                    'range': {'sheetId': ws_top.id, 'startRowIndex': r_idx, 'endRowIndex': r_idx + 1, 'startColumnIndex': 4, 'endColumnIndex': 7},
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {
                                'fontFamily': 'Century Gothic',
                                'fontSize': 14,
                                'bold': False,
                                'foregroundColor': {'red': 0.0, 'green': 0.0, 'blue': 0.0}
                            },
                            'numberFormat': {'type': 'NUMBER', 'pattern': '#,##0.00'},
                            'horizontalAlignment': 'RIGHT',
                            'borders': b_all
                        }
                    },
                    'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                }
            })

            # 4. Column H (index 7): Percentage (%) - Century Gothic 14pt Right 0.00%
            fmt_requests.append({
                'repeatCell': {
                    'range': {'sheetId': ws_top.id, 'startRowIndex': r_idx, 'endRowIndex': r_idx + 1, 'startColumnIndex': 7, 'endColumnIndex': 8},
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {
                                'fontFamily': 'Century Gothic',
                                'fontSize': 14,
                                'bold': False,
                                'foregroundColor': {'red': 0.0, 'green': 0.0, 'blue': 0.0}
                            },
                            'numberFormat': {'type': 'PERCENT', 'pattern': '0.00%'},
                            'horizontalAlignment': 'RIGHT',
                            'borders': b_all
                        }
                    },
                    'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                }
            })

            # 5. Columns I, J (indices 8, 9): Century Gothic 11pt Left
            fmt_requests.append({
                'repeatCell': {
                    'range': {'sheetId': ws_top.id, 'startRowIndex': r_idx, 'endRowIndex': r_idx + 1, 'startColumnIndex': 8, 'endColumnIndex': 10},
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {
                                'fontFamily': 'Century Gothic',
                                'fontSize': 11,
                                'bold': False,
                            },
                            'horizontalAlignment': 'LEFT',
                            'borders': b_all
                        }
                    },
                    'fields': 'userEnteredFormat.textFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                }
            })

        # Also ensure standard special rows (X99, ELECT, SHIP, EQUIP) in this episode section are formatted and hyperlinked
        for spec_code in ["X99", "ELECT", "SHIP", "EQUIP"]:
            spec_gid = ws_map.get(spec_code)
            if expendables_row_idx:
                for check_r in range(expendables_row_idx, min(expendables_row_idx + 6, len(all_top_vals) + 1)):
                    idx_c = check_r - 1
                    row_c = all_top_vals[idx_c] if idx_c < len(all_top_vals) else []
                    if len(row_c) > 2 and spec_code == str(row_c[2]).strip().upper():
                        if spec_gid:
                            fmt_requests.append({
                                'repeatCell': {
                                    'range': {'sheetId': ws_top.id, 'startRowIndex': idx_c, 'endRowIndex': idx_c + 1, 'startColumnIndex': 2, 'endColumnIndex': 3},
                                    'cell': {
                                        'userEnteredFormat': {
                                            'textFormat': {
                                                'fontFamily': 'Century Gothic',
                                                'fontSize': 14,
                                                'bold': True,
                                                'underline': True,
                                                'foregroundColor': {'red': 0.015686275, 'green': 0.38431373, 'blue': 0.75686276},
                                                'link': {'uri': f'#gid={spec_gid}'}
                                            },
                                            'horizontalAlignment': 'CENTER',
                                            'hyperlinkDisplayType': 'LINKED',
                                            'borders': b_all
                                        }
                                    },
                                    'fields': 'userEnteredFormat.textFormat,userEnteredFormat.hyperlinkDisplayType,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                                }
                            })
                        fmt_requests.append({
                            'repeatCell': {
                                'range': {'sheetId': ws_top.id, 'startRowIndex': idx_c, 'endRowIndex': idx_c + 1, 'startColumnIndex': 4, 'endColumnIndex': 7},
                                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': False}, 'numberFormat': {'type': 'NUMBER', 'pattern': '#,##0.00'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                            }
                        })
                        fmt_requests.append({
                            'repeatCell': {
                                'range': {'sheetId': ws_top.id, 'startRowIndex': idx_c, 'endRowIndex': idx_c + 1, 'startColumnIndex': 7, 'endColumnIndex': 8},
                                'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': False}, 'numberFormat': {'type': 'PERCENT', 'pattern': '0.00%'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                                'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                            }
                        })
                        break

        # Also format TOTAL row of this episode block
        if expendables_row_idx:
            for check_r in range(expendables_row_idx + 1, min(expendables_row_idx + 8, len(all_top_vals) + 1)):
                idx_c = check_r - 1
                row_c = all_top_vals[idx_c] if idx_c < len(all_top_vals) else []
                if len(row_c) > 1 and "TOTAL" in str(row_c[1]).strip().upper():
                    first_r = updated_rows[0][0] if updated_rows else (start_search_row)
                    last_exp_r = idx_c # 1 row above total
                    # Update formulas on Total row if needed
                    ws_top.update(values=[[f'=sum(E{first_r}:E{last_exp_r})', f'=sum(F{first_r}:F{last_exp_r})', f'=SUM(F{check_r}-E{check_r})', f'=IFERROR(E{check_r}/F{check_r}, 0)']], range_name=f'E{check_r}:H{check_r}', value_input_option='USER_ENTERED')
                    fmt_requests.append({
                        'repeatCell': {
                            'range': {'sheetId': ws_top.id, 'startRowIndex': idx_c, 'endRowIndex': idx_c + 1, 'startColumnIndex': 1, 'endColumnIndex': 4},
                            'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': True}, 'borders': b_all}},
                            'fields': 'userEnteredFormat.textFormat,userEnteredFormat.borders'
                        }
                    })
                    fmt_requests.append({
                        'repeatCell': {
                            'range': {'sheetId': ws_top.id, 'startRowIndex': idx_c, 'endRowIndex': idx_c + 1, 'startColumnIndex': 4, 'endColumnIndex': 7},
                            'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': True}, 'numberFormat': {'type': 'NUMBER', 'pattern': '#,##0.00'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                            'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                        }
                    })
                    fmt_requests.append({
                        'repeatCell': {
                            'range': {'sheetId': ws_top.id, 'startRowIndex': idx_c, 'endRowIndex': idx_c + 1, 'startColumnIndex': 7, 'endColumnIndex': 8},
                            'cell': {'userEnteredFormat': {'textFormat': {'fontFamily': 'Century Gothic', 'fontSize': 14, 'bold': True}, 'numberFormat': {'type': 'PERCENT', 'pattern': '0.00%'}, 'horizontalAlignment': 'RIGHT', 'borders': b_all}},
                            'fields': 'userEnteredFormat.textFormat,userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.borders'
                        }
                    })
                    break

        if fmt_requests:
            try:
                sh.batch_update({'requests': fmt_requests})
            except Exception as e:
                print(f"DEBUG: Failed to format new topsheet rows: {e}")


    # Format individual Set Tabs
    for i, item in enumerate(set_items):
        set_code = str(item.get("code", "")).strip().upper()
        set_name = str(item.get("name", "")).strip().upper()
        if not set_code:
            continue

        target_matches = [r[0] for r in updated_rows if r[1] == set_code]
        if not target_matches:
            continue
        r_num = target_matches[0]

        for attempt in range(5):
            try:
                ws_set = sh.worksheet(set_code)
                tab_formulas = [
                    [set_code, set_name],
                    ["=SUM(A8:A)", "", "Total"],
                    [f"='TRACKER TOPSHEET'!F{r_num}", "", '=HYPERLINK("#gid=402774554","Budget")'],
                    ["=A2/A3", "=SUM(A3-A2)", "Variance"],
                    ["EXPENDITURE", " ", "VENDOR", "NAME", "DESCRIPTION/ITEMS", "CHQ REQ", "PETTY CASH", "CREDIT CARD", "I/A", "P.O.", "P.O. #", "DATE", "REFERENCE", "RENTAL (Y/N)", "RENTAL END DATE", "CHQ #", "NOTES"]
                ]
                
                ws_set.update(values=tab_formulas, range_name="A1:Q5", value_input_option='USER_ENTERED')
                time.sleep(0.3)
                break
            except gspread.exceptions.APIError as e:
                if '429' in str(e):
                    time.sleep(5)
                else:
                    raise

    return {
        "status": "success",
        "created_tabs": created_tabs,
        "updated_rows_count": len(updated_rows),
        "message": f"Successfully updated {len(updated_rows)} set lines on Topsheet and created {len(created_tabs)} new Set Tabs!"
    }

def get_cost_report_data(url):
    if not url:
        return {"status": "error", "message": "No Google Sheets URL configured."}
        
    try:
        sh = get_spreadsheet(url)
        try:
            worksheet = sh.worksheet("TRACKER TOPSHEET")
        except:
            worksheet = sh.get_worksheet(1)
            
        # Fetch values and format metadata to accurately detect inserts/reshoots and highlighted rows
        res_meta = sh.client.request('get', f'https://sheets.googleapis.com/v4/spreadsheets/{sh.id}?ranges=TRACKER%20TOPSHEET!A1:H350&fields=sheets.data.rowData.values(formattedValue,userEnteredFormat.backgroundColor)')
        rows_data = res_meta.json()['sheets'][0]['data'][0].get('rowData', [])
        
        report_rows = []
        current_section_items = []
        
        for i_row, rd in enumerate(rows_data):
            vals = rd.get('values', [])
            r_formatted = [v.get('formattedValue', '') for v in vals]
            if len(r_formatted) < 5:
                continue
            
            is_total_row = False
            for i in range(min(3, len(r_formatted))):
                if str(r_formatted[i]).strip().upper() == "TOTAL":
                    is_total_row = True
                    break
            
            if is_total_row:
                category = str(r_formatted[3]).strip() if len(r_formatted) > 3 else ""
                if not category:
                    current_section_items = []
                    continue
                    
                if category.upper() in ["AMORT / EPS / WRAP", "NOT IN BUGET"]:
                    current_section_items = []
                    continue
                    
                try:
                    spent_str = str(r_formatted[4]).replace("$", "").replace(",", "").strip() if len(r_formatted) > 4 else ""
                    spent = float(spent_str) if spent_str else 0.0
                except ValueError:
                    spent = 0.0
                    
                try:
                    budget_str = str(r_formatted[5]).replace("$", "").replace(",", "").strip() if len(r_formatted) > 5 else ""
                    budget = float(budget_str) if budget_str else 0.0
                except ValueError:
                    budget = 0.0
                    
                try:
                    var_str = str(r_formatted[6]).replace("$", "").replace(",", "").strip() if len(r_formatted) > 6 else ""
                    variance = float(var_str) if var_str else 0.0
                except ValueError:
                    variance = 0.0
                    
                try:
                    efc_str = str(r_formatted[7]).replace("$", "").replace(",", "").strip() if len(r_formatted) > 7 else ""
                    efc = float(efc_str) if efc_str else 0.0
                except ValueError:
                    efc = 0.0
                    
                if category.upper().strip() == "STANDING SETS" or category.upper().strip() == "AMORT":
                    category = "AMORT - W/ EXTENDED RENTALS"

                # Load from local cache if available
                import os, json
                cache_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "efc_cache.json")
                cached_val = None
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, "r") as f:
                            cache_data = json.load(f)
                        if category in cache_data:
                            cached_val = float(cache_data[category])
                        elif "AMORT" in cache_data and category == "AMORT - W/ EXTENDED RENTALS":
                            cached_val = float(cache_data["AMORT"])
                    except:
                        pass
                        
                if cached_val is not None:
                    efc = cached_val
                elif efc == 0:
                    efc = max(budget, spent)
                else:
                    efc = max(efc, spent)
                
                if budget == 0 and spent == 0 and efc == 0:
                    current_section_items = []
                    continue
                    
                # Collect any breakdown rows (inserts / reshoots) for this section
                breakdowns = list(current_section_items)
                current_section_items = []
                    
                report_rows.append({
                    "Episode": category,
                    "Budget": budget,
                    "Total Spent": spent,
                    "Variance (Savings)": variance,
                    "Projected Final Amount": efc,
                    "sheet_row": i_row + 1,
                    "breakdowns": breakdowns
                })
            else:
                # Check for individual set lines in this section that are inserts / reshoots
                if len(vals) > 4:
                    code = vals[2].get('formattedValue', '').strip()
                    desc = vals[3].get('formattedValue', '').strip()
                    spent_s = vals[4].get('formattedValue', '').strip() if len(vals) > 4 else ''
                    bgt_s = vals[5].get('formattedValue', '').strip() if len(vals) > 5 else ''
                    try:
                        s_val = float(spent_s.replace("$", "").replace(",", "").strip()) if spent_s else 0.0
                    except ValueError:
                        s_val = 0.0
                    try:
                        b_val = float(bgt_s.replace("$", "").replace(",", "").strip()) if bgt_s else 0.0
                    except ValueError:
                        b_val = 0.0
                        
                    is_yellow = False
                    for col_idx in [2, 3, 4]:
                        if len(vals) > col_idx:
                            bg = vals[col_idx].get('userEnteredFormat', {}).get('backgroundColor', {})
                            if bg.get('red', 0) > 0.85 and bg.get('green', 0) > 0.75 and bg.get('blue', 1) < 0.75:
                                is_yellow = True
                                break
                                
                    is_keyword = any(k in desc.upper() for k in ['INSERT', 'RESHOOT', 'RE-SHOOT', 'PICKUP', 'PICK UP', 'EXTENDED', 'EXTENSION', 'EXTENTION', 'ADDITION'])
                    is_standard_bottom = (code.upper() in ['X99', 'EQUIP', 'SHIP', 'ELECT'] and desc.upper().strip() in ['EXPENDABLES / SUPPLIES', 'HEAVY EQUIPMENT', 'SHIPPING', 'WIREPERSON', 'WIREPERSON ', 'START UP EXPENDABLES / SUPPLIES (STREET KIT INCLUDED)'])
                    
                    if code and desc and 'TOTAL' not in code.upper():
                        if is_yellow or (is_keyword and not is_standard_bottom):
                            current_section_items.append({
                                'code': code,
                                'desc': desc,
                                'spent': s_val,
                                'budget': b_val
                            })
                
        return {"status": "success", "report_rows": report_rows}
        
    except Exception as e:
        from core.logger import log_error
        import traceback
        log_error(f"Error fetching cost report data: {e}\\n{traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

def generate_cost_report_pdf(report_rows, save_path):
    try:
        total_budget = sum(r["Budget"] for r in report_rows)
        total_spent = sum(r["Total Spent"] for r in report_rows)
        total_variance = sum(r["Variance (Savings)"] for r in report_rows)
        total_efc = sum(r["Projected Final Amount"] for r in report_rows)

        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        import datetime

        doc = SimpleDocTemplate(save_path, pagesize=landscape(letter), leftMargin=36, rightMargin=36, topMargin=25, bottomMargin=25)
        elements = []
        
        styles = getSampleStyleSheet()
        date_str = datetime.datetime.now().strftime('%m/%d/%Y')
        title_text = f"SET DEC - COST REPORT<br/>SAMPLE SHOW S1<br/>{date_str}"
        title = Paragraph(title_text, styles['Title'])
        elements.append(title)
        elements.append(Spacer(1, 10))
        
        sub_style = styles['Normal'].clone('SubBreakdownStyle')
        sub_style.fontSize = 8
        sub_style.textColor = colors.HexColor('#555555')
        sub_style.leading = 9
        
        table_data = [["Episode", "Budget", "Total Spent", "Projected Final Amount", "Variance (Savings)"]]
        
        subrow_indices = []
        positive_variance_rows = []
        
        current_table_row = 1
        for r in report_rows:
            table_data.append([
                r["Episode"],
                f"${r['Budget']:,.2f}",
                f"${r['Total Spent']:,.2f}",
                f"${r['Projected Final Amount']:,.2f}",
                f"${r['Variance (Savings)']:,.2f}"
            ])
            if r['Variance (Savings)'] > 0:
                positive_variance_rows.append(current_table_row)
            current_table_row += 1
            
            # Add any breakdown sub-rows (inserts / reshoots / extensions)
            for b in r.get("breakdowns", []):
                b_code = b.get('code', '')
                b_desc = b.get('desc', '')
                b_spent = b.get('spent', 0.0)
                label = f"&nbsp;&nbsp;&nbsp;&nbsp;↳ <i>Includes: {b_code} {b_desc}</i>" if b_code else f"&nbsp;&nbsp;&nbsp;&nbsp;↳ <i>Includes: {b_desc}</i>"
                p_label = Paragraph(label, sub_style)
                table_data.append([
                    p_label,
                    "",
                    f"${b_spent:,.2f}",
                    "",
                    ""
                ])
                subrow_indices.append(current_table_row)
                current_table_row += 1
            
        table_data.append([
            "TOTAL",
            f"${total_budget:,.2f}",
            f"${total_spent:,.2f}",
            f"${total_efc:,.2f}",
            f"${total_variance:,.2f}"
        ])
        
        table = Table(table_data, colWidths=[270, 105, 115, 140, 110], repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#002b36')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#fdf6e3')),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#eee8d5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#93a1a1')),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('FONTSIZE', (0, 1), (-1, -1), 9.5),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 1), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
        ]
        
        # Style positive variance cells
        for row_idx in positive_variance_rows:
            style_cmds.append(('BACKGROUND', (4, row_idx), (4, row_idx), colors.HexColor('#d4edda')))
            
        # Style breakdown subrows (lighter background, subdued text, smaller padding)
        for sub_idx in subrow_indices:
            style_cmds.append(('BACKGROUND', (0, sub_idx), (-1, sub_idx), colors.HexColor('#fffdf7')))
            style_cmds.append(('TEXTCOLOR', (0, sub_idx), (-1, sub_idx), colors.HexColor('#555555')))
            style_cmds.append(('FONTSIZE', (0, sub_idx), (-1, sub_idx), 8))
            style_cmds.append(('TOPPADDING', (0, sub_idx), (-1, sub_idx), 1))
            style_cmds.append(('BOTTOMPADDING', (0, sub_idx), (-1, sub_idx), 1))
                
        table.setStyle(TableStyle(style_cmds))
        
        elements.append(table)
        doc.build(elements)
            
        return {"status": "success", "message": f"Cost report saved to {save_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}



def update_cost_report_efc(url, updated_rows):
    try:
        from services.sheets import get_spreadsheet
        sh = get_spreadsheet(url)
        try:
            worksheet = sh.worksheet("TRACKER TOPSHEET")
        except:
            worksheet = sh.get_worksheet(1)
            
        cells_to_update = []
        for r in updated_rows:
            if "sheet_row" in r:
                # EFC is column H (which is column index 8 in A1 notation)
                row_num = r["sheet_row"]
                cells_to_update.append({
                    'range': f'H{row_num}',
                    'values': [[r["Projected Final Amount"]]]
                })
                
        if cells_to_update:
            worksheet.batch_update(cells_to_update, value_input_option="USER_ENTERED")
            
        return {"status": "success"}
    except Exception as e:
        from core.logger import log_error
        import traceback
        log_error(f"Error updating EFC back to sheets: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


def is_orange_color(bg):
    if not bg: return False
    r = bg.get('red', 0)
    g = bg.get('green', 0)
    b = bg.get('blue', 0)
    # Red must be high (at least 0.75)
    if r < 0.75:
        return False
    # In orange / peach, green must be noticeably higher than blue (at least 0.06).
    # Desaturated reds, salmons, and pinks have g ≈ b (e.g. red=0.918, green=0.6, blue=0.6).
    if (g - b) < 0.06:
        return False
    # Red must be noticeably higher than green (at least 0.05), distinguishing from yellow (r ≈ g).
    if (r - g) < 0.05:
        return False
    # Blue must not be too high (prevents white / gray highlights)
    if b > 0.85:
        return False
    return True


MONTH_ABBRS = {
    1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
}

def normalize_placeholder_date(val: str) -> str:
    if not val:
        return ''
    s = str(val).strip()
    if not s:
        return ''
    if s.upper() in ['TBD', 'N/A', 'NONE', 'PENDING']:
        return s.upper()
    
    # Already formatted as 'Oct 16' or 'Dec 18'
    m = re.match(r'^([a-zA-Z]{3,9})\s+(\d{1,2})$', s)
    if m:
        m_str = m.group(1).capitalize()[:3]
        d_num = int(m.group(2))
        return f'{m_str} {d_num}'

    # Format '1-Nov' or '14-Aug' or '12/Aug/26'
    m2 = re.match(r'^(\d{1,2})[-/]([a-zA-Z]{3,9})(?:[-/]\d{2,4})?$', s)
    if m2:
        d_num = int(m2.group(1))
        m_str = m2.group(2).capitalize()[:3]
        return f'{m_str} {d_num}'

    from core.database import parse_date_key
    try:
        dt = parse_date_key(s)
        if dt and dt.year < 9000:
            m_str = MONTH_ABBRS.get(dt.month, dt.strftime('%b'))
            return f'{m_str} {dt.day}'
    except Exception:
        pass
    return s


def sync_placeholders_tab(url):
    """
    Scans all set tabs in the spreadsheet for placeholders (rows highlighted in orange
    or containing 'placeholder' in description/values).
    Compiles and organizes them grouped by Set in set order into a tab at the very end
    called 'PLACEHOLDERS', styled with headers, metrics, and orange highlights.
    """
    if not url:
        return {"status": "error", "message": "No spreadsheet URL configured."}
    try:
        import urllib.parse
        from datetime import datetime
        sh = get_spreadsheet(url)
        worksheets = sh.worksheets()
        ws_map = {w.title: w.id for w in worksheets}
        
        skip_tabs = {'SET DEC BUDGET', 'TRACKER TOPSHEET', 'SECURITY DEPOSITS', 'PLACEHOLDERS', 'GREENS'}
        set_tabs = [w.title for w in worksheets if w.title.upper().strip() not in skip_tabs and 'GREEN' not in w.title.upper()]
        
        placeholders_by_set = {}
        tab_set_names = {}
        batch_size = 15
        
        for i in range(0, len(set_tabs), batch_size):
            batch = set_tabs[i:i+batch_size]
            encoded_ranges = [urllib.parse.quote(f'{t}!A1:U80', safe='') for t in batch]
            url_call = f'https://sheets.googleapis.com/v4/spreadsheets/{sh.id}?fields=sheets(properties(title),data(rowData(values(formattedValue,userEnteredFormat/backgroundColor))))'
            params = '&'.join([f'ranges={r}' for r in encoded_ranges])
            try:
                res = sh.client.request('get', f'{url_call}&{params}').json()
            except Exception as e:
                print(f"Error fetching batch of tabs for placeholders: {e}")
                continue
            
            for sheet in res.get('sheets', []):
                title = sheet['properties']['title']
                for data in sheet.get('data', []):
                    rows = data.get('rowData', [])
                    if not rows:
                        continue
                    # Check Row 1 for Set Name (Cell B1)
                    r1 = [v.get('formattedValue', '') for v in rows[0].get('values', [])] if len(rows) > 0 else []
                    set_name_val = title
                    if len(r1) > 1 and r1[1].strip() and not r1[1].strip().isdigit() and title != 'L&D':
                        set_name_val = r1[1].strip()
                    elif len(r1) > 0 and r1[0].strip() and title != 'L&D':
                        set_name_val = r1[0].strip()
                    tab_set_names[title] = set_name_val

                    for row_idx, row in enumerate(rows[7:], start=8):
                        cells = row.get('values', [])
                        vals = [v.get('formattedValue', '') for v in cells]
                        if not any(vals): continue
                        
                        val_str = ' '.join(str(v) for v in vals).upper()
                        if any(x in val_str for x in ['TOTAL', 'BUDGET', 'VARIANCE', 'EXPENDITURE']):
                            desc = vals[4] if len(vals) > 4 else ''
                            if 'placeholder' not in desc.lower():
                                continue
                        if len(vals) >= 2 and vals[0] in ['SHIP', 'EQUIP', 'ELECT', 'TRANS', 'L&D', 'GREENS', 'PROD'] and vals[1] in ['SHIPPING', 'HEAVY EQUIPMENT', 'ELECTRICAL']:
                            continue
                        
                        # Count orange highlighted cells across the row
                        orange_count = sum(1 for v in cells if is_orange_color(v.get('userEnteredFormat', {}).get('backgroundColor', {})))
                        # Must be fully or close to fully highlighted (at least 5 cells highlighted in orange)
                        row_orange = orange_count >= 5
                        
                        desc_val = vals[4] if len(vals) > 4 else ''
                        has_word = 'placeholder' in desc_val.lower()
                        
                        if row_orange or has_word:
                            if title not in placeholders_by_set:
                                placeholders_by_set[title] = []
                            placeholders_by_set[title].append({
                                'row': row_idx,
                                'vals': vals
                            })

        total_count = sum(len(v) for v in placeholders_by_set.values())
        
        ws_target = None
        for w in worksheets:
            if w.title.upper() == 'PLACEHOLDERS':
                ws_target = w
                break

        # Read existing estimates from PLACEHOLDERS tab before updating so estimates aren't lost
        existing_estimates = {
            ('B15', 'LOCK UP PROPS INC.', 'PLACEHOLDER BEDSIDE TABLE'): 250.0,
            ('B15', 'UNITED PROPS', 'PLACEHOLDER BEDSPREAD, CLOCK'): 250.0
        }
        if ws_target is not None:
            try:
                cur_vals = ws_target.get_all_values()
                for r in cur_vals[4:]:
                    if len(r) >= 5:
                        s_code = r[0].strip()
                        v_name = r[2].strip().upper()
                        d_text = r[4].strip().upper()
                        amt = str(r[1]).replace('$', '').replace(',', '').strip()
                        if amt:
                            try:
                                existing_estimates[(s_code, v_name, d_text)] = float(amt)
                                existing_estimates[(v_name, d_text)] = float(amt)
                            except ValueError:
                                pass
            except Exception:
                pass
                
        num_sets = len(placeholders_by_set)
        needed_rows = max(150, total_count + num_sets * 3 + 20)
        
        if ws_target is None:
            ws_target = sh.add_worksheet(title='PLACEHOLDERS', rows=needed_rows, cols=7, index=len(worksheets))
        else:
            if ws_target.col_count != 6:
                try:
                    ws_target.resize(cols=7)
                except Exception:
                    pass
            current_index = ws_target.index
            last_index = len(worksheets) - 1
            if current_index != last_index:
                try:
                    sh.batch_update({
                        "requests": [{
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": ws_target.id,
                                    "index": len(worksheets)
                                },
                                "fields": "index"
                            }
                        }]
                    })
                except Exception:
                    pass
                    
        topsheet_gid = ws_map.get('TRACKER TOPSHEET')
        topsheet_link = f'=HYPERLINK("#gid={topsheet_gid}", "TOPSHEET")' if topsheet_gid else 'TOPSHEET'
        
        output_rows = []
        output_rows.append(['PLACEHOLDERS TRACKER', '', '', '', '', '', topsheet_link])
        
        placeholder_lines = []
        orange_rows = []
        set_header_rows = []
        current_row_num = 5
        total_amount = 0.0
        
        for set_tab in set_tabs:
            if set_tab not in placeholders_by_set:
                continue
            items = placeholders_by_set[set_tab]
            
            set_display_name = tab_set_names.get(set_tab, set_tab).strip()
            if not set_display_name:
                set_display_name = set_tab

            # Prepend Episode number before set name (e.g. 'EP 202 - INT MOTEL ROOM', 'EP 207 - EXTENDED RENTALS')
            ep_prefix = ''
            if set_tab:
                first_char = set_tab[0].upper()
                if 'A' <= first_char <= 'J':
                    ep_num = 200 + (ord(first_char) - ord('A') + 1)
                    ep_prefix = f'EP {ep_num}'
                elif first_char == 'X':
                    ep_prefix = 'AMORT'

            if ep_prefix:
                if not set_display_name.upper().startswith(ep_prefix.upper()) and not set_display_name.upper().startswith('EPISODE') and not set_display_name.upper().startswith('AMORT'):
                    set_display_name = f'{ep_prefix} - {set_display_name}'
                
            target_gid = ws_map.get(set_tab)
            set_header_rows.append((current_row_num, target_gid))
            
            escaped_banner_name = set_display_name.replace('"', '""')
            if target_gid is not None:
                banner_cell = f'=HYPERLINK("#gid={target_gid}", "{escaped_banner_name}")'
            else:
                banner_cell = set_display_name
                
            placeholder_lines.append([banner_cell, '', '', '', '', '', ''])
            current_row_num += 1
            
            for item in items:
                row_vals = item['vals']
                padded = row_vals + [''] * max(0, 20 - len(row_vals))
                vendor = padded[2]
                name = padded[3]
                description = padded[4]
                return_date_raw = padded[14]
                return_date_val = normalize_placeholder_date(return_date_raw)
                
                row_set_code = set_tab
                # Check for secondary set code and set name in columns Q & R (indices 16, 17) or subsequent cells
                sub_set_code = ''
                sub_set_name = ''

                col_q = padded[16].strip() if len(padded) > 16 else ''
                col_r = padded[17].strip() if len(padded) > 17 else ''

                if col_q:
                    m = re.match(r'^([A-Z]\d{2,3})$', col_q.upper())
                    if m:
                        sub_set_code = m.group(1)
                        sub_set_name = col_r
                    else:
                        m2 = re.search(r'\b([A-Z]\d{2,3})\b', col_q.upper())
                        if m2:
                            sub_set_code = m2.group(1)
                            sub_set_name = col_r

                if not sub_set_code:
                    for idx, cell in enumerate(padded[15:], start=15):
                        cell_str = str(cell).strip()
                        if not cell_str:
                            continue
                        m = re.match(r'^([A-Z]\d{2,3})$', cell_str.upper())
                        if m:
                            sub_set_code = m.group(1)
                            if idx + 1 < len(padded):
                                sub_set_name = str(padded[idx + 1]).strip()
                            break
                        m2 = re.search(r'\b([A-Z]\d{2,3})\b', cell_str.upper())
                        if m2:
                            sub_set_code = m2.group(1)
                            if idx + 1 < len(padded):
                                sub_set_name = str(padded[idx + 1]).strip()
                            break

                if sub_set_code and sub_set_code.upper() != set_tab.upper():
                    if sub_set_name:
                        row_set_code = f'{set_tab} ({sub_set_code} - {sub_set_name})'
                    else:
                        row_set_code = f'{set_tab} ({sub_set_code})'
                else:
                    row_set_code = set_tab

                escaped_code = row_set_code.replace('"', '""')
                if target_gid is not None:
                    code_cell = f'=HYPERLINK("#gid={target_gid}", "{escaped_code}")'
                else:
                    code_cell = row_set_code

                # Expenditure extraction & preservation
                raw_exp = padded[0]
                clean_exp = str(raw_exp).replace('$', '').replace(',', '').strip()
                exp_val = ""
                if clean_exp:
                    try:
                        exp_val = float(clean_exp)
                    except ValueError:
                        exp_val = raw_exp
                else:
                    key = (row_set_code, str(vendor).strip().upper(), str(description).strip().upper())
                    if key in existing_estimates:
                        exp_val = existing_estimates[key]
                    elif (str(vendor).strip().upper(), str(description).strip().upper()) in existing_estimates:
                        exp_val = existing_estimates[(str(vendor).strip().upper(), str(description).strip().upper())]

                if isinstance(exp_val, (int, float)):
                    total_amount += float(exp_val)

                # Notes extraction logic:
                # Extension tabs (G98, X98, I98, or any tab ending in 98/99 or with secondary set code): notes are in Column S (index 18)
                # Standard sets: notes are in Column Q (index 16)
                is_extension_tab = set_tab.upper().endswith("98") or set_tab.upper().endswith("99") or bool(sub_set_code)
                note_val = ""
                if is_extension_tab:
                    if len(padded) > 18 and padded[18].strip():
                        note_val = padded[18].strip()
                    else:
                        for cell in padded[19:]:
                            if str(cell).strip():
                                note_val = str(cell).strip()
                                break
                else:
                    if len(padded) > 16 and padded[16].strip():
                        note_val = padded[16].strip()
                    elif len(padded) > 17 and padded[17].strip():
                        note_val = padded[17].strip()

                full_line = [
                    code_cell,
                    exp_val,
                    vendor,
                    name,
                    description,
                    return_date_val,
                    note_val
                ]
                placeholder_lines.append(full_line)
                orange_rows.append((current_row_num, target_gid))
                current_row_num += 1
                
            placeholder_lines.append([''] * 7)
            current_row_num += 1

        try:
            now_str = datetime.now().strftime("%b %#d, %Y %#I:%M %p")
        except Exception:
            dt = datetime.now()
            hour = dt.strftime("%I").lstrip("0")
            day = dt.strftime("%d").lstrip("0")
            now_str = f"{dt.strftime('%b')} {day}, {dt.year} {hour}:{dt.strftime('%M %p')}"
        # Row 2 (Summary) - LAST UPDATED in Column E
        output_rows.append([f'TOTAL PLACEHOLDERS: {total_count}', f'ESTIMATED TOTAL: ${total_amount:,.2f}', '', '', '', f'LAST UPDATED: {now_str}', ''])
        output_rows.append([''] * 7)
        
        headers = ['SET', 'EXPENDITURE', 'VENDOR', 'NAME', 'DESCRIPTION/ITEMS', 'RETURN DATE', 'NOTES']
        output_rows.append(headers)
        output_rows.extend(placeholder_lines)

        if ws_target.row_count < len(output_rows) + 20:
            ws_target.add_rows(len(output_rows) + 30 - ws_target.row_count)
            
        ws_target.clear()
        ws_target.update(values=output_rows, range_name=f'A1:G{len(output_rows)}', raw=False)
        
        requests = []
        sheet_id = ws_target.id
        
        # Reset background color for rows below summary (Row 3 downwards) to pure white
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": ws_target.row_count, "startColumnIndex": 0, "endColumnIndex": 7},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        })

        # Style Row 1 (Title) - Pastel Sage
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 6},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.718, "green": 0.835, "blue": 0.769},
                        "textFormat": {"foregroundColor": {"red": 0.12, "green": 0.25, "blue": 0.18}, "fontSize": 13, "bold": True},
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        })
        
        # Style Row 1, Col F (Topsheet Link at Top Right)
        topsheet_tf = {
            "foregroundColor": {"red": 0.08, "green": 0.28, "blue": 0.65},
            "fontSize": 10,
            "bold": True,
            "underline": True
        }
        if topsheet_gid is not None:
            topsheet_tf["link"] = {"uri": f"#gid={topsheet_gid}"}

        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.718, "green": 0.835, "blue": 0.769},
                        "textFormat": topsheet_tf,
                        "horizontalAlignment": "RIGHT",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        })
        
        # Style Row 2 (Summary) - Pastel Pearl
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": 7},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.95, "green": 0.96, "blue": 0.96},
                        "textFormat": {"foregroundColor": {"red": 0.25, "green": 0.30, "blue": 0.35}, "fontSize": 10, "bold": True},
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        })
        
        # Style Row 4 (Table Headers) - Pastel Periwinkle, All CENTER Aligned
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 7},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.812, "green": 0.886, "blue": 0.953},
                        "textFormat": {"foregroundColor": {"red": 0.15, "green": 0.25, "blue": 0.45}, "fontSize": 10, "bold": True},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        })
        
        # Style Set Headers - Pastel Lavender / Lilac with clickable link, LEFT Aligned
        for r_idx, gid_val in set_header_rows:
            banner_tf = {
                "foregroundColor": {"red": 0.22, "green": 0.18, "blue": 0.42},
                "fontSize": 11,
                "bold": True,
                "underline": True
            }
            if gid_val is not None:
                banner_tf["link"] = {"uri": f"#gid={gid_val}"}

            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 0, "endColumnIndex": 7},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.851, "green": 0.824, "blue": 0.914},
                            "textFormat": banner_tf,
                            "horizontalAlignment": "LEFT",
                            "verticalAlignment": "MIDDLE"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
                }
            })
            
        # Style Orange Placeholder Rows - Soft Pastel Peach with explicit column alignments & date formats
        PEACH_BG = {"red": 0.988, "green": 0.898, "blue": 0.804}
        DATA_TF = {"foregroundColor": {"red": 0.15, "green": 0.15, "blue": 0.15}, "fontSize": 10, "bold": False}

        for r_idx, gid_val in orange_rows:
            # Col A: SET (Centered blue link)
            code_tf = {
                "foregroundColor": {"red": 0.08, "green": 0.28, "blue": 0.65},
                "fontSize": 10,
                "bold": True,
                "underline": True
            }
            if gid_val is not None:
                code_tf["link"] = {"uri": f"#gid={gid_val}"}

            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 0, "endColumnIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": PEACH_BG,
                            "textFormat": code_tf,
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
                }
            })

            # Col B: EXPENDITURE (Accounting / Currency format, Centered)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 1, "endColumnIndex": 2},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": PEACH_BG,
                            "textFormat": DATA_TF,
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "numberFormat": {
                                "type": "NUMBER",
                                "pattern": '_("$"* #,##0.00_);_("$"* \(#,##0.00\);_("$"* "-"??_);_(@_)'
                            }
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,numberFormat)"
                }
            })

            # Col C: VENDOR (Left aligned)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 2, "endColumnIndex": 3},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": PEACH_BG,
                            "textFormat": DATA_TF,
                            "horizontalAlignment": "LEFT",
                            "verticalAlignment": "MIDDLE"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
                }
            })

            # Col D: NAME (Centered)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 3, "endColumnIndex": 4},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": PEACH_BG,
                            "textFormat": DATA_TF,
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
                }
            })

            # Col E: DESCRIPTION/ITEMS (Left aligned)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 4, "endColumnIndex": 5},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": PEACH_BG,
                            "textFormat": DATA_TF,
                            "horizontalAlignment": "LEFT",
                            "verticalAlignment": "MIDDLE"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
                }
            })

            # Col F: RETURN DATE (Centered, mmm d date pattern)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 5, "endColumnIndex": 6},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": PEACH_BG,
                            "textFormat": DATA_TF,
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "numberFormat": {
                                "type": "DATE",
                                "pattern": "mmm d"
                            }
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,numberFormat)"
                }
            })

            # Col G: NOTES (Left aligned)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": r_idx - 1, "endRowIndex": r_idx, "startColumnIndex": 6, "endColumnIndex": 7},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": PEACH_BG,
                            "textFormat": DATA_TF,
                            "horizontalAlignment": "LEFT",
                            "verticalAlignment": "MIDDLE"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
                }
            })

        col_widths = [220, 140, 170, 80, 380, 100, 280]
        for c_idx, w in enumerate(col_widths):
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c_idx, "endIndex": c_idx + 1},
                    "properties": {"pixelSize": w},
                    "fields": "pixelSize"
                }
            })
                # Merge F2:G2 for LAST UPDATED timestamp
        requests.append({
            "mergeCells": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 5, "endColumnIndex": 7},
                "mergeType": "MERGE_ALL"
            }
        })
        sh.batch_update({"requests": requests})
        return {"status": "success", "count": total_count, "amount": total_amount}
    except Exception as e:
        import traceback
        print(f"Error syncing placeholders tab: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": str(e)}
def sync_assets_tab(url=None):

    """

    Scans all set tabs for assets (rows where Column I is 'A').

    Maintains all row details, searches online for item photos, embeds photos in Column A,

    and organizes everything into an 'ASSETS' worksheet at the end of the spreadsheet.

    """

    try:

        import os

        import json

        import urllib.parse

        import re

        from datetime import datetime
        if not url:

            from core.settings import load_settings

            settings = load_settings()

            url = settings.get("spreadsheet_url", "")

            if not url:

                return {"status": "error", "message": "No spreadsheet URL configured."}
        sh = get_spreadsheet(url)

        client = get_client()

        worksheets = sh.worksheets()

        ws_map = {w.title: w.id for w in worksheets}
        # Cache file location in app root

        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        cache_path = os.path.join(app_root, "assets_photo_cache.json")
        def load_cache():

            if os.path.exists(cache_path):

                try:

                    with open(cache_path, 'r', encoding='utf-8') as f:

                        return json.load(f)

                except Exception:

                    pass

            return {}
        def save_cache(cache):

            try:

                with open(cache_path, 'w', encoding='utf-8') as f:

                    json.dump(cache, f, indent=2)

            except Exception as e:

                print("Error saving assets photo cache:", e)
        def search_photo_online(vendor, description, set_tab=None, ref=None, date=None):
            # Strict rule: DO NOT return any photo unless 100% certain it is that exact item.
            # Never return random search engine thumbnails.
            v_upper = vendor.upper()
            
            # Sunpan exact SKU (e.g. 110582, 109559, 111956, 108075, 111069)
            m_sunpan = re.search(r'\b(1\d{5})\b', description)
            if 'SUNPAN' in v_upper and m_sunpan:
                sku = m_sunpan.group(1)
                return f"https://sunpan.com/cdn/shop/files/{sku}.jpg"

            # Uline exact SKU in description (e.g. H-3206 -> H-3202 image, H-6301, H-3955)
            m_uline = re.search(r'\b(H-\d{4,5}[A-Z]*)\b', description, flags=re.IGNORECASE)
            if 'ULINE' in v_upper and m_uline:
                sku = m_uline.group(1).upper()
                if sku == 'H-3206':
                    return "https://img.uline.com/is/image/uline/H-3202?$Medium$"
                return f"https://img.uline.com/is/image/uline/{sku}?$Medium$"

            # Sourcing via local receipts (database.sqlite or Receipts/{set_tab})
            pdf_path = None
            db_path = os.path.join(app_root, "database.sqlite")
            if os.path.exists(db_path):
                try:
                    import sqlite3
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    if ref:
                        cur.execute("SELECT file_path FROM receipts WHERE reference_number=? ORDER BY id DESC LIMIT 1;", (ref,))
                        row = cur.fetchone()
                        if row and row[0] and os.path.exists(row[0]):
                            pdf_path = row[0]
                    if not pdf_path and set_tab:
                        cur.execute("SELECT file_path FROM receipts WHERE set_number=? AND vendor LIKE ? ORDER BY id DESC LIMIT 1;", (set_tab, f"%{vendor}%"))
                        row = cur.fetchone()
                        if row and row[0] and os.path.exists(row[0]):
                            pdf_path = row[0]
                    conn.close()
                except Exception as e:
                    print("Error checking receipt db:", e)

            if not pdf_path and set_tab:
                receipts_dir = os.path.join(os.path.dirname(app_root), "Receipts", set_tab)
                if os.path.exists(receipts_dir):
                    for fname in os.listdir(receipts_dir):
                        if (ref and ref in fname) or (vendor and vendor.lower() in fname.lower()):
                            cand = os.path.join(receipts_dir, fname)
                            if os.path.exists(cand):
                                pdf_path = cand
                                break

            if pdf_path and pdf_path.lower().endswith(".pdf"):
                try:
                    import fitz
                    doc = fitz.open(pdf_path)
                    pdf_text = ""
                    for page in doc:
                        pdf_text += page.get_text() + "\n"
                    
                    if 'ULINE' in v_upper:
                        skus = re.findall(r'\b(H-\d{4,5}[A-Z]*)\b', pdf_text, flags=re.IGNORECASE)
                        # Filter out promotional $0 items (like H-10882 job site light)
                        valid_skus = [s.upper() for s in skus if s.upper() not in ['H-10882']]
                        if valid_skus:
                            chosen = valid_skus[0]
                            for s_cand in valid_skus:
                                if '8224' in s_cand:
                                    chosen = s_cand
                                    break
                            return f"https://img.uline.com/is/image/uline/{chosen}?$Medium$"
                            
                    if 'SUNPAN' in v_upper:
                        m = re.findall(r'\b(1\d{5})\b', pdf_text)
                        if m:
                            return f"https://sunpan.com/cdn/shop/files/{m[0]}.jpg"

                    if 'URBAN BARN' in v_upper:
                        m = re.findall(r'\b(2\d{5})\b', pdf_text)
                        if m:
                            return f"https://www.urbanbarn.com/dw/image/v2/BCKH_PRD/on/demandware.static/-/Sites-masterCatalog_Urban_Barn/default/dw68827abd/images/original/{m[0]}-full.jpg"
                except Exception as e:
                    print("Error reading receipt PDF:", e)

            # Default to empty string if not 100% certain
            return ""

        skip_tabs = {'SET DEC BUDGET', 'TRACKER TOPSHEET', 'SECURITY DEPOSITS', 'PLACEHOLDERS', 'GREENS', 'CH REQS', 'ASSETS'}

        set_tabs = [w.title for w in worksheets if w.title.upper().strip() not in skip_tabs and 'GREEN' not in w.title.upper()]
        all_assets = []

        tab_set_names = {}

        batch_size = 15
        for i in range(0, len(set_tabs), batch_size):

            batch = set_tabs[i:i+batch_size]

            ranges_param = '&'.join([f"ranges={urllib.parse.quote(f'{t}!A1:Q100', safe='')}" for t in batch])

            try:

                res_vals = client.http_client.request('get', f'https://sheets.googleapis.com/v4/spreadsheets/{sh.id}/values:batchGet?{ranges_param}').json()

                for vr in res_vals.get('valueRanges', []):

                    tab_name = vr.get('range', '').split('!')[0].strip("'")

                    rows = vr.get('values', [])

                    if rows:

                        r1 = rows[0]

                        set_name_val = tab_name

                        for cell_val in r1[:6]:

                            c_str = str(cell_val).strip()

                            if c_str and c_str.upper() != tab_name.upper() and not c_str.isdigit() and len(c_str) > 3 and tab_name != 'L&D':

                                set_name_val = c_str

                                break

                        else:

                            if len(r1) > 0 and r1[0].strip() and tab_name != 'L&D':

                                set_name_val = r1[0].strip()

                        tab_set_names[tab_name] = set_name_val
                    for r_idx, r in enumerate(rows):

                        if len(r) > 8:

                            col_i = str(r[8]).strip().upper()

                            if col_i == 'A' or (col_i.startswith('A') and len(col_i) <= 2):

                                first_col = str(r[0]).strip().upper() if r else ''

                                if first_col not in ['EXPENDITURE', 'TOTAL', 'BUDGET', 'VARIANCE'] and 'EXPENDITURE' not in col_i and 'I/A' not in col_i:

                                    padded = [str(c) if c is not None else '' for c in r] + [''] * max(0, 17 - len(r))

                                    # INVARIANT: Rentals can NEVER be assets!
                                    if padded[13].strip().upper() in ['Y', 'YES']:
                                        continue

                                    all_assets.append({

                                        'tab': tab_name,

                                        'set_name': tab_set_names.get(tab_name, tab_name),

                                        'row': r_idx + 1,

                                        'expenditure': padded[0].strip(),

                                        'col_b': padded[1].strip(),

                                        'vendor': padded[2].strip(),

                                        'buyer': padded[3].strip(),

                                        'description': padded[4].strip(),

                                        'chq_req': padded[5].strip(),

                                        'petty_cash': padded[6].strip(),

                                        'credit_card': padded[7].strip(),

                                        'ia': padded[8].strip(),

                                        'po_type': padded[9].strip(),

                                        'po_num': padded[10].strip(),

                                        'date': padded[11].strip(),

                                        'reference': padded[12].strip(),

                                        'rental': padded[13].strip(),

                                        'rental_end_date': padded[14].strip(),

                                        'chq_num': padded[15].strip(),

                                        'notes': padded[16].strip()

                                    })

            except Exception as e:

                print(f"Error fetching batch {i}: {e}")
        # Special rule for 98 tabs (Extended Rentals):
        # List the real set name / set number from notes at the front, and put "<Tab> EXTENDED RENTALS" in notes.
        for a in all_assets:
            if a['tab'].endswith('98'):
                notes_text = a['notes'].strip()
                cand = notes_text.split()[0].strip().upper() if notes_text else ''
                if cand in tab_set_names or re.match(r'^[A-Z]\d{2}$', cand):
                    real_set_num = cand
                    real_set_name = tab_set_names.get(cand, cand)
                    original_tab = a['tab']
                    a['tab'] = real_set_num
                    a['set_name'] = real_set_name
                    a['notes'] = f"{original_tab} EXTENDED RENTALS"

        # Update cache for any new assets

        cache = load_cache()

        cache_dirty = False

        for a in all_assets:

            k = f"{a['vendor']} | {a['description']}"

            if k not in cache or not cache[k]:

                photo_found = search_photo_online(a['vendor'], a['description'], set_tab=a['tab'], ref=a['reference'], date=a['date'])

                if photo_found:

                    cache[k] = photo_found

                    cache_dirty = True

        if cache_dirty:

            save_cache(cache)
        # Worksheet setup

        ws_assets = None

        needed_rows = max(100, len(all_assets) + 15)

        needed_cols = 19
        for w in worksheets:

            if w.title.upper() == 'ASSETS':

                ws_assets = w

                break
        if not ws_assets:

            ws_assets = sh.add_worksheet(title='ASSETS', rows=needed_rows, cols=needed_cols, index=len(worksheets))

        else:

            if ws_assets.row_count < needed_rows or ws_assets.col_count < needed_cols:

                ws_assets.resize(rows=needed_rows, cols=needed_cols)

            ws_assets.clear()
        sheet_id = ws_assets.id

        topsheet_id = ws_map.get('TRACKER TOPSHEET', '')

        topsheet_link = f'=HYPERLINK("#gid={topsheet_id}", "↩ BACK TO TOPSHEET")' if topsheet_id != '' else 'TRACKER TOPSHEET'
        # Build output rows

        output_rows = []

        # Row 1: Header banner

        output_rows.append(['✨ ASSETS INVENTORY TRACKER 📦'] + [''] * 17 + [topsheet_link])
        # Calculate total value

        total_val = 0.0

        for a in all_assets:

            clean_num = a['expenditure'].replace('$', '').replace(',', '').strip()

            if clean_num.startswith('(') and clean_num.endswith(')'):

                clean_num = '-' + clean_num[1:-1]

            try:

                total_val += float(clean_num)

            except Exception:

                pass
        # Row 2: KPI Metrics Cards

        now_str = datetime.now().strftime('%Y-%m-%d %I:%M %p')

        metrics_row = [

            f"TOTAL ASSETS: {len(all_assets)}",

            "", "",

            f"=SUM(D5:D{len(all_assets)+4})",

            "", "", "", "", "", "", "", "", "", "", "", "", "", "",

            f"LAST SYNCED: {now_str}"

        ]

        output_rows.append(metrics_row)
        # Row 3: Blank separator

        output_rows.append([''] * needed_cols)
        # Row 4: Column Headers

        headers = [

            'PHOTO', 'SET #', 'SET NAME', 'EXPENDITURE', 'VENDOR', 'BUYER',

            'DESCRIPTION / ITEMS', 'CHQ REQ', 'PETTY CASH', 'CREDIT CARD',

            'I/A', 'P.O.', 'P.O. #', 'DATE', 'REFERENCE', 'RENTAL',

            'RENTAL END DATE', 'CHQ #', 'NOTES'

        ]

        output_rows.append(headers)
        # Rows 5+: Data rows

        for a in all_assets:

            k = f"{a['vendor']} | {a['description']}"

            photo_url = cache.get(k, "")

            photo_cell = f'=IFERROR(IMAGE("{photo_url}"), "")' if photo_url else ''

            output_rows.append([

                photo_cell,

                a['tab'],

                a['set_name'],

                a['expenditure'],

                a['vendor'],

                a['buyer'],

                a['description'],

                a['chq_req'],

                a['petty_cash'],

                a['credit_card'],

                a['ia'],

                a['po_type'],

                a['po_num'],

                a['date'],

                a['reference'],

                a['rental'],

                a['rental_end_date'],

                a['chq_num'],

                a['notes']

            ])
        ws_assets.update(range_name=f'A1:S{len(output_rows)}', values=output_rows, value_input_option='USER_ENTERED')
        # Formatting batch_update

        requests = []

        requests.append({"unmergeCells": {"range": {"sheetId": sheet_id}}})
        col_widths = [120, 70, 200, 110, 220, 95, 320, 65, 75, 80, 50, 60, 85, 85, 95, 65, 110, 80, 240]

        for c_idx, w in enumerate(col_widths):

            requests.append({

                "updateDimensionProperties": {

                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c_idx, "endIndex": c_idx + 1},

                    "properties": {"pixelSize": w},

                    "fields": "pixelSize"

                }

            })
        requests.append({

            "updateDimensionProperties": {

                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},

                "properties": {"pixelSize": 40},

                "fields": "pixelSize"

            }

        })

        requests.append({

            "updateDimensionProperties": {

                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},

                "properties": {"pixelSize": 32},

                "fields": "pixelSize"

            }

        })

        requests.append({

            "updateDimensionProperties": {

                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 3, "endIndex": 4},

                "properties": {"pixelSize": 32},

                "fields": "pixelSize"

            }

        })
        if all_assets:

            requests.append({

                "updateDimensionProperties": {

                    "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 4, "endIndex": 4 + len(all_assets)},

                    "properties": {"pixelSize": 90},

                    "fields": "pixelSize"

                }

            })
        requests.append({

            "mergeCells": {

                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 18},

                "mergeType": "MERGE_ALL"

            }

        })

        requests.append({

            "mergeCells": {

                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": 3},

                "mergeType": "MERGE_ALL"

            }

        })

        requests.append({

            "mergeCells": {

                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 3, "endColumnIndex": 6},

                "mergeType": "MERGE_ALL"

            }

        })

        requests.append({

            "mergeCells": {

                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 6, "endColumnIndex": 18},

                "mergeType": "MERGE_ALL"

            }

        })
        requests.append({

            "repeatCell": {

                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 19},

                "cell": {

                    "userEnteredFormat": {

                        "backgroundColor": {"red": 0.957, "green": 0.835, "blue": 0.882},

                        "textFormat": {"foregroundColor": {"red": 0.322, "green": 0.176, "blue": 0.259}, "fontSize": 14, "bold": True, "fontFamily": "Roboto"},

                        "horizontalAlignment": "CENTER",

                        "verticalAlignment": "MIDDLE"

                    }

                },

                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"

            }

        })
        requests.append({

            "repeatCell": {

                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 18, "endColumnIndex": 19},

                "cell": {

                    "userEnteredFormat": {

                        "backgroundColor": {"red": 0.886, "green": 0.824, "blue": 0.925},

                        "textFormat": {"foregroundColor": {"red": 0.341, "green": 0.208, "blue": 0.443}, "fontSize": 10, "bold": True, "fontFamily": "Roboto"},

                        "horizontalAlignment": "CENTER",

                        "verticalAlignment": "MIDDLE"

                    }

                },

                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"

            }

        })
        requests.append({

            "repeatCell": {

                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": 3},

                "cell": {

                    "userEnteredFormat": {

                        "backgroundColor": {"red": 1.0, "green": 0.902, "blue": 0.855},

                        "textFormat": {"foregroundColor": {"red": 0.498, "green": 0.239, "blue": 0.239}, "fontSize": 11, "bold": True, "fontFamily": "Roboto"},

                        "horizontalAlignment": "CENTER",

                        "verticalAlignment": "MIDDLE"

                    }

                },

                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"

            }

        })
        requests.append({

            "repeatCell": {

                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 3, "endColumnIndex": 6},

                "cell": {

                    "userEnteredFormat": {

                        "backgroundColor": {"red": 0.847, "green": 0.953, "blue": 0.863},

                        "textFormat": {"foregroundColor": {"red": 0.176, "green": 0.416, "blue": 0.310}, "fontSize": 11, "bold": True, "fontFamily": "Roboto"},

                        "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"},

                        "horizontalAlignment": "CENTER",

                        "verticalAlignment": "MIDDLE"

                    }

                },

                "fields": "userEnteredFormat(backgroundColor,textFormat,numberFormat,horizontalAlignment,verticalAlignment)"

            }

        })
        requests.append({

            "repeatCell": {

                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 18, "endColumnIndex": 19},

                "cell": {

                    "userEnteredFormat": {

                        "backgroundColor": {"red": 0.941, "green": 0.925, "blue": 0.965},

                        "textFormat": {"foregroundColor": {"red": 0.455, "green": 0.388, "blue": 0.514}, "fontSize": 9, "italic": True, "fontFamily": "Roboto"},

                        "horizontalAlignment": "CENTER",

                        "verticalAlignment": "MIDDLE"

                    }

                },

                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"

            }

        })
        requests.append({

            "repeatCell": {

                "range": {"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 19},

                "cell": {

                    "userEnteredFormat": {

                        "backgroundColor": {"red": 0.875, "green": 0.824, "blue": 0.918},

                        "textFormat": {"foregroundColor": {"red": 0.239, "green": 0.176, "blue": 0.302}, "fontSize": 10, "bold": True, "fontFamily": "Roboto"},

                        "horizontalAlignment": "CENTER",

                        "verticalAlignment": "MIDDLE",

                        "wrapStrategy": "WRAP"

                    }

                },

                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)"

            }

        })
        if all_assets:

            end_r = 4 + len(all_assets)

            requests.append({

                "repeatCell": {

                    "range": {"sheetId": sheet_id, "startRowIndex": 4, "endRowIndex": end_r, "startColumnIndex": 0, "endColumnIndex": 19},

                    "cell": {

                        "userEnteredFormat": {

                            "textFormat": {"fontSize": 10, "fontFamily": "Roboto"},

                            "verticalAlignment": "MIDDLE",

                            "wrapStrategy": "CLIP"

                        }

                    },

                    "fields": "userEnteredFormat(textFormat,verticalAlignment,wrapStrategy)"

                }

            })
            center_cols = [0, 1, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            left_cols = [2, 4, 6, 18]

            for c in left_cols:

                requests.append({

                    "repeatCell": {

                        "range": {"sheetId": sheet_id, "startRowIndex": 4, "endRowIndex": end_r, "startColumnIndex": c, "endColumnIndex": c + 1},

                        "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},

                        "fields": "userEnteredFormat(horizontalAlignment)"

                    }

                })

            for c in center_cols:

                requests.append({

                    "repeatCell": {

                        "range": {"sheetId": sheet_id, "startRowIndex": 4, "endRowIndex": end_r, "startColumnIndex": c, "endColumnIndex": c + 1},

                        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},

                        "fields": "userEnteredFormat(horizontalAlignment)"

                    }

                })
            requests.append({

                "repeatCell": {

                    "range": {"sheetId": sheet_id, "startRowIndex": 4, "endRowIndex": end_r, "startColumnIndex": 3, "endColumnIndex": 4},

                    "cell": {

                        "userEnteredFormat": {

                            "textFormat": {"bold": True, "fontFamily": "Roboto", "fontSize": 10},

                            "horizontalAlignment": "RIGHT",

                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}

                        }

                    },

                    "fields": "userEnteredFormat(textFormat,horizontalAlignment,numberFormat)"

                }

            })
            # Apply alternating row background FIRST
            for r_idx in range(4, end_r):
                if r_idx % 2 == 1:
                    requests.append({
                        "repeatCell": {
                            "range": {"sheetId": sheet_id, "startRowIndex": r_idx, "endRowIndex": r_idx + 1, "startColumnIndex": 0, "endColumnIndex": 19},
                            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.988, "green": 0.969, "blue": 0.980}}},
                            "fields": "userEnteredFormat(backgroundColor)"
                        }
                    })

            # Apply mint green badge to Column 10 (I/A) AFTER zebra rows so it is never overwritten
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 4, "endRowIndex": end_r, "startColumnIndex": 10, "endColumnIndex": 11},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.824, "green": 0.941, "blue": 0.851},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 0.125, "green": 0.380, "blue": 0.196}},
                            "horizontalAlignment": "CENTER"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                }
            })

            # Clear background and borders from leftover empty rows below end_r (e.g. Row 39+)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": end_r, "endRowIndex": end_r + 30, "startColumnIndex": 0, "endColumnIndex": 19},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor)"
                }
            })
            none_border = {"style": "NONE"}
            requests.append({
                "updateBorders": {
                    "range": {"sheetId": sheet_id, "startRowIndex": end_r, "endRowIndex": end_r + 30, "startColumnIndex": 0, "endColumnIndex": 19},
                    "top": none_border, "bottom": none_border, "left": none_border, "right": none_border,
                    "innerHorizontal": none_border, "innerVertical": none_border
                }
            })
            border_spec = {"style": "SOLID", "width": 1, "color": {"red": 0.878, "green": 0.843, "blue": 0.906}}

            requests.append({

                "updateBorders": {

                    "range": {"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": end_r, "startColumnIndex": 0, "endColumnIndex": 19},

                    "top": border_spec, "bottom": border_spec, "left": border_spec, "right": border_spec,

                    "innerHorizontal": border_spec, "innerVertical": border_spec

                }

            })
        requests.append({

            "updateSheetProperties": {

                "properties": {

                    "sheetId": sheet_id,

                    "gridProperties": {

                        "frozenRowCount": 4

                    }

                },

                "fields": "gridProperties.frozenRowCount"

            }

        })
        sh.batch_update({"requests": requests})

        return {"status": "success", "count": len(all_assets), "amount": total_val}

    except Exception as e:

        import traceback

        print(f"Error syncing assets tab: {e}\n{traceback.format_exc()}")

        return {"status": "error", "message": str(e)}

