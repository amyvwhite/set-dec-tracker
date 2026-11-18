import unittest
import re
import os
import sys

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.settings import (
    normalize_buyer_name,
    is_greens_buyer,
    normalize_vendor_key,
    get_vendor_payment_pref,
    set_vendor_payment_pref,
    get_default_buyer
)

class TestReceiptParsing(unittest.TestCase):
    """
    Automated test suite validating receipt data parsing, currency extraction,
    vendor normalization, and buyer alias resolution from settings.
    """

    def parse_currency(self, val_str: str) -> float:
        """Helper to parse currency strings from receipts/OCR."""
        if val_str is None:
            return 0.0
        s = str(val_str).strip()
        if not s:
            return 0.0
        # Check negative parentheses: ($50.00) or (50.00)
        is_neg = False
        if '(' in s and ')' in s:
            is_neg = True
        elif '-' in s:
            is_neg = True
            
        clean_num = re.sub(r'[^0-9\.]', '', s)
        try:
            val = float(clean_num)
            return -val if is_neg else val
        except ValueError:
            return 0.0

    def test_currency_parsing(self):
        """Test parsing of various receipt currency formats."""
        self.assertEqual(self.parse_currency("$1,234.56"), 1234.56)
        self.assertEqual(self.parse_currency(" $ 45.99 "), 45.99)
        self.assertEqual(self.parse_currency("(50.00)"), -50.00)
        self.assertEqual(self.parse_currency("($1,000.00)"), -1000.00)
        self.assertEqual(self.parse_currency("-25.50"), -25.50)
        self.assertEqual(self.parse_currency("CAD 100.00"), 100.00)
        self.assertEqual(self.parse_currency(""), 0.0)
        self.assertEqual(self.parse_currency(None), 0.0)

    def test_buyer_alias_resolution(self):
        """Verify that buyer aliases from settings correctly resolve to canonical names."""
        test_cases = [
            ("RAVI KHAN", "RAVI"),
            ("Ravi", "RAVI"),
            ("ROWAN", "ROWAN"),
            ("ROWAN P CARD", "ROWAN"),
            ("ROWAN PCARD", "ROWAN"),
            ("Nick D", "NICK D"),
            ("Nikolas", "NICK D"),
            ("Nick Kova", "NICK D"),
            ("Sam Rivera", "SAM"),
            ("Samuel Rivera", "SAM"),
            ("NINA CLARK", "NINA"),
            ("Nina", "NINA"),
            ("Kyle Brandt", "BRANDT"),
            ("Brandt Expense", "BRANDT"),
            ("harlow", "MACDOUGALL"),
            ("Kyle Macdougall", "MACDOUGALL"),
            ("A.T.", "MILO"),
            ("Milo Taran", "MILO"),
            ("Eva Lund", "JAN"),
            ("Josh Varvoe", "JOSH VARCOE"),
            ("Liam Cole", "LIAM COLE"),
            ("Oscar Finch", "OSCAR FINCH"),
            ("", get_default_buyer()),
            (None, get_default_buyer())
        ]

        for raw_input, expected in test_cases:
            resolved = normalize_buyer_name(raw_input)
            self.assertEqual(resolved, expected,
                msg=f"Raw '{raw_input}' failed to normalize to '{expected}', got '{resolved}'")

    def test_greens_buyer_detection(self):
        """Test detection of Greens department buyers."""
        self.assertTrue(is_greens_buyer("JAN"))
        self.assertTrue(is_greens_buyer("Eva Lund"))
        self.assertTrue(is_greens_buyer("MILO"))
        self.assertTrue(is_greens_buyer("Milo"))
        self.assertFalse(is_greens_buyer("JORDAN"))
        self.assertFalse(is_greens_buyer("NINA"))
        self.assertFalse(is_greens_buyer("SAM"))
        self.assertFalse(is_greens_buyer(""))
        self.assertFalse(is_greens_buyer(None))

    def test_vendor_normalization(self):
        """Test vendor name key normalization."""
        v1 = normalize_vendor_key("ALLEN GALLERY ART SALES & RENTALS INC.")
        self.assertIn("ALLEN GALLERY ART SALES", v1)
        self.assertNotIn("INC", v1.split())

        v2 = normalize_vendor_key("SUPA HOLDINGS dba ALLEN GALLERY")
        self.assertEqual(v2, "ALLEN GALLERY")

        v3 = normalize_vendor_key("THE HOME DEPOT #7115")
        self.assertIn("HOME DEPOT", v3)

    def test_vendor_payment_preferences(self):
        """Test remembering and retrieving vendor payment preferences (ACH vs CHQ)."""
        test_vendor = "TEST UNIQUE VENDOR XYZ"
        set_vendor_payment_pref(test_vendor, "ACH")
        pref = get_vendor_payment_pref(test_vendor)
        self.assertEqual(pref, "ACH")

        # Test case-insensitivity and substring matching
        pref_lower = get_vendor_payment_pref("test unique vendor xyz")
        self.assertEqual(pref_lower, "ACH")

if __name__ == '__main__':
    unittest.main()
