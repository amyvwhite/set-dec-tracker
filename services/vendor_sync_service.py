import os
import re
import json
import gspread
from core.settings import load_settings
from services.sheets import get_client, extract_spreadsheet_id

def norm(s):
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'[\'\".,/\\()\-&`+!#]', ' ', s)
    s = re.sub(r'\b(inc|ltd|llc|corp|co|the|warehouse|shop|holdings|dba)\b', ' ', s)
    return ' '.join(s.split())

# Standard categories/vendors to completely exclude from master prop/vendor list
EXCLUDED_CATEGORIES = {
    # Big-box chains & supermarkets
    'home depot', 'canadian tire', 'ikea', 'costco', 'rona', 'walmart', 'loblaws',
    'value village', 'homesense', 'winners', 'marshalls', 'dollarama', 'dollar tree', 'giant tiger',
    'farm boy', 'food basics', 'fortinos', 'no frills', 'metro', 'sobeys', 'longos', 'wholesale club',
    'staples', 'best buy', 'michaels', 'wayfair', 'structube', 'simons', 'west elm', 'bouclair', 'cb2', 'pottery barn', 'urban barn',
    'the brick', 'linen chest', 'jysk', 'muji', 'old navy', 'h&m', 'zara',
    # Craft, food, restaurants, takeout
    'tim hortons', 'mcdonalds', 'starbucks', 'subway', 'avenue cafe', 'burger shack', 'eddies meat',
    'eddie s meat', 'palm bites', 'nut factory', 'the nut factory', 'almast',
    # Fuel, gas stations, travel
    'petro canada', 'petro-canada', 'esso', 'shell', 'pioneer', 'circle k', 'bvd', 'bvd petroleum',
    'husk', 'husky', 'speedway', 'chevron', 'sunoco', 'mobil', 'gas station',
    'uber', 'lyft', 'taxi', 'cab',
    'toronto parking', 'toronto parking authority', 'city of toronto', 'city of hamilton', 'green p', 'impark', 'sp',
    # Shipping & generic
    'fedex', 'ups', 'canada post', 'open po', 'pending vendor', 'various', 'misc',
    # Thrift & charity stores requested to be excluded
    'mission thrift', 'mission thrift store', 'habitat for humanity', 'restore'
}

def is_excluded_vendor(vendor_name: str, item_description: str = "") -> bool:
    """Checks whether the vendor or purchase should be excluded (craft, food, fuel, gas, etc.)."""
    v_norm = norm(vendor_name)
    desc_lower = (item_description or "").lower()

    # Direct match in EXCLUDED_CATEGORIES
    for ex in EXCLUDED_CATEGORIES:
        ex_norm = norm(ex)
        if ex_norm and (ex_norm in v_norm or v_norm in ex_norm):
            return True

    # Fuel / gas detection
    fuel_keywords = ['fuel', 'gasoline', 'gas station', 'diesel', 'petroleum', 'propane tank']
    if any(k in v_norm for k in fuel_keywords) or any(k in desc_lower for k in fuel_keywords):
        return True

    # Craft / catering / food keywords
    craft_keywords = ['craft:', 'craft service', 'catering', 'takeout', 'drive-thru', 'fast food', 'restaurant', 'bakery', 'deli']
    if any(k in desc_lower for k in craft_keywords):
        return True

    return False

def format_vendor_title(name: str) -> str:
    """Formats a vendor name into Title Case, preserving common acronyms."""
    if not name:
        return ""
    words = name.strip().split()
    acronyms = {'inc', 'inc.', 'ltd', 'ltd.', 'llc', 'llc.', 'corp', 'corp.', 'tv', 'led', 'usa', 'gta', 'ont', 'hvac'}
    out = []
    for w in words:
        if w.lower() in acronyms:
            out.append(w.upper())
        elif w.lower() in ['and', '&', 'of', 'for', 'by', 'in', 'on', 'at', 'to', 'the'] and out:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out)

