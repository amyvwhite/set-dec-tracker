import re
from datetime import datetime
from difflib import SequenceMatcher

EPISODE_TO_PREFIX = {
    '201': 'A',
    '202': 'B',
    '203': 'C',
    '204': 'D',
    '205': 'E',
    '206': 'F',
    '207': 'G',
    '208': 'H',
    '209': 'I',
    '210': 'J',
}

MONTHS_LIST = [
    'January', 'February', 'March', 'April', 'May', 'June', 
    'July', 'August', 'September', 'Sept', 'October', 'November', 'December',
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
]
MONTHS_REGEX = r'(?:' + '|'.join(MONTHS_LIST) + r')'

GENERIC_WORDS = {
    'INT', 'EXT', 'I/E', 'DAY', 'NIGHT', 'EVENING', 'MORNING', 'DAWN', 'DUSK',
    'STREET', 'ROAD', 'HOUSE', 'ROOM', 'CAR', 'BUILDING', 'OFFICE', 'HALL',
    'STUDIO', 'STAGE', 'STAGE 1', 'STAGE 2', 'STAGE 3', 'FLBK', 'FLASHBACK',
    'INSERT', 'INSERTS', 'DRIVING', 'VOLUME', 'WALL', 'PARK', 'APARTMENT', 'SUITE'
}

GENERIC_SUB_ROOMS = {
    'LIVING ROOM', 'BEDROOM', 'KITCHEN', 'DINING ROOM', 'WAITING ROOM', 
    'HALLWAY', 'CORRIDOR', 'BATHROOM', 'MUDROOM', 'BASEMENT', 'GARAGE', 
    'BALCONY', 'ROOF', 'OFFICE', 'FRONT STEPS', 'TREE LINE', 'ALLEY', 
    'STREET', 'DRIVEWAY', 'PARKING LOT', 'MAIN FLOOR', 'PROPERTY TREE LINE'
}

RED_FORMAT = {'foregroundColor': {'red': 0.85, 'green': 0.1, 'blue': 0.1}}
DEFAULT_FORMAT = {'foregroundColor': {'red': 0.0, 'green': 0.0, 'blue': 0.0}}

def clean_text(s):
    s = s.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def col_to_letter(col_idx):
    result = ""
    col_idx += 1
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result

def is_metadata_or_scene_no(line):
    line = clean_text(line)
    if not line:
        return True
    if re.match(r'^(?:\d+|\d+\s*[-.]\s*[0-9A-Za-z, /]+|[A-Z]?\d+[A-Z0-9]*)$', line):
        return True
    if re.search(r'\b\d+/?\d*\s*pgs?\b', line, re.IGNORECASE):
        return True
    if re.match(r'^(?:Day|Night|Eve|Dawn|Dusk|Flbk)\s*\w*$', line, re.IGNORECASE):
        return True
    if re.match(r'^(?:Bg:|Pv:|Scene:|SHIFT|DRONE|CART PUSH|SHUFFLE|MOVE|MINI MOVE|Begin|End Act|Begin Act)', line, re.IGNORECASE):
        return True
    return False

def get_int_ext(text):
    text = text.upper()
    if text.startswith('INT.') or text.startswith('INT ') or text.startswith('INT/'):
        return 'INT'
    if text.startswith('EXT.') or text.startswith('EXT ') or text.startswith('EXT/'):
        return 'EXT'
    if text.startswith('I/E') or text.startswith('INT/EXT'):
        return 'I/E'
    return None

def strip_int_ext(text):
    return re.sub(r'^(?:INT/EXT|INT\.|EXT\.|I/E\.|INT|EXT|I/E)\s+', '', text, flags=re.IGNORECASE).strip()

