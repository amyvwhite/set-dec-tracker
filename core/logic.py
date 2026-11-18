import re
from .models import Receipt

def process_receipt_splits(receipt: Receipt):
    """
    If the set_number contains slashes, ampersands, or commas (e.g. A01/A05, A01 & A02 & A03),
    it splits the receipt into multiple objects and divides the subtotal/tax/total evenly.
    """
    if not receipt.set_number:
        return [receipt]
        
    # Split by / or , or & or "and"
    raw_sets = re.split(r'[/,&]+|\band\b', receipt.set_number)
    sets = [s.strip() for s in raw_sets if s.strip()]
    
    if len(sets) <= 1:
        return [receipt]
        
    split_receipts = []
    num_splits = len(sets)
    
    # Divide amounts safely
    def divide_amount(amt):
        if amt is None: return None
        return round(amt / num_splits, 2)
        
    subtotal_split = divide_amount(receipt.subtotal)
    tax_split = divide_amount(receipt.tax)
    total_split = divide_amount(receipt.total)
    shipping_split = divide_amount(receipt.shipping)
    
    from dataclasses import replace
    for current_set in sets:
        other_sets = [s for s in sets if s != current_set]
        split_note_str = f"SPLIT WITH {', '.join(other_sets)}"
        
        # Clean description so it NEVER contains (SPLIT WITH ...) for Expense or Sheets
        clean_desc = receipt.description or ""
        clean_desc = re.sub(r'\s*\(\s*SPLIT WITH[^)]*\)', '', clean_desc, flags=re.IGNORECASE).strip()
        
        # Append split note to notes field
        existing_notes = receipt.notes or ""
        if split_note_str.upper() not in existing_notes.upper():
            new_notes = f"({split_note_str}) {existing_notes}".strip() if existing_notes else f"({split_note_str})"
        else:
            new_notes = existing_notes

        split_receipt = replace(
            receipt,
            set_number=current_set,
            description=clean_desc,
            notes=new_notes,
            subtotal=subtotal_split,
            shipping=shipping_split,
            tax=tax_split,
            total=total_split,
            status='SPLIT'
        )
        split_receipts.append(split_receipt)
        
    return split_receipts