def lookup_online_vendor_info(vendor_name: str, item_description: str = ""):
    """
    Uses Gemini AI with web search grounding to find the official business catalog,
    general summary of what they sell or rent (not specific receipt items),
    website, contact person, phone number, email address, physical address, and store hours.
    """
    settings = load_settings()
    api_key = settings.get("gemini_api_key", "")
    info = {
        "summary": "",
        "classification": "Purchase",
        "website": "",
        "contact": "",
        "phone": "",
        "email": "",
        "address": "",
        "hours": ""
    }
    if not api_key or not vendor_name:
        return info

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            f"You are a professional set decorator and production coordinator for film and television in Ontario, Canada (Toronto/GTA).\n"
            f"Research official business information for vendor: '{vendor_name}'.\n"
            f"Context (one transaction receipt line): '{item_description}'.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. DO NOT simply output the specific items bought in the context (e.g. do NOT say 'lexington media unit', 'tarp mesh', '2 bouquets of lilies').\n"
            "2. Instead, summarize what the vendor sells or rents overall as a business (e.g., 'Consignment furniture, vintage home decor, lighting, mirrors' or 'Industrial tools, safety supplies, material handling, hardware').\n"
            "3. State whether they primarily offer Rental, Purchase, or both.\n"
            "4. Provide the official website domain, contact phone, contact email, physical address, and business hours.\n\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            "{\n"
            '  "summary": "comprehensive 5-10 word category summary of what the company sells or rents (general merchandise categories)",\n'
            '  "classification": "Rental or Purchase",\n'
            '  "website": "official domain or url (e.g. example.com)",\n'
            '  "contact": "name of contact person or department if known, or blank",\n'
            '  "phone": "primary phone number with area code",\n'
            '  "email": "primary contact or sales email address if known",\n'
            '  "address": "full physical address including street, city, province/state, postal code",\n'
            '  "hours": "standard business or store hours"\n'
            "}\n"
            "Do not include code markdown fences or additional explanation."
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt]
        )
        if response and response.text:
            cleaned = response.text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            data = json.loads(cleaned)
            for k in info:
                if data.get(k):
                    info[k] = str(data[k]).strip()
    except Exception as e:
        print(f"lookup_online_vendor_info error for '{vendor_name}': {e}")

    return info

