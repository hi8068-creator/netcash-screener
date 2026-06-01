#!/usr/bin/env python3
"""各銘柄の GICS 業種(yfinance sector/industry)を取得して industry_raw.csv に保存。

60業種の分類精度を上げるための事業内容信号。info は重いのでレジューム付き。
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--out", default="industry_raw.csv")
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
            cache[str(r["コード"]).zfill(4)] = (r.get("sector"), r.get("industry"))
        print(f"キャッシュ {len(cache)} 件")

    todo = [c for c in codes if c.zfill(4) not in cache]
    print(f"GICS取得対象 {len(todo)} 社(全{len(codes)})")

    def flush():
        rows = [{"コード": c, "sector": v[0], "industry": v[1]} for c, v in cache.items()]
        pd.DataFrame(rows).to_csv(args.out, index=False, encoding="utf-8-sig")

    for i, code in enumerate(todo, 1):
        sec = ind = None
        try:
            info = yf.Ticker(f"{code}.T").info or {}
            sec, ind = info.get("sector"), info.get("industry")
        except Exception:
            pass
        cache[code.zfill(4)] = (sec, ind)
        if i % 50 == 0:
            print(f"  [{i}/{len(todo)}]")
        if args.save_every and i % args.save_every == 0:
            flush()
        if args.sleep:
            time.sleep(args.sleep)
    flush()
    got = sum(1 for v in cache.values() if v[1])
    print(f"完了: industry取得 {got}/{len(cache)} → {args.out}")


if __name__ == "__main__":
    main()
