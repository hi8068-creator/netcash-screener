#!/usr/bin/env python3
"""見通しの全文(長め)を抽出して outlook_full.csv に保存する。

outlook_raw.csv に保存済みの短信PDF URLを再利用(適時開示の再取得なし)し、
fetch_outlook.extract_outlook で本文を抽出。要約作成の素材にする。
"""
import os

import pandas as pd

import fetch_outlook as fo


def main():
    src = pd.read_csv("outlook_raw.csv", dtype={"コード": str})
    out_path = "outlook_full.csv"
    done = {}
    if os.path.exists(out_path):
        prev = pd.read_csv(out_path, dtype={"コード": str})
        done = {str(r["コード"]).zfill(4): r.get("見通し原文") for _, r in prev.iterrows()}

    rows = []
    todo = src[src["短信PDF_URL"].fillna("").astype(str).str.startswith("http")]
    print(f"対象 {len(todo)} 社")
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        code = str(r["コード"]).zfill(4)
        if code in done and str(done[code]).strip() and str(done[code]) != "nan":
            rows.append({"コード": code, "見通し原文": done[code]})
            continue
        try:
            text = fo.extract_outlook(r["短信PDF_URL"])
        except Exception as e:
            text = ""
            print(f"  {code} エラー: {e}")
        rows.append({"コード": code, "見通し原文": text})
        if i % 20 == 0:
            pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
            print(f"  [{i}/{len(todo)}] 保存")
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    got = sum(1 for x in rows if str(x["見通し原文"]).strip())
    print(f"完了: {got}/{len(rows)} 社で全文取得 → {out_path}")


if __name__ == "__main__":
    main()
