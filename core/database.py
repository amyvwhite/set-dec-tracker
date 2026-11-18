import sqlite3
import re
import os
import hashlib
from datetime import datetime
from .models import Receipt

DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DATA_DIR, 'database.sqlite')
# print(f"DEBUG: Using Database at {DB_PATH}")

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            set_number TEXT,
            buyer_name TEXT,
            description TEXT,
            vendor TEXT,
            subtotal REAL,
            shipping REAL DEFAULT 0.0,
            tax REAL,
            total REAL,
            payment_method TEXT,
            date TEXT,
            reference_number TEXT,
            po_number TEXT,
            is_rental INTEGER DEFAULT 0,
            rental_end_date TEXT,
            is_greens INTEGER DEFAULT 0,
            is_craft INTEGER DEFAULT 0,
            is_gas INTEGER DEFAULT 0,
            is_parking INTEGER DEFAULT 0,
            craft_people INTEGER,
            episode_code TEXT,
            notes TEXT,
            status TEXT DEFAULT 'PENDING',
            co_code TEXT,
            loc_code TEXT,
            account_code TEXT,
            tax_code TEXT,
            hst_account TEXT,
            expense_only INTEGER DEFAULT 0,
            is_asset INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Migrations: Add new columns if they don't exist
    columns = [
        ('co_code', 'TEXT'),
        ('loc_code', 'TEXT'),
        ('account_code', 'TEXT'),
        ('tax_code', 'TEXT'),
        ('hst_account', 'TEXT'),
        ('expense_only', 'INTEGER DEFAULT 0'),
        ('is_greens', 'INTEGER DEFAULT 0'),
        ('shipping', 'REAL DEFAULT 0.0'),
        ('import_fees', 'REAL DEFAULT 0.0'),
        ('is_usd', 'INTEGER DEFAULT 0'),
        ('exchange_rate', 'REAL'),
        ('special_tab', 'TEXT'),
        ('is_asset', 'INTEGER DEFAULT 0')
    ]
    for col_name, col_type in columns:
        try:
            cursor.execute(f'ALTER TABLE receipts ADD COLUMN {col_name} {col_type}')
        except:
            pass # Already exists
            
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cheque_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_submitted TEXT,
            date_required TEXT,
            payment_type TEXT DEFAULT 'CHQ',
            vendor TEXT,
            set_number TEXT,
            description TEXT,
            reference_number TEXT,
            invoice_date TEXT,
            subtotal REAL,
            tax REAL,
            total REAL,
            rental_period TEXT,
            buyer_name TEXT,
            cheque_number TEXT,
            delivery_notes TEXT,
            status TEXT DEFAULT 'PENDING',
            sheet_row_id INTEGER,
            pdf_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS offline_sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            action TEXT DEFAULT 'APPEND',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (receipt_id) REFERENCES receipts(id)
        )
    ''')
    try:
        cursor.execute("UPDATE receipts SET account_code = '2716' WHERE account_code = '2493-000' OR account_code = '2493'")
        cursor.execute("UPDATE receipts SET account_code = REPLACE(account_code, '-000', '') WHERE account_code LIKE '%-000'")
        cursor.execute("UPDATE receipts SET hst_account = REPLACE(hst_account, '-000', '') WHERE hst_account LIKE '%-000'")
    except Exception as e:
        print("DEBUG DB cleanup error:", e)
        
    conn.commit()
    conn.close()

def compute_file_hash(file_path):
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as afile:
        buf = afile.read()
        hasher.update(buf)
    return hasher.hexdigest()

def is_file_processed(file_path):
    if not os.path.exists(file_path):
        return False
    # Skip if the exact file path is in DB AND it doesn't have an error message
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT description FROM receipts WHERE file_path = ?', (file_path,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        desc = str(row[0]).upper()
        # If it failed or exhausted quota, it's NOT "processed" (we want to retry)
        if "FAILED" in desc or "EXHAUSTED" in desc:
            return False
        return True
    return False

def insert_receipt(receipt: Receipt):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Delete any existing entry for this path so we don't get duplicates on retry
        cursor.execute('DELETE FROM receipts WHERE file_path = ?', (receipt.file_path,))
        
        cursor.execute('''
            INSERT INTO receipts (
                file_path, file_hash, set_number, special_tab, buyer_name, description, vendor,
                subtotal, shipping, import_fees, tax, total, payment_method, date, reference_number, 
                po_number, is_rental, rental_end_date, notes, status,
                is_greens, is_craft, is_gas, is_parking, craft_people, episode_code,
                co_code, loc_code, account_code, tax_code, hst_account, expense_only, is_usd, exchange_rate, is_asset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            receipt.file_path, receipt.file_hash, receipt.set_number, receipt.special_tab, receipt.buyer_name,
            receipt.description, receipt.vendor, receipt.subtotal, receipt.shipping, receipt.import_fees, receipt.tax, receipt.total,
            receipt.payment_method, receipt.date, receipt.reference_number,
            receipt.po_number, 1 if receipt.is_rental else 0, receipt.rental_end_date,
            receipt.notes, receipt.status, 1 if receipt.is_greens else 0,
            1 if receipt.is_craft else 0, 1 if receipt.is_gas else 0, 1 if receipt.is_parking else 0,
            receipt.craft_people, receipt.episode_code,
            receipt.co_code, receipt.loc_code, receipt.account_code, receipt.tax_code, receipt.hst_account,
            1 if receipt.expense_only else 0, 1 if receipt.is_usd else 0, receipt.exchange_rate,
            1 if (getattr(receipt, 'is_asset', False) and not getattr(receipt, 'is_rental', False)) else 0
        ))
        conn.commit()
        try:
            from services.vendor_sync_service import sync_new_vendor_to_sheet
            import threading
            threading.Thread(
                target=sync_new_vendor_to_sheet,
                args=(receipt.vendor, receipt.description, receipt.is_rental, receipt.rental_end_date),
                daemon=True
            ).start()
        except Exception as ve:
            print(f"DEBUG: vendor_sync error: {ve}")
        receipt.id = cursor.lastrowid
    except sqlite3.IntegrityError:
        print(f"DEBUG: Receipt with hash {receipt.file_hash} already exists in DB. Updating instead.")
        cursor.execute('''
            UPDATE receipts SET
                file_path = ?, set_number = ?, buyer_name = ?, description = ?, vendor = ?,
                subtotal = ?, shipping = ?, import_fees = ?, tax = ?, total = ?, payment_method = ?, date = ?, 
                reference_number = ?, po_number = ?, is_rental = ?, 
                rental_end_date = ?, notes = ?, status = ?, is_greens = ?,
                is_craft = ?, is_gas = ?, is_parking = ?, craft_people = ?, episode_code = ?,
                co_code = ?, loc_code = ?, account_code = ?, tax_code = ?, hst_account = ?, expense_only = ?, is_usd = ?, exchange_rate = ?, is_asset = ?
            WHERE file_hash = ?
        ''', (
            receipt.file_path, receipt.set_number, receipt.buyer_name,
            receipt.description, receipt.vendor, receipt.subtotal, receipt.shipping, receipt.import_fees, receipt.tax, receipt.total,
            receipt.payment_method, receipt.date, receipt.reference_number,
            receipt.po_number, 1 if receipt.is_rental else 0, receipt.rental_end_date,
            receipt.notes, receipt.status, 1 if receipt.is_greens else 0,
            1 if receipt.is_craft else 0, 1 if receipt.is_gas else 0, 1 if receipt.is_parking else 0,
            receipt.craft_people, receipt.episode_code,
            receipt.co_code, receipt.loc_code, receipt.account_code, receipt.tax_code, receipt.hst_account,
            1 if receipt.expense_only else 0, 1 if receipt.is_usd else 0, receipt.exchange_rate,
            1 if (getattr(receipt, 'is_asset', False) and not getattr(receipt, 'is_rental', False)) else 0,
            receipt.file_hash
        ))
        conn.commit()
        try:
            from services.vendor_sync_service import sync_new_vendor_to_sheet
            import threading
            threading.Thread(
                target=sync_new_vendor_to_sheet,
                args=(receipt.vendor, receipt.description, receipt.is_rental, receipt.rental_end_date),
                daemon=True
            ).start()
        except Exception as ve:
            print(f"DEBUG: vendor_sync error: {ve}")
        cursor.execute('SELECT id FROM receipts WHERE file_hash = ?', (receipt.file_hash,))
        row = cursor.fetchone()
        if row:
            receipt.id = row['id']
    except Exception as e:
        print(f"DEBUG: SQLite Insertion Error: {e}")
        raise e
    finally:
        conn.close()

