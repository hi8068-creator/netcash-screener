#!/usr/bin/env python3
"""JPX公式の監理・整理銘柄一覧を取得して jpx_alerts.csv に保存する。

監理銘柄(審査中)=上場廃止基準への該当を審査中、整理銘柄=上場廃止が決定、
監理銘柄(確認中)=TOB成立等の確認中。いずれもスクリーナーの「割安」上位に
紛れ込みやすい(株価が廃止リスクを織り込んで安いだけ)ため、注意フラグの元データにする。

出力: jpx_alerts.csv (コード, 銘柄名, 区分, 指定年月日)
取得失敗時は既存ファイルを残して正常終了する(パイプラインを止めない)。
"""
import csv
import os
import re
import sys

import requests

URL = "https://www.jpx.co.jp/listing/market-alerts/supervision/index.html"
OUT = os.path.join(os.path.dirname(__file__), "jpx_alerts.csv")

# 表の直前テキストに現れるキーワード → 区分ラベル
SECTION_LABELS = [
    ("審査中", "監理(審査中)"),
    ("確認中", "監理(確認中)"),
    ("整理銘柄", "整理"),
]


def parse_tables(html):
    rows_out = []
    parts = html.split("<table")
    for i, part in enumerate(parts[1:], 1):
        preceding = re.sub(r"<[^>]+>", " ", parts[i - 1][-300:])
        label = next((lab for key, lab in SECTION_LABELS if key in preceding), None)
        if not label:
            continue
        for tr in re.findall(r"<tr[\s\S]*?</tr>", part):
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr)]
            # ヘッダ行を除き、3列目が証券コード(数字始まり4文字)の行のみ採用
            if len(cells) >= 3 and re.fullmatch(r"[0-9][0-9A-Z]{3}", cells[2]):
                rows_out.append({
                    "コード": cells[2],
                    "銘柄名": cells[1],
                    "区分": label,
                    "指定年月日": cells[0],
                })
    return rows_out


def main():
    try:
        r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        rows = parse_tables(r.text)
    except Exception as e:
        print(f"JPX取得失敗(既存の jpx_alerts.csv を維持): {e}", file=sys.stderr)
        return 0
    if not rows:
        print("表が1件も取れなかったため既存ファイルを維持(ページ構造変更の可能性)",
              file=sys.stderr)
        return 0
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["コード", "銘柄名", "区分", "指定年月日"])
        w.writeheader()
        w.writerows(rows)
    by = {}
    for row in rows:
        by[row["区分"]] = by.get(row["区分"], 0) + 1
    print(f"jpx_alerts.csv 更新: {len(rows)}銘柄 {by}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
