import os
import re
from datetime import datetime, timedelta
import gspread
from core.settings import load_settings
from services.sheets import get_spreadsheet
from core.database import (
    add_cheque_request, get_pending_cheque_requests, get_cheque_request_by_id,
    update_cheque_request_completion, delete_cheque_request, find_receipt_by_reference,
    get_connection, update_cheque_request_status
)

PASTEL_HEADER_BG = {"red": 0.91, "green": 0.84, "blue": 0.95}       # #E8D7F1 Soft Lilac
PASTEL_COL_HEADER_BG = {"red": 0.95, "green": 0.90, "blue": 0.97}   # #F2E6F7 Soft Pastel Lavender
PASTEL_BORDER_COLOR = {"red": 0.80, "green": 0.70, "blue": 0.87}    # #CBB2DE
PASTEL_TEXT_COLOR = {"red": 0.20, "green": 0.18, "blue": 0.26}      # Dark Slate Purple
PASTEL_TAB_COLOR = {"red": 0.88, "green": 0.77, "blue": 0.95}       # Tab Color
PASTEL_PENDING_BG = {"red": 1.0, "green": 0.95, "blue": 0.80}       # Soft warm pastel gold for PENDING
PASTEL_REQ_BG = {"red": 0.80, "green": 0.93, "blue": 0.82}          # Soft Mint Green (#CCECD1)
PASTEL_REQ_TEXT = {"red": 0.08, "green": 0.40, "blue": 0.16}
PASTEL_CHQ_BG = PASTEL_REQ_BG
PASTEL_CHQ_TEXT = PASTEL_REQ_TEXT        # Deep Green text (#146629)
PASTEL_ACH_BG = {"red": 1.0, "green": 1.0, "blue": 1.0}             # White
PASTEL_ACH_TEXT = {"red": 0.20, "green": 0.18, "blue": 0.26}        # Dark Slate
DATE_REQ_HIGHLIGHT_BG = {"red": 1.0, "green": 0.898, "blue": 0.60}  # #FFE599 Light Yellow 2
DATE_REQ_OVERDUE_BG = {"red": 0.96, "green": 0.80, "blue": 0.80}    # #F4CCCC Soft Light Red
DATE_REQ_OVERDUE_TEXT = {"red": 0.60, "green": 0.10, "blue": 0.10}  # #990000 Deep Red text
PASTEL_PO_BG = {"red": 0.81, "green": 0.89, "blue": 0.97}          # Soft Light Blue (#CFE2F3)
PASTEL_PO_TEXT = {"red": 0.04, "green": 0.33, "blue": 0.58}        # Deep Blue text (#0B5394)


MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "June",
    7: "July", 8: "Aug", 9: "Sept", 10: "Oct", 11: "Nov", 12: "Dec"
}

MONTH_LOOKUP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12
}

def format_single_date(m, d):
    m_name = MONTH_NAMES.get(m, "")
    return f"{m_name} {int(d)}"

