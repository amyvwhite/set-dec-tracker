from PySide6.QtCore import QThread, Signal
import os
import time
import json
import io
import concurrent.futures

from google import genai
from core.database import is_file_processed, insert_receipt, compute_file_hash
from core.models import Receipt
from core.settings import load_settings
import PIL.Image
import fitz  # PyMuPDF
import glob
import shutil

def images_to_multipage_pdf(file_paths, output_pdf_path):
    """
    Combines multiple images or PDFs into a single, clean multi-page PDF document
    where each image/page remains on its own individual page without being stitched
    into a giant tall image. This ensures clean printing and standard Expense uploads.
    """
    try:
        doc = fitz.open()
        for fp in file_paths:
            ext = os.path.splitext(fp)[1].lower()
            if ext == '.pdf':
                sub_doc = fitz.open(fp)
                doc.insert_pdf(sub_doc)
                sub_doc.close()
            else:
                img = fitz.open(fp)
                rect = img[0].rect
                pdfbytes = img.convert_to_pdf()
                img.close()
                img_pdf = fitz.open("pdf", pdfbytes)
                page = doc.new_page(width=rect.width, height=rect.height)
                page.show_pdf_page(rect, img_pdf, 0)
                img_pdf.close()
        doc.save(output_pdf_path)
        doc.close()
        return True
    except Exception as e:
        print(f"DEBUG: Error creating multi-page PDF: {e}")
        return False

def stitch_images_vertically(image_paths, output_path):
    try:
        images = [PIL.Image.open(x).convert('RGB') for x in image_paths]
        if not images: return False
        
        widths, heights = zip(*(i.size for i in images))
        max_width = max(widths)
        total_height = sum(heights)
        
        new_im = PIL.Image.new('RGB', (max_width, total_height))
        y_offset = 0
        for im in images:
            new_im.paste(im, (0, y_offset))
            y_offset += im.size[1]
            
        new_im.save(output_path, "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"DEBUG: Error stitching images: {e}")
        return False

def stitch_pdf_vertically(pdf_path, output_path):
    try:
        doc = fitz.open(pdf_path)
        images = []
        matrix = fitz.Matrix(1.5, 1.5)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matrix)
            img = PIL.Image.open(io.BytesIO(pix.tobytes("png"))).convert('RGB')
            images.append(img)
            
        if not images: return False
        
        widths, heights = zip(*(i.size for i in images))
        max_width = max(widths)
        total_height = sum(heights)
        
        new_im = PIL.Image.new('RGB', (max_width, total_height))
        y_offset = 0
        for im in images:
            new_im.paste(im, (0, y_offset))
            y_offset += im.size[1]
            
        new_im.save(output_path, "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"DEBUG: Error stitching PDF: {e}")
        return False

def auto_group_receipts(image_paths, api_key):
    if len(image_paths) <= 1:
        return [[p] for p in image_paths]
        
    client = genai.Client(api_key=api_key)
    contents = [
        "You are an AI assistant helping to sort receipt photos. "
        "I am providing several images of receipts. Some images are pieces of the exact same long receipt cut into multiple photos. "
        "Please analyze them for visual continuity (e.g. items continuing across photos, overlapping totals, identical paper texture). "
        "Group the exact file paths that belong to the SAME receipt together. "
        "Return ONLY a valid JSON array of arrays of strings. Example: [[\"path1.jpg\", \"path2.jpg\"], [\"path3.jpg\"]] "
        "Do NOT return any markdown formatting, only the raw JSON."
    ]
    
    valid_paths = []
    for fp in image_paths:
        try:
            img = PIL.Image.open(fp)
            img.thumbnail((1024, 1024))
            contents.append(f"File path: {fp}")
            contents.append(img)
            valid_paths.append(fp)
        except Exception as e:
            print(f"DEBUG: Could not load {fp} for grouping: {e}")
            
    if not valid_paths:
        return []
        
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=genai.types.GenerateContentConfig(temperature=0.0)
        )
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        groups = json.loads(text)
        
        valid_groups = []
        seen = set()
        for g in groups:
            cur_g = []
            for p in g:
                if p in valid_paths and p not in seen:
                    cur_g.append(p)
                    seen.add(p)
            if cur_g:
                valid_groups.append(cur_g)
                
        for p in valid_paths:
            if p not in seen:
                valid_groups.append([p])
                
        return valid_groups
    except Exception as e:
        print(f"DEBUG: Auto-grouping failed: {e}")
        return [[p] for p in valid_paths]

