import re
import json
import datetime
from core.settings import load_settings
from services.sheets import get_client, extract_spreadsheet_id

def norm_vendor(s):
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'[\'\".,/\\()\-&`+!#]', ' ', s)
    s = re.sub(r'\b(inc|ltd|llc|corp|co|the|warehouse|shop|holdings|dba)\b', ' ', s)
    return ' '.join(s.split())

def lookup_vendor_details(vendor_name: str):
    """
    Looks up website and contact info for a vendor:
    1. Checks local vendor_profiles in settings.
    2. Checks Master Vendor List Google Sheet.
    3. If still missing website or contact info, queries Gemini with live Google Search
       to find official website, phone, email, and address in Ontario/Canada.
    """
    website = ""
    contact_info = ""
    norm_target = norm_vendor(vendor_name)
    if not norm_target:
        return website, contact_info

    settings = load_settings()

    # 1. Check local vendor_profiles
    try:
        profiles = settings.get("vendor_profiles", {})
        for vp_name, vp_data in profiles.items():
            if norm_vendor(vp_name) == norm_target:
                parts = []
                if vp_data.get("contact"): parts.append(vp_data["contact"])
                if vp_data.get("tel"): parts.append(vp_data["tel"])
                addr = ", ".join(filter(None, [vp_data.get("address1", ""), vp_data.get("address2", "")]))
                if addr: parts.append(addr)
                if parts and not contact_info:
                    contact_info = ", ".join(parts)
                break
    except Exception as e:
        print(f"vendor_profiles lookup error for {vendor_name}: {e}")

    # 2. Check Master Vendor List Sheet
    try:
        master_url = settings.get("vendor_list_url")
        if master_url:
            client = get_client()
            m_id = extract_spreadsheet_id(master_url)
            sh = client.open_by_key(m_id)
            rows = sh.sheet1.get_all_values()
            for r in rows[1:]:
                if r and r[0].strip():
                    nv = norm_vendor(r[0].strip())
                    if nv == norm_target or (len(norm_target) >= 4 and norm_target in nv) or (len(nv) >= 4 and nv in norm_target):
                        if len(r) > 3 and r[3].strip() and not website:
                            website = r[3].strip()
                        parts = []
                        if len(r) > 4 and r[4].strip(): parts.append(r[4].strip())
                        if len(r) > 5 and r[5].strip(): parts.append(r[5].strip())
                        if len(r) > 6 and r[6].strip(): parts.append(r[6].strip())
                        if len(r) > 7 and r[7].strip(): parts.append(r[7].strip())
                        if parts and not contact_info:
                            contact_info = ", ".join(parts)
                        break
    except Exception as e:
        print(f"Master vendor list lookup error for {vendor_name}: {e}")

    # 3. If website or contact_info still missing, query Gemini with live Google Search
    if not website or not contact_info:
        try:
            api_key = settings.get("gemini_api_key", "")
            if api_key:
                from google import genai
                ai_client = genai.Client(api_key=api_key)
                prompt = (
                    f"Look up the official website and business contact information for this business in Ontario, Canada: {vendor_name}.\n"
                    "Return a JSON object with:\n"
                    "- 'website': the official website URL (e.g. 'https://example.com' or 'example.com')\n"
                    "- 'phone': main phone number\n"
                    "- 'email': contact email address if available\n"
                    "- 'address': street address, city, province, postal code if available\n"
                    "Respond with ONLY valid JSON."
                )
                resp = ai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config={"tools": [{"google_search": {}}]}
                )
                if resp and resp.text:
                    txt = resp.text.strip()
                    txt = re.sub(r'^```json\s*', '', txt)
                    txt = re.sub(r'^```\s*', '', txt)
                    txt = re.sub(r'\s*```$', '', txt)
                    data = json.loads(txt)
                    if not website and data.get("website"):
                        w = data["website"].strip()
                        if not w.startswith("http"):
                            w = f"https://{w}"
                        website = w
                    
                    c_parts = []
                    if isinstance(data.get("contact_info"), dict):
                        ci = data["contact_info"]
                        if ci.get("phone"): c_parts.append(str(ci["phone"]).strip())
                        if ci.get("email"): c_parts.append(str(ci["email"]).strip())
                        if ci.get("address"): c_parts.append(str(ci["address"]).strip())
                    else:
                        if data.get("phone"): c_parts.append(str(data["phone"]).strip())
                        if data.get("email"): c_parts.append(str(data["email"]).strip())
                        if data.get("address"): c_parts.append(str(data["address"]).strip())
                    
                    if c_parts and not contact_info:
                        contact_info = ", ".join(c_parts)
        except Exception as e:
            print(f"Gemini live web search lookup error for {vendor_name}: {e}")

    return website, contact_info

