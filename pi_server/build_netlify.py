#!/usr/bin/env python3
"""env_data.csv를 dashboard.html에 넣어 Netlify용 단일 index.html을 만든다.

파이 대시보드는 /api/data에서 실시간으로 값을 가져오지만, Netlify에는 파이가 없으므로
데이터를 HTML 안에 직접 넣는다 (노션 안내: "데이터 포함 단일 HTML로 다시 생성").

사용법: python3 build_netlify.py [CSV경로] [출력폴더]
"""

import csv
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
csv_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "env_data.csv")
out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE_DIR, "dashboard")

with open(csv_path, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

template = open(os.path.join(BASE_DIR, "dashboard.html"), encoding="utf-8").read()
marker = "const EMBEDDED_DATA = null;"
if marker not in template:
    sys.exit("dashboard.html에서 EMBEDDED_DATA 자리를 찾지 못했습니다.")
html = template.replace(marker, "const EMBEDDED_DATA = " + json.dumps(rows, ensure_ascii=False) + ";")

# 그래프 라이브러리를 CDN 대신 파일 안에 넣는다 → 학교망 차단·오프라인에서도 열린다
VENDOR = {
    "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js": "chart.umd.min.js",
    "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js":
        "chartjs-adapter-date-fns.bundle.min.js",
}
for url, name in VENDOR.items():
    path = os.path.join(BASE_DIR, "vendor", name)
    tag = f'<script src="{url}"></script>'
    if os.path.exists(path) and tag in html:
        js = open(path, encoding="utf-8").read().replace("</script", "<\\/script")
        html = html.replace(tag, "<script>\n" + js + "\n</script>")

os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "index.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"{len(rows)}건 → {out_path}")
