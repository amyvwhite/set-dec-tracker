import json
import os
import re
import sys

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.dirname(sys.executable)
else:
    DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')

def load_settings():
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"spreadsheet_url": "", "gemini_api_key": ""}

def save_settings(settings):
    try:
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

def normalize_vendor_key(vendor_name: str) -> str:
    if not vendor_name:
        return ""
    s = str(vendor_name).strip().upper()
    if " DBA " in s:
        parts = s.split(" DBA ")
        s = parts[1].strip()
    s = re.sub(r'\b(INC\.?|LTD\.?|LLC\.?|CORP\.?|CORPORATION|CO\.?)\b', '', s)
    s = re.sub(r'[^A-Z0-9\s]', ' ', s)
    return ' '.join(s.split())

def get_vendor_payment_pref(vendor_name: str) -> str:
    """Returns 'ACH' or 'CHQ' (or 'CH REQ') if remembered for this vendor, else None."""
    if not vendor_name:
        return None
    settings = load_settings()
    prefs = settings.get("vendor_payment_preferences", {})
    if not prefs:
        return None
        
    v_clean = str(vendor_name).strip().upper()
    if v_clean in prefs:
        return prefs[v_clean]
        
    norm_key = normalize_vendor_key(vendor_name)
    if norm_key in prefs:
        return prefs[norm_key]
        
    for k, p in prefs.items():
        if k in v_clean or v_clean in k or (norm_key and (k in norm_key or norm_key in k)):
            return p
            
    return None

def set_vendor_payment_pref(vendor_name: str, payment_type: str):
    """Saves 'ACH' or 'CHQ' preference for the vendor in settings.json."""
    if not vendor_name or not payment_type:
        return
    pt = "ACH" if "ACH" in str(payment_type).upper() else ("PO" if "PO" in str(payment_type).upper() else "CHQ")
    
    settings = load_settings()
    if "vendor_payment_preferences" not in settings:
        settings["vendor_payment_preferences"] = {}
        
    prefs = settings["vendor_payment_preferences"]
    v_clean = str(vendor_name).strip().upper()
    norm_key = normalize_vendor_key(vendor_name)
    
    # Update all matching keys in prefs so no stale conflicting choices linger
    keys_to_update = [k for k in list(prefs.keys()) if (k in v_clean or v_clean in k or (norm_key and (k in norm_key or norm_key in k)))]
    for k in keys_to_update:
        prefs[k] = pt
        
    prefs[v_clean] = pt
    if norm_key:
        prefs[norm_key] = pt
        
    save_settings(settings)

def get_vendor_profile(vendor_name: str) -> dict:
    """Returns the remembered profile dictionary for a vendor, or None."""
    if not vendor_name:
        return None
    settings = load_settings()
    profiles = settings.get("vendor_profiles", {})
    if not profiles:
        # Seed default known profiles on first access
        seed_profiles = {
            "ALLEN GALLERY ART SALES RENTALS": {
                "payee": "SUPA HOLDINGS dba ALLEN GALLERY ART SALES & RENTALS",
                "address1": "2965 Lake Shore Blvd. W.",
                "address2": "Toronto ON, M8V 1J5 Canada",
                "tel": "4165262635",
                "hst_number": "805615960",
                "payment_type": "ACH"
            },
            "GOOD DOG DIGITAL": {
                "payee": "8752311 CANADA INC. dba GOOD DOG DIGITAL",
                "hst_number": "831605779"
            },
            "EXECUTIVE FURNITURE RENTALS": {
                "payee": "4206720 CANADA INC. dba EXECUTIVE FURNITURE RENTALS"
            },
            "DIVINE FURNITURE RENTAL": {
                "hst_number": "860957638RT0001"
            },
            "HERCULES": {
                "address1": "120 St. Regis Crescent South",
                "address2": "North York, ON M3J 1Y8"
            }
        }
        settings["vendor_profiles"] = seed_profiles
        save_settings(settings)
        profiles = seed_profiles

    v_clean = str(vendor_name).strip().upper()
    norm_key = normalize_vendor_key(vendor_name)

    if v_clean in profiles:
        return profiles[v_clean]
    if norm_key in profiles:
        return profiles[norm_key]

    for k, prof in profiles.items():
        if k in v_clean or v_clean in k or (norm_key and (k in norm_key or norm_key in k)):
            return prof

    return None