def sync_new_vendor_to_sheet(vendor_name: str, item_description: str = "", is_rental: bool = False, rental_period: str = ""):
    """
    Checks if vendor_name exists in:
    1. The active show's Master Vendor List Google Sheet (e.g., 2026 VENDOR LIST).
    2. The show-specific Vendor List (e.g., Vendor List SAMPLE).
    If it is a brand-new vendor, researches what they sell/rent online and appends to BOTH sheets
    with complete info, summary of merchandise, and formatting.
    """
    if not vendor_name or not vendor_name.strip():
        return False

    vendor_clean = format_vendor_title(vendor_name)
    norm_v = norm(vendor_clean)
    if not norm_v:
        return False

    # Block craft, fuel, gas, and excluded vendors immediately
    if is_excluded_vendor(vendor_clean, item_description):
        print(f"sync_new_vendor_to_sheet: Vendor '{vendor_clean}' excluded (craft/fuel/chain/unwanted).")
        return False

    settings = load_settings()
    master_url = settings.get("vendor_list_url")
    sample_url = settings.get("rental_agreements_sheet_url")

    # Research info once so both sheets can be enriched
    online_info = None

    # Determine classification
    classification = "Purchase"
    item_lower = (item_description or "").lower()
    if is_rental or (rental_period and str(rental_period).strip()) or any(w in item_lower for w in ['rent', 'rental', 'prop']):
        classification = "Rental"

    # --- 1. Sync to Master Sheet ---
    if master_url and master_url.strip():
        try:
            client = get_client()
            m_id = extract_spreadsheet_id(master_url)
            sh_master = client.open_by_key(m_id)
            ws_master = sh_master.sheet1
            
            existing_master = ws_master.col_values(1)
            is_in_master = False
            for ev in existing_master:
                if not ev: continue
                nev = norm(ev)
                if nev == norm_v or (len(norm_v) >= 5 and norm_v in nev) or (len(nev) >= 5 and nev in norm_v):
                    is_in_master = True
                    break

            if not is_in_master:
                if online_info is None:
                    online_info = lookup_online_vendor_info(vendor_clean, item_description)

                # Use the researched summary of what they sell/rent rather than specific receipt items
                summary_items = online_info.get("summary", "").strip()
                if not summary_items:
                    summary_items = "Set decoration furnishings, props & supplies"

                if online_info.get("classification") in ["Rental", "Purchase"]:
                    classification = online_info["classification"]

                if classification == "Rental" and not any(w in summary_items.lower() for w in ['rent', 'rental', 'prop']):
                    summary_items = f"{summary_items} (Rental)"

                next_idx = len(existing_master) + 1
                if next_idx > ws_master.row_count:
                    ws_master.add_rows(20)

                new_master_row = [
                    vendor_clean,                   # VENDORS (A)
                    summary_items,                  # Items (B)
                    classification,                 # Rental / Purchase (C)
                    online_info.get("website", ""), # Website (D)
                    online_info.get("contact", ""), # Contact (E)
                    online_info.get("phone", ""),   # Phone # (F)
                    online_info.get("email", ""),   # Email (G)
                    online_info.get("address", ""), # Address (H)
                    online_info.get("hours", "")    # Hours (I)
                ]

                range_target = f"Sheet1!A{next_idx}:I{next_idx}"
                client.http_client.request(
                    'put',
                    f"https://sheets.googleapis.com/v4/spreadsheets/{m_id}/values/{range_target}?valueInputOption=USER_ENTERED",
                    json={'values': [new_master_row]}
                )

                # Format row matching row 623
                meta = sh_master.fetch_sheet_metadata({'includeGridData': True, 'ranges': ['Sheet1!A623:I623']})
                template_cells = meta['sheets'][0]['data'][0]['rowData'][0]['values']
                format_requests = []
                for col_idx, cell in enumerate(template_cells):
                    fmt = cell.get('userEnteredFormat', {})
                    format_requests.append({
                        'repeatCell': {
                            'range': {
                                'sheetId': ws_master.id,
                                'startRowIndex': next_idx - 1,
                                'endRowIndex': next_idx,
                                'startColumnIndex': col_idx,
                                'endColumnIndex': col_idx + 1
                            },
                            'cell': {'userEnteredFormat': fmt},
                            'fields': 'userEnteredFormat(backgroundColor,borders,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)'
                        }
                    })
                sh_master.batch_update({'requests': format_requests})
                print(f"Successfully added brand-new vendor '{vendor_clean}' to Master Vendor List at row {next_idx}!")
        except Exception as e:
            print(f"Error syncing vendor '{vendor_name}' to Master Vendor List: {e}")

    # --- 2. Sync to SAMPLE Sheet (Show Specific Vendor List) ---
    if sample_url and sample_url.strip():
        try:
            client = get_client()
            sample_id = extract_spreadsheet_id(sample_url)
            sh_sample = client.open_by_key(sample_id)
            ws_sample = sh_sample.sheet1
            
            existing_sample = ws_sample.col_values(1)
            is_in_sample = False
            for ev in existing_sample:
                if not ev: continue
                nev = norm(ev)
                if nev == norm_v or (len(norm_v) >= 5 and norm_v in nev) or (len(nev) >= 5 and nev in norm_v):
                    is_in_sample = True
                    break

            if not is_in_sample:
                if online_info is None:
                    online_info = lookup_online_vendor_info(vendor_clean, item_description)

                next_sample_idx = len(existing_sample) + 1
                if next_sample_idx > ws_sample.row_count:
                    ws_sample.add_rows(20)

                contact_parts = []
                if online_info.get("contact"): contact_parts.append(online_info["contact"])
                if online_info.get("phone"): contact_parts.append(online_info["phone"])
                if online_info.get("email"): contact_parts.append(online_info["email"])
                contact_str = ", ".join(contact_parts) if contact_parts else online_info.get("phone", "")

                new_sample_row = [
                    vendor_clean,                   # VENDOR (A)
                    online_info.get("website", ""), # WEBSITE (B)
                    contact_str,                    # CONTACT (C)
                    "",                             # CREDIT APP/ACCOUNT (D)
                    "",                             # ACCOUNT # / LOGIN (E)
                    "",                             # PASSWORD (F)
                    "",                             # DEPOSIT CHEQUE (G)
                    ""                              # RENTAL AGREEMENT (H)
                ]

                range_target = f"Sheet1!A{next_sample_idx}:H{next_sample_idx}"
                client.http_client.request(
                    'put',
                    f"https://sheets.googleapis.com/v4/spreadsheets/{sample_id}/values/{range_target}?valueInputOption=USER_ENTERED",
                    json={'values': [new_sample_row]}
                )

                # Format font and alignment
                format_reqs = [
                    {
                        'repeatCell': {
                            'range': {
                                'sheetId': ws_sample.id,
                                'startRowIndex': next_sample_idx - 1,
                                'endRowIndex': next_sample_idx,
                                'startColumnIndex': 0,
                                'endColumnIndex': 8
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'textFormat': {
                                        'fontFamily': 'Arial',
                                        'fontSize': 10
                                    },
                                    'verticalAlignment': 'MIDDLE',
                                    'wrapStrategy': 'WRAP'
                                }
                            },
                            'fields': 'userEnteredFormat.textFormat,userEnteredFormat.verticalAlignment,userEnteredFormat.wrapStrategy'
                        }
                    }
                ]
                sh_sample.batch_update({'requests': format_reqs})
                print(f"Successfully added brand-new vendor '{vendor_clean}' to Vendor List SAMPLE at row {next_sample_idx}!")
        except Exception as e:
            print(f"Error syncing vendor '{vendor_name}' to Vendor List SAMPLE: {e}")

    return True