def update_rental_agreement_sheet_status(vendor_name: str, status_text: str = None, is_completed: bool = True, date_str: str = None, contact_info: str = "", website: str = ""):
    """
    Updates or appends a vendor in the Rental Agreements Google Sheet.
    - If is_completed is True: sets status to 'COMPLETED <date>' with green background (#b6d7a8).
    - If is_completed is False: sets status to 'SENT TO VENDOR <date>' with orange background (#f9cb9c).
    Ensures NO duplicates are created and that Website & Contact info are completely populated.
    """
    if not vendor_name or not vendor_name.strip():
        return False

    vendor_clean = vendor_name.strip()
    norm_v = norm_vendor(vendor_clean)
    if not norm_v:
        return False

    now = datetime.datetime.now()
    if not date_str:
        date_str = now.strftime('%m/%d')
    else:
        clean_d = re.sub(r'[^0-9/]', '', date_str)
        if clean_d:
            date_str = clean_d

    if not status_text:
        if is_completed:
            status_text = f"COMPLETED {date_str}"
        else:
            status_text = f"SENT TO VENDOR {date_str}"

    settings = load_settings()
    sheet_url = settings.get("rental_agreements_sheet_url")
    if not sheet_url or not sheet_url.strip():
        print("update_rental_agreement_sheet_status: No rental_agreements_sheet_url configured in settings.")
        return False

    try:
        client = get_client()
        spreadsheet_id = extract_spreadsheet_id(sheet_url)
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.sheet1

        rows = ws.get_all_values()
        existing_vendors = [r[0].strip() if r and len(r) > 0 else "" for r in rows]

        matched_row_idx = None
        for idx, ev in enumerate(existing_vendors[1:], start=2):
            if not ev:
                continue
            nev = norm_vendor(ev)
            if nev == norm_v or (len(norm_v) >= 4 and norm_v in nev) or (len(nev) >= 4 and nev in norm_v):
                matched_row_idx = idx
                break

        bg_color = {
            "red": 0.7137255,
            "green": 0.84313726,
            "blue": 0.65882355
        } if is_completed else {
            "red": 0.9764706,
            "green": 0.79607844,
            "blue": 0.6117647
        }

        sheet_id = ws.id

        # If website or contact missing, look them up automatically
        if not website or not contact_info:
            lk_web, lk_contact = lookup_vendor_details(vendor_clean)
            if not website:
                website = lk_web
            if not contact_info:
                contact_info = lk_contact

        if matched_row_idx:
            # Update existing row Column H (col 8, 0-based col 7)
            ws.update_acell(f"H{matched_row_idx}", status_text)
            
            # If existing row was missing website or contact, backfill them
            cur_r = rows[matched_row_idx - 1]
            cur_web = cur_r[1].strip() if len(cur_r) > 1 else ""
            cur_contact = cur_r[2].strip() if len(cur_r) > 2 else ""
            if (not cur_web and website) or (not cur_contact and contact_info):
                fill_web = cur_web or website
                fill_contact = cur_contact or contact_info
                ws.update(f"B{matched_row_idx}:C{matched_row_idx}", [[fill_web, fill_contact]])

            format_req = {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": matched_row_idx - 1,
                        "endRowIndex": matched_row_idx,
                        "startColumnIndex": 7,
                        "endColumnIndex": 8
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": bg_color
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor"
                }
            }
            sh.batch_update({"requests": [format_req]})
            print(f"Updated rental agreement status for '{vendor_clean}' at row {matched_row_idx} to '{status_text}'.")
            return True
        else:
            # Append new vendor row at the bottom of data
            last_data_idx = len(existing_vendors)
            while last_data_idx > 0 and not any(rows[last_data_idx - 1]):
                last_data_idx -= 1
            new_row_idx = last_data_idx + 1

            new_row = [
                vendor_clean,   # VENDOR (A)
                website,        # WEBSITE (B)
                contact_info,   # CONTACT (C)
                "",             # CREDIT APP/ACCOUNT (D)
                "",             # ACCOUNT # / LOGIN (E)
                "",             # PASSWORD (F)
                "",             # DEPOSIT CHEQUE (G)
                status_text     # RENTAL AGREEMENT (H)
            ]

            if new_row_idx > ws.row_count:
                ws.add_rows(20)

            ws.update(f"A{new_row_idx}:H{new_row_idx}", [new_row])

            # Apply formatting
            format_reqs = [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": new_row_idx - 1,
                            "endRowIndex": new_row_idx,
                            "startColumnIndex": 7,
                            "endColumnIndex": 8
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": bg_color
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor"
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": new_row_idx - 1,
                            "endRowIndex": new_row_idx,
                            "startColumnIndex": 0,
                            "endColumnIndex": 8
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {
                                    "fontFamily": "Arial",
                                    "fontSize": 10
                                },
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP"
                            }
                        },
                        "fields": "userEnteredFormat.textFormat,userEnteredFormat.verticalAlignment,userEnteredFormat.wrapStrategy"
                    }
                }
            ]
            sh.batch_update({"requests": format_reqs})
            print(f"Appended new vendor '{vendor_clean}' at row {new_row_idx} with complete info & status '{status_text}'.")
            return True

    except Exception as e:
        print(f"Error updating rental agreement sheet for '{vendor_name}': {e}")
        return False
