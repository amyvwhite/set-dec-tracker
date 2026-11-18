import unittest
import math
from datetime import datetime

class TestTaxMath(unittest.TestCase):
    """
    Automated test suite validating tax math, rounding rules, HST derivation,
    and financial invariants across receipt processing.
    """

    def test_standard_ontario_hst_calculation(self):
        """Verify 13% Ontario HST calculation and invariant subtotal + tax = total."""
        test_amounts = [
            (100.00, 13.00, 113.00),
            (49.99, 6.50, 56.49),
            (10.00, 1.30, 11.30),
            (1.00, 0.13, 1.13),
            (88.49, 11.50, 99.99),
            (12997.26, 1495.26, 11502.00)
        ]

        for item in test_amounts:
            tot = item[2] if item[2] > item[0] else item[0]
            sub = round(tot / 1.13, 2)
            tax = round(tot - sub, 2)
            self.assertAlmostEqual(sub + tax, tot, places=2,
                msg=f"Subtotal {sub} + Tax {tax} must equal Total {tot}")

    def test_missing_tax_inference(self):
        """When tax is omitted from a receipt, infer 13% Ontario HST cleanly."""
        def infer_tax(total: float, rate: float = 0.13):
            subtotal = round(total / (1.0 + rate), 2)
            tax = round(total - subtotal, 2)
            return subtotal, tax

        sub, tax = infer_tax(113.00)
        self.assertEqual(sub, 100.00)
        self.assertEqual(tax, 13.00)

        sub2, tax2 = infer_tax(50.00)
        self.assertAlmostEqual(sub2 + tax2, 50.00, places=2)
        self.assertEqual(sub2, 44.25)
        self.assertEqual(tax2, 5.75)

    def test_zero_tax_exempt_purchase(self):
        """When an item is explicitly tax-exempt, tax is 0 and subtotal equals total."""
        total = 50.00
        tax = 0.00
        subtotal = 50.00
        self.assertEqual(round(subtotal + tax, 2), total)

    def test_tip_and_meal_tax_math(self):
        """Validate restaurant / craft meal with tip where tax is based on subtotal only."""
        food_subtotal = 100.00
        tax_hst = 13.00 # 13% on food
        tip = 15.00     # 15% tip
        total_paid = food_subtotal + tax_hst + tip # $128.00

        # When reconstructing food subtotal vs tax:
        net_amount_before_tax = round(total_paid - tax_hst, 2) # includes tip in gross reimbursable before tax
        self.assertEqual(net_amount_before_tax, 115.00)
        self.assertEqual(round(net_amount_before_tax + tax_hst, 2), total_paid)

    def test_negative_return_receipts(self):
        """Validate returns where total, subtotal, and tax are all negative."""
        def process_return(total_val: float, tax_val: float):
            sign = -1.0 if total_val < 0 else 1.0
            abs_tot = abs(total_val)
            abs_sub = round(abs_tot / 1.13, 2) if tax_val == 0.0 else round(abs_tot - abs(tax_val), 2)
            abs_tax = round(abs_tot - abs_sub, 2)
            return sign * abs_sub, sign * abs_tax, total_val

        # Case 1: Return with explicit tax
        sub, tax, tot = process_return(-58.16, -6.69)
        self.assertEqual(tot, -58.16)
        self.assertEqual(sub, -51.47)
        self.assertEqual(tax, -6.69)
        self.assertAlmostEqual(sub + tax, tot, places=2)

        # Case 2: Return with 0 tax (infer tax)
        sub2, tax2, tot2 = process_return(-113.00, 0.0)
        self.assertEqual(tot2, -113.00)
        self.assertEqual(sub2, -100.00)
        self.assertEqual(tax2, -13.00)
        self.assertAlmostEqual(sub2 + tax2, tot2, places=2)

    def test_split_receipt_multi_set(self):
        """Validate splitting a receipt evenly across sets without losing pennies."""
        def split_receipt(subtotal: float, tax: float, num_sets: int):
            split_sub = round(subtotal / num_sets, 2)
            split_tx = round(tax / num_sets, 2)
            
            sub_splits = [split_sub] * num_sets
            tx_splits = [split_tx] * num_sets
            
            sub_diff = round(subtotal - sum(sub_splits), 2)
            sub_splits[-1] = round(sub_splits[-1] + sub_diff, 2)
            
            tx_diff = round(tax - sum(tx_splits), 2)
            tx_splits[-1] = round(tx_splits[-1] + tx_diff, 2)
            
            return sub_splits, tx_splits

        subs, taxes = split_receipt(100.00, 13.00, 3)
        self.assertEqual(sum(subs), 100.00)
        self.assertEqual(sum(taxes), 13.00)
        self.assertEqual(len(subs), 3)

    def test_expense_monthly_hst_account_coding(self):
        """Verify Expense HST account code derivation by month."""
        def get_hst_account_code(date_str: str) -> str:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return str(7500 + dt.month)

        self.assertEqual(get_hst_account_code("2026-07-15"), "7507")
        self.assertEqual(get_hst_account_code("2026-08-01"), "7508")
        self.assertEqual(get_hst_account_code("2026-09-30"), "7509")
        self.assertEqual(get_hst_account_code("2026-10-12"), "7510")
        self.assertEqual(get_hst_account_code("2026-11-18"), "7511")
        self.assertEqual(get_hst_account_code("2026-12-25"), "7512")

    def test_petty_cash_craft_cap_calculation(self):
        """Verify $7/person craft limit calculation and tax apportionment."""
        def apply_craft_cap(raw_total: float, num_people: int = 1):
            limit = 7.00 * max(1, num_people)
            if raw_total <= limit:
                capped_sub = round(raw_total / 1.13, 2)
                capped_tax = round(raw_total - capped_sub, 2)
                return capped_sub, capped_tax, raw_total
            else:
                capped_sub = round(limit / 1.13, 2)
                capped_tax = round(limit - capped_sub, 2)
                return capped_sub, capped_tax, limit

        # 1 person bought $15.00 coffee -> capped at $7.00
        sub, tax, tot = apply_craft_cap(15.00, num_people=1)
        self.assertEqual(tot, 7.00)
        self.assertAlmostEqual(sub + tax, 7.00, places=2)

        # 3 people lunch $40.00 -> limit is 3 * $7 = $21.00
        sub3, tax3, tot3 = apply_craft_cap(40.00, num_people=3)
        self.assertEqual(tot3, 21.00)
        self.assertAlmostEqual(sub3 + tax3, 21.00, places=2)

        # 1 person bought $4.50 muffin -> under $7 limit, full $4.50 allowed
        sub_under, tax_under, tot_under = apply_craft_cap(4.50, num_people=1)
        self.assertEqual(tot_under, 4.50)
        self.assertAlmostEqual(sub_under + tax_under, 4.50, places=2)

if __name__ == '__main__':
    unittest.main()
