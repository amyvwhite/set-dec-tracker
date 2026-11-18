import os
import re
import shutil
import io
import fitz

GENERIC_NAMES = {'scan', 'doc', 'img', 'image', 'attachment', 'signed', 'agreement', 'completed', 'complete', 'pdf', 'file', 'unknown', 'scanner', 'camscanner'}
BOILERPLATE_WORDS = {'warrants', 'represents', 'agreement', 'lessee', 'lessor', 'production', 'sampleproductions', 'series', 'program', 'sole', 'owner', 'props', 'set', 'items', 'properly', 'properll', 'properiy', 'dated', 'term', 'exhibit'}

def is_generic_filename(fname):
    name = os.path.splitext(fname)[0].lower()
    for word in ["rental_agreement", "rental", "agreement", "completed", "complete", "v2", "v1", "signed", "done"]:
        name = re.sub(r'[_\s-]*' + re.escape(word) + r'[_\s-]*', '_', name, flags=re.IGNORECASE)
    clean_str = name.strip('_ -')
    
    if not clean_str or clean_str.isdigit():
        return True
        
    if any(k in clean_str for k in ['credit_memo', 'creditmemo', 'invoice', 'receipt', 'bill_of_sale', 'packing_slip', 'statement', 'memo']):
        return True
    
    letters_only = re.sub(r'[^a-z]', '', clean_str)
    if len(letters_only) < 3 or letters_only in GENERIC_NAMES:
        return True
        
    for prefix in ['scan', 'doc', 'img', 'image', 'scanner', 'camscanner', 'file', 'upload', 'untitled', 'attachment', 'skm', 'xerox', 'brother', 'hp', 'pdf']:
        if clean_str.startswith(prefix):
            remainder = clean_str[len(prefix):].strip('_ -')
            remainder_letters = re.sub(r'[^a-z]', '', remainder)
            if len(remainder_letters) < 3 or remainder.isdigit():
                return True
    return False

def get_active_uncompleted_vendors(root_dir):
    vendors = []
    if root_dir and os.path.exists(root_dir):
        for f in os.listdir(root_dir):
            if f.lower().endswith('.pdf') and not f.lower().endswith('_completed.pdf') and 'complete' not in f.lower():
                base = f.replace("Rental_Agreement_", "").replace(".pdf", "").replace("_", " ").strip()
                if base and base.lower() not in ['sampleshow', 'props version redline']:
                    vendors.append(base)
    return vendors

def find_matching_uncompleted_vendor(candidate_name, root_dir):
    """
    Checks uncompleted agreement files in root_dir to match against candidate name.
    """
    if not candidate_name or not root_dir or not os.path.exists(root_dir):
        return candidate_name

    cand_clean = re.sub(r'[^a-z0-9]', '', candidate_name.lower())
    if len(cand_clean) < 3:
        return candidate_name

    for f in os.listdir(root_dir):
        if f.lower().endswith('.pdf') and not f.lower().endswith('_completed.pdf') and 'complete' not in f.lower():
            base = f.replace("Rental_Agreement_", "").replace(".pdf", "")
            base_clean = re.sub(r'[^a-z0-9]', '', base.lower())
            if cand_clean and (cand_clean in base_clean or base_clean in cand_clean):
                return base.replace("_", " ")

    return candidate_name

def extract_vendor_name_from_pdf_text(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None
        page = doc[0]
        text = page.get_text()
        doc.close()

        if not text or not text.strip():
            return None

        # Search for pattern: Lessee...") and <VENDOR_NAME> ("Lessor")
        match = re.search(r'Lessee[”"]\)\s+and\s+([^\n\(\”"]+?)\s+[\(\”"]Lessor', text, re.IGNORECASE)
        if match:
            vendor = match.group(1).strip()
            vendor = re.sub(r'^_+', '', vendor).strip()
            if vendor and 2 <= len(vendor) <= 50:
                words = set(vendor.lower().split())
                if not words.intersection(BOILERPLATE_WORDS):
                    return vendor

        # Fallback search for "Lessor" block
        match2 = re.search(r'Lessor[:\s]+([^\n]+)', text, re.IGNORECASE)
        if match2:
            vendor = match2.group(1).strip()
            vendor = re.sub(r'^_+', '', vendor).strip()
            if vendor and 2 <= len(vendor) <= 50:
                words = set(vendor.lower().split())
                if not words.intersection(BOILERPLATE_WORDS):
                    return vendor

    except Exception as e:
        print(f"Error reading PDF text {pdf_path}: {e}")

    return None

def extract_vendor_name_with_vision(pdf_path, root_dir=None):
    """
    Uses Gemini Vision to read scanned or image-only rental agreement PDFs.
    Passes the show's active uncompleted vendors as context for 100% accuracy.
    """
    try:
        import PIL.Image
        from google import genai
        from core.settings import load_settings

        settings = load_settings()
        api_key = settings.get("gemini_api_key", "")
        if not api_key:
            return None

        active_vendors = get_active_uncompleted_vendors(root_dir)

        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=150)
        doc.close()

        img = PIL.Image.open(io.BytesIO(pix.tobytes("png")))
        client = genai.Client(api_key=api_key)

        vendor_hint = ""
        if active_vendors:
            vendor_hint = f"Active uncompleted vendors on this production include: {', '.join(active_vendors)}.\n"

        prompt = (
            "This is Page 1 of a film production Rental Agreement.\n"
            "Sample Productions, Inc. is the LESSEE.\n"
            "Find the LESSOR (the third-party vendor / company renting to Sampleproductions).\n"
            "It is filled in on the blank line right after 'Inc. (\"Lessee\") and' and before '(\"Lessor\")'.\n"
            f"{vendor_hint}"
            "If the name written on the line corresponds to one of the active vendors, return that exact name.\n"
            "Otherwise, return the exact vendor/company name written on the line.\n"
            "Return ONLY the company name, nothing else."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, img]
        )

        if response and response.text:
            val = response.text.strip().strip("\"'").strip()
            val = re.sub(r'^(the\s+vendor\s+is|vendor\s+name\s+is|lessor\s+is)\s*[:\-]?\s*', '', val, flags=re.IGNORECASE).strip()
            val = re.sub(r'^_+', '', val).strip()
            val = re.sub(r'_+$', '', val).strip()
            
            if val and 2 <= len(val) <= 60:
                words = set(val.lower().split())
                if not words.intersection(BOILERPLATE_WORDS):
                    return val

    except Exception as e:
        print(f"DEBUG: Vision extraction error on {pdf_path}: {e}")

    return None

