#!/usr/bin/env python3
"""各銘柄の事業説明文(yfinance longBusinessSummary)を取得して summary_raw.csv に保存。

英語だが事業内容が具体的に書かれており、60業種分類の最良の信号。info は重いのでレジューム付き。
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--out", default="summary_raw.csv")
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--save-every", type=int, default=25)
    args = ap.parse_args()

    res = pd.read_csv(args.results)
    codes = [str(c).replace(".T", "") for c in res["コード"]]

    cache = {}
    if args.resume and os.path.exists(args.out):
        prev = pd.read_csv(args.out, dtype={"コード": str})
        for _, r in prev.iterrows():
            cache[str(r["コード"]).zfill(4)] = r.get("summary")
        print(f"キャッシュ {len(cache)} 件")

    todo = [c for c in codes if c.zfill(4) not in cache]
    print(f"説明文取得対象 {len(todo)} 社(全{len(codes)})")

    def flush():
        rows = [{"コード": c, "summary": v} for c, v in cache.items()]
        pd.DataFrame(rows).to_csv(args.out, index=False, encoding="utf-8-sig")

    for i, code in enumerate(todo, 1):
        s = None
        try:
            s = (yf.Ticker(f"{code}.T").info or {}).get("longBusinessSummary")
        except Exception:
            pass
        cache[code.zfill(4)] = s
        if i % 50 == 0:
            print(f"  [{i}/{len(todo)}]")
        if args.save_every and i % args.save_every == 0:
            flush()
        if args.sleep:
            time.sleep(args.sleep)
    flush()
    got = sum(1 for v in cache.values() if isinstance(v, str) and v.strip())
    print(f"完了: 説明文取得 {got}/{len(cache)} → {args.out}")


if __name__ == "__main__":
    main()