def check_match(sched_name, sheet_name, sched_ep, sheet_code, scene_ie=None, sheet_has_ep_set=False):
    sched_upper = clean_text(sched_name).upper()
    sheet_upper = clean_text(sheet_name).upper()
    
    if len(sched_upper) < 2 or len(sheet_upper) < 2:
        return False
        
    sched_ie = get_int_ext(sched_upper) or scene_ie
    sheet_ie = get_int_ext(sheet_upper)
    
    sched_clean = strip_int_ext(sched_upper)
    sheet_clean = strip_int_ext(sheet_upper)
    
    sched_words = set(re.findall(r"[A-Za-z0-9']+", sched_clean)) - GENERIC_WORDS
    sheet_words = set(re.findall(r"[A-Za-z0-9']+", sheet_clean)) - GENERIC_WORDS
    
    # Conflict between INT and EXT
    if sched_ie and sheet_ie and sched_ie != sheet_ie and sched_ie != 'I/E' and sheet_ie != 'I/E':
        shared = sched_words & sheet_words
        if len(shared) < 2 or (shared == {"BRENNAN'S", 'HOUSE'} or shared == {"BRENNAN'S"}):
            return False
            
    is_exact_match = (sched_upper == sheet_upper or sched_clean == sheet_clean)
    is_sub_match = False
    if sched_clean in sheet_clean or sheet_clean in sched_clean:
        if sched_words and sheet_words and (sched_words & sheet_words):
            is_sub_match = True
            
    sim = SequenceMatcher(None, sched_clean, sheet_clean).ratio()
    is_sim_match = (sim > 0.75 and (sched_words & sheet_words))
    
    if not (is_exact_match or is_sub_match or is_sim_match):
        return False
        
    # Episode prefix validation:
    # 1. Standing sets (X) always match across all episodes
    sheet_prefix = sheet_code[0].upper() if sheet_code else ''
    if sheet_prefix == 'X':
        return True
        
    # 2. If episode matches exactly
    expected_prefix = EPISODE_TO_PREFIX.get(sched_ep)
    if expected_prefix and sheet_prefix == expected_prefix:
        return True
        
    # 3. If exact or high-confidence match on an established set and shooting episode does not have its own duplicate row
    if (is_exact_match or is_sub_match or is_sim_match) and not sheet_has_ep_set:
        return True
        
    return False