def process_file_with_gemini(file_path, api_key, client=None, settings_data=None):
    """
    Processes a file with Gemini. Uses gemini-2.5-flash with zero thinking budget for ultra-fast
    structured JSON parsing and automatic retry-with-backoff for rate limits.
    Returns (data_dict, error_string).
    """
    if client is None:
        client = genai.Client(api_key=api_key)
    if settings_data is None:
        settings_data = load_settings()

    # Build image content
    try:
        images = []
        if file_path.lower().endswith('.pdf'):
            doc = fitz.open(file_path)
            matrix = fitz.Matrix(1.5, 1.5)
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(matrix=matrix)
                img_page = PIL.Image.open(io.BytesIO(pix.tobytes("png"))).convert('RGB')
                w, h = img_page.size
                max_dim = 1800
                if max(w, h) > max_dim:
                    img_page.thumbnail((max_dim, max_dim), PIL.Image.Resampling.BILINEAR)
                images.append(img_page)
            doc.close()
        else:
            img = PIL.Image.open(file_path)
            w, h = img.size
            if h > w * 2:
                if w > 1400:
                    new_w = 1400
                    new_h = int(h * (1400 / w))
                    img = img.resize((new_w, new_h), PIL.Image.Resampling.BILINEAR)
            else:
                max_dim = 1800
                if max(w, h) > max_dim:
                    img.thumbnail((max_dim, max_dim), PIL.Image.Resampling.BILINEAR)
            images = [img]
    except Exception as e:
        return None, f"Image loading error: {e}"
    dynamic_sets = settings_data.get("dynamic_sets", {})
    set_list_str = "  * AMORT SETS: X80 (Victor's Apartment), X81 (Cafe Roma / Kitchen), X82 (Cafe Roma / Max's Office), X83 (Tré's Apartment / Hallway), X84 (Memory Care Facility), X85 (Joe's Apartment), X86 (Ext Subway Entrance), X98 (Extended Amort), X99 (Expendables / Supplies)\n"
    if dynamic_sets:
        for ep_name, sets in dynamic_sets.items():
            set_list_str += f"  * {ep_name}: " + ", ".join([f"{s['code']} ({s['name']})" for s in sets]) + "\n"
    else:
        # Fallback if no sets are uploaded yet
        set_list_str = "  * AMORT SETS: X80 (Victor's Apartment), X81 (Cafe Roma / Kitchen), X82 (Cafe Roma / Max's Office), X83 (Tré's Apartment / Hallway), X84 (Memory Care Facility), X85 (Joe's Apartment), X86 (Ext Subway Entrance), X98 (Extended Amort), X99 (Expendables / Supplies)\n"

    prompt = f"""You are a Set Dec accountant parsing a receipt. 
Extract the following fields from the receipt image:
- set_number: The set number written on the receipt or sticky note (e.g., A14, A16, A27, B10, B15, X80, GREENS). Extract the ACTUAL set code written or implied by handwritten set names. 
OFFICIAL SET LIST:
{set_list_str}
  IMPORTANT: Match handwritten set names to the official set list (e.g., "POLICE STATION" in Ep 201 -> A18 or A19). Do NOT output "GREENS" unless the word "GREENS" is explicitly written on the paper/receipt, or if buyer is JAN or MILO, or card ends in 7519 or 3385. If a set name like POLICE STATION is written, output the set code (e.g. A18). Leave this field completely blank for craft receipts.
- buyer_name: The name of the buyer, often written by hand on a sticky note. IMPORTANT: If the name says "EVA LUND" or looks like cursive "Eva Lund", output "EVA". If the name says "A.t.", output "MILO". If the name says "ROWAN P CARD" or "ROWAN", output "ROWAN". If the name says "NICK D" or "NICK", output "NICK D". (DO NOT CONFUSE NICK WITH ROWAN - THEY ARE TWO DIFFERENT PEOPLE). If the name says "EXPENSE RAVI" or "EXPENSE", output just the buyer's name "RAVI". If the name says "KYLE BRANDT" or "BRANDT", output "BRANDT". If the name says "KYLE MACDOUGALL" or "MACDOUGALL", output "MACDOUGALL" (ALWAYS spell with two L's: MACDOUGALL, NEVER HARLOW). Ignore words like "EXPENSE", "P CARD", "PCARD", or "CREDIT CARD" in the buyer name. ALWAYS KEEP AN EYE OUT FOR THESE NAMES: JAN, EVA LUND, MILO, A.t., ROWAN, RAVI, RAVI KHAN, JR, DAN, DAN REID, JOHN, NICK, NICK D, NOAH, NOAH BELL, SAM, SAM RIVERA, SAMUEL, SAMUEL RIVERA, OWEN, OWEN PARK, ELI, ELI VANCE, ELIAS, ELIAS VANCE, NINA, MAYA, MAYA STONE, LEO, LEO GRANT, ZOE, ZOE LANE, IAN, IAN WEST, IAN WEST, CODY BLAKE, BRANDT, KYLE BRANDT, MACDOUGALL, KYLE MACDOUGALL, JOSH VARCOE, TAMAS PAL, AL GECEKUSU.
- vendor: The store or company name printed on the receipt. IMPORTANT: If the receipt says "Amazon.com.ca", "Amazon", or has "www.amazon.ca", the vendor MUST ALWAYS be "AMAZON.CA", regardless of what the "Sold by" or "Vendu par" company is.
- description: Provide a clean, summarized list of the items bought. REMOVE all receipt jargon, product codes, random numbers, dimensions/sizes (e.g. remove "2x2", "4x8", "10 inch"), non-essential info, and repeated words (e.g., if it says "2x2 POST ITS BLK 12345", just output "Post Its"). Combine this with any description written by hand on the paper. IMPORTANT: If this is a return, refund, or a negative invoice, you MUST prefix the description with "rtn: ". NEVER use the generic term "hardware" or "Hardware" to describe items unless the invoice/receipt explicitly contains the word "hardware".
- total: The final total amount paid. Return as a number only, no $ sign. IMPORTANT: If this is a return or a refund, ensure this number is negative (starts with a minus sign, e.g. -15.00). NEVER use parentheses.
- subtotal: The item subtotal before tax and BEFORE any shipping, freight, or import fee charges. If there are any discounts applied to the entire receipt (like a total discount or coupon applied after the subtotal), you MUST subtract the discount amount from the subtotal. If the receipt's subtotal line includes shipping or import fees, you MUST subtract them from it so this field only reflects the final discounted cost of the items. Return as a number only, no $ sign. IMPORTANT: If this is a return or a refund, ensure this number is negative. NEVER use parentheses.
- shipping: Extract any distinct shipping, freight, or delivery charges. Return as a number only, no $ sign. If none exist, return null.
- import_fees: Extract any distinct "Import Fees Deposit" charges (often found on Amazon receipts). Return as a number only, no $ sign. If none exist, return null.
- tax: The tax amount (e.g. HST, GST). Read this directly from the receipt. Return as a number only, no $ sign. IMPORTANT: If the receipt lists a quantity > 1 and the tax shown is per-unit (like on Amazon invoices), you MUST multiply the unit tax by the quantity to get the total tax. Always verify that subtotal + shipping + import_fees + tax equals the total. If this is a return or a refund, ensure this number is negative. NEVER use parentheses.
- payment_method: CRITICAL - look carefully at the receipt and any handwritten notes. Use EXACTLY one of these values:
  * "CREDIT" - if paid by Visa, Credit Card, or Expense (IMPORTANT: Do NOT output "VISA", output "CREDIT")
  * "MASTERCARD" - if paid by Mastercard
  * "CASH" - if paid with cash
  * "CH REQ" - if you see "cheque", "ch req", "cheque requisition", or any handwritten note indicating a cheque payment
  * "PETTY" - if paid from petty cash
  * "P.O." - if you see "purchase order", "P.O.", "PO#", or any purchase order reference
  * "AMEX" - if paid by American Express
- po_number: The purchase order number. Only fill this if payment_method is "P.O.", otherwise return "".
- reference_number: Any transaction reference or approval number on the receipt. IMPORTANT: If there is an "Invoice Number", "Invoice", or "INV" number, prioritize that as the reference_number over any other approval codes. If there is no Invoice number, you MUST use the Order number as the reference_number.
- date: The date on the receipt. MUST always be formatted exactly as YYYY-MM-DD (e.g. 2026-06-25).
- is_greens: true ONLY if the word "GREENS" is explicitly written on the paper/receipt, OR if the buyer is JAN (Eva Lund) or MILO (Milo), OR payment card ends in 7519 or 3385. Otherwise false.
- is_rental: true if this is a rental receipt, false otherwise.
- rental_end_date: The rental return date (YYYY-MM-DD) if applicable.
- is_gas: true if receipt is for gas/fuel or from a gas station (e.g. Petro Canada, Shell, Esso, Pioneer, Ultramar, Husky, Chevron, Mobil, Irving, Gas, Fuel). IMPORTANT: Gas/fuel is NEVER craft! Extract full total paid.
- is_parking: true if this receipt is for parking (e.g. parking meter, parking garage, TPA, TORPRKAUT, Green P, parking ticket/stub), false otherwise.
- is_craft: true if this is a craft service receipt (e.g., food, snacks, coffee, meals, restaurants, grocery stores, fast food like McDonald's, Tim Hortons, Starbucks). NEVER true for gas, hardware, parking, or props.
- craft_people: If the receipt is for a sit-down restaurant meal or clearly indicates the number of guests/people (e.g., "Guests: 4", "Table: 2"), extract the number of people. Otherwise, return "".
- is_toll: true if this receipt is for tolls or highway charges (e.g. 407 ETR, Highway 407, tolls, bridge, tunnel), false otherwise.
IMPORTANT REIMBURSEMENT RULE: The $7 per person cap applies ONLY to CRAFT. For ALL Tolls, 407 ETR, E-transfers, Cash Payment Forms, Fuel/Gas, Parking, Supplies, and non-craft items, 100% of the ENTIRE bill MUST be reimbursed!

IMPORTANT RULES:
- CRITICAL FOR HIGHLIGHTED RECEIPTS / HYATT INVOICES:
  If a receipt or invoice (especially Hyatt or hotel invoices) contains HIGHLIGHTED text, lines, or items (e.g., yellow, green, pink, or color highlighter marked line items):
  * ONLY extract and sum up line items that are HIGHLIGHTED with color highlighter.
  * Completely IGNORE and EXCLUDE any unhighlighted line items (as they belong to other departments).
  * Calculate the subtotal, tax, and final total strictly for the HIGHLIGHTED portion belonging to Set Dec.
- CRITICAL FOR MULTI-PAGE / MULTI-INVOICE PDFs (e.g., COMBINED AMAZON INVOICES):
  If this PDF document contains multiple pages, multiple sub-invoices, or multiple shipments representing one combined transaction (and NO items are highlighted):
  * You MUST SUM UP the subtotal, tax/HST, shipping, import fees, and total across ALL pages/invoices into one single grand total bill.
  * Combine all item descriptions across all pages into a clean, combined description list.
  * Output ONE single JSON object for the combined transaction.
- items: list of objects for each line item on the invoice: [{{"description": string, "extended_price": float, "is_highlighted": boolean}}]. Set is_highlighted to true ONLY for items marked with color highlighter. Set is_highlighted to false for all unhighlighted items.
- If any field is not found, return an empty string "" — never return "N/A", "None", or "null"
- Return ONLY a valid JSON object, no markdown, no extra text
"""

    contents = [prompt] + images
    models_to_try = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]
    
    from google.genai import types
    gemini_config = types.GenerateContentConfig(
        response_mime_type='application/json',
        thinking_config=types.ThinkingConfig(thinking_budget=0)
    )
    
    for model_name in models_to_try:
        # Try up to 6 times per model for transient per-minute quota hits
        for attempt in range(6):
            try:
                print(f"DEBUG: Trying {model_name} (attempt {attempt + 1})...")
                response = client.models.generate_content(
                    model=model_name,
                    config=gemini_config,
                    contents=contents
                )
                json_str = response.text.strip()
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0]

                data = json.loads(json_str.strip())
                print(f"DEBUG: SUCCESS with {model_name}")

                # Automatic Post-Processing for Highlighted Line Items
                items = data.get("items", [])
                highlighted = [it for it in items if it.get("is_highlighted") is True]
                if highlighted:
                    print(f"DEBUG: Found {len(highlighted)} highlighted line items out of {len(items)} total.")
                    calc_subtotal = round(sum(float(it.get("extended_price", 0.0) or 0.0) for it in highlighted), 2)
                    if calc_subtotal > 0:
                        calc_tax = round(calc_subtotal * 0.13, 2)
                        calc_total = round(calc_subtotal + calc_tax, 2)
                        desc_list = [str(it.get("description", "")).strip() for it in highlighted if it.get("description")]
                        
                        data["subtotal"] = calc_subtotal
                        data["tax"] = calc_tax
                        data["total"] = calc_total
                        if desc_list:
                            data["description"] = ", ".join(desc_list)
                            print(f"DEBUG: Recalculated highlighted totals -> Subtotal: {calc_subtotal}, Tax: {calc_tax}, Total: {calc_total}")

                return data, ""

            except Exception as e:
                err = str(e)
                print(f"DEBUG: {model_name} attempt {attempt + 1} failed: {err[:120]}")

                # Broaden error detection for quota/rate limits
                is_quota_error = any(x in err.upper() for x in ["QUOTA", "EXHAUSTED", "429", "RATE", "LIMIT", "503", "UNAVAILABLE", "DEMAND"])
                
                if is_quota_error:
                    # Check if it's a per-day limit or depleted billing (no retry possible)
                    if any(x in err for x in ["PerDay", "RequestsPerDay", "limit: 0", "depleted"]):
                        print(f"DEBUG: {model_name} daily quota exhausted. Trying next model.")
                        break
                    elif "503" in err or "UNAVAILABLE" in err:
                        if attempt >= 2:
                            print(f"DEBUG: {model_name} is completely overloaded (503). Skipping to next model.")
                            break
                        wait_secs = 5
                        print(f"DEBUG: 503 High Demand hit, waiting {wait_secs}s before retry {attempt + 2}...")
                        time.sleep(wait_secs)
                        continue
                    else:
                        # Per-minute limit - wait and retry with moderate backoff
                        wait_secs = 10 * (attempt + 1)
                        print(f"DEBUG: Rate limit hit, waiting {wait_secs}s before retry {attempt + 2}...")
                        time.sleep(wait_secs)
                        continue
                elif "404" in err or "NOT_FOUND" in err:
                    print(f"DEBUG: {model_name} not found, trying next model.")
                    break
                else:
                    print(f"DEBUG: Unexpected error: {err[:200]}")
                    break

    return None, "All Gemini models failed or quota exhausted."