def save_vendor_profile(vendor_name: str, profile_data: dict):
    """
    Saves or updates vendor-specific info (payee, address, tel, hst, contact, payment_type).
    Merges with existing data so non-empty fields update and existing fields are preserved.
    """
    if not vendor_name or not profile_data:
        return

    settings = load_settings()
    if "vendor_profiles" not in settings:
        settings["vendor_profiles"] = {}
    profiles = settings["vendor_profiles"]

    v_clean = str(vendor_name).strip().upper()
    norm_key = normalize_vendor_key(vendor_name)

    existing = get_vendor_profile(vendor_name) or {}
    merged = dict(existing)

    for k, v in profile_data.items():
        val_str = str(v).strip() if v is not None else ""
        if val_str:
            merged[k] = val_str

    if merged.get("payment_type"):
        pt = "ACH" if "ACH" in str(merged["payment_type"]).upper() else ("PO" if "PO" in str(merged["payment_type"]).upper() else "CHQ")
        merged["payment_type"] = pt
        if "vendor_payment_preferences" not in settings:
            settings["vendor_payment_preferences"] = {}
        settings["vendor_payment_preferences"][v_clean] = pt
        if norm_key:
            settings["vendor_payment_preferences"][norm_key] = pt

    matching_keys = [k for k in list(profiles.keys()) if (k in v_clean or v_clean in k or (norm_key and (k in norm_key or norm_key in k)))]
    for k in matching_keys:
        profiles[k] = merged

    profiles[v_clean] = merged
    if norm_key:
        profiles[norm_key] = merged

    save_settings(settings)

# ==========================================
# Centralized Buyer Names & Aliases
# ==========================================

DEFAULT_BUYERS_DATA = {
    "buyers": [
        "JORDAN", "NINA", "ROWAN", "NICK D", "RAVI", "SAM", "BRANDT",
        "MACDOUGALL", "MILO", "JAN", "TAMAS PAL", "AL GECEKUSU",
        "JOSH VARCOE", "LIAM COLE", "OSCAR FINCH", "TJ MORROW",
        "NOAH BELL", "OWEN PARK", "ELI VANCE", "DAN REID",
        "MAYA STONE", "LEO GRANT", "ZOE LANE", "IAN WEST"
    ],
    "buyer_aliases": {
        "JORDAN": ["JORDAN", "JORDAN PRICE", "PRICE"],
        "NINA": ["NINA", "NINA CLARK", "CLARK"],
        "ROWAN": ["ROWAN", "ROWAN K", "ROWAN P CARD", "ROWAN PCARD"],
        "NICK D": ["NICK", "NICK D", "NIKOLAS", "NICK KOVA"],
        "RAVI": ["RAVI", "RAVI KHAN", "KHAN"],
        "SAM": ["SAM", "SAM RIVERA", "SAMUEL", "SAMUEL RIVERA", "RIVERA"],
        "BRANDT": ["BRANDT"],
        "MACDOUGALL": ["MACDOUGALL", "HARLOW", "HARLOW", "MCDOUGALL"],
        "MILO": ["MILO", "MILO", "TARAN", "A.T.", "A.T", "A T"],
        "JAN": ["JAN", "LUND"],
        "TAMAS PAL": ["TAMAS", "TAMAS PAL", "PAL"],
        "AL GECEKUSU": ["AL", "AL G", "AL GECEKUSU", "GECEK", "GECEKUSU"],
        "JOSH VARCOE": ["JOSH", "JOSH VARCOE", "JOSH VARVOE", "VARCOE"],
        "LIAM COLE": ["JOHN", "LIAM COLE", "COLE"],
        "OSCAR FINCH": ["OSCAR", "OSCAR C", "FINCH"],
        "TJ MORROW": ["JR", "TJ MORROW", "MORROW"],
        "NOAH BELL": ["NOAH", "NOAH BELL", "MARCH"],
        "OWEN PARK": ["OWEN", "OWEN PARK", "PETER"],
        "ELI VANCE": ["ELI", "ELI VANCE", "ELIAS", "ELIAS VANCE", "VANCE"],
        "DAN REID": ["DAN", "DAN REID", "REID"],
        "MAYA STONE": ["MAYA", "MAYA STONE", "STONE"],
        "LEO GRANT": ["LEO", "LEO GRANT", "GRANT"],
        "ZOE LANE": ["ZOE", "ZOE LANE", "SMITH"],
        "IAN WEST": ["IAN", "IAN WEST", "IAN WEST", "WILSON"]
    },
    "default_buyer": "JORDAN",
    "greens_buyers": ["JAN", "LUND", "MILO", "MILO"],
    "petty_cash_envelope_owners": ["AMY WHITE", "ROWAN", "JORDAN PRICE", "RAVI", "SAM RIVERA", "OTHER"]
}

def get_buyers() -> list:
    """Returns the list of department buyer names configured in settings."""
    settings = load_settings()
    buyers = settings.get("buyers")
    if not buyers:
        buyers = list(DEFAULT_BUYERS_DATA["buyers"])
        settings["buyers"] = buyers
        save_settings(settings)
    return buyers

def get_buyer_aliases() -> dict:
    """Returns the dictionary of canonical buyer -> alias list from settings."""
    settings = load_settings()
    aliases = settings.get("buyer_aliases")
    if not aliases:
        aliases = {k: list(v) for k, v in DEFAULT_BUYERS_DATA["buyer_aliases"].items()}
        settings["buyer_aliases"] = aliases
        save_settings(settings)
    return aliases

