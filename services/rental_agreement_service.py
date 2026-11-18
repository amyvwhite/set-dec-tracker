import fitz
import os
from datetime import datetime

def format_date_with_ordinal(d):
    """Formats a datetime object to a string like 'August 11th'."""
    day = d.day
    if 11 <= day <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return f"{d.strftime('%B')} {day}{suffix}"

def generate_rental_agreement(vendor_name, start_date=None, end_date=None, dated_as_of=None, template_path=None, output_dir=None):
    """
    Generates a filled rental agreement PDF using PyMuPDF (fitz) overlay text.
    Handles long vendor names and long date strings gracefully by auto-scaling fonts and multi-line stacking.
    """
    if not vendor_name or not vendor_name.strip():
        raise ValueError("Vendor / Company Name is required.")

    vendor_name = vendor_name.strip()
    now = datetime.now()

    if not dated_as_of or not dated_as_of.strip():
        dated_as_of = format_date_with_ordinal(now)
    else:
        dated_as_of = dated_as_of.strip()

    if not start_date or not start_date.strip():
        start_date = format_date_with_ordinal(now)
    else:
        start_date = start_date.strip()

    if not end_date or not end_date.strip():
        end_date = "Dec 16th"
    else:
        end_date = end_date.strip()

    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
    default_template = os.path.join(show_dir, "CH REQS", "MK - Rental Agmt - Set Dec, Props.pdf")
    if not template_path or not os.path.exists(template_path):
        template_path = default_template

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Rental Agreement template PDF not found at: {template_path}")

    default_output_dir = os.path.join(show_dir, "Rental Agreements")
    if not output_dir or not output_dir.strip():
        output_dir = default_output_dir
    else:
        output_dir = output_dir.strip()

    os.makedirs(output_dir, exist_ok=True)

    safe_vendor_name = "".join([c for c in vendor_name if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
    if not safe_vendor_name:
        safe_vendor_name = "Vendor"
    pdf_filename = f"Rental_Agreement_{safe_vendor_name.replace(' ', '_')}.pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)

    doc = fitz.open(template_path)
    page = doc[0]

    # Current year last digit (e.g. '6' for 2026)
    year_digit = str(now.year)[-1]

    def get_date_fontsize(d_str):
        if len(d_str) > 12:
            return 6.5
        elif len(d_str) > 8:
            return 7.5
        return 9.0

    # 1. "dated as of"
    rects1 = page.search_for("dated as of")
    if rects1:
        fsize_d = get_date_fontsize(dated_as_of)
        page.insert_text((rects1[0].x1 + 2, rects1[0].y1 - 1), dated_as_of, fontsize=fsize_d, fontname="helv", color=(0, 0, 1))

    rects_202 = page.search_for("202_")
    if len(rects_202) > 0:
        page.insert_text((rects_202[0].x1 - 6, rects_202[0].y1 - 1), year_digit, fontsize=9.0, fontname="helv", color=(0, 0, 1))

    # 2. Vendor Name (Multi-line / stacked if long)
    rects2 = page.search_for("Lessee”) and")
    if not rects2:
        rects2 = page.search_for("Lessee\") and")
    if rects2:
        x_pos = rects2[0].x1 + 3
        y_pos = rects2[0].y1 - 1
        
        if len(vendor_name) > 18 and " " in vendor_name:
            words = vendor_name.split()
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            
            fsize_v = 6.5 if (len(line1) > 18 or len(line2) > 18) else 7.5
            page.insert_text((x_pos, y_pos - 3.5), line1, fontsize=fsize_v, fontname="helv", color=(0, 0, 1))
            page.insert_text((x_pos, y_pos + 4.5), line2, fontsize=fsize_v, fontname="helv", color=(0, 0, 1))
        else:
            fsize_v = 9.5 if len(vendor_name) <= 15 else (8.0 if len(vendor_name) <= 18 else 7.0)
            page.insert_text((x_pos, y_pos), vendor_name, fontsize=fsize_v, fontname="helv", color=(0, 0, 1))

    # 3. Start date
    rects3 = page.search_for("Set Items from")
    if rects3:
        fsize_s = get_date_fontsize(start_date)
        page.insert_text((rects3[0].x1 + 2, rects3[0].y1 - 1), start_date, fontsize=fsize_s, fontname="helv", color=(0, 0, 1))

    if len(rects_202) > 1:
        page.insert_text((rects_202[1].x1 - 6, rects_202[1].y1 - 1), year_digit, fontsize=9.0, fontname="helv", color=(0, 0, 1))

    # 4. End date
    rects4 = page.search_for(", 202_, to")
    if rects4:
        fsize_e = get_date_fontsize(end_date)
        page.insert_text((rects4[-1].x1 + 2, rects4[-1].y1 - 1), end_date, fontsize=fsize_e, fontname="helv", color=(0, 0, 1))

    if len(rects_202) > 2:
        page.insert_text((rects_202[2].x1 - 6, rects_202[2].y1 - 1), year_digit, fontsize=9.0, fontname="helv", color=(0, 0, 1))

    doc.save(pdf_path)
    doc.close()

    # Automatically record/sync "SENT TO VENDOR <date>" on Rental Agreements Sheet
    try:
        from services.rental_sheet_sync_service import update_rental_agreement_sheet_status
        update_rental_agreement_sheet_status(vendor_name=vendor_name, is_completed=False)
    except Exception as e:
        print(f"Could not auto-sync newly generated rental agreement status for {vendor_name}: {e}")

    return pdf_path
