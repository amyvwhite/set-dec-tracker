import os
import re
import shutil
from datetime import datetime
from .models import Receipt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
show_receipts_parent = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'Receipts'))
RECEIPTS_DIR = show_receipts_parent if os.path.exists(show_receipts_parent) else os.path.join(BASE_DIR, 'Receipts')
CHECKME_DIR = os.path.join(BASE_DIR, 'CheckMe')
INPUT_DIR = os.path.join(BASE_DIR, 'Input')

def sanitize_filename(name):
    if not name:
        return "Unknown"
    # Remove invalid characters for Windows/Mac
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '')
    return name.strip()

def format_date_mm_dd_yyyy(date_val, fallback_year=None):
    if not date_val:
        return datetime.now().strftime("%m-%d-%Y")
    s = str(date_val).strip()
    
    # 1. MM-DD-YYYY
    m = re.match(r'^(\d{2})-(\d{2})-(\d{4})$', s)
    if m:
        return s
        
    # 2. YYYY-MM-DD
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s)
    if m:
        return f"{m.group(2)}-{m.group(3)}-{m.group(1)}"
        
    # 3. MM/DD/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}-{m.group(3)}"
        
    # 4. MMDDYYYY (8 digits)
    m = re.match(r'^(\d{2})(\d{2})(\d{4})$', s)
    if m:
        mo, d, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{mo:02d}-{d:02d}-{yr}"
            
    # 5. Fallback via dateutil
    try:
        from dateutil import parser as date_parser
        curr_yr = fallback_year or datetime.now().year
        dt = date_parser.parse(s.replace("SEPT", "SEP"), fuzzy=True)
        if dt.year < 2000:
            dt = dt.replace(year=curr_yr)
        return dt.strftime("%m-%d-%Y")
    except Exception:
        return datetime.now().strftime("%m-%d-%Y")

def move_and_rename_receipt(receipt: Receipt):
    """
    Moves an approved receipt to the corresponding Set folder inside Receipts/
    and renames it to MM-DD-YYYY - VENDOR - $AMOUNT - DESCRIPTION.ext (all capitals).
    If multiple sets are provided (e.g. A01 / A02), the file is copied to both.
    """
    if not os.path.exists(RECEIPTS_DIR):
        os.makedirs(RECEIPTS_DIR)
        
    raw_sets = re.split(r'[/,&]+|\band\b', str(receipt.set_number), flags=re.IGNORECASE)
    sets = [s.strip() for s in raw_sets if s.strip()]
    if not sets:
        sets = ["Unknown"]
        
    first_filepath = None
    
    date_str = format_date_mm_dd_yyyy(receipt.date)
    vendor_str = sanitize_filename(receipt.vendor).upper()
    amount_str = f"${receipt.total}" if receipt.total else "$0.00"
    desc_str = sanitize_filename(receipt.description).upper()
    if len(desc_str) > 50:
        desc_str = desc_str[:50].strip() + "..."
    ext = os.path.splitext(receipt.file_path)[1].lower()
    
    for idx, set_name in enumerate(sets):
        clean_set = sanitize_filename(set_name)
        
        is_greens = receipt.is_greens or "GREENS" in clean_set.upper()
        
        if is_greens:
            if receipt.is_craft or "CRAFT" in clean_set.upper():
                sub_folder = "CRAFT"
            elif getattr(receipt, 'is_parking', False) or "PARKING" in clean_set.upper():
                sub_folder = "PARKING"
            elif getattr(receipt, 'is_gas', False) or "GAS" in clean_set.upper():
                sub_folder = "GAS"
            else:
                set_name_clean = clean_set.upper().replace("GREENS", "").strip()
                sub_folder = os.path.join("SETS", set_name_clean) if set_name_clean else os.path.join("SETS", "GENERAL")
            set_folder = os.path.join(RECEIPTS_DIR, "GREENS", sub_folder)
        # Standard PARKING Special Folder Logic
        elif getattr(receipt, 'is_parking', False) or "PARKING" in clean_set.upper():
            set_folder = os.path.join(RECEIPTS_DIR, "PARKING")
        # Standard CRAFT Special Folder Logic
        elif receipt.is_craft or "CRAFT" in clean_set.upper():
            set_folder = os.path.join(RECEIPTS_DIR, "CRAFT")
        # Standard GAS Special Folder Logic
        elif getattr(receipt, 'is_gas', False) or "GAS" in clean_set.upper():
            set_folder = os.path.join(RECEIPTS_DIR, "GAS")
        else:
            set_folder = os.path.join(RECEIPTS_DIR, clean_set)

        if not os.path.exists(set_folder):
            os.makedirs(set_folder)
            
        new_filename = f"{date_str} - {vendor_str} - {amount_str} - {desc_str}{ext}"
        new_filepath = os.path.join(set_folder, new_filename)
        
        # Handle filename collisions
        counter = 1
        while os.path.exists(new_filepath):
            new_filename = f"{date_str} - {vendor_str} - {amount_str} - {desc_str} - {counter}{ext}"
            new_filepath = os.path.join(set_folder, new_filename)
            counter += 1
            
        if idx == len(sets) - 1:
            # Last set, move the original file
            shutil.move(receipt.file_path, new_filepath)
        else:
            # Not the last set, just copy
            shutil.copy(receipt.file_path, new_filepath)
            
        if first_filepath is None:
            first_filepath = new_filepath
            
    return first_filepath

