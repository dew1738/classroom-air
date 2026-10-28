#!/usr/bin/env python3
"""ESP32를 파이 USB에 꽂았을 때, 시리얼로 들어오는 "DATA {json}" 줄을 server.py로 넘긴다.

학교 Wi-Fi처럼 기기끼리 통신이 막힌 네트워크에서 Wi-Fi 전송 대신 쓰는 경로다.
외부 라이브러리 없이 동작한다 (pyserial 불필요: USB CDC 장치는 파일처럼 읽힌다).
"""

import glob
import json
import time
import urllib.request
from datetime import datetime

SERVER_URL = "http://127.0.0.1:5000/api/data"


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')}  {msg}", flush=True)


def find_port():
    ports = sorted(glob.glob("/dev/ttyACM*"))
    return ports[0] if ports else None


def forward(payload):
    req = urllib.request.Request(SERVER_URL, data=payload.encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status


def run():
    while True:
        port = find_port()
        if not port:
            time.sleep(5)  # ESP32가 꽂힐 때까지 대기
            continue
        log(f"연결: {port}")
        try:
            with open(port, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("DATA "):
                        continue
                    payload = line[5:]
                    try:
                        json.loads(payload)  # 깨진 줄은 건너뛴다
                        log(f"전달 {forward(payload)}  {payload}")
                    except Exception as e:
                        log(f"[건너뜀] {e!r}  {payload}")
        except OSError as e:
            log(f"[재시도] {e!r}")  # 케이블 분리 등 → 잠시 후 다시 연다
        time.sleep(3)


if __name__ == "__main__":
    run()
