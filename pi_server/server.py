#!/usr/bin/env python3
"""ESP32가 보낸 센서값을 받아 env_data.csv에 쌓고, 대시보드를 서빙한다.

  POST /api/data   ESP32 → JSON 한 건 저장
  GET  /api/data   최근 데이터 (JSON, ?hours=24)
  GET  /data.csv   전체 CSV 다운로드
  GET  /           대시보드 (dashboard.html)

외부 라이브러리 없이 파이썬 표준 라이브러리만 사용한다.
"""

import csv
import json
import os
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "env_data.csv")
DASHBOARD_PATH = os.path.join(BASE_DIR, "dashboard.html")
PORT = 5000

FIELDS = ["timestamp", "device", "temp_c", "humidity", "pressure_hpa",
          "gas_kohm", "co2_ppm", "scd_temp_c", "scd_humidity"]

write_lock = threading.Lock()


def append_row(row):
    with write_lock:
        write_header = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)


def read_rows(hours):
    if not os.path.exists(CSV_PATH):
        return []
    since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    with open(CSV_PATH, newline="") as f:
        return [r for r in csv.DictReader(f) if r["timestamp"] >= since]


class Handler(BaseHTTPRequestHandler):
    def send_body(self, code, body, content_type):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if urlparse(self.path).path != "/api/data":
            return self.send_body(404, "not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
            row = {k: payload.get(k, "") for k in FIELDS}
            row["timestamp"] = datetime.now().isoformat(timespec="seconds")  # 시각은 파이 기준
            append_row(row)
            print(f"{row['timestamp']}  {row['device']}  CO2 {row['co2_ppm']}  T {row['temp_c']}", flush=True)
            self.send_body(200, '{"ok":true}', "application/json")
        except Exception as e:
            self.send_body(400, json.dumps({"ok": False, "error": repr(e)}), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/data":
            hours = float(parse_qs(url.query).get("hours", ["24"])[0])
            self.send_body(200, json.dumps(read_rows(hours)), "application/json")
        elif url.path == "/data.csv":
            body = open(CSV_PATH, "rb").read() if os.path.exists(CSV_PATH) else b""
            self.send_body(200, body, "text/csv; charset=utf-8")
        elif url.path in ("/", "/index.html"):
            self.send_body(200, open(DASHBOARD_PATH, "rb").read(), "text/html; charset=utf-8")
        else:
            self.send_body(404, "not found", "text/plain")

    def log_message(self, *args):
        pass  # 요청마다 찍히는 기본 로그는 끈다


if __name__ == "__main__":
    print(f"서버 시작: http://0.0.0.0:{PORT}  → {CSV_PATH}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