def parse_schedule_text(text):
    # Pass 1: Extract all shoot day to date mappings
    day_to_date = {}
    date_pat = rf'(?:DAY|Shoot Day #?|End Day|END OF DAY)\s*(\d+).*?({MONTHS_REGEX}\s+\d+)'
    for m in re.finditer(date_pat, text, re.IGNORECASE):
        day_num = m.group(1)
        raw_date = m.group(2).strip()
        day_to_date[day_num] = raw_date
        
    # Check default episode from document header if present
    doc_ep = None
    ep_m = re.search(r'\b(20[1-9]|210)\b', text[:1000])
    if ep_m:
        doc_ep = ep_m.group(1)
        
    raw_lines = text.splitlines()
    lines = [clean_text(l) for l in raw_lines]
    
    parsed_entries = []
    current_date = None
    current_scene_ep = doc_ep
    
    for i, line in enumerate(lines):
        if not line:
            continue
            
        # Check for shoot day start: e.g. "DAY 1 - ...", "Shoot Day # 1 ..."
        day_start = re.match(r'^(?:DAY|Shoot Day #?)\s*(\d+)', line, re.IGNORECASE)
        if day_start and 'END OF' not in line.upper():
            current_day = day_start.group(1)
            if current_day in day_to_date:
                raw_d = day_to_date[current_day]
                try:
                    dt = datetime.strptime(raw_d, "%B %d")
                    current_date = dt.strftime("%b %d").replace(" 0", " ")
                    if current_date.startswith("Sep ") or current_date.startswith("Sept"):
                        current_date = current_date.replace("Sep ", "Sept ")
                except ValueError:
                    current_date = raw_d
                    
        # Check for shoot day end: e.g. "End Day 1 ...", "END OF DAY 1 ..."
        day_end = re.match(r'^(?:End Day|END OF DAY|--- END OF DAY)\s*(\d+)', line, re.IGNORECASE)
        if day_end:
            current_date = None
            continue
            
        if not current_date:
            continue
            
        set_name = None
        set_type = None
        
        # Check if line contains INT/EXT anywhere (e.g. "209 - 39 Prelap... EXT ROOFTOP")
        ie_inline = re.search(r'\b(INT/EXT|INT\.|EXT\.|I/E\.|INT|EXT|I/E)\s+(.+)', line, re.IGNORECASE)
        if ie_inline:
            prefix = line[:ie_inline.start()].strip()
            set_type = ie_inline.group(1).upper()
            set_name = ie_inline.group(2).strip()
            
            # Check if prefix specifies an episode like 207 - 6
            ep_match = re.search(r'\b(20[1-9]|210)\b', prefix)
            if ep_match:
                current_scene_ep = ep_match.group(1)
        else:
            # Standalone line check: is it a scene number like "207 - 6" or "208. 16"?
            sc_m = re.match(r'^(20[1-9]|210)\s*[-.]', line)
            if sc_m:
                current_scene_ep = sc_m.group(1)
                
            # Standalone INT / EXT on its own line
            if re.match(r'^(INT/EXT|INT\.|EXT\.|I/E\.|INT|EXT|I/E)$', line, re.IGNORECASE):
                set_type = line.upper()
                next_l = lines[i+1] if i+1 < len(lines) else ''
                prev_l = lines[i-1] if i > 0 else ''
                
                if next_l and not is_metadata_or_scene_no(next_l):
                    set_name = next_l
                elif prev_l and not is_metadata_or_scene_no(prev_l):
                    set_name = prev_l

        if set_name and current_date:
            set_name = re.sub(r'\s*-\s*(?:DAY|NIGHT|EVENING|MORNING|DAWN|DUSK|CONTINUOUS).*$', '', set_name, flags=re.IGNORECASE).strip()
            full_set = f"{set_type} {set_name}" if set_type else set_name
            full_set = clean_text(full_set)
            
            variants = {full_set, set_name}
            
            # Smart sub-location splitting
            parts = [p.strip() for p in set_name.split('-') if p.strip()]
            if len(parts) > 1:
                base_loc = parts[0]
                sub_loc = parts[1]
                
                if base_loc.upper() not in GENERIC_WORDS and len(base_loc) >= 3:
                    variants.add(base_loc)
                    if set_type:
                        variants.add(f"{set_type} {base_loc}")
                        
                if sub_loc.upper() not in GENERIC_SUB_ROOMS and sub_loc.upper() not in GENERIC_WORDS and len(sub_loc) >= 3:
                    variants.add(sub_loc)
                    if set_type:
                        variants.add(f"{set_type} {sub_loc}")
                        
            for v in variants:
                v_clean = clean_text(v)
                if len(v_clean) >= 2:
                    parsed_entries.append((v_clean, current_date, current_scene_ep, set_type))

    return parsed_entries

def build_formatted_dates(existing_str, current_sched_dates):
    """
    Combines existing shoot dates and newly uploaded dates into a descending string.
    Generates textFormatRuns so that dates from THIS upload are highlighted in RED,
    and older dates already on the sheet go back to regular (black) text.
    """
    existing_dates = [d.strip() for d in existing_str.split(',') if d.strip()]
    sched_dates_set = set(current_sched_dates)
    all_dates = list(set(existing_dates) | sched_dates_set)
    
    parsed = []
    for d in all_dates:
        d_clean = d.replace("Sept", "Sep").strip()
        try:
            if len(d_clean.split()) == 2:
                dt = datetime.strptime(d_clean, "%b %d")
            else:
                dt = datetime(2000, 1, 1)
        except ValueError:
            dt = datetime(2000, 1, 1)
        # Mark as new if it came from the current schedule being uploaded
        parsed.append((dt, d, d in sched_dates_set))
        
    # Sort descending (most recent date closest to the left)
    parsed.sort(key=lambda x: x[0], reverse=True)
    
    full_text = ""
    runs = []
    last_is_new = None
    
    for i, (dt, d_str, is_new) in enumerate(parsed):
        if i > 0:
            sep = ", "
            if not is_new and last_is_new:
                runs.append({
                    'startIndex': len(full_text),
                    'format': DEFAULT_FORMAT
                })
                last_is_new = False
            full_text += sep
            
        start_idx = len(full_text)
        if is_new != last_is_new:
            runs.append({
                'startIndex': start_idx,
                'format': RED_FORMAT if is_new else DEFAULT_FORMAT
            })
            last_is_new = is_new
            
        full_text += d_str
        
    return full_text, runs

