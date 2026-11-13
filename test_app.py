import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import app
from monitor import Store


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")
        self.patcher = patch.object(app, "STORE", self.store)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_export_removes_unrecognized_secrets(self):
        self.store.import_events({"logdetails": "****** 8.8.8.8", "date": "2026-01-01",
                                  "unknown-secret-key": "private-token-784513", "error": 1})
        self.store.add_measurement({"timestamp": app.now(), "source": "test", "ssid": "private-ssid",
                                    "bssid": "aa:bb:cc:dd:ee:ff", "gateway_ms": 3,
                                    "internet1_ms": 10, "internet2_ms": 11})
        content = app.export_zip("2000-01-01", "9999-12-31")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            all_files = b"".join(archive.read(name) for name in archive.namelist())
        for secret in (b"private-token-784513", b"unknown-secret-key", b"private-ssid", b"aa:bb:cc:dd:ee:ff", b"8.8.8.8"):
            self.assertNotIn(secret, all_files)

    def test_host_and_csrf_protection(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            bad_host = urllib.request.Request(url + "/", headers={"Host": "attacker.example"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(bad_host)
            self.assertEqual(error.exception.code, 403)
            req = urllib.request.Request(url + "/api/config", data=b"{}", headers={"Origin": "http://attacker.example", "X-Monitor-Token": app.TOKEN})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code, 403)
            with urllib.request.urlopen(url + "/api/data") as response:
                self.assertIn("measurements", json.load(response))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_shutdown_returns_response_before_server_stops(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            req = urllib.request.Request(url + "/api/shutdown", data=b"{}",
                                         headers={"Origin": url, "X-Monitor-Token": app.TOKEN})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(json.load(response), {"ok": True})
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        finally:
            if thread.is_alive():
                server.shutdown()
                thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