def parse_date_token(tok: str):
    if not tok:
        return None
    s = str(tok).strip()
    s = re.sub(r'\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b\.?,?\s*', '', s, flags=re.IGNORECASE).strip()
    
    # YYYY-MM-DD
    m = re.match(r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$', s)
    if m:
        return int(m.group(2)), int(m.group(3))
        
    # MM/DD/YYYY or MM/DD
    m = re.match(r'^(\d{1,2})/(\d{1,2})(?:/\d{2,4})?$', s)
    if m:
        return int(m.group(1)), int(m.group(2))

    # DD-Mon-YYYY (e.g. 20-Oct-2026 or 20 Oct)
    m = re.match(r'^(\d{1,2})(?:st|nd|rd|th)?[\s\-_.]+([a-zA-Z]+)(?:[\s\-_.]+\d{2,4})?$', s)
    if m:
        m_num = MONTH_LOOKUP.get(m.group(2).lower())
        if m_num:
            return m_num, int(m.group(1))

    # Mon-DD-YYYY or Mon DD (e.g. Oct 20, 2026 or Oct-20)
    m = re.match(r'^([a-zA-Z]+)[\s\-_.]+(\d{1,2})(?:st|nd|rd|th)?(?:[\s\-_.,]+\d{2,4})?$', s)
    if m:
        m_num = MONTH_LOOKUP.get(m.group(1).lower())
        if m_num:
            return m_num, int(m.group(2))

    return None

def normalize_rental_period(val: str) -> str:
    """
    Always normalizes rental date ranges to the standard format:
    'Oct 20 - Oct 27' or 'Sept 10 - Oct 14'
    """
    if not val:
        return ""
    s = str(val).strip()
    if not s:
        return ""

    s = re.sub(r'\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b\.?,?\s*', '', s, flags=re.IGNORECASE)

    parts = re.split(r'\s+(?:to|until|thru|through)\s+|\s*(?:–|—)\s*|\s+-\s+', s, flags=re.IGNORECASE)
    if len(parts) == 1 and '-' in s and not re.search(r'\d{4}-\d{2}-\d{2}', s):
        parts = s.split('-')

    if len(parts) >= 2:
        part1 = parts[0].strip()
        part2 = parts[1].strip()

        d1 = parse_date_token(part1)
        d2 = parse_date_token(part2)

        if d1 and not d2:
            m_day_only = re.match(r'^(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*\d{4})?$', part2)
            if m_day_only:
                d2 = (d1[0], int(m_day_only.group(1)))

        if d1 and d2:
            s_str = format_single_date(d1[0], d1[1])
            e_str = format_single_date(d2[0], d2[1])
            return f"{s_str} - {e_str}"

    return s

HEADERS = [
    "DATE SUBMITTED",
    "DATE REQUIRED",
    "TYPE",
    "VENDOR",
    "INV / REF #",
    "SET #",
    "DESCRIPTION / ITEMS",
    "INVOICE DATE",
    "SUBTOTAL",
    "TOTAL",
    "RENTAL DATES",
    "BUYER",
    "CHQ / ACH #",
    "DELIVERY / NOTES",
    "STATUS"
]

COL_WIDTHS = [
    135, # A: Date Submitted
    135, # B: Date Required
    95,  # C: Type (CH REQ / ACH / PO)
    250, # D: Vendor
    140, # E: Inv / Ref #
    90,  # F: Set #
    320, # G: Description
    125, # H: Invoice Date
    120, # I: Subtotal
    120, # J: Total
    180, # K: Rental Dates
    125, # L: Buyer
    150, # M: CHQ / ACH #
    200, # N: Delivery / Notes
    110  # O: Status
]

def get_or_create_ch_reqs_worksheet(sh):
    """
    Finds or creates the cute pastel CH REQS tab in the Google Spreadsheet.
    """
    try:
        ws = sh.worksheet("CH REQS")
        return ws
    except gspread.exceptions.WorksheetNotFound:
        # Create worksheet at index 2 (right after TRACKER TOPSHEET)
        try:
            ws = sh.add_worksheet(title="CH REQS", rows=100, cols=len(HEADERS), index=2)
        except Exception:
            ws = sh.add_worksheet(title="CH REQS", rows=100, cols=len(HEADERS))
        
        apply_ch_reqs_tab_styling(sh, ws)
        return ws

def apply_ch_reqs_tab_styling(sh, ws):
    """
    Applies the cute pastel aesthetic to the CH REQS worksheet.
    """
    sheet_id = ws.id
    title_row = ["🌸 CHEQUE REQUISITION & ACH TRACKER 🌸"] + [""] * (len(HEADERS) - 1)
    
    ws.update(values=[title_row, HEADERS], range_name=f"A1:{chr(ord('A') + len(HEADERS) - 1)}2", value_input_option='USER_ENTERED')
    
    requests = []
    
    # 1. Set Tab Color and Frozen Rows
    requests.append({
        'updateSheetProperties': {
            'properties': {
                'sheetId': sheet_id,
                'tabColorStyle': {
                    'rgbColor': PASTEL_TAB_COLOR
                },
                'gridProperties': {
                    'frozenRowCount': 2
                }
            },
            'fields': 'tabColorStyle,gridProperties.frozenRowCount'
        }
    })
    
    # 2. Merge Row 1 Title Banner (A1:O1)
    requests.append({
        'mergeCells': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 0,
                'endRowIndex': 1,
                'startColumnIndex': 0,
                'endColumnIndex': len(HEADERS)
            },
            'mergeType': 'MERGE_ALL'
        }
    })
    
    # 3. Format Title Banner (Row 1)
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 0,
                'endRowIndex': 1,
                'startColumnIndex': 0,
                'endColumnIndex': len(HEADERS)
            },
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': PASTEL_HEADER_BG,
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE',
                    'textFormat': {
                        'foregroundColor': PASTEL_TEXT_COLOR,
                        'fontSize': 13,
                        'bold': True
                    }
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)'
        }
    })
    
    # 4. Format Column Headers (Row 2)
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 1,
                'endRowIndex': 2,
                'startColumnIndex': 0,
                'endColumnIndex': len(HEADERS)
            },
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': PASTEL_COL_HEADER_BG,
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE',
                    'wrapStrategy': 'WRAP',
                    'textFormat': {
                        'foregroundColor': PASTEL_TEXT_COLOR,
                        'fontSize': 12,
                        'bold': True
                    },
                    'borders': {
                        'bottom': {
                            'style': 'SOLID_MEDIUM',
                            'color': PASTEL_BORDER_COLOR
                        }
                    }
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat,borders)'
        }
    })
    
    # 5. Row Heights: Row 1 = 42px, Row 2 = 36px, Row 3-1000 = 32px (for Font 12 readability)
    requests.append({
        'updateDimensionProperties': {
            'range': {'sheetId': sheet_id, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 1},
            'properties': {'pixelSize': 42},
            'fields': 'pixelSize'
        }
    })
    requests.append({
        'updateDimensionProperties': {
            'range': {'sheetId': sheet_id, 'dimension': 'ROWS', 'startIndex': 1, 'endIndex': 2},
            'properties': {'pixelSize': 36},
            'fields': 'pixelSize'
        }
    })
    requests.append({
        'updateDimensionProperties': {
            'range': {'sheetId': sheet_id, 'dimension': 'ROWS', 'startIndex': 2, 'endIndex': 1000},
            'properties': {'pixelSize': 32},
            'fields': 'pixelSize'
        }
    })
    
    # 6. Column Widths
    for c_idx, width in enumerate(COL_WIDTHS):
        requests.append({
            'updateDimensionProperties': {
                'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': c_idx, 'endIndex': c_idx + 1},
                'properties': {'pixelSize': width},
                'fields': 'pixelSize'
            }
        })
        
    # 7. Data rows Font 12 format (Rows 3 to 1000) - Center aligned by default
    data_font_fmt = {
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 1000,
                'startColumnIndex': 0,
                'endColumnIndex': len(HEADERS)
            },
            'cell': {
                'userEnteredFormat': {
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE',
                    'textFormat': {
                        'fontSize': 12
                    }
                }
            },
            'fields': 'userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.fontSize)'
        }
    }
    requests.append(data_font_fmt)

    # Left-align Vendor (Col D, index 3)
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 1000,
                'startColumnIndex': 3,
                'endColumnIndex': 4
            },
            'cell': {
                'userEnteredFormat': {
                    'horizontalAlignment': 'LEFT',
                    'verticalAlignment': 'MIDDLE',
                    'textFormat': {
                        'fontSize': 12
                    }
                }
            },
            'fields': 'userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.fontSize)'
        }
    })

    # Left-align Description (Col G, index 6)
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 1000,
                'startColumnIndex': 6,
                'endColumnIndex': 7
            },
            'cell': {
                'userEnteredFormat': {
                    'horizontalAlignment': 'LEFT',
                    'verticalAlignment': 'MIDDLE',
                    'textFormat': {
                        'fontSize': 12
                    }
                }
            },
            'fields': 'userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.fontSize)'
        }
    })

    # Highlight Header Cell B2 (DATE REQUIRED) in #FFE599
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 1,
                'endRowIndex': 2,
                'startColumnIndex': 1,
                'endColumnIndex': 2
            },
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': DATE_REQ_HIGHLIGHT_BG,
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE',
                    'wrapStrategy': 'WRAP',
                    'textFormat': {
                        'foregroundColor': PASTEL_TEXT_COLOR,
                        'fontSize': 12,
                        'bold': True
                    },
                    'borders': {
                        'bottom': {
                            'style': 'SOLID_MEDIUM',
                            'color': PASTEL_BORDER_COLOR
                        }
                    }
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat,borders)'
        }
    })

    # Highlight Data Column B (Rows 3 to 1000) in #FFE599
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 1000,
                'startColumnIndex': 1,
                'endColumnIndex': 2
            },
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': DATE_REQ_HIGHLIGHT_BG,
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE',
                    'textFormat': {
                        'foregroundColor': PASTEL_TEXT_COLOR,
                        'fontSize': 12
                    }
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)'
        }
    })

    # 8. Number Formatting for Subtotal (Col I, index 8) and Total (Col J, index 9) - Center aligned
    currency_fmt = {
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 1000,
                'startColumnIndex': 8,
                'endColumnIndex': 10
            },
            'cell': {
                'userEnteredFormat': {
                    'numberFormat': {
                        'type': 'CURRENCY',
                        'pattern': '"$"#,##0.00'
                    },
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE',
                    'textFormat': {
                        'fontSize': 12
                    }
                }
            },
            'fields': 'userEnteredFormat(numberFormat,horizontalAlignment,verticalAlignment,textFormat.fontSize)'
        }
    }
    requests.append(currency_fmt)

    # Reset Column C (Type) base background to clean white so only conditional rules color it
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 1000,
                'startColumnIndex': 2,
                'endColumnIndex': 3
            },
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0},
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE',
                    'textFormat': {
                        'fontSize': 12
                    }
                }
            },
            'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat.fontSize)'
        }
    })

    # 9. Clear any existing conditional formatting rules on this tab to avoid duplication
    try:
        sheet_metadata = sh.fetch_sheet_metadata()
        for s in sheet_metadata.get('sheets', []):
            if s['properties']['sheetId'] == sheet_id:
                cfrs = s.get('conditionalFormats', [])
                for i in reversed(range(len(cfrs))):
                    requests.append({
                        'deleteConditionalFormatRule': {
                            'sheetId': sheet_id,
                            'index': i
                        }
                    })
                break
    except Exception as e:
        print(f"Warning: could not inspect existing conditional format rules: {e}")

    # 10. Conditional Formatting: DATE REQUIRED (Col B, index 1) is light red when passed (DATE_BEFORE TODAY)
    requests.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': 1000,
                    'startColumnIndex': 1,
                    'endColumnIndex': 2
                }],
                'booleanRule': {
                    'condition': {
                        'type': 'DATE_BEFORE',
                        'values': [{'relativeDate': 'TODAY'}]
                    },
                    'format': {
                        'backgroundColor': DATE_REQ_OVERDUE_BG,
                        'textFormat': {
                            'foregroundColor': DATE_REQ_OVERDUE_TEXT,
                            'bold': True
                        }
                    }
                }
            },
            'index': 0
        }
    })

    # 11. Conditional Formatting: CHQ / REQ highlighted green, ACH stays white
    requests.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': 1000,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                }],
                'booleanRule': {
                    'condition': {
                        'type': 'TEXT_CONTAINS',
                        'values': [{'userEnteredValue': 'CHQ'}]
                    },
                    'format': {
                        'backgroundColor': PASTEL_CHQ_BG,
                        'textFormat': {
                            'foregroundColor': PASTEL_CHQ_TEXT,
                            'bold': True
                        }
                    }
                }
            },
            'index': 1
        }
    })
    requests.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': 1000,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                }],
                'booleanRule': {
                    'condition': {
                        'type': 'TEXT_CONTAINS',
                        'values': [{'userEnteredValue': 'REQ'}]
                    },
                    'format': {
                        'backgroundColor': PASTEL_CHQ_BG,
                        'textFormat': {
                            'foregroundColor': PASTEL_CHQ_TEXT,
                            'bold': True
                        }
                    }
                }
            },
            'index': 2
        }
    })
    requests.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': 1000,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                }],
                'booleanRule': {
                    'condition': {
                        'type': 'TEXT_EQ',
                        'values': [{'userEnteredValue': 'ACH'}]
                    },
                    'format': {
                        'backgroundColor': PASTEL_ACH_BG,
                        'textFormat': {
                            'foregroundColor': PASTEL_ACH_TEXT,
                            'bold': True
                        }
                    }
                }
            },
            'index': 2
        }
    })
    # 12. Conditional Formatting: PO highlighted light blue
    requests.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': 1000,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                }],
                'booleanRule': {
                    'condition': {
                        'type': 'TEXT_CONTAINS',
                        'values': [{'userEnteredValue': 'PO'}]
                    },
                    'format': {
                        'backgroundColor': PASTEL_PO_BG,
                        'textFormat': {
                            'foregroundColor': PASTEL_PO_TEXT,
                            'bold': True
                        }
                    }
                }
            },
            'index': 3
        }
    })
    # 13. Conditional Formatting: STATUS (Col O) RECEIVED highlighted mint green
    requests.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': 1000,
                    'startColumnIndex': 14,
                    'endColumnIndex': 15
                }],
                'booleanRule': {
                    'condition': {
                        'type': 'TEXT_CONTAINS',
                        'values': [{'userEnteredValue': 'RECEIVED'}]
                    },
                    'format': {
                        'backgroundColor': {'red': 0.82, 'green': 0.98, 'blue': 0.90},
                        'textFormat': {
                            'foregroundColor': {'red': 0.05, 'green': 0.40, 'blue': 0.25},
                            'bold': True
                        }
                    }
                }
            },
            'index': 4
        }
    })
    # 14. Conditional Formatting: STATUS (Col O) PENDING highlighted warm gold
    requests.append({
        'addConditionalFormatRule': {
            'rule': {
                'ranges': [{
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': 1000,
                    'startColumnIndex': 14,
                    'endColumnIndex': 15
                }],
                'booleanRule': {
                    'condition': {
                        'type': 'TEXT_CONTAINS',
                        'values': [{'userEnteredValue': 'PENDING'}]
                    },
                    'format': {
                        'backgroundColor': PASTEL_PENDING_BG,
                        'textFormat': {
                            'foregroundColor': {'red': 0.45, 'green': 0.35, 'blue': 0.05},
                            'bold': True
                        }
                    }
                }
            },
            'index': 5
        }
    })
    
    sh.batch_update({'requests': requests})


def sort_ch_reqs_worksheet(ws, sh=None):
    """
    Sorts all data rows in 'CH REQS' so the soonest Date Required is always at the top.
    """
    try:
        all_vals = ws.get_all_values()
        if len(all_vals) <= 2:
            return
            
        data_rows = all_vals[2:]
        clean_data = [r for r in data_rows if any(str(c).strip() for c in r[:6])]
        if not clean_data:
            return

        from core.database import parse_date_key
        clean_data.sort(key=lambda r: (parse_date_key(r[1] if len(r)>1 else ""), parse_date_key(r[0] if len(r)>0 else "")))

        for r in clean_data:
            while len(r) < len(HEADERS):
                r.append("")

        end_col = chr(ord('A') + len(HEADERS) - 1)
        end_row = len(clean_data) + 2
        ws.update(values=clean_data, range_name=f"A3:{end_col}{end_row}", value_input_option='USER_ENTERED')
        
        if sh:
            apply_ch_reqs_tab_styling(sh, ws)
    except Exception as e:
        print(f"Error sorting CH REQS sheet: {e}")