def update_receipt(receipt: Receipt):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE receipts SET
            file_path = ?, set_number = ?, special_tab = ?, buyer_name = ?, description = ?, vendor = ?,
            subtotal = ?, shipping = ?, import_fees = ?, tax = ?, total = ?, payment_method = ?, date = ?, 
            reference_number = ?, po_number = ?, is_rental = ?, 
            rental_end_date = ?, notes = ?, status = ?, is_greens = ?,
            is_craft = ?, is_gas = ?, is_parking = ?, craft_people = ?, episode_code = ?,
            co_code = ?, loc_code = ?, account_code = ?, tax_code = ?, hst_account = ?,
            expense_only = ?, is_usd = ?, exchange_rate = ?, is_asset = ?
        WHERE id = ?
    ''', (
        receipt.file_path, receipt.set_number, receipt.special_tab, receipt.buyer_name, receipt.description, receipt.vendor,
        receipt.subtotal, receipt.shipping, receipt.import_fees, receipt.tax, receipt.total, receipt.payment_method, receipt.date,
        receipt.reference_number, receipt.po_number, 1 if receipt.is_rental else 0,
        receipt.rental_end_date, receipt.notes, receipt.status, 1 if receipt.is_greens else 0,
        1 if receipt.is_craft else 0, 1 if receipt.is_gas else 0, 1 if receipt.is_parking else 0,
        receipt.craft_people, receipt.episode_code,
        receipt.co_code, receipt.loc_code, receipt.account_code, receipt.tax_code, receipt.hst_account,
        1 if receipt.expense_only else 0, 1 if receipt.is_usd else 0, receipt.exchange_rate,
        1 if (getattr(receipt, 'is_asset', False) and not getattr(receipt, 'is_rental', False)) else 0,
        receipt.id
    ))
    conn.commit()
    conn.close()

def get_pending_receipts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM receipts WHERE status IN ("PENDING", "SKIPPED")')
    rows = cursor.fetchall()
    conn.close()
    
    receipts = []
    for row in rows:
        receipts.append(Receipt(
            id=row['id'], file_path=row['file_path'], file_hash=row['file_hash'], set_number=row['set_number'],
            special_tab=row['special_tab'] if 'special_tab' in row.keys() else None,
            buyer_name=row['buyer_name'], description=row['description'], vendor=row['vendor'], subtotal=row['subtotal'],
            shipping=row['shipping'], import_fees=row['import_fees'] if 'import_fees' in row.keys() else None, tax=row['tax'], total=row['total'], payment_method=row['payment_method'], date=row['date'],
            reference_number=row['reference_number'], po_number=row['po_number'], is_rental=bool(row['is_rental']),
            rental_end_date=row['rental_end_date'], notes=row['notes'], status=row['status'], created_at=row['created_at'],
            is_greens=bool(row['is_greens']), is_craft=bool(row['is_craft']), is_gas=bool(row['is_gas']), is_parking=bool(row['is_parking']),
            craft_people=row['craft_people'], episode_code=row['episode_code'], co_code=row['co_code'], loc_code=row['loc_code'], 
            account_code=row['account_code'], tax_code=row['tax_code'], hst_account=row['hst_account'], expense_only=bool(row['expense_only']),
            is_usd=bool(row['is_usd']) if 'is_usd' in row.keys() else False, exchange_rate=row['exchange_rate'] if 'exchange_rate' in row.keys() else None,
            is_asset=bool(row['is_asset']) if 'is_asset' in row.keys() else False
        ))
    return receipts

def get_approved_receipts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM receipts WHERE status = "APPROVED"')
    rows = cursor.fetchall()
    conn.close()
    
    receipts = []
    for row in rows:
        receipts.append(Receipt(
            id=row['id'], file_path=row['file_path'], file_hash=row['file_hash'], set_number=row['set_number'],
            special_tab=row['special_tab'] if 'special_tab' in row.keys() else None,
            buyer_name=row['buyer_name'], description=row['description'], vendor=row['vendor'], subtotal=row['subtotal'],
            shipping=row['shipping'], import_fees=row['import_fees'] if 'import_fees' in row.keys() else None, tax=row['tax'], total=row['total'], payment_method=row['payment_method'], date=row['date'],
            reference_number=row['reference_number'], po_number=row['po_number'], is_rental=bool(row['is_rental']),
            rental_end_date=row['rental_end_date'], notes=row['notes'], status=row['status'], created_at=row['created_at'],
            is_greens=bool(row['is_greens']), is_craft=bool(row['is_craft']), is_gas=bool(row['is_gas']), is_parking=bool(row['is_parking']),
            craft_people=row['craft_people'], episode_code=row['episode_code'], co_code=row['co_code'], loc_code=row['loc_code'], 
            account_code=row['account_code'], tax_code=row['tax_code'], hst_account=row['hst_account'], expense_only=bool(row['expense_only']),
            is_usd=bool(row['is_usd']) if 'is_usd' in row.keys() else False, exchange_rate=row['exchange_rate'] if 'exchange_rate' in row.keys() else None,
            is_asset=bool(row['is_asset']) if 'is_asset' in row.keys() else False
        ))
    return receipts

def check_for_duplicate(vendor, date, total, ref_num=None, po_num=None, exclude_id=None):
    if not vendor or not date or not total:
        return None
        
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM receipts WHERE vendor = ? AND date = ? AND total = ? AND status = 'APPROVED'"
    params = [vendor, date, total]
    
    if exclude_id:
        query += ' AND id != ?'
        params.append(exclude_id)
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    for row in rows:
        # If both have a reference number and they are different, not a duplicate
        if ref_num and row['reference_number']:
            if str(ref_num).strip().lower() != str(row['reference_number']).strip().lower():
                continue
                
        # If both have a PO number and they are different, not a duplicate
        if po_num and row['po_number']:
            if str(po_num).strip().lower() != str(row['po_number']).strip().lower():
                continue
                
        return Receipt(
            id=row['id'], file_path=row['file_path'], file_hash=row['file_hash'], set_number=row['set_number'],
            special_tab=row['special_tab'] if 'special_tab' in row.keys() else None,
            buyer_name=row['buyer_name'], description=row['description'], vendor=row['vendor'], subtotal=row['subtotal'],
            shipping=row['shipping'], import_fees=row['import_fees'] if 'import_fees' in row.keys() else None, tax=row['tax'], total=row['total'], payment_method=row['payment_method'], date=row['date'],
            reference_number=row['reference_number'], po_number=row['po_number'], is_rental=bool(row['is_rental']),
            rental_end_date=row['rental_end_date'], notes=row['notes'], status=row['status'], created_at=row['created_at'],
            is_greens=bool(row['is_greens']), is_craft=bool(row['is_craft']), is_gas=bool(row['is_gas']), is_parking=bool(row['is_parking']),
            craft_people=row['craft_people'], episode_code=row['episode_code'], co_code=row['co_code'], loc_code=row['loc_code'], 
            account_code=row['account_code'], tax_code=row['tax_code'], hst_account=row['hst_account'], expense_only=bool(row['expense_only']),
            is_usd=bool(row['is_usd']) if 'is_usd' in row.keys() else False, exchange_rate=row['exchange_rate'] if 'exchange_rate' in row.keys() else None,
            is_asset=bool(row['is_asset']) if 'is_asset' in row.keys() else False
        )
    return None

def get_receipt_by_id(receipt_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM receipts WHERE id = ?', (receipt_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return Receipt(
            id=row['id'], file_path=row['file_path'], file_hash=row['file_hash'], set_number=row['set_number'],
            special_tab=row['special_tab'] if 'special_tab' in row.keys() else None,
            buyer_name=row['buyer_name'], description=row['description'], vendor=row['vendor'], subtotal=row['subtotal'],
            shipping=row['shipping'], import_fees=row['import_fees'] if 'import_fees' in row.keys() else None, tax=row['tax'], total=row['total'], payment_method=row['payment_method'], date=row['date'],
            reference_number=row['reference_number'], po_number=row['po_number'], is_rental=bool(row['is_rental']),
            rental_end_date=row['rental_end_date'], notes=row['notes'], status=row['status'], created_at=row['created_at'],
            is_greens=bool(row['is_greens']), is_craft=bool(row['is_craft']), is_gas=bool(row['is_gas']), is_parking=bool(row['is_parking']),
            craft_people=row['craft_people'], episode_code=row['episode_code'], co_code=row['co_code'], loc_code=row['loc_code'], 
            account_code=row['account_code'], tax_code=row['tax_code'], hst_account=row['hst_account'], expense_only=bool(row['expense_only']),
            is_usd=bool(row['is_usd']) if 'is_usd' in row.keys() else False, exchange_rate=row['exchange_rate'] if 'exchange_rate' in row.keys() else None,
            is_asset=bool(row['is_asset']) if 'is_asset' in row.keys() else False
        )
    return None

def get_receipt_by_path(path):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM receipts WHERE file_path = ?', (path,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return Receipt(
            id=row['id'], file_path=row['file_path'], file_hash=row['file_hash'], set_number=row['set_number'],
            special_tab=row['special_tab'] if 'special_tab' in row.keys() else None,
            buyer_name=row['buyer_name'], description=row['description'], vendor=row['vendor'], subtotal=row['subtotal'],
            shipping=row['shipping'], import_fees=row['import_fees'] if 'import_fees' in row.keys() else None, tax=row['tax'], total=row['total'], payment_method=row['payment_method'], date=row['date'],
            reference_number=row['reference_number'], po_number=row['po_number'], is_rental=bool(row['is_rental']),
            rental_end_date=row['rental_end_date'], notes=row['notes'], status=row['status'], created_at=row['created_at'],
            is_greens=bool(row['is_greens']), is_craft=bool(row['is_craft']), is_gas=bool(row['is_gas']), is_parking=bool(row['is_parking']),
            craft_people=row['craft_people'], episode_code=row['episode_code'], co_code=row['co_code'], loc_code=row['loc_code'], 
            account_code=row['account_code'], tax_code=row['tax_code'], hst_account=row['hst_account'], expense_only=bool(row['expense_only']),
            is_usd=bool(row['is_usd']) if 'is_usd' in row.keys() else False, exchange_rate=row['exchange_rate'] if 'exchange_rate' in row.keys() else None,
            is_asset=bool(row['is_asset']) if 'is_asset' in row.keys() else False
        )
    return None

def skip_receipt(receipt: Receipt):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE receipts SET status = "SKIPPED" WHERE id = ?', (receipt.id,))
    conn.commit()
    conn.close()


# --- CHEQUE REQUEST & ACH TRACKING FUNCTIONS ---

def add_cheque_request(data: dict) -> int:
    try:
        from services.ch_req_sheet_helper import normalize_rental_period
        if data.get('rental_period'):
            data['rental_period'] = normalize_rental_period(data['rental_period'])
    except Exception:
        pass
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO cheque_requests (
            date_submitted, date_required, payment_type, vendor, set_number,
            description, reference_number, invoice_date, subtotal, tax,
            total, rental_period, buyer_name, cheque_number, delivery_notes,
            status, sheet_row_id, pdf_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.get('date_submitted', datetime.now().strftime('%m/%d/%Y')),
        data.get('date_required', ''),
        data.get('payment_type', 'CHQ'),
        data.get('vendor', ''),
        data.get('set_number', ''),
        data.get('description', ''),
        data.get('reference_number', ''),
        data.get('invoice_date', ''),
        float(data.get('subtotal') or 0.0),
        float(data.get('tax') or 0.0),
        float(data.get('total') or 0.0),
        data.get('rental_period', ''),
        data.get('buyer_name', ''),
        data.get('cheque_number', ''),
        data.get('delivery_notes', ''),
        data.get('status', 'PENDING'),
        data.get('sheet_row_id'),
        data.get('pdf_path', '')
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    try:
        from services.vendor_sync_service import sync_new_vendor_to_sheet
        import threading
        threading.Thread(
            target=sync_new_vendor_to_sheet,
            args=(data.get('vendor'), data.get('description'), bool(data.get('rental_period')), data.get('rental_period')),
            daemon=True
        ).start()
    except Exception as ve:
        print(f'DEBUG: vendor_sync error: {ve}')
    return new_id

def parse_date_key(d_str):
    if not d_str:
        return datetime.max
    s = str(d_str).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d-%b-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    try:
        from dateutil import parser
        return parser.parse(s, fuzzy=True)
    except Exception:
        return datetime.max

def get_pending_cheque_requests(status_filter: str = None) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    if status_filter:
        cursor.execute('SELECT * FROM cheque_requests WHERE status = ?', (status_filter,))
    else:
        cursor.execute('SELECT * FROM cheque_requests WHERE status IN ("PENDING", "RECEIVED")')
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    rows.sort(key=lambda x: (parse_date_key(x.get("date_required")), parse_date_key(x.get("date_submitted")), x.get("id", 0)))
    return rows

def get_all_cheque_requests() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM cheque_requests ORDER BY id DESC')
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_cheque_request_by_id(req_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM cheque_requests WHERE id = ?', (req_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_cheque_request_completion(req_id: int, cheque_number: str, delivery_notes: str, status: str = 'DELIVERED') -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE cheque_requests 
        SET cheque_number = ?, delivery_notes = ?, status = ?
        WHERE id = ?
    ''', (cheque_number, delivery_notes, status, req_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def update_cheque_request_status(req_id: int, status: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE cheque_requests SET status = ? WHERE id = ?', (status, req_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def delete_cheque_request(req_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM cheque_requests WHERE id = ?', (req_id,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def find_receipt_by_reference(ref_num: str, vendor: str = None) -> list:
    if not ref_num and not vendor:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    clean_ref = str(ref_num).strip()
    rows = []
    if clean_ref:
        cursor.execute('SELECT * FROM receipts WHERE reference_number = ?', (clean_ref,))
        rows = [dict(r) for r in cursor.fetchall()]
        if not rows:
            cursor.execute('SELECT * FROM receipts WHERE reference_number LIKE ?', (f'%{clean_ref}%',))
            rows = [dict(r) for r in cursor.fetchall()]
        if not rows and clean_ref.isdigit():
            num_val = str(int(clean_ref))
            cursor.execute('SELECT * FROM receipts WHERE reference_number LIKE ?', (f'%{num_val}%',))
            rows = [dict(r) for r in cursor.fetchall()]
    if not rows and vendor:
        clean_vendor = str(vendor).strip().upper()
        words = [w for w in re.split(r'[^A-Za-z0-9]', clean_vendor) if len(w) >= 3 and w not in ['INC', 'LTD', 'CORP', 'LLC', 'THE', 'AND', 'PROP', 'PROPS', 'RENTAL', 'RENTALS']]
        if words:
            query_word = words[0]
            cursor.execute('SELECT * FROM receipts WHERE vendor LIKE ?', (f'%{query_word}%',))
            rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def queue_offline_receipt(receipt_id: int, action: str = 'APPEND', error_message: str = '') -> int:
    conn = get_connection()
    cursor = conn.cursor()
    # Avoid duplicate queuing for the same receipt
    cursor.execute('SELECT id FROM offline_sync_queue WHERE receipt_id = ?', (receipt_id,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute('UPDATE offline_sync_queue SET action = ?, error_message = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?',
                       (action, error_message, existing[0]))
        queue_id = existing[0]
    else:
        cursor.execute('INSERT INTO offline_sync_queue (receipt_id, action, error_message) VALUES (?, ?, ?)',
                       (receipt_id, action, error_message))
        queue_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return queue_id

def get_offline_queue() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, receipt_id, action, error_message, created_at FROM offline_sync_queue ORDER BY id ASC')
    rows = cursor.fetchall()
    conn.close()
    items = []
    for r in rows:
        receipt = get_receipt_by_id(r['receipt_id'])
        if receipt:
            items.append({
                'queue_id': r['id'],
                'receipt_id': r['receipt_id'],
                'receipt': receipt,
                'action': r['action'],
                'error_message': r['error_message'],
                'created_at': r['created_at']
            })
    return items

def remove_from_offline_queue(queue_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM offline_sync_queue WHERE id = ?', (queue_id,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected

def get_offline_queue_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM offline_sync_queue')
    count = cursor.fetchone()[0]
    conn.close()
    return count