class ProcessFolderThread(QThread):
    progress_update = Signal(str)
    receipt_processed = Signal(Receipt)
    finished_processing = Signal()

    def __init__(self, input_dir, action="process"):
        super().__init__()
        self.input_dir = input_dir
        self._is_running = True
        self.force_reprocess = False
        self.action = action

    def stop(self):
        self._is_running = False
        self.requestInterruption()

    def run(self):
        try:
            if hasattr(self, 'files_to_process') and self.files_to_process:
                files_to_process = self.files_to_process
            elif self.action == "group_only":
                self.progress_update.emit("Scanning for loose photos to group...")
                valid_extensions = ('.png', '.jpg', '.jpeg')
                loose_images = []
                for file in os.listdir(self.input_dir):
                    if self.isInterruptionRequested() or not self._is_running:
                        return
                    fp = os.path.join(self.input_dir, file)
                    if os.path.isfile(fp) and fp.lower().endswith(valid_extensions):
                        loose_images.append(fp)
                        
                settings = load_settings()
                api_key = settings.get("gemini_api_key", "")
                if loose_images and self._is_running and not self.isInterruptionRequested():
                    self.progress_update.emit(f"AI is analyzing {len(loose_images)} photos to find connected receipt pieces...")
                    groups = auto_group_receipts(loose_images, api_key)
                    for group in groups:
                        if self.isInterruptionRequested() or not self._is_running:
                            break
                        if len(group) > 1:
                            self.progress_update.emit(f"Combining {len(group)} matched photos into a multi-page PDF...")
                            base_name = os.path.splitext(os.path.basename(group[0]))[0]
                            output_pdf = os.path.join(self.input_dir, f"{base_name}_combined.pdf")
                            if images_to_multipage_pdf(group, output_pdf):
                                for p in group:
                                    try: os.remove(p)
                                    except: pass
                self.progress_update.emit("Finished AI grouping! Ready to process.")
                return # stop after grouping
            else:
                self.progress_update.emit("Scanning Input folder for new receipts...")
                valid_extensions = ('.png', '.jpg', '.jpeg', '.pdf')
                files_to_process = []
                
                # First, process subdirectories
                for item in os.listdir(self.input_dir):
                    if self.isInterruptionRequested() or not self._is_running:
                        return
                    item_path = os.path.join(self.input_dir, item)
                    if os.path.isdir(item_path):
                        # It's a subfolder, collect images and stitch them
                        sub_files = []
                        for sub_f in os.listdir(item_path):
                            sub_fp = os.path.join(item_path, sub_f)
                            if os.path.isfile(sub_fp) and sub_fp.lower().endswith(valid_extensions):
                                sub_files.append(sub_fp)
                        
                        if sub_files:
                            self.progress_update.emit(f"Combining subfolder: {item} into multi-page PDF...")
                            sub_files.sort() # Sort alphabetically to maintain order
                            output_pdf = os.path.join(self.input_dir, f"{item}.pdf")
                            if images_to_multipage_pdf(sub_files, output_pdf):
                                files_to_process.append(output_pdf)
                                shutil.rmtree(item_path) # Delete the folder after successful combination
                                
                # Now collect loose files in root input dir (keep PDFs natively as PDFs!)
                loose_files = []
                for file in os.listdir(self.input_dir):
                    if self.isInterruptionRequested() or not self._is_running:
                        return
                    fp = os.path.join(self.input_dir, file)
                    if os.path.isfile(fp) and fp.lower().endswith(valid_extensions):
                        loose_files.append(fp)

                for p in loose_files:
                    files_to_process.append(p)

            total_files = len(files_to_process)
            print(f"Found {total_files} candidate files in {self.input_dir}")

            if not files_to_process or not self._is_running or self.isInterruptionRequested():
                self.progress_update.emit("No new receipts found in Input folder.")
                return

            hashes_in_batch = {}
            
            settings = load_settings()
            api_key = settings.get("gemini_api_key", "")
            concurrency = int(settings.get("processing_concurrency", 3))
            
            # Shared client reuses HTTP/2 connection pool for major network latency savings
            client = genai.Client(api_key=api_key)

            import threading
            hashes_lock = threading.Lock()
            
            completed = 0
            start_time = time.time()
            
            def process_file_worker(fp):
                if self.isInterruptionRequested() or not self._is_running:
                    return None
                try:
                    return self.process_single_file(fp, api_key, hashes_in_batch, client=client, settings_data=settings)
                except Exception as e:
                    print(f"Error processing file {fp}: {e}")
                    return None

            executor = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
            try:
                futures = {executor.submit(process_file_worker, fp): fp for fp in files_to_process}
                
                for future in concurrent.futures.as_completed(futures):
                    if self.isInterruptionRequested() or not self._is_running:
                        executor.shutdown(wait=False, cancel_futures=True)
                        print("DEBUG: Processing interrupted by user.")
                        break
                        
                    receipt = future.result()
                    if receipt:
                        with hashes_lock:
                            if receipt.file_hash not in hashes_in_batch:
                                hashes_in_batch[receipt.file_hash] = receipt.file_path
                        self.receipt_processed.emit(receipt)

                    completed += 1
                    
                    elapsed = time.time() - start_time
                    avg_time_per_file = elapsed / completed
                    remaining_files = total_files - completed
                    eta_seconds = int(avg_time_per_file * remaining_files)
                    
                    if eta_seconds > 60:
                        eta_str = f"{eta_seconds // 60}m {eta_seconds % 60}s"
                    else:
                        eta_str = f"{eta_seconds}s"
                        
                    self.progress_update.emit(f"Processed {completed} of {total_files} | ETA: ~{eta_str}")
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            self.progress_update.emit("Finished processing all receipts.")
        except Exception as e:
            print(f"Critical error in processing thread: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.finished_processing.emit()

    def process_single_file(self, file_path, api_key, hashes_in_batch, client=None, settings_data=None):
        if settings_data is None:
            settings_data = load_settings()
        file_name = os.path.basename(file_path)
        try:
            file_hash = compute_file_hash(file_path)

            if not self.force_reprocess and is_file_processed(file_path):
                print(f"DEBUG: Skipping already-processed file: {file_name}")
                return None

            # Batch duplicate check
            if file_hash in hashes_in_batch:
                receipt = Receipt(file_path=file_path, file_hash=file_hash)
                receipt.description = f"DUPLICATE OF {os.path.basename(hashes_in_batch[file_hash])}"
                insert_receipt(receipt)
                return receipt

            data, error_msg = process_file_with_gemini(file_path, api_key, client=client, settings_data=settings_data)

            receipt = Receipt(file_path=file_path, file_hash=file_hash)
            if data:
                def clean(val):
                    s = str(val).strip()
                    return "" if s.upper() in ("N/A", "NONE", "NULL", "NAN", "NONE") else s

                raw_set_extracted = clean(data.get("set_number", "")).upper()
                desc_extracted = clean(data.get("description", "")).upper()
                notes_extracted = clean(data.get("notes", "")).upper()
                combined_text = f"{raw_set_extracted} {desc_extracted} {notes_extracted}"

                # 203-T Tandem & 2nd Unit rule
                if "203-T" in combined_text or "203 TANDEM" in combined_text or "203T" in combined_text or "TANDEM" in combined_text:
                    receipt.special_tab = "203-T"
                    receipt.episode_code = "253"
                    receipt.account_code = "4004"
                    receipt.set_number = ""
                    has_mapped = True
                    if "FANCY" in combined_text or "RESTAURANT" in combined_text or "C26" in combined_text:
                        receipt.notes = "FANCY RESTAURANT"
                    elif "DITTY" in combined_text:
                        receipt.notes = "EXT DITTY LANE"
                    elif "POLICE" in combined_text:
                        receipt.notes = "EXT POLICE STATION"
                else:
                    receipt.set_number = raw_set_extracted
                    has_mapped = False
                    from core.set_list import derive_episode_code
                    epi_derived = derive_episode_code(receipt.set_number, special_tab=receipt.special_tab)
                    if epi_derived:
                        receipt.episode_code = epi_derived
                        has_mapped = True
                    else:
                        try:
                            import json
                            mappings_str = settings_data.get("episode_prefix_mappings", "[]")
                            prefix_mappings = json.loads(mappings_str)
                            prefix_mappings.sort(key=lambda x: len(x.get("prefix", "")), reverse=True)
                            for m in prefix_mappings:
                                prefix = str(m.get("prefix", "")).strip().upper()
                                if prefix and receipt.set_number.startswith(prefix):
                                    receipt.episode_code = m.get("code", "")
                                    has_mapped = True
                                    break
                        except Exception as e:
                            print("Error matching episode code from prefix mappings in threads.py:", e)
                            
                        if not has_mapped and receipt.set_number:
                            if receipt.set_number.startswith('A'):
                                receipt.episode_code = "251"
                            elif receipt.set_number.startswith('X'):
                                receipt.episode_code = "297"

                from core.settings import normalize_buyer_name
                receipt.buyer_name = normalize_buyer_name(data.get("buyer_name", ""))

                receipt.vendor = clean(data.get("vendor", "")).upper()
                receipt.description = clean(data.get("description", "")).upper().replace(", ", ",")

                pm = clean(data.get("payment_method", "")).upper()
                if pm in ["VISA", "VISA CREDIT", "VISA DEBIT"]:
                    pm = "CREDIT"
                receipt.payment_method = pm
                receipt.reference_number = clean(data.get("reference_number", ""))
                receipt.po_number = clean(data.get("po_number", ""))
                receipt.is_rental = bool(data.get("is_rental", False))
                receipt.is_craft = bool(data.get("is_craft", False))
                receipt.is_usd = bool(data.get("is_usd", False))
                try:
                    cp = data.get("craft_people")
                    receipt.craft_people = int(cp) if cp is not None and str(cp).isdigit() else None
                except:
                    receipt.craft_people = None
                receipt.is_greens = bool(data.get("is_greens", False))
                if "GREENS" in receipt.set_number:
                    receipt.is_greens = True
                    
                gas_terms = ["PETRO", "SHELL", "ESSO", "PIONEER", "ULTRAMAR", "HUSKY", "CHEVRON", "MOBIL", "IRVING", "GAS", "FUEL"]
                v_u = (receipt.vendor or "").upper()
                d_u = (receipt.description or "").upper()
                s_u = (receipt.set_number or "").upper()
                
                if not receipt.is_gas and any(k in v_u or k in d_u for k in gas_terms):
                    receipt.is_gas = True

                if receipt.is_gas:
                    receipt.is_craft = False
                    receipt.is_parking = False
                    # Calculate 13% HST for fuel receipts if tax is missing, 0, or subtotal equals total
                    if receipt.total is not None and receipt.total != 0.0:
                        if receipt.tax is None or receipt.tax == 0.0 or receipt.subtotal == receipt.total or receipt.subtotal == 0.0:
                            sign = -1.0 if receipt.total < 0 else 1.0
                            abs_tot = abs(receipt.total)
                            abs_sub = round(abs_tot / 1.13, 2)
                            abs_tax = round(abs_tot - abs_sub, 2)
                            receipt.subtotal = sign * abs_sub
                            receipt.tax = sign * abs_tax
                elif receipt.is_craft:
                    receipt.is_gas = False
                    receipt.is_parking = False
                    receipt.set_number = ""
                    desc_u = (receipt.description or "").upper()
                    date_str = ""
                    import re
                    m_range = re.search(r'(\d{4})\s*(?:to|[-–])\s*(\d{4})', str(receipt.description or ""), re.IGNORECASE)
                    if m_range:
                        date_str = f"{m_range.group(1)}-{m_range.group(2)}"
                    elif receipt.date:
                        try:
                            from dateutil import parser as dparser
                            p_date = dparser.parse(str(receipt.date).replace("SEPT", "SEP"), fuzzy=True)
                            date_str = p_date.strftime("%m%d")
                        except:
                            pass
                    suffix = "GREENS" if receipt.is_greens else "SET DEC"
                    if any(k in desc_u for k in ["LOCK UP", "LOCKUP", "LOCK-UP"]):
                        receipt.description = f"{date_str} CRAFT:{suffix} LOCK-UP".strip()
                    elif "OFFICE" in desc_u:
                        receipt.description = f"{date_str} CRAFT:{suffix} OFFICE".strip()
                    else:
                        count = receipt.craft_people
                        if not count:
                            m_p = re.search(r'CRAFT\s*X\s*(\d+)|CRAFT\s*(\d+)|X\s*(\d+)', desc_u)
                            if m_p:
                                count = m_p.group(1) or m_p.group(2) or m_p.group(3)
                        if count and str(count).isdigit():
                            receipt.description = f"{date_str} CRAFT X{int(count)}: {suffix}".strip()
                        else:
                            receipt.description = f"{date_str} CRAFT: {suffix}".strip()
                elif receipt.is_parking:
                    receipt.is_gas = False
                    receipt.set_number = ""
                    # Calculate 13% HST for parking receipts if tax is missing or subtotal equals total
                    if receipt.total is not None and receipt.total != 0.0:
                        if receipt.tax is None or receipt.tax == 0.0 or receipt.subtotal == receipt.total or receipt.subtotal == 0.0:
                            sign = -1.0 if receipt.total < 0 else 1.0
                            abs_tot = abs(receipt.total)
                            abs_sub = round(abs_tot / 1.13, 2)
                            abs_tax = round(abs_tot - abs_sub, 2)
                            receipt.subtotal = sign * abs_sub
                            receipt.tax = sign * abs_tax
                    
                    date_str = ""
                    import re
                    m_range = re.search(r'(\d{2}/?\d{2})\s*(?:to|[-–])\s*(\d{2}/?\d{2})', str(receipt.description or ""), re.IGNORECASE)
                    if m_range:
                        d1 = m_range.group(1).replace('/', '')
                        d2 = m_range.group(2).replace('/', '')
                        date_str = f"{d1}-{d2}"
                    elif receipt.date:
                        try:
                            from dateutil import parser as dparser
                            p_date = dparser.parse(str(receipt.date).replace("SEPT", "SEP"), fuzzy=True)
                            date_str = p_date.strftime("%m%d")
                        except:
                            pass
                    v_u = (receipt.vendor or "").upper()
                    d_u = (receipt.description or "").upper()
                    combined_park = f"{v_u} {d_u}"
                    is_tpa = any(k in combined_park for k in ["TORONTO PARKING", "TORPRKAUT", "GREEN P", "TPA", "T.P.A", "TP PARKING", "CITY OF TORONTO", "TORONTO"])
                    is_permit = ("-" in date_str) or any(k in combined_park for k in ["PERMIT", "PRMIT", "TEMP"])
                    
                    if is_permit and "-" in date_str:
                        permit_suffix = "GREENS" if receipt.is_greens else "SETS"
                        pfx = f"{date_str} TPA PRKG PRMIT:" if is_tpa else f"{date_str} PRKG PRMIT:"
                        receipt.description = f"{pfx.strip()} {permit_suffix}".strip()
                    else:
                        suffix = "GREENS" if receipt.is_greens else "SET DEC"
                        pfx = f"{date_str} TPA PRKG:" if is_tpa else f"{date_str} PRKG:"
                        receipt.description = f"{pfx.strip()} {suffix}".strip()
                    
                from services.sheets import format_rental_date
                receipt.rental_end_date = format_rental_date(clean(data.get("rental_end_date", "")))
                receipt.date = clean(data.get("date", ""))
                if receipt.date:
                    try:
                        from dateutil import parser as date_parser
                        r_date = date_parser.parse(str(receipt.date).replace("SEPT", "SEP"), fuzzy=True)
                        month_idx = r_date.month
                        key = f"hst_month_{month_idx}"
                        receipt.hst_account = settings_data.get(key, str(7500 + month_idx))
                    except Exception:
                        receipt.hst_account = None

                try:
                    raw_total = data.get("total")
                    if raw_total:
                        total_val = float(str(raw_total).replace('$', '').replace(',', '').replace('CAD', '').strip())
                        receipt.total = total_val

                        raw_sub = data.get("subtotal")
                        raw_shipping = data.get("shipping")
                        raw_import_fees = data.get("import_fees")
                        raw_tax = data.get("tax")
                        
                        try:
                            # Safely convert to float
                            def to_f(val):
                                if val is None or str(val).strip() == "": return 0.0
                                return float(str(val).replace('$', '').replace(',', '').replace('CAD', '').strip())
                            
                            sub_f = to_f(raw_sub)
                            ship_f = to_f(raw_shipping)
                            import_fees_f = to_f(raw_import_fees)
                            tax_f = to_f(raw_tax)
                            tot_f = total_val

                            # 1. Detect if 13% Ontario HST was misclassified into shipping
                            if (tax_f == 0.0 or raw_tax is None) and ship_f > 0.0 and sub_f > 0.0:
                                if abs(round(sub_f * 0.13, 2) - ship_f) <= 0.05 and abs(sub_f + ship_f - tot_f) <= 0.05:
                                    tax_f = ship_f
                                    ship_f = 0.0

                            # 2. Check if subtotal includes shipping/import_fees (subtotal + tax = total)
                            if (ship_f != 0.0 or import_fees_f != 0.0) and sub_f != 0.0:
                                if abs(sub_f + tax_f - tot_f) < 0.05:
                                    sub_f = round(sub_f - ship_f - import_fees_f, 2)

                            # 3. If Subtotal == Total while Tax > 0, recalculate subtotal
                            if abs(tot_f) > 0.0 and abs(tax_f) > 0.0:
                                if sub_f == tot_f or abs((sub_f + ship_f + import_fees_f + tax_f) - tot_f) > 0.05:
                                    sub_f = round(tot_f - tax_f - ship_f - import_fees_f, 2)

                            # 4. If Subtotal is missing but Total and Tax are known
                            if sub_f == 0.0 and tot_f != 0.0 and tax_f != 0.0:
                                sub_f = round(tot_f - tax_f - ship_f - import_fees_f, 2)

                            receipt.subtotal = sub_f
                            receipt.shipping = ship_f
                            receipt.import_fees = import_fees_f
                            receipt.tax = tax_f
                        except Exception as e:
                            print(f"Error parsing financial math in threads.py: {e}")
                                
                        print(f"DEBUG AI RAW: subtotal={raw_sub}, tax={raw_tax}, total={raw_total}")
                except Exception as e:
                    print(f"DEBUG: Could not parse totals: {e}")

            else:
                if "quota" in error_msg.lower() or "RESOURCE_EXHAUSTED" in error_msg:
                    receipt.description = "⚠ API QUOTA EXHAUSTED - PLEASE WAIT AND RETRY"
                else:
                    receipt.description = "AI DETECTION FAILED - PLEASE ENTER MANUALLY"
                print(f"Extraction failed for {file_name}: {error_msg}")

            insert_receipt(receipt)
            return receipt

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error processing {file_name}: {e}")
            return None

    def stop(self):
        self._is_running = False