def extract_vendor_name(fpath, root_dir=None):
    """
    Determines vendor name with highest accuracy:
    1. Read the document itself:
       - Use Gemini Vision OCR with active vendor matching (most reliable for scans).
       - Or use PDF text layer if clean text exists.
    2. Fall back to filename only if document extraction returns nothing.
    """
    fname = os.path.basename(fpath)

    # Step 1: Read the document with Gemini Vision (best for scans & agreements)
    vision_vendor = extract_vendor_name_with_vision(fpath, root_dir=root_dir)
    if vision_vendor and not is_generic_filename(vision_vendor):
        if root_dir:
            return find_matching_uncompleted_vendor(vision_vendor, root_dir)
        return vision_vendor

    # Step 2: Try text layer from PDF
    text_vendor = extract_vendor_name_from_pdf_text(fpath)
    if text_vendor and not is_generic_filename(text_vendor):
        if root_dir:
            return find_matching_uncompleted_vendor(text_vendor, root_dir)
        return text_vendor

    # Step 3: Fallback to filename if document reading was inconclusive
    if not is_generic_filename(fname):
        fn_vendor = extract_vendor_from_filename(fname)
        if fn_vendor:
            if root_dir:
                return find_matching_uncompleted_vendor(fn_vendor, root_dir)
            return fn_vendor

    return os.path.splitext(fname)[0]

def extract_vendor_from_filename(filename):
    name = os.path.splitext(filename)[0]
    name = re.sub(r'^Rental[_\s-]*Agreement[_\s-]*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_\s-]*(?:complete[d]?|signed|v2|v1|done)[_\s-]*$', '', name, flags=re.IGNORECASE)
    name = name.replace("_", " ").strip()
    name = re.sub(r'\s+', ' ', name)
    
    if name and not is_generic_filename(name):
        return name
    return None

def clean_company_name(name):
    name = re.sub(r'^Rental[_\s-]*Agreement[_\s-]*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_\s-]*(?:complete[d]?|signed|v2|v1|done)[_\s-]*$', '', name, flags=re.IGNORECASE)
    name = name.replace("_", " ").strip()
    name = re.sub(r'\s+', ' ', name)

    if name.islower():
        name = name.title()

    safe_name = "".join([c for c in name if c.isalpha() or c.isdigit() or c == ' ']).strip()
    safe_filename = safe_name.replace(' ', '_')
    return safe_name, safe_filename

def get_default_agreements_dir():
    try:
        from core.settings import load_settings
        custom_dir = load_settings().get('rental_output_dir')
        if custom_dir and os.path.exists(custom_dir):
            return custom_dir
    except Exception:
        pass
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    show_agreements = os.path.abspath(os.path.join(app_dir, '..', '..', 'Rental Agreements'))
    return show_agreements if os.path.exists(show_agreements) else os.path.join(app_dir, 'Rental Agreements')

