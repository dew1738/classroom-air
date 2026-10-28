#!/usr/bin/env python3
"""환경 센서 CSV → 분석 리포트 (report.md, report.html, summary.json)

어떤 환경 센서 CSV든 받아서:
  - 시간 열과 숫자 열을 자동으로 찾고
  - CO2·온도·습도·기압·가스·미세먼지 같은 항목을 열 이름으로 알아보고
  - 기본 통계, 시간대별 평균, 학교 실내 공기질 기준 초과 비율을 계산한다.

파이썬 표준 라이브러리만 사용한다 (설치할 것 없음).
사용법: python analyze.py 데이터.csv [--out 출력폴더] [--title 제목]
"""

import argparse
import csv
import html
import json
import math
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime

# ---------------------------------------------------------------------------
# 항목 사전: 열 이름에 들어 있는 단어로 항목을 알아본다.
# 기준값 출처: 학교보건법 시행규칙 [별표 4의2] 교사 안 공기질 유지·관리 기준
#   CO2 1,000ppm 이하 / 온도 18~28℃ / 상대습도 30~80% / PM10 75㎍/㎥, PM2.5 35㎍/㎥ 이하
# ---------------------------------------------------------------------------
METRICS = [
    # key, 표시 이름, 단위, 열 이름 패턴, (하한, 상한)
    ("co2", "CO₂", "ppm", r"co2|이산화탄소", (None, 1000)),
    ("pm25", "초미세먼지(PM2.5)", "㎍/㎥", r"pm2\.?5|초미세", (None, 35)),
    ("pm10", "미세먼지(PM10)", "㎍/㎥", r"pm10|미세먼지", (None, 75)),
    ("temp", "온도", "℃", r"temp|온도|기온", (18, 28)),
    ("hum", "습도", "%", r"hum|습도|rh\b", (30, 80)),
    ("press", "기압", "hPa", r"press|기압|hpa", (None, None)),
    ("gas", "가스 저항(VOC)", "kΩ", r"gas|voc|가스", (None, None)),
]

TIME_NAME = re.compile(r"time|date|시각|시간|일시|날짜|timestamp", re.I)
TIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"]


def parse_time(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return t.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    if re.fullmatch(r"\d{10}(\.\d+)?", text):  # 유닉스 시간(초)
        return datetime.fromtimestamp(float(text))
    return None


def parse_num(text):
    try:
        v = float(str(text).strip().replace(",", ""))
        return v if math.isfinite(v) else None
    except ValueError:
        return None


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))


def detect_columns(rows):
    cols = list(rows[0].keys())
    sample = rows[: min(len(rows), 200)]

    def ratio(col, fn):
        vals = [r.get(col) for r in sample if (r.get(col) or "").strip()]
        return sum(fn(v) is not None for v in vals) / len(vals) if vals else 0

    time_col = next((c for c in cols if TIME_NAME.search(c) and ratio(c, parse_time) > 0.8), None)
    if not time_col:
        time_col = next((c for c in cols if ratio(c, parse_time) > 0.8), None)
    num_cols = [c for c in cols if c != time_col and ratio(c, parse_num) > 0.8]
    return time_col, num_cols


def classify(col):
    name = col.lower()
    for key, label, unit, pattern, limits in METRICS:
        if re.search(pattern, name):
            return {"key": key, "label": label, "unit": unit, "limits": limits}
    return {"key": None, "label": col, "unit": "", "limits": (None, None)}


def fmt(v, d=1):
    return "–" if v is None else f"{v:,.{d}f}"