def record_cheque_request(data: dict) -> int:
    """
    Saves a new cheque requisition or ACH request locally to SQLite
    and appends it to the 'CH REQS' tab in Google Sheets.
    """
    # 1. Normalize data fields
    now_str = datetime.now().strftime("%m/%d/%Y")
    date_submitted = data.get("date_submitted") or data.get("DateSubmitted") or now_str
    date_required = data.get("date_required") or data.get("DateRequired") or ""
    payment_type = data.get("payment_type") or data.get("PaymentType") or "CHQ"
    if str(payment_type).upper() in ("CH REQ", "REQ"):
        payment_type = "CHQ"
    vendor = data.get("vendor") or data.get("Payee") or ""
    raw_set = data.get("set_number") or data.get("SetLocation") or ""
    
    # Special Set rule (e.g. X83 - X98 -> set is X98, initial set is X83)
    from core.set_list import resolve_special_and_initial_set
    sp_info = resolve_special_and_initial_set(
        set_input=raw_set,
        special_tab=data.get("special_tab"),
        notes=data.get("notes") or data.get("delivery_notes") or data.get("Notes")
    )
    if sp_info.get("is_special_98"):
        if sp_info.get("special_set") == "203-T":
            set_number = sp_info.get("display_pdf_set")
        else:
            set_number = sp_info.get("special_set")
        initial_set = sp_info.get("initial_set")
    else:
        set_number = raw_set
        initial_set = ""
    description = data.get("description") or data.get("Details") or ""
    reference_number = data.get("reference_number") or data.get("ReferenceNumber") or ""
    invoice_date = data.get("invoice_date") or data.get("Date") or ""
    
    # Clean up numeric values
    def parse_float(v):
        if not v: return 0.0
        clean = re.sub(r'[^0-9.-]', '', str(v))
        try:
            return float(clean)
        except ValueError:
            return 0.0

    subtotal = parse_float(data.get("subtotal") or data.get("AmountBeforeHST"))
    tax = parse_float(data.get("tax") or data.get("HSTAmount"))
    total = parse_float(data.get("total") or data.get("TotalAmount"))
    if total == 0.0 and (subtotal > 0 or tax > 0):
        total = round(subtotal + tax, 2)
    # Mathematical invariant: On a Cheque Requisition / ACH, subtotal + tax must equal total.
    # If subtotal equals total while tax > 0, or if subtotal was corrupted/mismatched, recalculate subtotal = total - tax.
    if total > 0 and tax > 0:
        if abs((subtotal + tax) - total) > 0.05 or subtotal == total:
            subtotal = round(total - tax, 2)
        
    # Automatic safety fallback: look up reference number from receipts table if missing
    if not reference_number and vendor:
        try:
            conn = get_connection()
            c = conn.cursor()
            if total > 0:
                c.execute("SELECT reference_number FROM receipts WHERE vendor LIKE ? AND total = ? AND reference_number IS NOT NULL AND reference_number != '' ORDER BY id DESC LIMIT 1", (f"%{vendor[:8]}%", total))
                found = c.fetchone()
                if found and found[0]:
                    reference_number = str(found[0]).strip()
            if not reference_number and invoice_date:
                c.execute("SELECT reference_number FROM receipts WHERE vendor LIKE ? AND date = ? AND reference_number IS NOT NULL AND reference_number != '' ORDER BY id DESC LIMIT 1", (f"%{vendor[:8]}%", invoice_date))
                found = c.fetchone()
                if found and found[0]:
                    reference_number = str(found[0]).strip()
            conn.close()
        except Exception:
            pass

    rental_period = data.get("rental_period") or data.get("RentalPeriod") or ""
    buyer_name = data.get("buyer_name") or data.get("RequestedBy") or ""
    cheque_number = data.get("cheque_number") or ""
    delivery_notes = data.get("delivery_notes") or ""
    if initial_set and initial_set.upper() not in delivery_notes.upper():
        delivery_notes = f"{initial_set} {delivery_notes}".strip()
    status = data.get("status") or "PENDING"
    pdf_path = data.get("pdf_path") or ""

    # Always pull full rental dates directly from the CH REQ PDF if available
    if pdf_path and os.path.exists(pdf_path):
        try:
            import fitz
            doc = fitz.open(pdf_path)
            if len(doc) > 0:
                for w in doc[0].widgets():
                    if w.field_name == "Rental Period" and w.field_value and str(w.field_value).strip():
                        rental_period = str(w.field_value).strip()
                    elif w.field_name == "Date5_af_date" and w.field_value and str(w.field_value).strip():
                        if not date_required:
                            date_required = str(w.field_value).strip()
                    elif w.field_name == "ACH" and w.field_value == "Yes":
                        if payment_type in ("CHQ", "REQ"):
                            payment_type = "ACH"
            doc.close()
        except Exception:
            pass

    rental_period = normalize_rental_period(rental_period)

    clean_dict = {
        "date_submitted": date_submitted,
        "date_required": date_required,
        "payment_type": payment_type,
        "vendor": vendor,
        "set_number": set_number,
        "description": description,
        "reference_number": reference_number,
        "invoice_date": invoice_date,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "rental_period": rental_period,
        "buyer_name": buyer_name,
        "cheque_number": cheque_number,
        "delivery_notes": delivery_notes,
        "status": status,
        "pdf_path": pdf_path
    }

    # User rule: Purchase Orders (POs) are tracked locally in the app tracker only,
    # NOT appended to the Google Sheets 'CH REQS' tab.
    if str(payment_type).strip().upper() == "PO":
        # Check if this item is already recorded as a CHQ or ACH - if so, do NOT record as PO
        try:
            conn_chk = get_connection()
            cur_chk = conn_chk.cursor()
            cur_chk.execute('''
                SELECT id, payment_type FROM cheque_requests 
                WHERE payment_type IN ('CHQ', 'ACH') 
                  AND UPPER(TRIM(vendor)) = UPPER(TRIM(?)) 
                  AND ABS(total - ?) < 0.05
            ''', (vendor, total))
            existing_chq = cur_chk.fetchone()
            conn_chk.close()
            if existing_chq:
                print(f"DEBUG: Skipping recording PO #{reference_number} because it already exists as {existing_chq[1]} #{existing_chq[0]}")
                return existing_chq[0]
        except Exception as e_chk:
            print(f"DEBUG: Error checking existing CHQ/ACH for PO: {e_chk}")

    # 2. Save locally in SQLite
    req_id = add_cheque_request(clean_dict)

    # Mutual exclusion: When recording a CHQ or ACH, remove any superseded PO entry for this vendor & total
    if str(payment_type).strip().upper() in ("CHQ", "ACH"):
        try:
            conn_clean = get_connection()
            cur_clean = conn_clean.cursor()
            cur_clean.execute('''
                DELETE FROM cheque_requests 
                WHERE payment_type = 'PO' 
                  AND UPPER(TRIM(vendor)) = UPPER(TRIM(?)) 
                  AND ABS(total - ?) < 0.05
            ''', (vendor, total))
            if cur_clean.rowcount > 0:
                print(f"DEBUG: Removed {cur_clean.rowcount} obsolete PO record(s) superseded by {payment_type} #{req_id} ({vendor})")
            conn_clean.commit()
            conn_clean.close()
        except Exception as e_clean:
            print(f"DEBUG: Error cleaning superseded PO: {e_clean}")
    
    # POs stay in the local SQLite tracker only
    if str(payment_type).strip().upper() == "PO":
        print(f"DEBUG: Saved PO #{reference_number} to local SQLite app tracker only (skipping Google Sheets CH REQS).")
        return req_id
    
    # 3. Append to Google Sheets 'CH REQS' tab
    try:
        settings = load_settings()
        url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
        if url:
            sh = get_spreadsheet(url)
            ws = get_or_create_ch_reqs_worksheet(sh)
            
            row_vals = [
                date_submitted,
                date_required,
                payment_type,
                vendor.upper(),
                reference_number.upper(),
                set_number.upper(),
                description.upper(),
                invoice_date,
                subtotal,
                total,
                rental_period,
                buyer_name.upper(),
                cheque_number,
                delivery_notes,
                status
            ]
            
            # Find next empty row starting at Row 3
            all_vals = ws.get_all_values()
            next_row = max(3, len(all_vals) + 1)
            for idx in range(2, len(all_vals)):
                r_data = all_vals[idx]
                if not r_data or not any(str(c).strip() for c in r_data[:6]):
                    next_row = idx + 1
                    break
                    
            end_col = chr(ord('A') + len(HEADERS) - 1)
            ws.update(values=[row_vals], range_name=f"A{next_row}:{end_col}{next_row}", value_input_option='USER_ENTERED')
            
            # Soft formatting for the newly added row (Font 12, center alignment except Vendor/Desc, Type highlighted)
            sheet_id = ws.id
            ws_requests = [{
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': next_row - 1,
                        'endRowIndex': next_row,
                        'startColumnIndex': 0,
                        'endColumnIndex': len(HEADERS)
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'horizontalAlignment': 'CENTER',
                            'verticalAlignment': 'MIDDLE',
                            'textFormat': {'fontSize': 12}
                        }
                    },
                    'fields': 'userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.fontSize)'
                }
            }]
            # Left-align Vendor (Col D, index 3)
            ws_requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': next_row - 1,
                        'endRowIndex': next_row,
                        'startColumnIndex': 3,
                        'endColumnIndex': 4
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'horizontalAlignment': 'LEFT',
                            'verticalAlignment': 'MIDDLE',
                            'textFormat': {'fontSize': 12}
                        }
                    },
                    'fields': 'userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.fontSize)'
                }
            })
            # Left-align Description (Col G, index 6)
            ws_requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': next_row - 1,
                        'endRowIndex': next_row,
                        'startColumnIndex': 6,
                        'endColumnIndex': 7
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'horizontalAlignment': 'LEFT',
                            'verticalAlignment': 'MIDDLE',
                            'textFormat': {'fontSize': 12}
                        }
                    },
                    'fields': 'userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.fontSize)'
                }
            })
            # Currency Formatting for Subtotal (Col I, index 8) and Total (Col J, index 9)
            ws_requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': next_row - 1,
                        'endRowIndex': next_row,
                        'startColumnIndex': 8,
                        'endColumnIndex': 10
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'numberFormat': {
                                'type': 'CURRENCY',
                                'pattern': '"$"#,##0.00'
                            },
                            'horizontalAlignment': 'CENTER',
                            'verticalAlignment': 'MIDDLE',
                            'textFormat': {'fontSize': 12}
                        }
                    },
                    'fields': 'userEnteredFormat(numberFormat,horizontalAlignment,verticalAlignment,textFormat.fontSize)'
                }
            })
            # Explicit highlight for Type cell: green for REQ, white for ACH
            type_bg = PASTEL_CHQ_BG if payment_type in ("CHQ", "REQ") else (PASTEL_ACH_BG if payment_type == "ACH" else {"red": 1.0, "green": 0.94, "blue": 0.84})
            type_fg = PASTEL_CHQ_TEXT if payment_type in ("CHQ", "REQ") else (PASTEL_ACH_TEXT if payment_type == "ACH" else {"red": 0.60, "green": 0.35, "blue": 0.05})
            ws_requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': next_row - 1,
                        'endRowIndex': next_row,
                        'startColumnIndex': 2,
                        'endColumnIndex': 3
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'backgroundColor': type_bg,
                            'horizontalAlignment': 'CENTER',
                            'verticalAlignment': 'MIDDLE',
                            'textFormat': {
                                'foregroundColor': type_fg,
                                'fontSize': 12,
                                'bold': True
                            }
                        }
                    },
                    'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)'
                }
            })
            sh.batch_update({'requests': ws_requests})
            sort_ch_reqs_worksheet(ws, sh)
            print(f"Recorded cheque request #{req_id} ({vendor}) to CH REQS sheet and sorted by soonest date.")
    except Exception as e:
        print(f"Error appending cheque request to Google Sheets: {e}")

    return req_id