def delete_uncompleted_version(safe_fname, root_dir=None):
    """
    Deletes the uncompleted / blank agreement PDF from root_dir matching vendor safe_fname.
    """
    if root_dir is None:
        root_dir = get_default_agreements_dir()
    if not os.path.exists(root_dir):
        return

    safe_fname_lower = re.sub(r'[^a-z0-9]', '', safe_fname.lower())
    if len(safe_fname_lower) < 3:
        return

    for f in os.listdir(root_dir):
        fpath = os.path.join(root_dir, f)
        if os.path.isfile(fpath) and f.lower().endswith('.pdf'):
            if f.lower().endswith('_completed.pdf') or 'complete' in f.lower():
                continue
            
            base_clean = clean_company_name(os.path.splitext(f)[0])[1]
            base_clean_lower = re.sub(r'[^a-z0-9]', '', base_clean.lower())
            
            if (safe_fname_lower in base_clean_lower or base_clean_lower in safe_fname_lower) and len(base_clean_lower) >= 3:
                try:
                    os.remove(fpath)
                    print(f"Deleted uncompleted agreement: {f}")
                except Exception as e:
                    print(f"Could not delete uncompleted agreement {f}: {e}")

def process_dropped_files(file_paths, root_dir=None):
    if root_dir is None:
        root_dir = get_default_agreements_dir()
    completed_dir = os.path.join(root_dir, "completed")
    os.makedirs(completed_dir, exist_ok=True)

    processed_count = 0
    results = []

    for fpath in file_paths:
        if not os.path.exists(fpath) or not fpath.lower().endswith('.pdf'):
            continue

        fname = os.path.basename(fpath)
        vendor_name = extract_vendor_name(fpath, root_dir=root_dir)

        safe_name, safe_fname = clean_company_name(vendor_name)
        new_filename = f"Rental_Agreement_{safe_fname}_Completed.pdf"
        target_path = os.path.join(completed_dir, new_filename)

        try:
            if os.path.abspath(fpath) != os.path.abspath(target_path):
                if os.path.exists(target_path):
                    os.remove(target_path)
                shutil.copy2(fpath, target_path)
                
                # Delete uncompleted version from root_dir
                delete_uncompleted_version(safe_fname, root_dir)
                
                processed_count += 1
                results.append((fname, new_filename))

                # Auto-sync status to Rental Agreements Google Sheet
                try:
                    from services.rental_sheet_sync_service import update_rental_agreement_sheet_status
                    update_rental_agreement_sheet_status(vendor_name=safe_name, is_completed=True)
                except Exception as e:
                    print(f"Could not auto-sync rental agreement sheet for {safe_name}: {e}")
        except Exception as e:
            print(f"Failed to process dropped file {fname}: {e}")

    return processed_count, results

def process_completed_agreements(root_dir=None):
    if root_dir is None:
        root_dir = get_default_agreements_dir()
    completed_dir = os.path.join(root_dir, "completed")
    os.makedirs(completed_dir, exist_ok=True)

    processed_count = 0
    results = []
    files_to_check = []
    
    # 1. Check root_dir for completed files
    for fname in os.listdir(root_dir):
        fpath = os.path.join(root_dir, fname)
        if os.path.isfile(fpath) and fname.lower().endswith('.pdf'):
            if any(w in fname.lower() for w in ['complete', 'signed', 'done', 'return']):
                files_to_check.append((fpath, fname))

    # 2. Check completed_dir for improperly named files (e.g. Scan..., generic names, boilerplate)
    for fname in os.listdir(completed_dir):
        fpath = os.path.join(completed_dir, fname)
        if os.path.isfile(fpath) and fname.lower().endswith('.pdf'):
            files_to_check.append((fpath, fname))

    for fpath, fname in files_to_check:
        clean_part = fname.replace("Rental_Agreement_", "").replace("_Completed.pdf", "").replace("_completed.pdf", "")
        
        # If it's already well-named and NOT generic, skip
        if (fname.startswith("Rental_Agreement_") and 
            fname.endswith("_Completed.pdf") and 
            not fname.endswith("_complete.pdf") and
            not is_generic_filename(clean_part) and
            not any(w in clean_part.lower() for w in ['warrants', 'represents', 'properly', 'sole_owner', 'warants'])):
            
            delete_uncompleted_version(clean_part, root_dir)
            continue

        vendor_name = extract_vendor_name(fpath, root_dir=root_dir)

        safe_name, safe_fname = clean_company_name(vendor_name)
        new_filename = f"Rental_Agreement_{safe_fname}_Completed.pdf"
        target_path = os.path.join(completed_dir, new_filename)

        if os.path.abspath(fpath) != os.path.abspath(target_path):
            try:
                if os.path.exists(target_path):
                    os.remove(target_path)
                shutil.move(fpath, target_path)
                
                # Delete uncompleted version from root_dir
                delete_uncompleted_version(safe_fname, root_dir)
                
                processed_count += 1
                results.append((fname, new_filename))

                # Auto-sync status to Rental Agreements Google Sheet
                try:
                    from services.rental_sheet_sync_service import update_rental_agreement_sheet_status
                    update_rental_agreement_sheet_status(vendor_name=safe_name, is_completed=True)
                except Exception as e:
                    print(f"Could not auto-sync rental agreement sheet for {safe_name}: {e}")
            except Exception as e:
                print(f"Error processing {fname}: {e}")

    return processed_count, results