def analyze(rows, time_col, num_cols):
    times = [parse_time(r[time_col]) for r in rows] if time_col else [None] * len(rows)
    order = sorted(range(len(rows)), key=lambda i: times[i] or datetime.min)
    rows = [rows[i] for i in order]
    times = [times[i] for i in order]

    # 측정 간격과 끊긴 구간
    coverage = {}
    valid_t = [t for t in times if t]
    if len(valid_t) >= 2:
        gaps = [(b - a).total_seconds() for a, b in zip(valid_t, valid_t[1:])]
        step = statistics.median(gaps) or 1
        breaks = [(valid_t[i], valid_t[i + 1]) for i, g in enumerate(gaps) if g > max(step * 10, 300)]
        coverage = {
            "start": valid_t[0].isoformat(sep=" "), "end": valid_t[-1].isoformat(sep=" "),
            "interval_sec": round(step), "rows": len(rows),
            "measured_hours": round(sum(g for g in gaps if g <= max(step * 10, 300)) / 3600, 1),
            "gaps": [{"from": a.isoformat(sep=" "), "to": b.isoformat(sep=" "),
                      "hours": round((b - a).total_seconds() / 3600, 1)} for a, b in breaks],
        }

    metrics = []
    for col in num_cols:
        info = classify(col)
        pts = [(t, parse_num(r[col])) for t, r in zip(times, rows)]
        pts = [(t, v) for t, v in pts if v is not None]
        vals = [v for _, v in pts]
        if not vals:
            continue
        m = {
            "column": col, **info, "count": len(vals),
            "min": min(vals), "max": max(vals), "mean": statistics.fmean(vals),
            "median": statistics.median(vals), "std": statistics.pstdev(vals),
            "first": vals[0], "last": vals[-1],
            "min_at": next((t.isoformat(sep=" ") for t, v in pts if v == min(vals) and t), None),
            "max_at": next((t.isoformat(sep=" ") for t, v in pts if v == max(vals) and t), None),
        }
        lo, hi = info["limits"]
        if lo is not None or hi is not None:
            out = [(lo is not None and v < lo) or (hi is not None and v > hi) for v in vals]
            m["out_of_range_pct"] = round(100 * sum(out) / len(out), 1)
            # 기준을 벗어난 상태가 가장 길게 이어진 구간 (측정이 끊긴 곳에서는 구간도 끊는다)
            max_gap = max(coverage.get("interval_sec", 30) * 10, 300)
            best, cur_start, last_t = None, None, None
            for (t, _), o in zip(pts, out):
                if cur_start and t and last_t and (t - last_t).total_seconds() > max_gap:
                    cur_start = None
                if o and t:
                    cur_start = cur_start or t
                    last_t = t
                    if not best or (last_t - cur_start) > (best[1] - best[0]):
                        best = (cur_start, last_t)
                else:
                    cur_start = None
            if best:
                m["longest_out"] = {"from": best[0].isoformat(sep=" "), "to": best[1].isoformat(sep=" "),
                                    "minutes": round((best[1] - best[0]).total_seconds() / 60)}
        # 시간대(0~23시)별 평균
        by_hour = defaultdict(list)
        for t, v in pts:
            if t:
                by_hour[t.hour].append(v)
        m["hourly_mean"] = {h: round(statistics.fmean(v), 2) for h, v in sorted(by_hour.items())}
        m["series"] = [(t.isoformat(), v) for t, v in pts if t]
        metrics.append(m)

    # 같은 이름이 둘 이상이면 (예: 센서 두 개의 온도) 열 이름을 붙여 구분한다
    labels = [m["label"] for m in metrics]
    for m in metrics:
        if labels.count(m["label"]) > 1:
            m["label"] = f"{m['label']}·{m['column']}"

    # 중요한 항목(기준이 있는 것)을 앞에 둔다
    rank = {k: i for i, (k, *_rest) in enumerate(METRICS)}
    metrics.sort(key=lambda m: rank.get(m["key"], 99))
    return coverage, metrics