def complete_cheque_and_update_tracker(req_id: int, cheque_number: str, delivery_notes: str) -> dict:
    """
    1. Looks up the request by req_id.
    2. Updates Column P (CHQ #) and Column Q (NOTES) in the Google Sheets set tab (e.g. H15).
    3. Deletes the row from the 'CH REQS' Google Sheet tab.
    4. Updates SQLite status to 'DELIVERED'.
    """
    req = get_cheque_request_by_id(req_id)
    if not req:
        return {"status": "error", "message": f"Cheque request #{req_id} not found in database."}

    settings = load_settings()
    url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
    if not url:
        return {"status": "error", "message": "Google Sheets URL missing in settings."}

    sh = get_spreadsheet(url)
    set_num = str(req.get("set_number", "")).strip().upper()
    ref_num = str(req.get("reference_number", "")).strip()
    vendor = str(req.get("vendor", "")).strip().upper()

    # If closing a PO with generic "PO COMPLETED", append completion date (e.g. "PO COMPLETED 11/17")
    if str(req.get("payment_type", "")).upper() == "PO":
        if cheque_number.strip().upper() == "PO COMPLETED":
            today_date = datetime.now().strftime("%m/%d")
            cheque_number = f"PO COMPLETED {today_date}"

    # Step A: Update Tracker Set Tab(s)
    # Handle split sets (e.g. "H15 / H16")
    target_sets = [s.strip().upper() for s in re.split(r'[/,&]+|\band\b', set_num) if s.strip()]
    if not target_sets:
        target_sets = ["H15"] # fallback

    updated_tabs = []
    
    for tab_title in target_sets:
        try:
            ws_set = sh.worksheet(tab_title)
            set_vals = ws_set.get_all_values()
            
            matched_row = None
            clean_po_ref = re.sub(r'^(PO\s*[:#]?\s*)', '', ref_num, flags=re.IGNORECASE).strip()
            
            # Priority 1: Match BOTH Vendor and Reference/PO
            for r_idx in range(7, len(set_vals)):
                r = set_vals[r_idx]
                r_vendor = str(r[2]).strip().upper() if len(r) > 2 else ""
                r_po = str(r[10]).strip().upper() if len(r) > 10 else ""
                r_ref = str(r[12]).strip().upper() if len(r) > 12 else ""
                
                vendor_matches = vendor and r_vendor and (vendor in r_vendor or r_vendor in vendor)
                ref_matches = False
                if clean_po_ref and r_po and (clean_po_ref.upper() == r_po or clean_po_ref.upper() in r_po):
                    ref_matches = True
                elif ref_num and r_ref:
                    if ref_num.upper() == r_ref:
                        ref_matches = True
                    elif len(ref_num) >= 3 and len(r_ref) >= 3 and (ref_num.upper() in r_ref or r_ref in ref_num.upper()):
                        ref_matches = True
                
                if vendor_matches and ref_matches:
                    matched_row = r_idx + 1
                    break

            # Priority 2: Match by exact Reference or exact PO
            if not matched_row:
                for r_idx in range(7, len(set_vals)):
                    r = set_vals[r_idx]
                    r_po = str(r[10]).strip().upper() if len(r) > 10 else ""
                    r_ref = str(r[12]).strip().upper() if len(r) > 12 else ""
                    
                    if clean_po_ref and r_po and (clean_po_ref.upper() == r_po):
                        matched_row = r_idx + 1
                        break
                    elif ref_num and r_ref:
                        if ref_num.upper() == r_ref or (len(r_ref) >= 4 and len(ref_num) >= 4 and (ref_num.upper() in r_ref or r_ref in ref_num.upper())):
                            matched_row = r_idx + 1
                            break

            # Priority 3: Match by Vendor
            if not matched_row and vendor:
                for r_idx in range(7, len(set_vals)):
                    r = set_vals[r_idx]
                    r_vendor = str(r[2]).strip().upper() if len(r) > 2 else ""
                    if r_vendor and (vendor in r_vendor or r_vendor in vendor):
                        matched_row = r_idx + 1
                        break
                    
            if matched_row:
                # Update Column P (CHQ #) and Column Q (NOTES), preserving existing notes (e.g. X83)
                existing_notes = str(set_vals[matched_row - 1][16]).strip() if len(set_vals[matched_row - 1]) > 16 else ""
                if existing_notes and delivery_notes.strip() and delivery_notes.strip() not in existing_notes:
                    final_notes = f"{existing_notes} {delivery_notes.strip()}".strip()
                else:
                    final_notes = existing_notes or delivery_notes.strip()
                updates = [[cheque_number.strip(), final_notes]]
                ws_set.update(values=updates, range_name=f"P{matched_row}:Q{matched_row}", value_input_option='USER_ENTERED')
                updated_tabs.append(f"{tab_title} (Row {matched_row})")
        except Exception as e:
            print(f"Error updating set tab {tab_title}: {e}")

    # Step B: Delete from 'CH REQS' tab in Google Sheets
    try:
        ws_ch = sh.worksheet("CH REQS")
        ch_vals = ws_ch.get_all_values()
        
        row_to_delete = None
        for idx in range(2, len(ch_vals)):
            r = ch_vals[idx]
            c_vendor = str(r[3]).strip().upper() if len(r) > 3 else ""
            c_ref = str(r[4]).strip().upper() if len(r) > 4 else ""
            
            vendor_match = bool(vendor and c_vendor and (vendor in c_vendor or c_vendor in vendor))
            ref_match = False
            if ref_num and c_ref:
                if ref_num.upper() == c_ref.upper():
                    ref_match = True
                elif len(ref_num) >= 4 and len(c_ref) >= 4 and (ref_num.upper() in c_ref.upper() or c_ref.upper() in ref_num.upper()):
                    ref_match = True

            if vendor_match and (ref_match or not ref_num):
                row_to_delete = idx + 1
                break
                
        if row_to_delete:
            ws_ch.delete_rows(row_to_delete)
            print(f"Deleted row {row_to_delete} from CH REQS sheet.")
    except Exception as e:
        print(f"Error removing from CH REQS sheet: {e}")

    # Step C: Update local SQLite status
    update_cheque_request_completion(req_id, cheque_number, delivery_notes, status="DELIVERED")

    summary_msg = f"Updated Tracker in {', '.join(updated_tabs) if updated_tabs else 'Set tab'} with CHQ #{cheque_number} and Notes '{delivery_notes}'. Removed from pending CH REQs."
    return {"status": "success", "message": summary_msg, "updated_tabs": updated_tabs}

