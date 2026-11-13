"""Local network sampling and persistent storage."""
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def database_path():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    path = base / "VodafoneNetworkMonitor"
    path.mkdir(parents=True, exist_ok=True)
    return path / "history.sqlite3"


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, source TEXT NOT NULL,
                    device TEXT, ssid TEXT, bssid TEXT, band TEXT, channel TEXT,
                    link_mbps REAL, signal_percent REAL, rssi_dbm REAL,
                    gateway_ms REAL, internet1_ms REAL, internet2_ms REAL, raw_wifi TEXT
                );
                CREATE TABLE IF NOT EXISTS station_events (
                    fingerprint TEXT PRIMARY KEY, imported_at TEXT NOT NULL,
                    source TEXT NOT NULL, event_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,
                    ended_at TEXT, details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS configuration (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def get_config(self):
        result = {"latency_ms": 100.0, "signal_percent": 30.0}
        with self.connect() as db:
            for row in db.execute("SELECT key, value FROM configuration"):
                if row["key"] in result:
                    result[row["key"]] = float(row["value"])
        return result

    def set_config(self, values):
        allowed = {"latency_ms": (1, 60000), "signal_percent": (0, 100)}
        updates = []
        for key, value in values.items():
            if key not in allowed:
                raise ValueError("Impostazione sconosciuta")
            value = float(value)
            if not allowed[key][0] <= value <= allowed[key][1]:
                raise ValueError("Soglia non valida")
            updates.append((key, str(value)))
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO configuration VALUES (?, ?)", updates)

    def add_measurement(self, sample):
        fields = ("timestamp", "source", "device", "ssid", "bssid", "band", "channel",
                  "link_mbps", "signal_percent", "rssi_dbm", "gateway_ms",
                  "internet1_ms", "internet2_ms", "raw_wifi")
        config = self.get_config()
        flags = {
            "gateway_unreachable": sample.get("gateway_ms") is None,
            "internet_unreachable": sample.get("internet1_ms") is None and sample.get("internet2_ms") is None,
            "gateway_latency": sample.get("gateway_ms") is not None and sample["gateway_ms"] > config["latency_ms"],
            "weak_signal": sample.get("signal_percent") is not None and sample["signal_percent"] < config["signal_percent"],
        }
        with self.connect() as db:
            db.execute("INSERT INTO measurements (%s) VALUES (%s)" %
                       (",".join(fields), ",".join("?" for _ in fields)),
                       [sample.get(field) for field in fields])
            for kind, active in flags.items():
                existing = db.execute("SELECT id FROM anomalies WHERE kind=? AND ended_at IS NULL", (kind,)).fetchone()
                if active and not existing:
                    db.execute("INSERT INTO anomalies (kind,started_at,details) VALUES (?,?,?)",
                               (kind, sample["timestamp"], json.dumps({"gateway_ms": sample.get("gateway_ms"),
                                                                      "signal_percent": sample.get("signal_percent")})))
                elif not active and existing:
                    db.execute("UPDATE anomalies SET ended_at=? WHERE id=?", (sample["timestamp"], existing["id"]))

    def close_anomalies(self):
        with self.connect() as db:
            db.execute("UPDATE anomalies SET ended_at=? WHERE ended_at IS NULL", (now(),))

    def import_events(self, document, source="manual_json"):
        # Preserve every recognizable record; the endpoint's enclosing schema is not known.
        records = []
        def visit(value):
            if isinstance(value, dict):
                if "logdetails" in value and any(k in value for k in ("date", "time", "category", "error")):
                    records.append(value)
                else:
                    for child in value.values():
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(document)
        if not records:
            raise ValueError("Nessun evento riconoscibile nel JSON")
        added = 0
        with self.connect() as db:
            for record in records:
                raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                added += db.execute("INSERT OR IGNORE INTO station_events VALUES (?,?,?,?)",
                                    (fingerprint, now(), source, raw)).rowcount
        return added


def run_command(args, timeout=3):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # Windows utilities normally use the console code page.
        return result.stdout.decode("oem" if os.name == "nt" else "utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def wifi_info(text):
    """Parse recognizable netsh fields without treating signal percentage as dBm."""
    data = {"raw_wifi": text}
    aliases = {
        "name": "device", "nome": "device", "ssid": "ssid", "bssid": "bssid",
        "channel": "channel", "canale": "channel", "band": "band", "banda": "band",
        "signal": "signal_percent", "segnale": "signal_percent",
        "receive rate (mbps)": "link_mbps", "velocità ricezione (mbps)": "link_mbps",
    }
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        field = aliases.get(key.strip().lower())
        if field and field not in data:
            value = value.strip()
            if field in ("signal_percent", "link_mbps"):
                match = re.search(r"\d+(?:[.,]\d+)?", value)
                value = float(match.group().replace(",", ".")) if match else None
            data[field] = value
    return data


def ping(host):
    if os.name != "nt":
        return None
    output = run_command(["ping", "-n", "1", "-w", "1000", host], timeout=2)
    # Both English and Italian output contain time= / tempo=.
    match = re.search(r"(?:time|tempo)\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", output, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def collect():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        wifi = executor.submit(run_command, ["netsh", "wlan", "show", "interfaces"]) if os.name == "nt" else None
        targets = [executor.submit(ping, host) for host in ("192.168.1.1", "1.1.1.1", "8.8.8.8")]
        sample = wifi_info(wifi.result()) if wifi else {}
        sample.update(zip(("gateway_ms", "internet1_ms", "internet2_ms"), (f.result() for f in targets)))
    sample.update(timestamp=now(), source="windows_netsh_ping")
    return sample


def window_metrics(rows, field):
    values = [row[field] for row in rows]
    valid = [value for value in values if value is not None]
    # Jitter uses consecutive successful probes only; missing probes break the sequence.
    deltas = [abs(b - a) for a, b in zip(values, values[1:]) if a is not None and b is not None]
    return {"loss_percent": 100 * (len(values) - len(valid)) / len(values) if values else None,
            "latency_ms": sum(valid) / len(valid) if valid else None,
            "jitter_ms": sum(deltas) / len(deltas) if deltas else None}


class Monitor:
    def __init__(self, store):
        self.store = store
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.error = None
        # An application restart ends an interrupted anomaly at the last known sample.
        with self.store.connect() as db:
            last = db.execute("SELECT MAX(timestamp) FROM measurements").fetchone()[0]
            db.execute("UPDATE anomalies SET ended_at=COALESCE(?, started_at) WHERE ended_at IS NULL", (last,))

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stop_event.set()
            thread = self.thread
        if thread:
            thread.join(timeout=8)

    def _run(self):
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                try:
                    self.store.add_measurement(collect())
                    self.error = None
                except Exception as exc:
                    self.error = str(exc)
                self.stop_event.wait(max(0, 2 - (time.monotonic() - started)))
        finally:
            self.store.close_anomalies()

    def running(self):
        return bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set())