# ---------------------------------------------------------------------------
# 출력: Markdown
# ---------------------------------------------------------------------------
def to_markdown(title, src, coverage, metrics):
    L = [f"# {title}", "", f"- 데이터: `{os.path.basename(src)}`"]
    if coverage:
        L += [f"- 기간: {coverage['start']} ~ {coverage['end']}",
              f"- 측정: {coverage['rows']:,}건 · 간격 약 {coverage['interval_sec']}초 · 실제 측정 {coverage['measured_hours']}시간"]
        if coverage["gaps"]:
            L.append(f"- 끊긴 구간 {len(coverage['gaps'])}곳: " +
                     ", ".join(f"{g['from'][5:16]}~{g['to'][5:16]}({g['hours']}h)" for g in coverage["gaps"][:5]))
    L += ["", "## 요약 통계", "", "| 항목 | 평균 | 중앙값 | 최소 | 최대 | 표준편차 | 기준 이탈 |",
          "|---|---|---|---|---|---|---|"]
    for m in metrics:
        d = 0 if m["key"] == "co2" else 1
        out = f"{m['out_of_range_pct']}%" if "out_of_range_pct" in m else "–"
        L.append(f"| {m['label']} ({m['unit'] or m['column']}) | {fmt(m['mean'], d)} | {fmt(m['median'], d)} | "
                 f"{fmt(m['min'], d)} | {fmt(m['max'], d)} | {fmt(m['std'], d)} | {out} |")

    L += ["", "## 기준과 비교 (학교보건법 시행규칙 교사 안 공기질 기준)", ""]
    judged = [m for m in metrics if "out_of_range_pct" in m]
    if not judged:
        L.append("- 기준이 있는 항목(CO₂·온도·습도·미세먼지)을 찾지 못했습니다.")
    for m in judged:
        lo, hi = m["limits"]
        rule = f"{lo}~{hi}{m['unit']}" if lo is not None else f"{hi}{m['unit']} 이하"
        line = f"- **{m['label']}** (기준 {rule}): 측정 시간의 **{m['out_of_range_pct']}%** 기준 이탈"
        if m.get("longest_out"):
            lo_ = m["longest_out"]
            to_txt = lo_["to"][11:16] if lo_["from"][:10] == lo_["to"][:10] else lo_["to"][5:16]
            line += f" · 가장 길게 이어진 구간 {lo_['from'][5:16]} ~ {to_txt} ({lo_['minutes']}분)"
        L.append(line)

    L += ["", "## 시간대별 평균", ""]
    hours = sorted({h for m in metrics for h in m["hourly_mean"]})
    if hours:
        L.append("| 시 | " + " | ".join(m["label"] for m in metrics) + " |")
        L.append("|---|" + "---|" * len(metrics))
        for h in hours:
            L.append(f"| {h:02d}시 | " + " | ".join(fmt(m["hourly_mean"].get(h), 0 if m["key"] == "co2" else 1)
                                                   for m in metrics) + " |")
    L += ["", "## 해석과 제언", "", "<!-- INSIGHTS -->", ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 출력: HTML (외부 라이브러리 없이 SVG로 그래프를 그린다 → 어디서든 열림)
# ---------------------------------------------------------------------------
COLORS = {"co2": "#d4483b", "temp": "#e07b24", "hum": "#2f7fd1", "press": "#5b6b7f",
          "gas": "#7a5bd1", "pm25": "#b5446e", "pm10": "#8a6d3b", None: "#3a8f7a"}


def svg_chart(m, width=440, height=220, max_points=800):
    series = m["series"]
    if len(series) < 2:
        return "<p class='muted'>그래프를 그릴 만큼 데이터가 없습니다.</p>"
    step = max(1, len(series) // max_points)
    pts = [(datetime.fromisoformat(t), v) for t, v in series[::step]]
    t0, t1 = pts[0][0], pts[-1][0]
    span = (t1 - t0).total_seconds() or 1
    lo, hi = m["limits"]
    vmin = min(min(v for _, v in pts), lo if lo is not None else math.inf)
    vmax = max(max(v for _, v in pts), hi if hi is not None else -math.inf)
    pad = (vmax - vmin) * 0.08 or 1
    vmin, vmax = vmin - pad, vmax + pad
    L, R, T, B = 48, 10, 10, 24
    X = lambda t: L + (width - L - R) * (t - t0).total_seconds() / span
    Y = lambda v: T + (height - T - B) * (1 - (v - vmin) / (vmax - vmin))

    # 5분 이상 끊긴 곳은 선을 끊는다
    paths, cur, prev = [], [], None
    for t, v in pts:
        if prev and (t - prev).total_seconds() > max(m.get("_gap", 300), 300) * max(step, 1):
            paths.append(cur)
            cur = []
        cur.append(f"{X(t):.1f},{Y(v):.1f}")
        prev = t
    paths.append(cur)
    color = COLORS.get(m["key"], COLORS[None])
    out = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{html.escape(m['label'])} 그래프'>"]
    for i in range(5):
        v = vmin + (vmax - vmin) * i / 4
        out.append(f"<line x1='{L}' x2='{width - R}' y1='{Y(v):.1f}' y2='{Y(v):.1f}' class='grid'/>"
                   f"<text x='{L - 6}' y='{Y(v) + 4:.1f}' class='axis' text-anchor='end'>{v:,.0f}</text>")
    for limit in (lo, hi):
        if limit is not None:
            out.append(f"<line x1='{L}' x2='{width - R}' y1='{Y(limit):.1f}' y2='{Y(limit):.1f}' class='limit'/>"
                       f"<text x='{width - R}' y='{Y(limit) - 4:.1f}' class='axis' text-anchor='end'>기준 {limit:g}</text>")
    for i in range(4):
        t = t0 + (t1 - t0) * i / 3
        out.append(f"<text x='{X(t):.1f}' y='{height - 6}' class='axis' text-anchor='middle'>{t:%m-%d %H:%M}</text>")
    for p in paths:
        if len(p) > 1:
            out.append(f"<polyline points='{' '.join(p)}' fill='none' stroke='{color}' stroke-width='1.6'/>")
    out.append("</svg>")
    return "".join(out)


def to_html(title, md_text, metrics):
    # Markdown 표·목록을 간단히 HTML로 바꾼다 (외부 라이브러리 없이)
    body, in_table, in_list = [], False, False
    for line in md_text.splitlines():
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
        esc = re.sub(r"`(.+?)`", r"<code>\1</code>", esc)
        if line.startswith("|"):
            cells = [c.strip() for c in esc.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            if not in_table:
                body.append("<table><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
                in_table = True
            else:
                body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{esc[2:]}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        if line.startswith("<!--"):
            body.append(line)
        elif line.startswith("## "):
            title_txt = esc[3:]
            body.append(f"<h2>{title_txt}</h2>")
            if title_txt == "요약 통계":
                body.append("<div class='charts'>" + "".join(
                    f"<figure><figcaption>{html.escape(m['label'])} ({html.escape(m['unit'])})</figcaption>{svg_chart(m)}</figure>"
                    for m in metrics) + "</div>")
        elif line.startswith("# "):
            body.append(f"<h1>{esc[2:]}</h1>")
        elif line.strip():
            body.append(f"<p>{esc}</p>")
    if in_table:
        body.append("</table>")
    if in_list:
        body.append("</ul>")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --text:#1d2433; --muted:#6b7385; --line:#e3e6ec; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171d; --card:#1d2129; --text:#e8ebf1; --muted:#9aa2b1; --line:#2c313b; }} }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family:system-ui,"Malgun Gothic",sans-serif; line-height:1.6; }}
main {{ max-width:960px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:1.6rem; }} h2 {{ margin-top:2rem; border-bottom:1px solid var(--line); padding-bottom:4px; }}
table {{ border-collapse:collapse; width:100%; background:var(--card); font-size:.92rem; display:block; overflow-x:auto; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:right; white-space:nowrap; }}
th:first-child, td:first-child {{ text-align:left; }}
.charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr)); gap:12px; margin:12px 0; }}
figure {{ margin:0; background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px; }}
figcaption {{ font-size:.9rem; color:var(--muted); }}
svg {{ width:100%; height:auto; }} .grid {{ stroke:var(--line); }} .limit {{ stroke:#d4483b; stroke-dasharray:4 3; }}
.axis {{ font-size:12px; fill:var(--muted); }} .muted {{ color:var(--muted); }}
code {{ background:var(--line); padding:1px 4px; border-radius:4px; }}
</style></head><body><main>
{chr(10).join(body)}
</main></body></html>"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 한글 깨짐 방지
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="환경 센서 CSV → 분석 리포트")
    ap.add_argument("csv")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본: CSV와 같은 폴더의 report_<파일명>)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--insights", default=None,
                    help="해석과 제언을 적은 Markdown 파일 → 리포트의 '해석과 제언' 칸에 넣는다")
    args = ap.parse_args()

    rows = read_csv(args.csv)
    if not rows:
        raise SystemExit("CSV에 데이터 행이 없습니다.")
    time_col, num_cols = detect_columns(rows)
    if not num_cols:
        raise SystemExit(f"숫자 열을 찾지 못했습니다. 열 목록: {list(rows[0].keys())}")

    stem = os.path.splitext(os.path.basename(args.csv))[0]
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.csv)), f"report_{stem}")
    os.makedirs(out_dir, exist_ok=True)
    title = args.title or f"환경 데이터 분석 리포트 · {stem}"

    coverage, metrics = analyze(rows, time_col, num_cols)
    md = to_markdown(title, args.csv, coverage, metrics)
    if args.insights:
        insights = open(args.insights, encoding="utf-8-sig").read().strip()
        md = md.replace("<!-- INSIGHTS -->", insights)

    summary = {"title": title, "source": os.path.abspath(args.csv), "time_column": time_col,
               "coverage": coverage,
               "metrics": [{k: v for k, v in m.items() if k != "series"} for m in metrics]}
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(to_html(title, md, metrics))

    print(f"시간 열: {time_col} / 분석 항목: {', '.join(m['label'] for m in metrics)}")
    print(f"출력: {out_dir}  (report.md, report.html, summary.json)")


if __name__ == "__main__":
    main()