def move_to_checkme(receipt: Receipt):
    """
    Moves a skipped or problematic receipt to the CheckMe/ directory for manual review later.
    """
    if not os.path.exists(CHECKME_DIR):
        os.makedirs(CHECKME_DIR)
    
    filename = os.path.basename(receipt.file_path)
    new_filepath = os.path.join(CHECKME_DIR, filename)
    shutil.move(receipt.file_path, new_filepath)
    return new_filepath

def get_canonical_vendor_dir(output_dir, raw_payee):
    """
    Resolves the canonical vendor folder inside output_dir, preventing duplicate or slightly
    differently-named folders (e.g. DBA, corporate suffixes, care of, punctuation, or known aliases).
    """
    from difflib import SequenceMatcher

    KNOWN_ALIASES = {
        "LEAL RENTAL CENTRE": "LEAL RENTAL",
        "JB EQUIPMENT": "JWB EQUIPMENT SALES",
        "JB EQUIPMENT SALES": "JWB EQUIPMENT SALES",
        "MEDICAL MOVIE PROPS": "HAMILTON HEALTH SCIENCES MEDICAL MOVIE PROPS",
        "HAMILTON HEALTH SCIENCES - MEDICAL MOVIE PROPS": "HAMILTON HEALTH SCIENCES MEDICAL MOVIE PROPS",
        "HAMILTON HEALTH SCIENCES MEDICAL MOVIE PROPS": "HAMILTON HEALTH SCIENCES MEDICAL MOVIE PROPS",
    }

    def clean_name_for_comparison(s):
        s = s.upper()
        if " DBA " in s:
            s = s.split(" DBA ")[-1]
        elif " D/B/A " in s:
            s = s.split(" D/B/A ")[-1]
        elif " O/A " in s:
            s = s.split(" O/A ")[-1]
        elif " C/O " in s:
            s = s.split(" C/O ")[0]
            
        s = re.sub(r'\b(INC\.?|LTD\.?|LLC\.?|CORP\.?|CO\.?|CORPORATION)\b', '', s)
        s = s.replace('&', ' ').replace('+', ' ').replace('-', ' ')
        s = "".join([c for c in s if c.isalnum() or c.isspace()])
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    raw_upper = str(raw_payee or "").upper().strip()

    # Special vendor rules
    if "GOOD DOG" in raw_upper:
        return os.path.join(output_dir, "GOOD DOG DIGITAL")
    if "FRAMING" in raw_upper and "ALLEN" in raw_upper:
        return os.path.join(output_dir, "ALLEN GALLERY FRAMING")
    if ("ALLEN GALLERY" in raw_upper or "SUPA HOLDINGS" in raw_upper) and "FRAMING" not in raw_upper:
        return os.path.join(output_dir, "ALLEN GALLERY ART SALES  RENTALS")
    if "KONZEPT" in raw_upper:
        return os.path.join(output_dir, "KONZEPT INTERIORS")
    if "WORKROOM BY DESIGN" in raw_upper and "KONZEPT" not in raw_upper:
        return os.path.join(output_dir, "WORKROOM BY DESIGN")

    # Check known aliases
    for alias, canonical in KNOWN_ALIASES.items():
        if alias in raw_upper or clean_name_for_comparison(alias) == clean_name_for_comparison(raw_upper):
            target = os.path.join(output_dir, canonical)
            if os.path.exists(target):
                return target

    cleaned = clean_name_for_comparison(raw_upper)
    if not cleaned:
        cleaned = "UNKNOWN_VENDOR"

    if os.path.exists(output_dir):
        existing_dirs = [d for d in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, d)) and d != '__pycache__']
        
        for d in existing_dirs:
            if d.upper() == cleaned:
                return os.path.join(output_dir, d)
                
        cleaned_compact = re.sub(r'[^A-Z0-9]', '', cleaned)
        for d in existing_dirs:
            d_clean = clean_name_for_comparison(d)
            d_compact = re.sub(r'[^A-Z0-9]', '', d_clean)
            if d_compact and (d_compact == cleaned_compact):
                return os.path.join(output_dir, d)
                
        best_match = None
        best_ratio = 0.0
        for d in existing_dirs:
            d_clean = clean_name_for_comparison(d)
            ratio = SequenceMatcher(None, cleaned, d_clean).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = d

        if best_ratio >= 0.88 and best_match:
            return os.path.join(output_dir, best_match)

    return os.path.join(output_dir, cleaned)

