import os, json
# SAMPLE SHOW S1 - OFFICIAL SET LIST
# This serves as a baseline, but dynamic sets from settings are merged in.

def get_merged_set_list():
    from core.settings import load_settings
    
    SET_LIST = {
        # SAMPLE SETS - replace with your show's set list (or add them in Settings)
        "X80": "LEAD CHARACTER'S APARTMENT",
        "X81": "RESTAURANT - KITCHEN / HALLWAY",
        "A10": "CITY STREET",
        "A11": "AMBULANCE",
        "A12": "SUBURBAN HOUSE - LIVING ROOM",
        "A13": "POLICE STATION - LOBBY",
        "A14": "COURTHOUSE - HALLWAY",
        "B20": "HOSPITAL - WAITING ROOM",
        "B21": "MOTEL ROOM",
        "C10": "OFFICE BUILDING - BOARDROOM",
    }

    settings_data = load_settings()
    dynamic_sets = settings_data.get("dynamic_sets", {})
    if dynamic_sets:
        for ep_name, sets in dynamic_sets.items():
            for s in sets:
                if s.get("code") and s.get("name"):
                    SET_LIST[s["code"].upper()] = s["name"].upper()

    # Merge external set_list.json from SAMPLE SHOW S1\CH REQS if available
    try:
        import json
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        json_path = os.path.abspath(os.path.join(app_dir, "..", "..", "CH REQS", "set_list.json"))
        if not os.path.exists(json_path):
            json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Input")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f_json:
                ext_sets = json.load(f_json)
                for code, name in ext_sets.items():
                    if code and name:
                        SET_LIST[code.upper()] = name.upper()
    except Exception as e_json:
        pass

    return SET_LIST

def get_set_name(set_code: str) -> str:
    """Returns the official Set Name for a given Set Code (e.g. 'A14' -> 'CITY REC CENTER - BLEACHERS')."""
    if not set_code:
        return ""
    code_clean = set_code.strip().upper()
    return get_merged_set_list().get(code_clean, "")

def format_set_display(set_code: str) -> str:
    """Formats set code + set name for display (e.g. 'A14 - CITY REC CENTER - BLEACHERS')."""
    name = get_set_name(set_code)
    if name:
        return f"{set_code.strip().upper()} - {name}"
    return set_code.strip().upper()

def resolve_special_and_initial_set(set_input: str, special_tab: str = None, notes: str = None) -> dict:
    """
    Handles special extension sets like X98, G98, I98 paired with initial sets (e.g. X83),
    as well as special tabs like 203-T (203 Tandem & 2nd Unit).
    Returns dict:
      - is_special_98: bool
      - special_set: e.g. 'X98' or '203-T'
      - initial_set: e.g. 'X83' or 'FANCY RESTAURANT'
      - initial_set_name: e.g. 'TRES' or 'FANCY RESTAURANT'
      - display_pdf_set: e.g. 'X98 - TRES' or '203 TANDEM - FANCY RESTAURANT'
    """
    import re
    raw = str(set_input or "").strip()
    sp_tab = str(special_tab or "").strip().upper()
    notes_str = str(notes or "").strip().upper()

    # 0. Check for 203 Tandem / 203-T
    is_203_t = (
        sp_tab == "203-T" or 
        "203-T" in raw.upper() or 
        "203 TANDEM" in raw.upper() or 
        "203 - TANDEM" in raw.upper() or 
        "203 TANDEM" in notes_str or 
        "203 - TANDEM" in notes_str or
        "TANDEM & 2ND UNIT" in raw.upper()
    )
    if is_203_t:
        tandem_set = ""
        combined_text = f"{raw} {notes_str}".upper()
        if "FANCY" in combined_text or "RESTAURANT" in combined_text or "RETAURANT" in combined_text or "C26" in combined_text:
            tandem_set = "FANCY RESTAURANT"
        elif "DITTY" in combined_text:
            tandem_set = "EXT DITTY LANE"
        elif "POLICE" in combined_text:
            tandem_set = "EXT POLICE STATION"
        else:
            # Clean out the base name "203 - TANDEM & 2ND UNIT" or "203-T"
            clean = re.sub(r'203\s*[-–—]?\s*(?:TANDEM)?(?:\s*&\s*2ND\s*UNIT)?', '', raw, flags=re.IGNORECASE).strip(" -/–—")
            if clean and clean.upper() not in ["2ND UNIT", "& 2ND UNIT", "T", "TANDEM", "UNKNOWN"]:
                tandem_set = clean.upper()

        display_name = f"203 TANDEM - {tandem_set}" if tandem_set else "203 - TANDEM & 2ND UNIT"
        return {
            "is_special_98": True,
            "special_set": "203-T",
            "initial_set": tandem_set,
            "initial_set_name": tandem_set,
            "display_pdf_set": display_name
        }

    special_set = None
    initial_set = None
    custom_name = None

    # 1. Check if special_tab is provided (e.g. X98, G98, I98)
    if sp_tab and re.search(r'^[A-Z]*98$', sp_tab):
        special_set = sp_tab

    # 2. Search for any token ending in 98 in raw (e.g. X83 - X98 or X98)
    m_98 = re.search(r'\b([A-Z]*98)\b', raw, re.IGNORECASE)
    if m_98:
        special_set = m_98.group(1).upper()
        if special_set == "98":
            special_set = None

    # 3. Find initial set code (letter + 1-2 digits, not ending in 98)
    all_codes = re.findall(r'\b([A-Za-z]\d{1,2}[A-Za-z]?)\b', raw)
    for c in all_codes:
        c_up = c.upper()
        if c_up.endswith("98"):
            special_set = c_up
        else:
            initial_set = c_up

    # 4. If initial set wasn't in raw, check notes (e.g. if notes has X83)
    if not initial_set and notes_str:
        m_notes_code = re.search(r'\b([A-Za-z]\d{1,2}[A-Za-z]?)\b', notes_str)
        if m_notes_code and not m_notes_code.group(1).upper().endswith("98"):
            initial_set = m_notes_code.group(1).upper()

    # 5. If special_set was just "98" without prefix, use initial set prefix (e.g. X83 -> X98)
    if special_set and len(special_set) == 2 and initial_set:
        special_set = f"{initial_set[0]}{special_set}"
    elif not special_set and sp_tab:
        special_set = sp_tab

    # 6. Extract any custom set name from raw (e.g. "X83 - X98 - Tres" -> "Tres")
    parts = [p.strip() for p in re.split(r'[-/–—,]+', raw) if p.strip()]
    for p in parts:
        p_clean = re.sub(r"[^A-Za-z0-9\s']", "", p).strip()
        if p_clean.upper() not in [str(special_set), str(initial_set), "98", "EXT"]:
            if len(p_clean) > 1 and not re.match(r'^[A-Z]\d+$', p_clean, re.IGNORECASE):
                custom_name = p_clean
                break

    # 7. Determine initial set name
    initial_set_name = ""
    if custom_name:
        initial_set_name = custom_name
    elif initial_set:
        set_map = get_merged_set_list()
        full_name = set_map.get(initial_set, "")
        if full_name:
            primary = full_name.split('/')[0].strip()
            if initial_set == "X83" or "TRE" in primary.upper() or "TRÉ" in primary.upper() or "TREY" in primary.upper():
                initial_set_name = "TRES"
            else:
                initial_set_name = primary
        else:
            initial_set_name = initial_set

    if special_set:
        if not initial_set_name and raw != special_set:
            initial_set_name = raw.replace(special_set, "").strip(" -/–—")
        display_pdf_set = f"{special_set} - {initial_set_name}".strip(" -") if initial_set_name else special_set
        return {
            "is_special_98": True,
            "special_set": special_set,
            "initial_set": initial_set or "",
            "initial_set_name": initial_set_name,
            "display_pdf_set": display_pdf_set
        }

    return {
        "is_special_98": False,
        "special_set": None,
        "initial_set": raw,
        "initial_set_name": "",
        "display_pdf_set": raw
    }


