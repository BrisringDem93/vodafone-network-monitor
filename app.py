"""Loopback-only dashboard for Vodafone Network Monitor."""
import csv
import datetime as dt
import io
import json
import os
import secrets
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from monitor import Monitor, Store, database_path, now, window_metrics

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
STORE = Store(database_path())
MONITOR = Monitor(STORE)
MAX_BODY = 8 * 1024 * 1024


def parse_time(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Il fuso orario è obbligatorio")
    return result.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds")


def interval(params):
    end = parse_time(params.get("end", [now()])[0])
    start = parse_time(params.get("start", [(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()])[0])
    if start > end:
        raise ValueError("Intervallo non valido")
    return start, end


def data(start, end):
    with STORE.connect() as db:
        rows = [dict(x) for x in db.execute(
            "SELECT * FROM measurements WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp", (start, end))]
        events = [dict(x) for x in db.execute(
            "SELECT * FROM station_events WHERE imported_at BETWEEN ? AND ? ORDER BY imported_at", (start, end))]
        anomalies = [dict(x) for x in db.execute(
            "SELECT * FROM anomalies WHERE started_at <= ? AND (ended_at IS NULL OR ended_at >= ?) ORDER BY started_at", (end, start))]
    return rows, events, anomalies


def export_zip(start, end):
    rows, events, anomalies = data(start, end)
    output = io.BytesIO()
    # Only explicitly safe fields are exported. Free text and identifiers are never exported.
    fields = ("timestamp", "source", "band", "channel", "link_mbps", "signal_percent",
              "rssi_dbm", "gateway_ms", "internet1_ms", "internet2_ms")
    safe_band = {"2.4 GHz", "5 GHz", "6 GHz", "2,4 GHz"}
    csv_file = io.StringIO(newline="")
    writer = csv.DictWriter(csv_file, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        safe = {key: row[key] for key in fields}
        safe["source"] = "windows_netsh_ping"
        safe["band"] = safe["band"] if safe["band"] in safe_band else ""
        safe["channel"] = safe["channel"] if str(safe["channel"]).isdigit() else ""
        writer.writerow(safe)
    sanitized = []
    for event in events:
        clean = {"imported_at": event["imported_at"], "source": "manual_json"}
        # Arbitrary Station text may include secrets, even without recognizable labels.
        clean["event"] = {key: "[REDACTED]" for key in ("date", "time", "category", "logdetails", "error")}
        sanitized.append(clean)
    safe_anomalies = [{"kind": item["kind"], "started_at": item["started_at"],
                       "ended_at": item["ended_at"], "metrics": json.loads(item["details"])}
                      for item in anomalies]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("measurements.csv", csv_file.getvalue())
        archive.writestr("station_events.json", json.dumps(sanitized, indent=2, ensure_ascii=False))
        archive.writestr("anomalies.json", json.dumps(safe_anomalies, indent=2))
        archive.writestr("technical.json", json.dumps({"band_channel": "See measurements.csv",
                                                       "adapter_driver": "Not collected to avoid identifying information"}, indent=2))
        archive.writestr("README.txt", "UTC timestamps. Measurements are probes, not throughput.\n"
                         "Station events are indexed by import time; all original values are redacted "
                         "because free text can contain secrets. Originals remain in the local database.\n"
                         "Review the archive before sharing. Missing values mean unavailable.\n")
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def valid_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def send(self, body, content_type, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def json(self, value, status=200):
        self.send(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def do_GET(self):
        if not self.valid_host():
            self.send(b"Forbidden", "text/plain", 403)
            return
        url = urlsplit(self.path)
        try:
            if url.path == "/":
                page = (ROOT / "dashboard.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                self.send(page.encode(), "text/html; charset=utf-8")
            elif url.path == "/dashboard.js":
                self.send((ROOT / "dashboard.js").read_bytes(), "text/javascript; charset=utf-8")
            elif url.path == "/api/data":
                start, end = interval(parse_qs(url.query))
                rows, events, anomalies = data(start, end)
                with STORE.connect() as db:
                    last_import = db.execute("SELECT MAX(imported_at) FROM station_events").fetchone()[0]
                self.json({"measurements": rows, "events": events, "anomalies": anomalies,
                           "metrics": {key: window_metrics(rows, key) for key in ("gateway_ms", "internet1_ms", "internet2_ms")},
                           "last_import": last_import, "running": MONITOR.running(),
                           "error": MONITOR.error, "config": STORE.get_config()})
            elif url.path == "/api/export":
                start, end = interval(parse_qs(url.query))
                self.send(export_zip(start, end), "application/zip", extra={"Content-Disposition": 'attachment; filename="diagnostica.zip"'})
            else:
                self.send(b"Not found", "text/plain", 404)
        except (ValueError, OverflowError):
            self.json({"error": "Intervallo non valido"}, 400)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if (not self.valid_host() or origin != f"http://127.0.0.1:{self.server.server_port}"
                or not secrets.compare_digest(self.headers.get("X-Monitor-Token", ""), TOKEN)):
            self.send(b"Forbidden", "text/plain", 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0 or size > MAX_BODY:
                raise ValueError("File troppo grande")
            payload = json.loads(self.rfile.read(size) or b"{}")
            if self.path == "/api/start":
                MONITOR.start()
                result = {"ok": True}
            elif self.path == "/api/stop":
                MONITOR.stop()
                result = {"ok": True}
            elif self.path == "/api/config":
                if not isinstance(payload, dict):
                    raise ValueError("Configurazione non valida")
                STORE.set_config(payload)
                result = {"ok": True}
            elif self.path == "/api/import":
                result = {"added": STORE.import_events(payload)}
            elif self.path == "/api/shutdown":
                MONITOR.stop()
                self.json({"ok": True})
                self.wfile.flush()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                self.send(b"Not found", "text/plain", 404)
                return
            self.json(result)
        except (ValueError, TypeError, RecursionError, UnicodeDecodeError):
            self.json({"error": "Richiesta o JSON non valido"}, 400)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    MONITOR.start()
    webbrowser.open("http://127.0.0.1:8765/")
    try:
        server.serve_forever()
    finally:
        MONITOR.stop()
        server.server_close()


if __name__ == "__main__":
    main()
