import os
import json
import fitz  # PyMuPDF
from google import genai
import PIL.Image
import io
from datetime import datetime, timedelta

def add_business_days(start_date, days_to_add):
    current_date = start_date
    while days_to_add > 0:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5: # Monday is 0, Friday is 4
            days_to_add -= 1
    return current_date

app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
TEMPLATE_PATH = os.path.join(show_dir, "CH REQS", "00 Cheque Requisiton Form.pdf")
SETTINGS_PATH = os.path.join(app_dir, "settings.json")
OUTPUT_DIR = os.path.join(show_dir, "CH REQS")
SET_LIST_PATH = os.path.join(show_dir, "CH REQS", "set_list.json")

def load_api_key():
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
            return data.get("gemini_api_key", "")
    except Exception as e:
        print("Could not load API key:", e)
        return ""

def extract_invoice_data(file_path):
    api_key = load_api_key()
    if not api_key:
        raise ValueError("Could not find Gemini API key in settings.")

    client = genai.Client(api_key=api_key)
    
    try:
        # Load the file - support multi-page PDFs so invoice data across all pages is captured!
        images = []
        if file_path.lower().endswith('.pdf'):
            doc = fitz.open(file_path)
            # Read up to 8 pages to capture multi-page invoices/orders
            for page_num in range(min(len(doc), 8)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=150)
                img_page = PIL.Image.open(io.BytesIO(pix.tobytes("png"))).convert('RGB')
                w, h = img_page.size
                max_dim = 2048
                if max(w, h) > max_dim:
                    img_page.thumbnail((max_dim, max_dim), PIL.Image.Resampling.LANCZOS)
                images.append(img_page)
            doc.close()
        else:
            img = PIL.Image.open(file_path)
            w, h = img.size
            max_dim = 2048
            if max(w, h) > max_dim:
                img.thumbnail((max_dim, max_dim), PIL.Image.Resampling.LANCZOS)
            images = [img]

        # Build dynamic set list from settings
        from core.settings import load_settings
        settings_data = load_settings()
        dynamic_sets = settings_data.get("dynamic_sets", {})
        set_list_str = ""
        if dynamic_sets:
            for ep_name, sets in dynamic_sets.items():
                set_list_str += f"{ep_name}: " + ", ".join([s['code'] for s in sets]) + "; "
        else:
            set_list_str = "A10-A31 for EP 201, B10-B35 for EP 202, C10-C34 for EP 203, X80-X86 for Amort Sets"

        prompt = f"""
        Extract the following details from this invoice and return it strictly as a JSON object with these keys:
        - Payee (String, the company or person to be paid. CRITICAL: If a numbered legal entity name like '1234567 CANADA INC.' is present alongside a trade name, format it as '1234567 CANADA INC. dba [Trade Name]'. Otherwise, just use the company name. IMPORTANT: If the receipt says 'Amazon.com.ca', 'Amazon', or has 'www.amazon.ca', the Payee MUST ALWAYS be 'AMAZON.CA', regardless of the 'Sold by' company.)
        - Date (String, in format DD-MMM-YYYY or natural format like Jan 1, 2026)
        - AddressLine1 (String, the VENDOR'S street address or unit number. DO NOT use the billing address or buyer's address like Sample Productions Inc)
        - AddressLine2 (String, the VENDOR'S city, province/state, postal code, country)
        - Contact (String, the sales rep or contact person from the vendor, NOT internal people like Nick or Jordan. If none, leave empty)
        - Tel (String, the vendor's phone number if any)
        - TotalAmount (String, numerical total amount including tax, just numbers/decimals. IMPORTANT: If this is a return or a refund, ensure this number is negative.)
        - AmountBeforeHST (String, subtotal before tax. CRITICAL: On a Cheque Requisition, this represents the total expenditure before tax to be paid, SO IT MUST INCLUDE packaging, handling, delivery, shipping, and any other non-tax fees. If there are any discounts, subtract them. Formula: Total Amount minus HST/Tax Amount. If return, make negative.)
        - HSTAmount (String, the tax amount. IMPORTANT: If the receipt lists a quantity > 1 and the tax shown is per-unit (like on Amazon invoices), you MUST multiply the unit tax by the quantity to get the total tax.)
        - HSTNumber (String, the tax/HST/GST number if provided)
        - Details (String, Provide a clean, summarized list of the items bought. REMOVE all receipt jargon, product codes, random numbers, dimensions/sizes. If this is a return/refund, you MUST prefix with 'rtn: '. NEVER use the generic term 'hardware' unless explicitly written.)
        - ReferenceNumber (String, the invoice number, order number, or reference number, e.g. '7149', '53670', 'INV-019967'. Prefer the INVOICE NUMBER over an order or quote number if an invoice number is present. Do NOT include prefix words like 'INVOICE #', just the number/code)
        - RentalPeriod (String, the start and end dates of the rental, formatted strictly as 'Month Day - Month Day' (e.g. 'Nov 2 - Nov 16' or 'Oct 20 - Oct 27'). 
          HOW TO DETERMINE THE RENTAL PERIOD:
          1. If an explicit start and end date range is stated anywhere on the invoice/order (e.g. 'Oct 20 - Oct 27'), use that range.
          2. Rental Start Date: Look for the designated pickup date (e.g. 'Desired Pick-Up Date', 'Pick-up Date', 'Pickup Date', 'Start Date'). If no pickup date is stated anywhere on the document, use the Invoice Date or Order Date as the start date.
          3. Rental Duration & End Date: Check the invoice text/terms for rental duration rules (e.g. 'short term rentals are for up to 2 wks' or '2 weeks' -> calculate 2 weeks / 14 days from the pickup/start date; '1 week' -> calculate 7 days; '1 month' -> calculate 30 days). If no duration rule is specified, default to 1 week (7 days) from the start date.
          4. Output formatted strictly as 'Month Day - Month Day' (e.g. 'Nov 2 - Nov 16'). If not a rental and no rental dates/terms exist, leave empty.)
        - SetLocation (String, the set code or set name if mentioned, e.g. 'A14 - CITY REC CENTER', 'B10', 'B15', 'X80', 'A16'. Refer to Set List: {set_list_str}. If set code like A14 or B10 is found, output the set code)
        - PaymentType (String, 'ACH' if invoice/order mentions ACH, direct deposit, wire, EFT, or paid via ACH; else 'CH REQ')
        - Episode (String, episode number if mentioned, e.g. '201', '202', '203', '204', '205', '206', '252', '259', or 'AMORT', else empty)
        - RequestedBy (String, the person requesting or 'buyer' if mentioned, else empty)
        
        CRITICAL MULTI-PAGE / COMBINED INVOICE RULES:
        If this PDF document contains multiple pages, multiple sub-invoices, or multiple shipments representing one combined transaction:
        * You MUST SUM UP the subtotal, tax/HST, and total across ALL pages/invoices into one single grand total bill.
        * Combine all item descriptions across all pages into a clean, combined description list.
        * Output ONE single JSON object for the combined transaction.
        
        CRITICAL HIGHLIGHTED ITEMS RULES:
        If a receipt or invoice contains HIGHLIGHTED text, lines, or items (e.g., color highlighter marked line items):
        * ONLY extract and sum up line items that are HIGHLIGHTED.
        * Calculate the subtotal, tax, and final total strictly for the HIGHLIGHTED portion.
        * Combine descriptions ONLY for highlighted items.
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt] + images,
            config={'response_mime_type': 'application/json'}
        )
        
        if not response or not response.text:
            return None
            
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        parsed_data = json.loads(text.strip())

        # Ensure AmountBeforeHST includes shipping/packaging (TotalAmount - HSTAmount)
        if parsed_data:
            try:
                tot_val = float(str(parsed_data.get("TotalAmount", "")).replace("$", "").replace(",", "").strip())
                hst_val = float(str(parsed_data.get("HSTAmount", "")).replace("$", "").replace(",", "").strip()) if str(parsed_data.get("HSTAmount", "")).strip() else 0.0
                calc_net = round(tot_val - hst_val, 2)
                curr_sub_str = str(parsed_data.get("AmountBeforeHST", "")).replace("$", "").replace(",", "").strip()
                curr_sub = float(curr_sub_str) if curr_sub_str else None
                # If parsed subtotal excluded shipping/packaging, or is missing, or equals total with tax present, use calc_net
                if tot_val > 0 and hst_val > 0:
                    if curr_sub is None or curr_sub == tot_val or abs((curr_sub + hst_val) - tot_val) > 0.05:
                        parsed_data["AmountBeforeHST"] = f"{calc_net:.2f}"
                elif curr_sub is None or (calc_net > 0 and curr_sub < calc_net - 0.05):
                    parsed_data["AmountBeforeHST"] = f"{calc_net:.2f}"
            except Exception:
                pass
        from services.ch_req_sheet_helper import normalize_rental_period
        if parsed_data and "RentalPeriod" in parsed_data:
            parsed_data["RentalPeriod"] = normalize_rental_period(parsed_data["RentalPeriod"])

        # Automatic Vendor & Legal Entity Normalization
        if parsed_data and "Payee" in parsed_data:
            p_upper = str(parsed_data["Payee"]).strip().upper()
            if "ALLEN GALLERY" in p_upper or "SUPA" in p_upper:
                parsed_data["Payee"] = "SUPA HOLDINGS dba ALLEN GALLERY ART SALES & RENTALS"
                if not parsed_data.get("HSTNumber"):
                    parsed_data["HSTNumber"] = "805615960"
                if not parsed_data.get("AddressLine1"):
                    parsed_data["AddressLine1"] = "2965 Lake Shore Blvd. W."
                if not parsed_data.get("AddressLine2"):
                    parsed_data["AddressLine2"] = "Toronto ON M8V 1J5"
                if not parsed_data.get("Tel"):
                    parsed_data["Tel"] = "+14165262636"
            elif "GOOD DOG" in p_upper:
                parsed_data["Payee"] = "8752311 CANADA INC. dba GOOD DOG DIGITAL"
                if not parsed_data.get("HSTNumber"):
                    parsed_data["HSTNumber"] = "831605779"
            elif "EXECUTIVE FURNITURE" in p_upper:
                parsed_data["Payee"] = "4206720 CANADA INC. dba EXECUTIVE FURNITURE RENTALS"

        # Check remembered vendor profile (legal entity, address, tel, HST, payment type)
        if parsed_data and "Payee" in parsed_data:
            try:
                from core.settings import get_vendor_profile
                prof = get_vendor_profile(parsed_data["Payee"])
                if prof:
                    if prof.get("payee") and ("dba" in str(prof["payee"]).lower() or "inc" in str(prof["payee"]).lower()):
                        parsed_data["Payee"] = prof["payee"]
                    if not parsed_data.get("AddressLine1") and prof.get("address1"):
                        parsed_data["AddressLine1"] = prof["address1"]
                    if not parsed_data.get("AddressLine2") and prof.get("address2"):
                        parsed_data["AddressLine2"] = prof["address2"]
                    if not parsed_data.get("Tel") and prof.get("tel"):
                        parsed_data["Tel"] = prof["tel"]
                    if not parsed_data.get("HSTNumber") and prof.get("hst_number"):
                        parsed_data["HSTNumber"] = prof["hst_number"]
                    if not parsed_data.get("Contact") and prof.get("contact"):
                        parsed_data["Contact"] = prof["contact"]
                    if prof.get("payment_type"):
                        parsed_data["PaymentType"] = "ACH" if "ACH" in prof["payment_type"].upper() else "CH REQ"
            except Exception as e_prof:
                print(f"DEBUG: Error applying vendor profile: {e_prof}")

        return parsed_data
    except Exception as e:
        # fallback if rate limit hit
        if "429" in str(e) or "EXHAUSTED" in str(e).upper():
            import time
            time.sleep(5)
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[prompt] + images,
                    config={'response_mime_type': 'application/json'}
                )
                text = response.text.strip()
                if text.startswith("```json"):
                    text = text[7:-3]
                elif text.startswith("```"):
                    text = text[3:-3]
                parsed_data = json.loads(text.strip())
                if parsed_data:
                    try:
                        tot_val = float(str(parsed_data.get("TotalAmount", "")).replace("$", "").replace(",", "").strip())
                        hst_val = float(str(parsed_data.get("HSTAmount", "")).replace("$", "").replace(",", "").strip()) if str(parsed_data.get("HSTAmount", "")).strip() else 0.0
                        calc_net = round(tot_val - hst_val, 2)
                        curr_sub_str = str(parsed_data.get("AmountBeforeHST", "")).replace("$", "").replace(",", "").strip()
                        curr_sub = float(curr_sub_str) if curr_sub_str else None
                        if tot_val > 0 and hst_val > 0:
                            if curr_sub is None or curr_sub == tot_val or abs((curr_sub + hst_val) - tot_val) > 0.05:
                                parsed_data["AmountBeforeHST"] = f"{calc_net:.2f}"
                        elif curr_sub is None or (calc_net > 0 and curr_sub < calc_net - 0.05):
                            parsed_data["AmountBeforeHST"] = f"{calc_net:.2f}"
                    except Exception:
                        pass
                return parsed_data
            except Exception as e2:
                raise ValueError(f"Failed to extract text using AI: {e2}")
        raise ValueError(f"Failed to extract text using AI: {e}")

def generate_pdf(invoice_path, entries_data):
    doc = fitz.open(TEMPLATE_PATH)
    page = doc[0]
    
    set_loc = entries_data.get("SetLocation", "").strip().upper()
    
    # Special Set rule (e.g. X83 - X98 -> "X98 - TRES")
    from core.set_list import resolve_special_and_initial_set
    sp_info = resolve_special_and_initial_set(
        set_input=set_loc,
        special_tab=entries_data.get("special_tab"),
        notes=entries_data.get("Notes") or entries_data.get("delivery_notes")
    )
    if sp_info.get("is_special_98"):
        set_loc = sp_info.get("display_pdf_set")
    elif os.path.exists(SET_LIST_PATH):
        try:
            with open(SET_LIST_PATH, "r") as f:
                set_list = json.load(f)
            clean_set_loc = set_loc.replace(" ", "")
            for code, name in set_list.items():
                if clean_set_loc == code.upper():
                    set_loc = f"{code} - {name}"
                    break
        except Exception as e:
            print("Could not load set list:", e)
    
    payee_val = entries_data.get("Payee", "")
    hst_val = entries_data.get("HSTNumber", "")
    
    # Save full vendor profile memory (payee, address, tel, HST, contact, payment type)
    if payee_val:
        try:
            from core.settings import save_vendor_profile
            save_vendor_profile(payee_val, {
                "payee": payee_val,
                "address1": address1_val,
                "address2": address2_val,
                "tel": entries_data.get("Tel", ""),
                "hst_number": hst_val,
                "contact": entries_data.get("Contact", ""),
                "payment_type": entries_data.get("PaymentType") or entries_data.get("payment_type")
            })
        except Exception as e_save_prof:
            print(f"DEBUG: Could not save vendor profile: {e_save_prof}")
    address1_val = entries_data.get("AddressLine1", "")
    address2_val = entries_data.get("AddressLine2", "")

    if "GOOD DOG" in payee_val.upper():
        payee_pdf = "8752311 CANADA INC. dba GOOD DOG DIGITAL"
        hst_val = "831605779"
    elif "EXECUTIVE FURNITURE" in payee_val.upper():
        payee_pdf = "4206720 CANADA INC. dba EXECUTIVE FURNITURE RENTALS"
    elif "DIVINE FURNITURE" in payee_val.upper():
        payee_pdf = payee_val
        hst_val = "860957638RT0001"
    elif "ALLEN GALLERY" in payee_val.upper() or "SUPA" in payee_val.upper():
        payee_pdf = "SUPA HOLDINGS dba ALLEN GALLERY ART SALES & RENTALS"
        if not hst_val: hst_val = "805615960"
        if not address1_val: address1_val = "2965 Lake Shore Blvd. W."
        if not address2_val: address2_val = "Toronto ON M8V 1J5"
    else:
        payee_pdf = payee_val

    if "HERCULES" in payee_val.upper():
        address1_val = "120 St. Regis Crescent South"
        address2_val = "North York, ON M3J 1Y8"

    import textwrap
    from datetime import datetime
    details_text = entries_data.get("Details")
    if not details_text: details_text = ""
    
    from services.ch_req_sheet_helper import normalize_rental_period
    norm_rental = normalize_rental_period(entries_data.get("RentalPeriod", ""))

    is_rental = entries_data.get("PurchaseType") == "Rental" or bool(norm_rental.strip())
    if is_rental and not str(details_text).upper().startswith("RENTAL:"):
        details_text = f"RENTAL: {details_text}"
        
    details_lines = textwrap.wrap(str(details_text), width=75)

    # Enforce mathematical balance before filling PDF
    tot_str = str(entries_data.get("TotalAmount", "")).replace("$", "").replace(",", "").strip()
    hst_str = str(entries_data.get("HSTAmount", "")).replace("$", "").replace(",", "").strip()
    sub_str = str(entries_data.get("AmountBeforeHST", "")).replace("$", "").replace(",", "").strip()
    if tot_str and hst_str:
        try:
            tot_v = float(tot_str)
            hst_v = float(hst_str)
            sub_v = float(sub_str) if sub_str else 0.0
            if tot_v > 0 and hst_v > 0:
                if sub_v == tot_v or abs((sub_v + hst_v) - tot_v) > 0.05 or sub_v == 0.0:
                    entries_data["AmountBeforeHST"] = f"{round(tot_v - hst_v, 2):.2f}"
        except Exception:
            pass

    field_map = {
        "Payee 1": payee_pdf,
        "Date1_af_date": datetime.now().strftime("%d-%b-%Y"),
        "Address 1": address1_val,
        "Address 2": address2_val,
        "Contact": entries_data.get("Contact", ""),
        "Tel": entries_data.get("Tel", ""),
        "Text5": entries_data.get("TotalAmount", ""),
        "Amount Before GST 1": entries_data.get("AmountBeforeHST", ""),
        "Amount Before GST 2": entries_data.get("HSTAmount", ""),
        "HST/SIN": hst_val,
        "Episode": entries_data.get("Episode", ""),
        "Set Location": set_loc,
        "Rental Period": norm_rental,
        "Details 1": details_lines[0] if len(details_lines) > 0 else "",
        "Details 2": details_lines[1] if len(details_lines) > 1 else "",
        "Details 3": details_lines[2] if len(details_lines) > 2 else "",
        "Details 4": details_lines[3] if len(details_lines) > 3 else "",
        "Requested By": entries_data.get("RequestedBy", ""),
        "Date5_af_date": entries_data.get("DateRequired", ""),
        "Department": "SET DEC"
    }
    
    is_ach = (str(entries_data.get("PaymentType", "")).upper() == "ACH" or
              str(entries_data.get("payment_type", "")).upper() == "ACH" or
              entries_data.get("IsACH") is True)

    for widget in page.widgets():
        if widget.field_name in field_map:
            widget.field_value = str(field_map[widget.field_name])
        elif widget.field_name == "Check Box10": # Total Amount CN
            widget.field_value = True
            
        elif widget.field_name == "Check Box3": # Purchase
            has_rental_dates = bool(norm_rental.strip())
            is_purchase_type = entries_data.get("PurchaseType") == "Purchase"
            widget.field_value = not has_rental_dates and is_purchase_type
            
        elif widget.field_name == "Check Box4": # Rental
            has_rental_dates = bool(norm_rental.strip())
            is_rental_type = entries_data.get("PurchaseType") == "Rental"
            widget.field_value = has_rental_dates or is_rental_type
            
        elif widget.field_name == "ACH":
            widget.field_value = "Yes" if is_ach else "Off"
        elif widget.field_name == "Pickup":
            widget.field_value = "Off" if is_ach else "Yes"
        widget.update()
        
    temp_template = os.path.join(OUTPUT_DIR, "temp_template.pdf")
    doc.save(temp_template)
    doc.close()
    
    final_doc = fitz.open(temp_template)
    
    if invoice_path:
        if invoice_path.lower().endswith('.pdf'):
            invoice_doc = fitz.open(invoice_path)
            final_doc.insert_pdf(invoice_doc)
            invoice_doc.close()
        else:
            img_doc = fitz.open(invoice_path)
            pdf_bytes = img_doc.convert_to_pdf()
            img_pdf = fitz.open("pdf", pdf_bytes)
            final_doc.insert_pdf(img_pdf)
            img_pdf.close()
            img_doc.close()
        
    from core.file_manager import format_date_mm_dd_yyyy, get_canonical_vendor_dir
    
    vendor_dir = get_canonical_vendor_dir(OUTPUT_DIR, entries_data.get("Payee", ""))
    is_new_company = not os.path.exists(vendor_dir)
    os.makedirs(vendor_dir, exist_ok=True)
    vendor_clean_name = os.path.basename(vendor_dir)
    
    raw_date = entries_data.get("Date", "")
    clean_date = format_date_mm_dd_yyyy(raw_date)
    
    raw_details = entries_data.get("Details", "")
    clean_details = "".join([c for c in raw_details if c.isalnum() or c in ' -_']).strip()
    clean_details = clean_details[:60].strip().upper()
    if not clean_details: clean_details = "NODESCRIPTION"
    
    filename = f"{clean_date} - {vendor_clean_name} - {clean_details}.pdf"
    output_path = os.path.join(vendor_dir, filename)
    
    final_doc.save(output_path)
    final_doc.close()
    
    # --- RENTAL AGREEMENT LOGIC ---
    rental_period = entries_data.get("RentalPeriod", "").strip()
    is_rental = bool(rental_period) or entries_data.get("PurchaseType") == "Rental"
    
    if is_new_company and is_rental:
        import re
        rental_template = os.path.join(OUTPUT_DIR, "MK - Rental Agmt - Set Dec, Props.pdf")
        if os.path.exists(rental_template):
            try:
                rdoc = fitz.open(rental_template)
                rpage = rdoc[0]
                
                parts = [p.strip() for p in re.split(r'-| to ', rental_period, flags=re.IGNORECASE)]
                start_date = parts[0] if len(parts) > 0 else rental_period
                end_date = parts[1] if len(parts) > 1 else ""
                
                # Agreement date
                rpage.insert_text((260, 110), f"{raw_date}", fontname="helv", fontsize=11)
                rpage.insert_text((356, 110), "6", fontname="helv", fontsize=11) # for 2026
                
                # Lessor (Company)
                rpage.insert_text((165, 122), f"{payee_clean.upper()}", fontname="helv", fontsize=11)
                
                # Term dates
                rpage.insert_text((305, 166), f"{start_date}", fontname="helv", fontsize=11)
                rpage.insert_text((392, 166), "6", fontname="helv", fontsize=11) # for 2026
                
                rpage.insert_text((410, 166), f"{end_date}", fontname="helv", fontsize=11)
                rpage.insert_text((488, 166), "6", fontname="helv", fontsize=11) # for 2026
                
                if invoice_path:
                    if invoice_path.lower().endswith('.pdf'):
                        invoice_doc = fitz.open(invoice_path)
                        rdoc.insert_pdf(invoice_doc)
                        invoice_doc.close()
                    else:
                        img_doc = fitz.open(invoice_path)
                        pdf_bytes = img_doc.convert_to_pdf()
                        img_pdf = fitz.open("pdf", pdf_bytes)
                        rdoc.insert_pdf(img_pdf)
                        img_pdf.close()
                        img_doc.close()
                
                rental_agmt_filename = f"{payee_clean.upper()} RENTAL AGREEMENT.pdf"
                rental_agmt_path = os.path.join(vendor_dir, rental_agmt_filename)
                rdoc.save(rental_agmt_path)
                rdoc.close()
                
                os.startfile(rental_agmt_path)
            except Exception as e:
                print(f"Failed to generate rental agreement: {e}")
    # ------------------------------
    
    if os.path.exists(temp_template):
        os.remove(temp_template)
        
    return output_path
