"""Engine-level tests for TaxKernel.

Kept in ``unittest`` style on purpose (see IMPLEMENTATION_PLAN.md, decision D2):
existing suites stay ``unittest``; only new intelligence-layer tests are pytest-style.
"""

import datetime
import os
import tempfile
import unittest

import database
import tax_rules
import main
from main import app
from fastapi.testclient import TestClient

# These tests call clear_db(), which drops every table. Point the module at a
# throwaway database so the live ledger (taxkernel_prod.db) is never touched.
_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "taxkernel_test_engine.db")


def setUpModule():
    database.DB_PATH = _TEST_DB_PATH
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)
    database.init_db()


def tearDownModule():
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


class TestTaxKernel(unittest.TestCase):

    def setUp(self):
        # Initialize and clear DB before each test
        database.clear_db()
        self.client = TestClient(app)
        self.user_id = database.get_primary_user_id()
        self.client_id = 1  # default seed client
        self.fy_id = database.get_active_fy_id()
        main.ledger_state["state"] = "green"
        main.ledger_state["last_approval_hash"] = "None"

    def tearDown(self):
        # Clear database to leave clean slate
        database.clear_db()

    # -- helpers ---------------------------------------------------------

    def _add_invoice(self, vendor, amount, date, is_anomaly=False):
        return database.add_invoice(
            user_id=self.user_id,
            client_id=self.client_id,
            fy_id=self.fy_id,
            vendor=vendor,
            amount=amount,
            date=date,
            is_anomaly=is_anomaly,
        )

    # -- tests -----------------------------------------------------------

    def test_database_invoice_operations(self):
        # Verify initial state is empty
        invoices = database.get_invoices()
        self.assertEqual(len(invoices), 0)

        # Add invoice
        inv_id = self._add_invoice("Google LLC", 150000.0, "2026-07-15")
        self.assertIsNotNone(inv_id)

        # Verify retrieval (vendor/date are stored encrypted, decrypted on read)
        invoices = database.get_invoices()
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["vendor"], "Google LLC")
        self.assertEqual(invoices[0]["amount"], 150000.0)
        self.assertEqual(invoices[0]["is_anomaly"], 0)

    def test_anomaly_detection_rules(self):
        # Setup: add 2 past invoices for a vendor
        self._add_invoice("Apple App Store", 10000.0, "2026-06-01")
        self._add_invoice("Apple App Store", 12000.0, "2026-07-01")

        # Retrieve past invoices for the rule check
        past = database.get_invoices()

        # Test case 1: normal amount (no anomaly)
        is_anom_normal = tax_rules.check_anomaly("Apple App Store", 15000.0, past)
        self.assertFalse(is_anom_normal)

        # Test case 2: >2x vendor average (average = 11000, 2x = 22000)
        is_anom_unusual = tax_rules.check_anomaly("Apple App Store", 25000.0, past)
        self.assertTrue(is_anom_unusual)

    def test_44ada_tax_rules(self):
        # Test Case 1: Gross receipts below rebate limit
        # Rs 10 Lakh receipts = Rs 5 Lakh presumptive income -> New regime tax should be 0
        res = tax_rules.calculate_44ada_tax(1000000.0)
        self.assertEqual(res["presumptive_income"], 500000.0)
        self.assertEqual(res["new_regime_tax"], 0.0)
        self.assertFalse(res["limit_exceeded"])

        # Test Case 2: Rs 24 Lakh receipts = Rs 12 Lakh presumptive income
        # New regime slabs: 0-3L nil, 3-6L 5%, 6-9L 10%, 9-12L 15% -> 90,000 + 4% cess
        res = tax_rules.calculate_44ada_tax(2400000.0)
        self.assertEqual(res["presumptive_income"], 1200000.0)
        self.assertAlmostEqual(res["new_regime_tax"], 93600.0, places=2)
        self.assertIn(res["preferred_regime"], ("New Tax Regime", "Old Tax Regime"))
        self.assertFalse(res["limit_exceeded"])

        # Test Case 3: Exceeding 44ADA cash limit of Rs 75 Lakh
        res = tax_rules.calculate_44ada_tax(8000000.0)
        self.assertTrue(res["limit_exceeded"])

    def test_advance_tax_deadlines(self):
        # Estimated tax = Rs 1,00,000, mocked date July 2026
        # The next deadline should be Q2 (Sept 15) with 45% cumulative due
        mock_date = datetime.date(2026, 7, 18)
        adv = tax_rules.get_upcoming_advance_tax(100000.0, current_date=mock_date)

        self.assertEqual(adv["installment"], "Q2 (Sept 15)")
        self.assertEqual(adv["due_date"], "15-Sep-2026")
        self.assertEqual(adv["percent"], 45)
        self.assertEqual(adv["cumulative_due"], 45000.0)

    def test_server_invoice_endpoints(self):
        # Post first invoice
        payload = {"vendor": "Google", "amount": 500000.0, "date": "2026-07-18"}
        response = self.client.post("/invoice", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["total"], 500000.0)
        self.assertIsNotNone(data["invoice_id"])
        self.assertIsNotNone(data["merkle_root"])

        # Verify status endpoint updates
        status_res = self.client.get("/status")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["total"], 500000.0)
        self.assertEqual(status_data["invoice_count"], 1)
        self.assertEqual(status_data["ledger_state"], "green")

        # Post enough to cross GST Amber (80% of 20L = 16L)
        self.client.post("/invoice", json={"vendor": "Google", "amount": 1200000.0, "date": "2026-07-18"})
        status_res = self.client.get("/status")
        self.assertEqual(status_res.json()["ledger_state"], "amber")

        # Post enough to cross GST Limit (20L)
        self.client.post("/invoice", json={"vendor": "Google", "amount": 400000.0, "date": "2026-07-18"})
        status_res = self.client.get("/status")
        self.assertEqual(status_res.json()["ledger_state"], "red")

    def test_ledger_approvals_chain(self):
        before = database.get_approvals(self.user_id)

        # Perform approval post
        test_hash = "f1e2d3c4b5a697887766554433221100abcdef1234567890abcdef1234567890"
        response = self.client.post("/approve", json={"hash": test_hash})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["hash"], test_hash)

        # Verify DB chain
        approvals = database.get_approvals(self.user_id)
        self.assertEqual(len(approvals), len(before) + 1)
        # approvals are ordered desc, so index 0 is our new block
        self.assertEqual(approvals[0]["current_hash"], test_hash)
        self.assertEqual(approvals[0]["previous_hash"], before[0]["current_hash"] if before else "GENESIS")
        self.assertEqual(main.ledger_state["last_approval_hash"], test_hash)

    def test_agent_reasoning_and_voice(self):
        # Test agent reasoning endpoint returns source and explanation
        response = self.client.get("/agent-reasoning")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("source", data)
        self.assertIn("explanation", data)

        # Test voice entry parsing (spoken number, hyphenated tens)
        payload = {"text": "invoice from Upwork of seventy-five thousand rupees"}
        response = self.client.post("/voice-entry", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["parsed_vendor"], "Upwork")
        self.assertEqual(data["parsed_amount"], 75000.0)

        # Digits still take precedence
        response = self.client.post("/voice-entry", json={"text": "invoice from Upwork of 1,25,000 rupees"})
        self.assertEqual(response.json()["parsed_amount"], 125000.0)


if __name__ == "__main__":
    unittest.main()