def complete_cheques_batch_and_update_tracker(req_ids: list, cheque_number: str, delivery_notes: str) -> dict:
    """
    Completes multiple cheque requests at the same time (e.g. multiple invoices paid on one single cheque).
    1. Looks up all requests by req_ids from database.
    2. Opens Google Sheets and batch-updates Column P (CHQ #) and Column Q (NOTES) in each requisition's set tab.
    3. Deletes matched rows from the 'CH REQS' Google Sheet tab in descending row order.
    4. Updates SQLite status to 'DELIVERED', cheque_number, and delivery_notes for all items.
    """
    if not req_ids:
        return {"status": "error", "message": "No requisition IDs provided."}

    # Normalize req_ids into list of ints
    clean_ids = []
    for r in req_ids:
        try:
            clean_ids.append(int(r))
        except (ValueError, TypeError):
            pass

    if not clean_ids:
        return {"status": "error", "message": "No valid requisition IDs provided."}

    # Fetch all requisitions from SQLite
    reqs = []
    for r_id in clean_ids:
        r = get_cheque_request_by_id(r_id)
        if r:
            reqs.append(r)

    if not reqs:
        return {"status": "error", "message": "None of the specified requisitions were found in the database."}

    settings = load_settings()
    url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
    if not url:
        return {"status": "error", "message": "Google Sheets URL missing in settings."}

    sh = get_spreadsheet(url)

    # If any req is PO and cheque_number is bare "PO COMPLETED", append completion date
    if any(str(r.get("payment_type", "")).upper() == "PO" for r in reqs):
        if cheque_number.strip().upper() == "PO COMPLETED":
            today_date = datetime.now().strftime("%m/%d")
            cheque_number = f"PO COMPLETED {today_date}"

    # Group requisitions by target set tabs
    set_to_reqs = {}
    for r in reqs:
        set_num = str(r.get("set_number", "")).strip().upper()
        target_sets = [s.strip().upper() for s in re.split(r'[/,&]+|\band\b', set_num) if s.strip()]
        if not target_sets:
            target_sets = ["H15"]
        for s in target_sets:
            if s not in set_to_reqs:
                set_to_reqs[s] = []
            set_to_reqs[s].append(r)

    updated_tabs = []
    failed_tabs = []

    # Step A: Update each set tab
    for tab_title, tab_reqs in set_to_reqs.items():
        try:
            ws_set = sh.worksheet(tab_title)
            set_vals = ws_set.get_all_values()
            used_rows = set()
            cell_updates = []

            for req in tab_reqs:
                vendor = str(req.get("vendor", "")).strip().upper()
                ref_num = str(req.get("reference_number", "")).strip()
                clean_po_ref = re.sub(r'^(PO\s*[:#]?\s*)', '', ref_num, flags=re.IGNORECASE).strip()

                matched_row = None

                # Priority 1: Match BOTH Vendor and Reference/PO
                for r_idx in range(7, len(set_vals)):
                    row_num = r_idx + 1
                    if row_num in used_rows:
                        continue
                    r = set_vals[r_idx]
                    r_vendor = str(r[2]).strip().upper() if len(r) > 2 else ""
                    r_po = str(r[10]).strip().upper() if len(r) > 10 else ""
                    r_ref = str(r[12]).strip().upper() if len(r) > 12 else ""

                    vendor_matches = bool(vendor and r_vendor and (vendor in r_vendor or r_vendor in vendor))
                    ref_matches = False
                    if clean_po_ref and r_po and (clean_po_ref.upper() == r_po or clean_po_ref.upper() in r_po):
                        ref_matches = True
                    elif ref_num and r_ref:
                        if ref_num.upper() == r_ref.upper():
                            ref_matches = True
                        elif len(ref_num) >= 3 and len(r_ref) >= 3 and (ref_num.upper() in r_ref.upper() or r_ref.upper() in ref_num.upper()):
                            ref_matches = True

                    if vendor_matches and ref_matches:
                        matched_row = row_num
                        break

                # Priority 2: Match by exact Reference or exact PO
                if not matched_row:
                    for r_idx in range(7, len(set_vals)):
                        row_num = r_idx + 1
                        if row_num in used_rows:
                            continue
                        r = set_vals[r_idx]
                        r_po = str(r[10]).strip().upper() if len(r) > 10 else ""
                        r_ref = str(r[12]).strip().upper() if len(r) > 12 else ""

                        if clean_po_ref and r_po and (clean_po_ref.upper() == r_po):
                            matched_row = row_num
                            break
                        elif ref_num and r_ref:
                            if ref_num.upper() == r_ref.upper() or (len(r_ref) >= 4 and len(ref_num) >= 4 and (ref_num.upper() in r_ref.upper() or r_ref.upper() in ref_num.upper())):
                                matched_row = row_num
                                break

                # Priority 3: Match by Vendor
                if not matched_row and vendor:
                    for r_idx in range(7, len(set_vals)):
                        row_num = r_idx + 1
                        if row_num in used_rows:
                            continue
                        r = set_vals[r_idx]
                        r_vendor = str(r[2]).strip().upper() if len(r) > 2 else ""
                        if r_vendor and (vendor in r_vendor or r_vendor in vendor):
                            matched_row = row_num
                            break

                if matched_row:
                    used_rows.add(matched_row)
                    existing_notes = str(set_vals[matched_row - 1][16]).strip() if len(set_vals[matched_row - 1]) > 16 else ""
                    if existing_notes and delivery_notes.strip() and delivery_notes.strip() not in existing_notes:
                        final_notes = f"{existing_notes} {delivery_notes.strip()}".strip()
                    else:
                        final_notes = existing_notes or delivery_notes.strip()

                    cell_updates.append((matched_row, cheque_number.strip(), final_notes))
                    updated_tabs.append(f"{tab_title} (Row {matched_row})")

            # Apply updates for this worksheet
            for m_row, chq_val, notes_val in cell_updates:
                try:
                    ws_set.update(values=[[chq_val, notes_val]], range_name=f"P{m_row}:Q{m_row}", value_input_option='USER_ENTERED')
                except Exception as ex_cell:
                    print(f"Error updating cell in {tab_title} row {m_row}: {ex_cell}")

        except Exception as e:
            print(f"Error updating set tab {tab_title}: {e}")
            failed_tabs.append(f"{tab_title}: {str(e)}")

    # Step B: Delete from 'CH REQS' tab in Google Sheets
    try:
        ws_ch = sh.worksheet("CH REQS")
        ch_vals = ws_ch.get_all_values()
        rows_to_delete = []

        for req in reqs:
            v_req = str(req.get("vendor", "")).strip().upper()
            r_req = str(req.get("reference_number", "")).strip()

            for idx in range(2, len(ch_vals)):
                row_num = idx + 1
                if row_num in rows_to_delete:
                    continue
                r = ch_vals[idx]
                c_vendor = str(r[3]).strip().upper() if len(r) > 3 else ""
                c_ref = str(r[4]).strip().upper() if len(r) > 4 else ""

                vendor_match = bool(v_req and c_vendor and (v_req in c_vendor or c_vendor in v_req))
                ref_match = False
                if r_req and c_ref:
                    if r_req.upper() == c_ref.upper():
                        ref_match = True
                    elif len(r_req) >= 4 and len(c_ref) >= 4 and (r_req.upper() in c_ref.upper() or c_ref.upper() in r_req.upper()):
                        ref_match = True

                if vendor_match and (ref_match or not r_req):
                    rows_to_delete.append(row_num)
                    break

        if rows_to_delete:
            rows_to_delete.sort(reverse=True)
            for r_del in rows_to_delete:
                try:
                    ws_ch.delete_rows(r_del)
                except Exception as ex_del:
                    print(f"Error deleting row {r_del} from CH REQS: {ex_del}")
            print(f"Deleted {len(rows_to_delete)} rows from CH REQS sheet.")

    except Exception as e:
        print(f"Error removing items from CH REQS sheet: {e}")

    # Step C: Update local SQLite status to DELIVERED for all reqs
    try:
        from core.database import get_connection
        conn = get_connection()
        c = conn.cursor()
        for req in reqs:
            r_id = req.get("id")
            c.execute("""
                UPDATE cheque_requests 
                SET status = 'DELIVERED', cheque_number = ?, delivery_notes = ?
                WHERE id = ?
            """, (cheque_number.strip(), delivery_notes.strip(), r_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating SQLite batch status: {e}")

    summary_msg = f"Successfully completed {len(reqs)} requisition{'s' if len(reqs) != 1 else ''} with Cheque #{cheque_number} across {', '.join(updated_tabs) if updated_tabs else 'set tabs'}."
    return {"status": "success", "message": summary_msg, "updated_count": len(reqs), "updated_tabs": updated_tabs}

def update_cheque_request_details(req_id: int, updates: dict) -> dict:
    """
    Updates any field of a cheque request (specifically payment_type, date_required,
    rental_period, vendor, set_number, total, etc.) in both SQLite and Google Sheets 'CH REQS' tab.
    """
    req = get_cheque_request_by_id(req_id)
    if not req:
        return {"status": "error", "message": f"Requisition #{req_id} not found."}

    # Normalize fields
    new_type = updates.get("payment_type") or req.get("payment_type", "CHQ")
    new_type = str(new_type).strip().upper()
    if new_type in ("CH REQ", "REQ"):
        new_type = "CHQ"
    if new_type not in ("CHQ", "ACH", "PO"):
        new_type = "CHQ"

    new_date_req = updates.get("date_required") if "date_required" in updates else req.get("date_required", "")
    new_rental = updates.get("rental_period") if "rental_period" in updates else req.get("rental_period", "")
    new_rental = normalize_rental_period(new_rental)
    new_vendor = updates.get("vendor") if "vendor" in updates else req.get("vendor", "")
    new_set = updates.get("set_number") if "set_number" in updates else req.get("set_number", "")
    new_desc = updates.get("description") if "description" in updates else req.get("description", "")
    new_ref = updates.get("reference_number") if "reference_number" in updates else req.get("reference_number", "")
    new_status = updates.get("status") if "status" in updates else req.get("status", "PENDING")

    # 1. Update SQLite
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE cheque_requests
        SET payment_type = ?,
            date_required = ?,
            rental_period = ?,
            vendor = ?,
            set_number = ?,
            description = ?,
            reference_number = ?,
            status = ?
        WHERE id = ?
    """, (new_type, new_date_req, new_rental, new_vendor, new_set, new_desc, new_ref, new_status, req_id))
    conn.commit()
    conn.close()

    # 2. Update Google Sheets 'CH REQS' Tab
    # POs are tracked locally in the app tracker only, not in the CH REQS Google Sheet
    if new_type == "PO" or str(req.get("payment_type", "")).upper() == "PO":
        return {
            "status": "success",
            "message": f"Updated PO #{req_id} ({new_vendor}) in App Tracker.",
            "payment_type": new_type
        }

    settings = load_settings()
    url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
    if not url:
        return {"status": "success", "message": f"Updated #{req_id} locally to {new_type}."}

    try:
        sh = get_spreadsheet(url)
        ws = get_or_create_ch_reqs_worksheet(sh)
        all_vals = ws.get_all_values()

        target_row = None
        s_row = req.get("sheet_row_id")
        ref_num = str(req.get("reference_number", "")).strip().upper()
        vendor = str(req.get("vendor", "")).strip().upper()

        if s_row and s_row <= len(all_vals):
            row_data = all_vals[s_row - 1]
            c_vendor = str(row_data[3]).strip().upper() if len(row_data) > 3 else ""
            c_ref = str(row_data[4]).strip().upper() if len(row_data) > 4 else ""
            if (ref_num and ref_num in c_ref) or (vendor and vendor[:6] in c_vendor):
                target_row = s_row

        if not target_row:
            for idx in range(2, len(all_vals)):
                r = all_vals[idx]
                c_vendor = str(r[3]).strip().upper() if len(r) > 3 else ""
                c_ref = str(r[4]).strip().upper() if len(r) > 4 else ""
                if ref_num and (ref_num == c_ref or ref_num in c_ref):
                    target_row = idx + 1
                    break
                elif vendor and c_vendor and (vendor[:8] in c_vendor or c_vendor[:8] in vendor):
                    target_row = idx + 1
                    break

        if target_row:
            ws.update(range_name=f"B{target_row}:C{target_row}", values=[[new_date_req, new_type]])
            ws.update(range_name=f"K{target_row}", values=[[new_rental]])
            if new_vendor != vendor or new_ref != req.get("reference_number", "") or new_set != req.get("set_number", "") or new_desc != req.get("description", ""):
                ws.update(range_name=f"D{target_row}:G{target_row}", values=[[new_vendor.upper(), new_ref.upper(), new_set.upper(), new_desc]])
            if "status" in updates:
                ws.update(range_name=f"O{target_row}", values=[[new_status]])

            sort_ch_reqs_worksheet(ws, sh)

            return {
                "status": "success",
                "message": f"Updated #{req_id} ({new_vendor}) to {new_type} in Sheet Row {target_row} and App.",
                "sheet_row": target_row,
                "payment_type": new_type
            }
        else:
            return {
                "status": "warning",
                "message": f"Updated #{req_id} locally to {new_type}, but matching row in Google Sheet was not found.",
                "payment_type": new_type
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Updated #{req_id} locally, but Google Sheet sync failed: {e}",
            "payment_type": new_type
        }

def normalize_pasted_text(text: str) -> str:
    """
    Normalizes pasted accountant text. If multiple items are pasted without newlines,
    splits them cleanly by boundary tokens.
    """
    if not text:
        return ""
    s = text.replace('\r\n', '\n').replace('\r', '\n')
    pattern = r'((?:entered\s*not\s*paid|not\s*paid|not\s*entered|unpaid|ACH\s*[:#]?\s*\w+\s+yesterday|yesterday|same|ditto|ACH\s*[:#]?\s*\w+|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?))\s+([A-Za-z0-9].*?\s*-\s*INV)'
    s = re.sub(pattern, r'\1\n\2', s, flags=re.IGNORECASE)
    return s.strip()

def parse_ach_batch_text(text: str, default_date: str = None) -> list:
    """
    Parses raw text from accountants into structured ACH payment items.
    Handles lines like:
    - UNITED PROP - INV 9402 PD ACH 200886
    - WISEACRE - INV 319825   PD ACH200888
    - SUPA HOLDING - ALLEN GALLERY - INV # 7125 - paid ACH200935 yesterday
    - WISEACRE RENTALS - INV # 319928 - same
    - 8752311 CANADA INC. DBA GOOD DOG DIGITAL - INV # 26-13944 - entered not paid
    - PROSOURCE - INV PS015800 NOT ENTERED WHEN DID WE GET IT
    """
    if not default_date:
        default_date = datetime.now().strftime("%m/%d")

    yesterday_date = (datetime.now() - timedelta(days=1)).strftime("%m/%d")

    # Normalize glued single-line paste
    norm_text = normalize_pasted_text(text)

    results = []
    lines = norm_text.splitlines()
    last_ach = ""
    last_date = default_date

    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.upper().startswith("ACH:"):
            continue

        # 1. Check for "same" / "ditto" referring to preceding line's ACH
        if re.search(r'\b(same|ditto)\b', line_clean, re.IGNORECASE) and last_ach:
            m_inv = re.search(r'(?:INV(?:OICE)?\s*[:#]?\s*)([A-Za-z0-9\-]+)', line_clean, re.IGNORECASE)
            inv = m_inv.group(1).strip() if m_inv else ""
            if "INV" in line_clean.upper():
                vendor_part = line_clean[:line_clean.upper().find("INV")].strip().rstrip('-').strip()
            else:
                vendor_part = line_clean.split('-')[0].strip()

            results.append({
                "vendor": vendor_part,
                "invoice": inv,
                "ach_number": last_ach,
                "payment_date": last_date,
                "formatted_col_p": f"{last_ach} {last_date}",
                "status": "PAID",
                "note": "Same ACH as previous",
                "raw": line_clean
            })
            continue

        # 2. Check for UNPAID / NOT PAID / ENTERED NOT PAID / NOT ENTERED / HOLD
        if re.search(r'\b(not\s*paid|entered\s*not\s*paid|not\s*entered|unpaid)\b', line_clean, re.IGNORECASE):
            m_inv = re.search(r'(?:INV(?:OICE)?\s*[:#]?\s*)([A-Za-z0-9\-]+)', line_clean, re.IGNORECASE)
            inv = m_inv.group(1).strip() if m_inv else ""
            
            if "INV" in line_clean.upper():
                vendor_part = line_clean[:line_clean.upper().find("INV")].strip().rstrip('-').strip()
            else:
                vendor_part = line_clean.split('-')[0].strip()
                
            m_note = re.search(r'(entered\s*not\s*paid|not\s*paid|not\s*entered|unpaid.*)', line_clean, re.IGNORECASE)
            note_str = m_note.group(1).strip().upper() if m_note else "NOT PAID"

            results.append({
                "vendor": vendor_part,
                "invoice": inv,
                "ach_number": "",
                "payment_date": default_date,
                "formatted_col_p": "",
                "status": "UNPAID",
                "note": note_str,
                "raw": line_clean
            })
            continue

        # 3. Check for ACH payment info (e.g. "paid ACH200935 yesterday" or "PD ACH 200886")
        m_ach = re.search(r'ACH\s*[:#]?\s*(\w+)', line_clean, re.IGNORECASE)
        if m_ach:
            raw_ach = m_ach.group(1).strip()
            ach_clean = raw_ach if raw_ach.upper().startswith("ACH") else f"ACH{raw_ach}"
            
            # Payment date calculation: support "yesterday"
            if "yesterday" in line_clean.lower():
                pay_date = yesterday_date
            else:
                m_d = re.search(r'\b(\d{1,2}/\d{1,2})\b', line_clean)
                pay_date = m_d.group(1) if m_d else default_date

            # Invoice extraction
            m_inv = re.search(r'(?:INV(?:OICE)?\s*[:#]?\s*)([A-Za-z0-9\-]+)', line_clean, re.IGNORECASE)
            if m_inv:
                inv = m_inv.group(1).strip()
            else:
                m_tokens = re.findall(r'\b[A-Za-z0-9\-]{4,}\b', line_clean)
                inv = m_tokens[0] if m_tokens else ""

            # Vendor extraction
            if "INV" in line_clean.upper():
                vendor_part = line_clean[:line_clean.upper().find("INV")].strip().rstrip('-').strip()
            else:
                vendor_part = line_clean.split('-')[0].strip()

            last_ach = ach_clean
            last_date = pay_date

            results.append({
                "vendor": vendor_part,
                "invoice": inv,
                "ach_number": ach_clean,
                "payment_date": pay_date,
                "formatted_col_p": f"{ach_clean} {pay_date}",
                "status": "PAID",
                "note": "",
                "raw": line_clean
            })
            continue

        # 4. Fallback for unrecognized line
        results.append({
            "vendor": "",
            "invoice": "",
            "ach_number": "",
            "payment_date": default_date,
            "formatted_col_p": "",
            "status": "UNKNOWN",
            "note": line_clean,
            "raw": line_clean
        })

    return results

def match_ach_items_to_sets(items: list) -> list:
    """
    Enriches parsed ACH items with the exact set tab and receipt information
    by querying the local SQLite database.
    """
    for item in items:
        inv = item.get("invoice", "")
        vendor = item.get("vendor", "")
        
        if not inv and not vendor:
            item["matched_set"] = ""
            item["matched_row"] = None
            item["match_status"] = "No Data"
            continue

        if item.get("status") != "PAID" or not item.get("ach_number"):
            item["matched_set"] = ""
            item["matched_row"] = None
            note_label = item.get("note") or "Unpaid"
            item["match_status"] = f"Skipped ({note_label})"
            continue

        # Look up in SQLite receipts table
        receipts = find_receipt_by_reference(inv, vendor)
        if receipts:
            r = receipts[0]
            item["matched_set"] = r.get("set_number", "")
            item["matched_vendor"] = r.get("vendor", "")
            item["matched_total"] = r.get("total", 0.0)
            item["match_status"] = f"Found ({r.get('set_number', '')})"
        else:
            # Check pending cheque_requests
            pending = get_pending_cheque_requests()
            found_ch = None
            for ch in pending:
                ch_ref = str(ch.get("reference_number", "")).strip().upper()
                if inv.upper() in ch_ref or ch_ref in inv.upper():
                    found_ch = ch
                    break
            if found_ch:
                item["matched_set"] = found_ch.get("set_number", "")
                item["matched_vendor"] = found_ch.get("vendor", "")
                item["matched_total"] = found_ch.get("total", 0.0)
                item["match_status"] = f"Found in Pending CH REQ ({found_ch.get('set_number', '')})"
            else:
                item["matched_set"] = ""
                item["match_status"] = "Not Found in DB (Will search sheet)"

    return items

def apply_ach_payments_to_tracker(items: list, progress_callback=None) -> dict:
    """
    Applies the ACH payments directly to Column P in Google Sheets using multi-range batching!
    Also removes matched items from the 'CH REQS' tab if they were in the pending list.
    Reduces API calls from 80+ down to 2-3 requests, completely avoiding 429 quota errors.
    """
    settings = load_settings()
    url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
    if not url:
        return {"status": "error", "message": "Google Sheets URL missing in settings."}

    sh = get_spreadsheet(url)
    
    updated_count = 0
    failed_items = []
    success_details = []

    # 1. Identify all candidate worksheets needed for search
    from services.sheets import batch_get_worksheets_data, clear_sheet_cache

    active_tabs = ["H15", "H16", "H10", "H11", "H12", "H19", "H20", "H21", "H22", "H24", "X98", "X83", "X80", "X82", "X84", "G13", "G18", "F17", "F20", "C19", "D12", "B14", "B21", "B25", "B27", "B32", "B35", "C25", "C32", "E12", "E15", "F10", "A21"]
    
    candidate_tabs_set = set(active_tabs)
    candidate_tabs_set.add("CH REQS")

    for item in items:
        target_set = str(item.get("matched_set", "")).strip().upper()
        if target_set:
            for s in re.split(r'[/,&]+|\band\b', target_set):
                if s.strip():
                    candidate_tabs_set.add(s.strip().upper())

    # Pre-fetch ALL candidate tabs in 1 SINGLE batch API call!
    if progress_callback:
        progress_callback(0, len(items), "Pre-fetching all candidate set tabs via batch API...")

    tab_data_map = batch_get_worksheets_data(sh, list(candidate_tabs_set), range_spec="A1:Q120", use_cache=False)

    # 2. Match each ACH item in memory
    pending_sheet_updates = []  # [{"range": "'Tab'!P12", "values": [[col_p_val]]}, ...]
    matched_inv_refs = []       # list of invoice numbers to remove from CH REQS & SQLite
    used_rows = set()

    for idx, item in enumerate(items):
        if progress_callback:
            progress_callback(idx, len(items), f"Matching {item.get('vendor')} (Inv {item.get('invoice')})...")

        if item.get("status") == "UNPAID" or not item.get("ach_number"):
            continue

        inv = str(item.get("invoice", "")).strip()
        vendor = str(item.get("vendor", "")).strip().upper()
        target_set = str(item.get("matched_set", "")).strip().upper()
        col_p_val = item.get("formatted_col_p", "")

        sets_to_search = [s.strip().upper() for s in re.split(r'[/,&]+|\band\b', target_set) if s.strip()] if target_set else []

        # Helper to search the in-memory tab data
        def search_tab_data(tab_title):
            vals = tab_data_map.get(tab_title)
            if not vals:
                return None
            for r_idx in range(7, len(vals)):
                row = vals[r_idx]
                r_ref = str(row[12]).strip().upper() if len(row) > 12 else ""  # Col M
                r_vendor = str(row[2]).strip().upper() if len(row) > 2 else ""  # Col C

                if inv and (inv.upper() in r_ref or r_ref in inv.upper()):
                    matched_row = r_idx + 1
                    if (tab_title, matched_row) not in used_rows:
                        return matched_row
            return None

        matched_tab = None
        matched_row = None

        # Try matched sets first
        for s in sets_to_search:
            m_row = search_tab_data(s)
            if m_row:
                matched_tab = s
                matched_row = m_row
                break

        # Fallback to active tabs if not found
        if not matched_row:
            for a_tab in active_tabs:
                if a_tab in sets_to_search:
                    continue
                m_row = search_tab_data(a_tab)
                if m_row:
                    matched_tab = a_tab
                    matched_row = m_row
                    break

        if matched_tab and matched_row:
            used_rows.add((matched_tab, matched_row))
            pending_sheet_updates.append({
                "range": f"'{matched_tab}'!P{matched_row}",
                "values": [[col_p_val]]
            })
            updated_count += 1
            success_details.append(f"{vendor} (Inv {inv}) -> {matched_tab} Row {matched_row}: {col_p_val}")
            matched_inv_refs.append(inv)
        else:
            failed_items.append(f"{vendor} (Inv {inv}): Could not locate row in sheet.")

    # 3. Commit ALL Column P updates across all tabs in ONE single batch API request!
    if pending_sheet_updates:
        if progress_callback:
            progress_callback(len(items), len(items), "Committing batch updates to Google Sheets...")
        try:
            sh.values_batch_update({
                "valueInputOption": "USER_ENTERED",
                "data": pending_sheet_updates
            })
            clear_sheet_cache(sh.id)
            print(f"DEBUG: Successfully batch-updated {len(pending_sheet_updates)} cells in Google Sheets.")
        except Exception as e:
            print(f"DEBUG: Error in values_batch_update: {e}")
            for upd in pending_sheet_updates:
                try:
                    r_spec = upd["range"]
                    val = upd["values"]
                    m = re.match(r"'?([^'!]+)'?!([A-Z0-9:]+)", r_spec)
                    if m:
                        t_name, a1 = m.group(1), m.group(2)
                        sh.worksheet(t_name).update(values=val, range_name=a1, value_input_option='USER_ENTERED')
                except Exception as ex:
                    print(f"Fallback update error for {upd}: {ex}")

    # 4. Remove matched ACH items from 'CH REQS' tab in Google Sheets using batch delete
    try:
        ws_ch = sh.worksheet("CH REQS")
        ch_vals = ws_ch.get_all_values()
        rows_to_delete = []

        for idx in range(2, len(ch_vals)):
            r = ch_vals[idx]
            c_type = str(r[2]).strip().upper() if len(r) > 2 else ""
            c_vendor = str(r[3]).strip().upper() if len(r) > 3 else ""
            c_ref = str(r[4]).strip().upper() if len(r) > 4 else ""

            # Only remove ACH items from the CH REQS sheet (never delete physical CHQs or POs)
            if c_type != "ACH":
                continue

            for item in items:
                if item.get("status") == "UNPAID" or not item.get("ach_number"):
                    continue
                inv = str(item.get("invoice", "")).strip().upper()
                vendor = str(item.get("vendor", "")).strip().upper()

                vendor_match = bool(vendor and c_vendor and (vendor in c_vendor or c_vendor in vendor))
                ref_match = False
                if inv and c_ref:
                    if inv == c_ref:
                        ref_match = True
                    elif len(inv) >= 4 and len(c_ref) >= 4 and (inv in c_ref or c_ref in inv):
                        ref_match = True

                if vendor_match and ref_match:
                    rows_to_delete.append(idx + 1)
                    break

        if rows_to_delete:
            rows_to_delete.sort(reverse=True)
            delete_requests = [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": ws_ch.id,
                            "dimension": "ROWS",
                            "startIndex": r - 1,
                            "endIndex": r
                        }
                    }
                }
                for r in rows_to_delete
            ]
            sh.batch_update({"requests": delete_requests})
            print(f"DEBUG: Batch deleted {len(rows_to_delete)} rows from CH REQS sheet in 1 request.")
    except Exception as e:
        print(f"Error removing from CH REQS sheet: {e}")

    # 5. Update local SQLite database in one transaction
    try:
        from core.database import get_connection
        conn = get_connection()
        c = conn.cursor()
        for item in items:
            if item.get("status") == "UNPAID" or not item.get("ach_number"):
                continue
            inv = str(item.get("invoice", "")).strip()
            vendor = str(item.get("vendor", "")).strip().upper()
            col_p_val = item.get("formatted_col_p", "")
            if inv:
                # STRICT matching: ONLY update ACH records with matching vendor and exact invoice
                c.execute("""
                    UPDATE cheque_requests 
                    SET status = 'DELIVERED', cheque_number = ?
                    WHERE status IN ('PENDING', 'RECEIVED')
                      AND payment_type = 'ACH'
                      AND (
                          UPPER(TRIM(vendor)) = ? OR
                          UPPER(TRIM(vendor)) LIKE ? OR
                          ? LIKE '%' || UPPER(TRIM(vendor)) || '%'
                      )
                      AND (
                          reference_number = ? OR 
                          (length(?) >= 4 AND reference_number LIKE ?) OR
                          (length(reference_number) >= 4 AND ? LIKE '%' || reference_number || '%')
                      )
                """, (col_p_val, vendor, f"%{vendor}%", vendor, inv, inv, f"%{inv}%", inv))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating SQLite status: {e}")

    return {
        "status": "success",
        "updated_count": updated_count,
        "failed_count": len(failed_items),
        "failed_items": failed_items,
        "success_details": success_details
    }


def find_actual_ch_req_pdf(vendor: str, description: str = "", invoice_date: str = "", total: float = 0.0) -> str:
    """
    Locates the actual generated CH REQ PDF in the CH REQS directory.
    """
    import glob
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    show_dir = os.path.abspath(os.path.join(app_dir, '..', '..'))
    ch_req_dir = os.path.join(show_dir, "CH REQS")
    if not os.path.exists(ch_req_dir):
        return None

    v_clean = re.sub(r'[^A-Za-z0-9]', '', (vendor or "").upper())
    matched_folder = None
    for d in os.listdir(ch_req_dir):
        dp = os.path.join(ch_req_dir, d)
        if os.path.isdir(dp):
            d_clean = re.sub(r'[^A-Za-z0-9]', '', d.upper())
            if v_clean and (v_clean in d_clean or d_clean in v_clean or v_clean[:6] in d_clean):
                matched_folder = dp
                break

    if not matched_folder:
        return None

    pdfs = glob.glob(os.path.join(matched_folder, "*.pdf"))
    if not pdfs:
        return None

    desc_clean = re.sub(r'[^A-Za-z0-9]', '', (description or "").upper())[:20]
    for p in pdfs:
        p_clean = re.sub(r'[^A-Za-z0-9]', '', os.path.basename(p).upper())
        if desc_clean and desc_clean[:12] in p_clean:
            return p

    if invoice_date:
        m = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', invoice_date)
        if m:
            date_prefix = f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            for p in pdfs:
                if date_prefix in os.path.basename(p):
                    return p

    return pdfs[0] if len(pdfs) == 1 else None

def update_pdf_payment_type(pdf_path: str, payment_type: str) -> bool:
    """
    Updates the checkbox in the actual CH REQ PDF:
    If ACH -> Check ACH, uncheck Pickup
    If REQ -> Check Pickup, uncheck ACH
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return False
    try:
        import fitz
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return False

        is_ach = (str(payment_type).strip().upper() == "ACH")
        updated = False
        for w in doc[0].widgets():
            if w.field_name == 'Pickup':
                w.field_value = 'Off' if is_ach else 'Yes'
                w.update()
                updated = True
            elif w.field_name == 'ACH':
                w.field_value = 'Yes' if is_ach else 'Off'
                w.update()
                updated = True

        if updated:
            tmp = pdf_path + ".tmp"
            doc.save(tmp)
            doc.close()
            os.replace(tmp, pdf_path)
            print(f"Updated checkmark in PDF {os.path.basename(pdf_path)}: ACH={is_ach}, Pickup={not is_ach}")
            return True
        else:
            doc.close()
            return False
    except Exception as e:
        print(f"Error updating PDF payment type checkmark: {e}")
        return False

def sync_cheque_request_from_pdf(req_id: int) -> dict:
    """
    Reads form fields from the actual CH REQ PDF and updates SQLite and Google Sheets.
    """
    req = get_cheque_request_by_id(req_id)
    if not req:
        return {"status": "error", "message": f"Requisition #{req_id} not found."}

    pdf_path = req.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path) or "Receipts" in pdf_path:
        actual_pdf = find_actual_ch_req_pdf(req.get("vendor", ""), req.get("description", ""), req.get("invoice_date", ""), req.get("total", 0.0))
        if actual_pdf and os.path.exists(actual_pdf):
            pdf_path = actual_pdf
            conn = get_connection()
            c = conn.cursor()
            c.execute("UPDATE cheque_requests SET pdf_path = ? WHERE id = ?", (pdf_path, req_id))
            conn.commit()
            conn.close()

    if not pdf_path or not os.path.exists(pdf_path):
        return {"status": "error", "message": f"CH REQ PDF not found for #{req_id} ({req.get('vendor')})."}

    try:
        import fitz
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return {"status": "error", "message": "PDF is empty."}

        fields = {w.field_name: str(w.field_value).strip() for w in doc[0].widgets() if w.field_value is not None}
        doc.close()

        # Determine payment type from checkboxes
        is_ach = fields.get("ACH") in ("Yes", "True", True)
        is_pickup = fields.get("Pickup") in ("Yes", "True", True)
        if is_ach:
            new_type = "ACH"
        elif is_pickup:
            new_type = "CHQ"
        else:
            new_type = req.get("payment_type", "CHQ")

        def parse_flt(v):
            if not v: return None
            clean = re.sub(r'[^0-9.-]', '', str(v))
            try: return float(clean)
            except ValueError: return None

        new_date_req = fields.get("Date5_af_date") or req.get("date_required", "")
        new_rental = normalize_rental_period(fields.get("Rental Period", "")) or req.get("rental_period", "")
        new_vendor = fields.get("Payee 1") or req.get("vendor", "")
        new_subtot = parse_flt(fields.get("Amount Before GST 1")) or req.get("subtotal", 0.0)
        new_total = parse_flt(fields.get("Text5")) or req.get("total", 0.0)
        new_set = fields.get("Set Location") or req.get("set_number", "")
        new_buyer = fields.get("Requested By") or req.get("buyer_name", "")

        desc_parts = [fields.get(f"Details {i}", "") for i in range(1, 5)]
        desc_joined = " ".join([p for p in desc_parts if p.strip()])
        new_desc = desc_joined if desc_joined else req.get("description", "")

        updates = {
            "payment_type": new_type,
            "date_required": new_date_req,
            "rental_period": new_rental,
            "vendor": new_vendor,
            "subtotal": new_subtot,
            "total": new_total,
            "set_number": new_set,
            "buyer_name": new_buyer,
            "description": new_desc
        }

        res = update_cheque_request_details(req_id, updates)
        res["pdf_path"] = pdf_path
        res["updated_fields"] = updates
        res["message"] = f"Synced #{req_id} ({new_vendor}) from PDF: Type={new_type}, Rental={new_rental or 'None'}, Date Req={new_date_req}"
        return res
    except Exception as e:
        return {"status": "error", "message": f"Failed to sync from PDF: {e}"}

def toggle_cheque_request_payment_type(req_id: int) -> dict:
    """
    Switches between Cheque (REQ) and ACH:
    1. Swaps payment_type.
    2. Updates the PDF checkbox (Pickup vs ACH).
    3. Updates SQLite and Google Sheets.
    """
    req = get_cheque_request_by_id(req_id)
    if not req:
        return {"status": "error", "message": f"Requisition #{req_id} not found."}

    curr_type = str(req.get("payment_type", "CHQ")).upper()
    new_type = "ACH" if curr_type in ("CHQ", "REQ", "CH REQ") else "CHQ"

    pdf_path = req.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path) or "Receipts" in pdf_path:
        actual_pdf = find_actual_ch_req_pdf(req.get("vendor", ""), req.get("description", ""), req.get("invoice_date", ""), req.get("total", 0.0))
        if actual_pdf and os.path.exists(actual_pdf):
            pdf_path = actual_pdf
            conn = get_connection()
            c = conn.cursor()
            c.execute("UPDATE cheque_requests SET pdf_path = ? WHERE id = ?", (pdf_path, req_id))
            conn.commit()
            conn.close()

    pdf_updated = False
    if pdf_path and os.path.exists(pdf_path):
        pdf_updated = update_pdf_payment_type(pdf_path, new_type)

    res = update_cheque_request_details(req_id, {"payment_type": new_type})
    type_label = "⚡ ACH" if new_type == "ACH" else "💵 CHEQUE (REQ)"
    pdf_status = " (PDF checkmark updated)" if pdf_updated else ""
    res["message"] = f"Switched #{req_id} to {type_label}{pdf_status}."
    res["new_type"] = new_type
    res["pdf_updated"] = pdf_updated
    return res