def derive_episode_code(set_input: str, special_tab: str = None) -> str:
    """
    Derives the Expense episode code (e.g. 251 for A, 252 for B... 260 for J, 297 for X/Amort).
    CRITICAL USER DIRECTIVE:
    For any 98 set (e.g. G98, I98, X98, B98, J98), whether in special_tab or in set_input
    (e.g. 'B18 - G98' or set 'B18' with special_tab 'G98'), the episode code MUST ALWAYS
    be the episode of the 98 set (e.g. G98 -> 257), NOT the initial set (e.g. NOT B18 -> 252).
    """
    import re
    s_raw = str(set_input or "").strip().upper()
    sp_tab = str(special_tab or "").strip().upper()

    # 1. Check for 203-T (203 Tandem & 2nd Unit)
    if sp_tab == "203-T" or "203-T" in s_raw or "203 TANDEM" in s_raw or "203 - TANDEM" in s_raw or "TANDEM & 2ND UNIT" in s_raw:
        return "253"

    # 2. Check for any 98 set in special_tab or in s_raw (e.g. G98, I98, X98, B98)
    # The 98 set ALWAYS overrides any initial set!
    target_98 = None
    if sp_tab and re.search(r'\b([A-Z]*98)\b', sp_tab):
        target_98 = sp_tab
    else:
        m_98 = re.search(r'\b([A-Z]*98)\b', s_raw)
        if m_98:
            target_98 = m_98.group(1).upper()

    if target_98:
        m_let = re.match(r'^([A-Z])', target_98)
        if m_let:
            let = m_let.group(1)
            if let == 'X':
                return "297"
            if 'A' <= let <= 'Z':
                return str(250 + (ord(let) - ord('A') + 1))

    # 3. Check if special_tab is provided and starts with an episode letter
    if sp_tab and sp_tab not in ["SHIP", "EQUIP", "PROD", "ELECT", "TRANS", "SECT", "L&D"]:
        m_sp = re.match(r'^([A-Z])', sp_tab)
        if m_sp:
            let = m_sp.group(1)
            if let == 'X':
                return "297"
            if 'A' <= let <= 'Z':
                return str(250 + (ord(let) - ord('A') + 1))

    # 4. Extract set code from s_raw (e.g. 'J22' -> 'J' -> '260', 'B18' -> '252')
    codes = re.findall(r'\b([A-Z])\d{1,2}[A-Z]?\b', s_raw)
    if codes:
        let = codes[0]
        if let == 'X':
            return "297"
        if 'A' <= let <= 'Z':
            return str(250 + (ord(let) - ord('A') + 1))

    # 5. Check if string starts with an episode letter (e.g. 'J' or 'A')
    m_start = re.match(r'^([A-Z])', s_raw)
    if m_start:
        let = m_start.group(1)
        if let == 'X':
            return "297"
        if 'A' <= let <= 'Z':
            return str(250 + (ord(let) - ord('A') + 1))

    return ""