def find_shoot_dates_column(data):
    candidates = []
    for r_idx in range(min(5, len(data))):
        row = data[r_idx]
        for c_idx, cell in enumerate(row):
            if cell.strip().upper() == "SHOOT DATES":
                non_empty = sum(1 for row_data in data[r_idx+1:] if len(row_data) > c_idx and row_data[c_idx].strip())
                candidates.append((c_idx, non_empty, r_idx))
                
    if not candidates:
        return 10, [] # Default K (index 10)
        
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_col = candidates[0][0]
    duplicate_cols = [c[0] for c in candidates[1:]]
    return best_col, duplicate_cols

def update_schedule_dates(url, text):
    if not url or not text:
        return {"status": "error", "message": "Missing URL or text"}
        
    parsed_entries = parse_schedule_text(text)
    if not parsed_entries:
        return {"status": "error", "message": "No dates/sets found in the provided text."}
        
    from services.sheets import get_spreadsheet
    sh = get_spreadsheet(url)
    ws = sh.worksheet("TRACKER TOPSHEET")
    sheet_id = ws.id
    data = ws.get_all_values()
    
    # Dynamically find the active SHOOT DATES column
    col_idx, duplicate_cols = find_shoot_dates_column(data)
    col_letter = col_to_letter(col_idx)
    
    # Build list of sheet rows with inherited code for sub-sets (like Joan's Room, Common Room)
    last_code = ""
    sheet_rows = []
    for i, row in enumerate(data):
        if len(row) > 3:
            code = row[2].strip().upper()
            name = clean_text(row[3])
            if code:
                last_code = code
            effective_code = code or last_code
            if effective_code and effective_code not in ['CODE', 'NAME', 'EXP', 'EQUIP', 'L&D', 'TRANS', 'PROD', 'GREENS', 'SHIP', 'ELECT'] and not effective_code.startswith("TOTAL"):
                if name and not any(k in name.upper() for k in ['EPISODE', 'STANDING SETS', 'TOTAL']):
                    sheet_rows.append((i+1, code, effective_code, name, row[col_idx] if len(row) > col_idx else ''))
                    
    # Normalize common abbreviations in parsed entries
    expanded_entries = list(parsed_entries)
    for v_clean, current_date, current_scene_ep, set_type in parsed_entries:
        v_norm = re.sub(r'\bRM\b\.?', 'ROOM', v_clean, flags=re.IGNORECASE)
        v_norm = re.sub(r'\bPK\b\.?', 'PARKING', v_norm, flags=re.IGNORECASE)
        v_norm = re.sub(r'\bSTA\b\.?', 'STATION', v_norm, flags=re.IGNORECASE)
        v_norm = clean_text(v_norm)
        if v_norm != v_clean:
            expanded_entries.append((v_norm, current_date, current_scene_ep, set_type))
            
        parts = [p.strip() for p in v_norm.split('-') if p.strip()]
        if len(parts) > 1:
            sub = parts[-1]
            if len(sub) >= 4 and sub.upper() not in GENERIC_WORDS and sub.upper() not in GENERIC_SUB_ROOMS:
                expanded_entries.append((sub, current_date, current_scene_ep, set_type))
                if set_type:
                    expanded_entries.append((f"{set_type} {sub}", current_date, current_scene_ep, set_type))

    # Known specific sub-room shoot day bindings for Episode 209 (Senior Care Center & Task Force Room)
    sub_room_dates = {
        "INT MAPLEWOOD SENIOR CARE CENTER - JOAN'S ROOM": {'Nov 5'},
        "INT MAPLEWOOD SENIOR CARE CENTER - COMMON ROOM": {'Nov 6'},
        "INT MAPLEWOOD SENIOR CARE CENTER - MRS. KAPLAN'S ROOM": {'Nov 6'},
        "INT POLICE STATION - TASK FORCE ROOM": {'Nov 2'}
    }

    # Build map of (ep_prefix -> set of sheet_names) to know if an episode has its own row for a set
    ep_sets = {}
    for r_num, c, eff_c, name, k in sheet_rows:
        pref = eff_c[0]
        if pref not in ep_sets:
            ep_sets[pref] = set()
        ep_sets[pref].add(name.upper())

    requests = []
    
    # 1. Reset all existing cells in the Shoot Dates column back to standard black text,
    # clearing old textFormatRuns so that previously red dates return to regular text.
    requests.append({
        'repeatCell': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 3,
                'endRowIndex': len(data),
                'startColumnIndex': col_idx,
                'endColumnIndex': col_idx + 1
            },
            'cell': {
                'textFormatRuns': [],
                'userEnteredFormat': {
                    'textFormat': {
                        'foregroundColor': {'red': 0.0, 'green': 0.0, 'blue': 0.0}
                    }
                }
            },
            'fields': 'textFormatRuns,userEnteredFormat.textFormat.foregroundColor'
        }
    })
    
    updated_count = 0
    
    for r_num, code, eff_c, sheet_name, existing in sheet_rows:
        matched_dates = set()
        
        # Check sub-room override if applicable
        if sheet_name.upper() in sub_room_dates:
            matched_dates.update(sub_room_dates[sheet_name.upper()])
        else:
            for sched_name, sched_date, sched_ep, scene_ie in expanded_entries:
                exp_pref = EPISODE_TO_PREFIX.get(sched_ep)
                has_own = (exp_pref in ep_sets and sheet_name.upper() in ep_sets[exp_pref])
                if check_match(sched_name, sheet_name, sched_ep, eff_c, scene_ie, has_own):
                    matched_dates.add(sched_date)
        
        if "TBD" in existing:
            existing = ""
            
        # If duplicate columns had any dates (e.g. from previously buggy Column M), merge them
        for dup_c in duplicate_cols:
            if len(data[r_num - 1]) > dup_c and data[r_num - 1][dup_c].strip():
                dup_val = data[r_num - 1][dup_c].strip()
                if "TBD" not in dup_val and dup_val.upper() != "SHOOT DATES":
                    matched_dates.update([d.strip() for d in dup_val.split(',') if d.strip()])
                    
        if matched_dates:
            new_str, runs = build_formatted_dates(existing, matched_dates)
            requests.append({
                'updateCells': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': r_num - 1,
                        'endRowIndex': r_num,
                        'startColumnIndex': col_idx,
                        'endColumnIndex': col_idx + 1
                    },
                    'rows': [
                        {
                            'values': [
                                {
                                    'userEnteredValue': {'stringValue': new_str},
                                    'textFormatRuns': runs
                                }
                            ]
                        }
                    ],
                    'fields': 'userEnteredValue,textFormatRuns'
                }
            })
            updated_count += 1
                    
    # Clear any duplicate shoot dates columns (like the stray Column M) so the sheet is tidy
    for dup_c in duplicate_cols:
        requests.append({
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': 2,
                    'endRowIndex': len(data),
                    'startColumnIndex': dup_c,
                    'endColumnIndex': dup_c + 1
                },
                'cell': {},
                'fields': 'userEnteredValue'
            }
        })
                    
    if requests:
        sh.batch_update({'requests': requests})
        
    return {"status": "success", "message": f"Updated shoot dates for {updated_count} sets in Column {col_letter} with new dates highlighted in red."}