def toggle_cheque_received_status(req_id: int, target_status: str = None) -> dict:
    """
    Toggles or sets the status of a cheque request between 'PENDING' (awaiting cheque)
    and 'RECEIVED' (cheque physically in hand, awaiting cheque # & delivery notes).
    Updates local SQLite and Column O (STATUS) in Google Sheets 'CH REQS' tab.
    """
    req = get_cheque_request_by_id(req_id)
    if not req:
        return {"status": "error", "message": f"Requisition #{req_id} not found."}

    curr_status = str(req.get("status", "PENDING")).upper()
    if target_status:
        new_status = str(target_status).strip().upper()
    else:
        new_status = "PENDING" if curr_status == "RECEIVED" else "RECEIVED"

    # 1. Update SQLite
    update_cheque_request_status(req_id, new_status)

    # POs are tracked locally in the app tracker only, not in the CH REQS Google Sheet
    if str(req.get("payment_type", "")).upper() == "PO":
        return {
            "status": "success",
            "message": f"Updated PO #{req_id} ({req.get('vendor')}) status to {new_status} in App Tracker.",
            "new_status": new_status,
            "sheet_updated": False
        }

    # 2. Update Google Sheets 'CH REQS' tab if connected
    sheet_updated = False
    try:
        settings = load_settings()
        url = settings.get("spreadsheet_url") or settings.get("google_sheets_url")
        if url:
            sh = get_spreadsheet(url)
            ws = get_or_create_ch_reqs_worksheet(sh)
            all_vals = ws.get_all_values()

            target_row = None
            s_row = req.get("sheet_row_id")
            ref_num = str(req.get("reference_number", "")).strip().upper()
            vendor = str(req.get("vendor", "")).strip().upper()

            if s_row and s_row <= len(all_vals):
                row_data = all_vals[s_row - 1]
                c_vendor = str(row_data[3]).strip().upper() if len(row_data) > 3 else ""
                c_ref = str(row_data[4]).strip().upper() if len(row_data) > 4 else ""
                if (ref_num and ref_num in c_ref) or (vendor and vendor[:6] in c_vendor):
                    target_row = s_row

            if not target_row:
                for idx in range(2, len(all_vals)):
                    r = all_vals[idx]
                    c_vendor = str(r[3]).strip().upper() if len(r) > 3 else ""
                    c_ref = str(r[4]).strip().upper() if len(r) > 4 else ""
                    if ref_num and (ref_num == c_ref or ref_num in c_ref):
                        target_row = idx + 1
                        break
                    elif vendor and c_vendor and (vendor[:8] in c_vendor or c_vendor[:8] in vendor):
                        target_row = idx + 1
                        break

            if target_row:
                ws.update(range_name=f"O{target_row}", values=[[new_status]])
                sheet_id = ws.id
                bg_color = {"red": 0.82, "green": 0.98, "blue": 0.90} if new_status == "RECEIVED" else {"red": 1.0, "green": 0.95, "blue": 0.80}
                text_color = {"red": 0.05, "green": 0.40, "blue": 0.25} if new_status == "RECEIVED" else {"red": 0.45, "green": 0.35, "blue": 0.05}
                sh.batch_update({
                    'requests': [{
                        'repeatCell': {
                            'range': {
                                'sheetId': sheet_id,
                                'startRowIndex': target_row - 1,
                                'endRowIndex': target_row,
                                'startColumnIndex': 14,
                                'endColumnIndex': 15
                            },
                            'cell': {
                                'userEnteredFormat': {
                                    'backgroundColor': bg_color,
                                    'horizontalAlignment': 'CENTER',
                                    'verticalAlignment': 'MIDDLE',
                                    'textFormat': {
                                        'foregroundColor': text_color,
                                        'bold': True,
                                        'fontSize': 11
                                    }
                                }
                            },
                            'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)'
                        }
                    }]
                })
                sheet_updated = True
    except Exception as e:
        print(f"Error syncing status to Google Sheet: {e}")

    status_label = "📬 IN HAND (Cheque Received)" if new_status == "RECEIVED" else "⏳ AWAITING CHEQUE (Pending)"
    vendor_display = req.get("vendor", "")
    return {
        "status": "success",
        "new_status": new_status,
        "sheet_updated": sheet_updated,
        "message": f"Updated #{req_id} ({vendor_display}) status to: {status_label}"
    }