def get_default_buyer() -> str:
    """Returns the default buyer name to use when none is specified on a receipt."""
    settings = load_settings()
    return settings.get("default_buyer", DEFAULT_BUYERS_DATA["default_buyer"])

def get_greens_buyers() -> list:
    """Returns the list of buyers considered part of Greens."""
    settings = load_settings()
    return settings.get("greens_buyers", DEFAULT_BUYERS_DATA["greens_buyers"])

def get_petty_cash_envelope_owners() -> list:
    """Returns the list of primary envelope owners for petty cash."""
    settings = load_settings()
    return settings.get("petty_cash_envelope_owners", DEFAULT_BUYERS_DATA["petty_cash_envelope_owners"])

def get_petty_cash_buyers() -> list:
    """Returns the list of buyers for petty cash dropdowns / completions."""
    settings = load_settings()
    petty_buyers = settings.get("petty_cash_buyers")
    if not petty_buyers:
        petty_buyers = [
            "LIAM COLE", "OSCAR FINCH", "TJ MORROW", "NOAH BELL",
            "SAM RIVERA", "OWEN PARK", "ELI VANCE", "DAN REID",
            "MAYA STONE", "LEO GRANT", "ZOE LANE", "IAN WEST",
            "OTHER"
        ]
        settings["petty_cash_buyers"] = petty_buyers
        save_settings(settings)
    return petty_buyers

def normalize_buyer_name(raw_name: str, default: str = None) -> str:
    """
    Standardizes raw buyer names, sticky notes, Expense/P-Card tags into a canonical buyer name
    using configured buyers and aliases from settings.
    """
    if not raw_name or not str(raw_name).strip():
        return default if default is not None else get_default_buyer()
        
    s = str(raw_name).strip().upper()
    s = re.sub(r'\b(EXPENSE|P\s*CARD|PCARD)\b', '', s).strip()
    s = re.sub(r'[\(\)\[\]\{\}\<\>\"\']', '', s).strip()
    s = ' '.join(s.split())
    
    if not s:
        return default if default is not None else get_default_buyer()

    aliases_dict = get_buyer_aliases()
    
    # 1. Exact canonical or alias match
    for canonical, alias_list in aliases_dict.items():
        if s == canonical.upper():
            return canonical
        for a in alias_list:
            if s == a.upper().strip():
                return canonical
                
    # 2. Check all alias pairs sorted by length descending (longest specific match first)
    all_alias_pairs = []
    for canonical, alias_list in aliases_dict.items():
        all_alias_pairs.append((canonical.upper(), canonical))
        for a in alias_list:
            all_alias_pairs.append((a.upper().strip(), canonical))
    all_alias_pairs.sort(key=lambda x: len(x[0]), reverse=True)
    
    for alias_u, canonical in all_alias_pairs:
        pattern = rf'\b{re.escape(alias_u)}\b'
        if re.search(pattern, s):
            return canonical

    # 3. Check buyers list directly
    buyers = get_buyers()
    for b in buyers:
        if s == b.upper():
            return b

    # 4. Fallback: return cleaned string
    return s

def is_greens_buyer(buyer_name: str) -> bool:
    """Returns True if the buyer is classified as a Greens team member."""
    if not buyer_name:
        return False
    b_upper = str(buyer_name).strip().upper()
    greens = [g.strip().upper() for g in get_greens_buyers()]
    return any(g in b_upper or b_upper in g for g in greens if len(g) >= 2)

def get_expense_buyer_tokens() -> dict:
    """
    Returns mapping of canonical buyer -> list of token strings for Expense transaction matching.
    """
    aliases_dict = get_buyer_aliases()
    result = {}
    for canonical, alias_list in aliases_dict.items():
        tokens = set()
        for a in [canonical] + alias_list:
            for part in re.sub(r'[^A-Z]', ' ', a.upper()).split():
                if len(part) >= 2:
                    tokens.add(part)
        result[canonical] = list(tokens)
    return result

def save_buyer_settings(buyers: list = None, aliases: dict = None, default_buyer: str = None, greens_buyers: list = None, envelope_owners: list = None, petty_cash_buyers: list = None):
    """Saves updated buyers and aliases into settings.json."""
    settings = load_settings()
    if buyers is not None:
        settings["buyers"] = buyers
    if aliases is not None:
        settings["buyer_aliases"] = aliases
    if default_buyer is not None:
        settings["default_buyer"] = default_buyer
    if greens_buyers is not None:
        settings["greens_buyers"] = greens_buyers
    if envelope_owners is not None:
        settings["petty_cash_envelope_owners"] = envelope_owners
    if petty_cash_buyers is not None:
        settings["petty_cash_buyers"] = petty_cash_buyers
    save_settings(settings)

