import unittest
import sqlite3
import os
import tempfile
from core.database import (
    init_db,
    queue_offline_receipt,
    get_offline_queue,
    remove_from_offline_queue,
    get_offline_queue_count,
    get_connection,
    insert_receipt
)
from core.models import Receipt

class TestOfflineQueue(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_queue_and_retrieve_receipt(self):
        # Create a mock receipt
        receipt = Receipt(
            vendor="TEST VENDOR OFFLINE",
            total=123.45,
            subtotal=109.25,
            tax=14.20,
            set_number="J22",
            date="11/18/2026",
            status="APPROVED",
            file_path="C:/dummy/test_offline.pdf",
            file_hash="mockhashoffline123"
        )
        insert_receipt(receipt)
        saved_id = receipt.id
        self.assertIsNotNone(saved_id)

        # Queue it for offline sync
        initial_count = get_offline_queue_count()
        queue_id = queue_offline_receipt(saved_id, action="APPEND", error_message="getaddrinfo failed")
        self.assertIsNotNone(queue_id)
        self.assertEqual(get_offline_queue_count(), initial_count + 1)

        # Retrieve items
        queue = get_offline_queue()
        matching = [item for item in queue if item['receipt_id'] == saved_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['action'], "APPEND")
        self.assertIn("getaddrinfo", matching[0]['error_message'])
        self.assertEqual(matching[0]['receipt'].vendor, "TEST VENDOR OFFLINE")

        # Cleanup: remove from queue and db
        remove_from_offline_queue(matching[0]['queue_id'])
        self.assertEqual(get_offline_queue_count(), initial_count)

        conn = get_connection()
        conn.execute("DELETE FROM receipts WHERE id = ?", (saved_id,))
        conn.commit()
        conn.close()

if __name__ == '__main__':
    unittest.main()
