import unittest
import os
import requests
import time
from services.mobile_scanner_server import get_scanner_server, get_destination_paths

class TestMobileScanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = get_scanner_server(port=5899)
        cls.server.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_status_endpoint(self):
        url = f"http://127.0.0.1:{self.server.port}/api/status"
        res = requests.get(url, timeout=5)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("local_ip", data)

    def test_upload_general(self):
        url = f"http://127.0.0.1:{self.server.port}/api/upload"
        files = {
            'files': ('test_mobile_general.jpg', b'TEST_RECEIPT_CONTENT_GENERAL', 'image/jpeg')
        }
        data = {
            'destination': 'general',
            'buyer': 'AMY'
        }
        res = requests.post(url, data=data, files=files, timeout=5)
        self.assertEqual(res.status_code, 200)
        resp_data = res.json()
        self.assertEqual(resp_data["status"], "success")
        self.assertEqual(resp_data["count"], 1)

        # Verify file exists on disk in Input folder
        paths = get_destination_paths()
        saved_filename = resp_data["files"][0]
        full_path = os.path.join(paths["general"], saved_filename)
        self.assertTrue(os.path.exists(full_path))
        self.assertTrue(saved_filename.startswith("AMY_"))

        # Clean up test file
        if os.path.exists(full_path):
            os.remove(full_path)

    def test_upload_petty_cash(self):
        url = f"http://127.0.0.1:{self.server.port}/api/upload"
        files = {
            'files': ('test_mobile_petty.jpg', b'TEST_RECEIPT_CONTENT_PETTY', 'image/jpeg')
        }
        data = {
            'destination': 'petty_cash',
            'buyer': 'JORDAN'
        }
        res = requests.post(url, data=data, files=files, timeout=5)
        self.assertEqual(res.status_code, 200)
        resp_data = res.json()
        self.assertEqual(resp_data["status"], "success")

        # Verify file exists on disk in petty cash input folder
        paths = get_destination_paths()
        saved_filename = resp_data["files"][0]
        full_path = os.path.join(paths["petty_cash"], saved_filename)
        self.assertTrue(os.path.exists(full_path))
        self.assertTrue(saved_filename.startswith("JORDAN_"))

        # Clean up test file
        if os.path.exists(full_path):
            os.remove(full_path)

    def test_exposure_enhancement(self):
        from services.mobile_scanner_server import enhance_receipt_image
        from PIL import Image, ImageStat
        import tempfile

        # Create a dim/gray test image
        temp_img_path = os.path.join(tempfile.gettempdir(), "test_dim_receipt.jpg")
        img = Image.new('RGB', (100, 100), color=(120, 120, 120))
        img.save(temp_img_path, 'JPEG')

        stat_before = ImageStat.Stat(Image.open(temp_img_path).convert('L'))
        lum_before = stat_before.mean[0]

        # Enhance exposure
        enhanced = enhance_receipt_image(temp_img_path, exposure_mode='high')
        self.assertTrue(enhanced)

        stat_after = ImageStat.Stat(Image.open(temp_img_path).convert('L'))
        lum_after = stat_after.mean[0]

        # Verify luminance is boosted significantly
        self.assertGreater(lum_after, lum_before)

        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)

if __name__ == '__main__':
    unittest.main()
