import tempfile
import unittest
from pathlib import Path

from monitor import Store, wifi_info, window_metrics


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_wifi_percent_is_not_dbm(self):
        result = wifi_info("    Name : Wi-Fi\n    SSID : home\n    BSSID : aa:bb:cc:dd:ee:ff\n    Signal : 75%\n    Channel : 6\n")
        self.assertEqual(result["ssid"], "home")
        self.assertEqual(result["bssid"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(result["signal_percent"], 75)
        self.assertNotIn("rssi_dbm", result)

    def test_loss_and_jitter(self):
        rows = [{"ping": x} for x in (10, 20, None, 50, 60)]
        metrics = window_metrics(rows, "ping")
        self.assertEqual(metrics["loss_percent"], 20)
        self.assertEqual(metrics["jitter_ms"], 10)
        self.assertEqual(metrics["latency_ms"], 35)

    def test_import_preserves_and_deduplicates(self):
        event = {"date": "2026-01-01", "time": "12:00", "logdetails": "WAN", "error": 1}
        self.assertEqual(self.store.import_events({"events": [event]}), 1)
        self.assertEqual(self.store.import_events({"events": [event]}), 0)
        with self.store.connect() as db:
            self.assertIn('"error":1', db.execute("SELECT event_json FROM station_events").fetchone()[0])

    def test_anomaly_opens_and_closes(self):
        sample = {"timestamp": "2026-01-01T00:00:00+00:00", "source": "test",
                  "gateway_ms": None, "internet1_ms": 20, "internet2_ms": 30}
        self.store.add_measurement(sample)
        sample.update(timestamp="2026-01-01T00:00:02+00:00", gateway_ms=10)
        self.store.add_measurement(sample)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM anomalies WHERE kind='gateway_unreachable'").fetchone()
            self.assertEqual(row["ended_at"], sample["timestamp"])


if __name__ == "__main__":
    unittest.main()
