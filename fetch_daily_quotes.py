#!/usr/bin/env python3
"""全銘柄の最新終値を一括取得して daily_quotes.csv に保存する。

場中に株価を拾い続けるのではなく、1日1回（引け後）の終値だけを更新する想定。
アプリ(app.py)は daily_quotes.csv があれば読み込み、前日終値を最新化し、
時価総額を「株数不変」の前提でスケールし直して各指標(比率/PER/PBR等)を引き直す。

使い方:
  python3 fetch_daily_quotes.py            # results.csv の全銘柄
  python3 fetch_daily_quotes.py --chunk 200
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf

BASE = os.path.dirname(__file__)
RESULTS_CSV = os.path.join(BASE, "results.csv")
OUT_CSV = os.path.join(BASE, "daily_quotes.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=300, help="一括ダウンロードの銘柄数")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    codes = (pd.read_csv(RESULTS_CSV, usecols=["コード"], dtype=str)["コード"]
             .dropna().unique().tolist())
    rows = []
    for i in range(0, len(codes), args.chunk):
        chunk = codes[i:i + args.chunk]
        try:
            data = yf.download(chunk, period="5d", interval="1d", auto_adjust=False,
                               progress=False, threads=True, group_by="ticker")
        except Exception as e:
            print(f"chunk {i} ERR {e!r}", flush=True)
            time.sleep(args.sleep)
            continue
        for c in chunk:
            try:
                close = (data[c]["Close"] if len(chunk) > 1 else data["Close"]).dropna()
            except Exception:
                continue
            if close.empty:
                continue
            rows.append({"コード": c,
                         "終値": round(float(close.iloc[-1]), 1),
                         "日付": str(close.index[-1].date())})
        print(f"{min(i + args.chunk, len(codes))}/{len(codes)} (取得 {len(rows)})", flush=True)
        time.sleep(args.sleep)

    pd.DataFrame(rows).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"完了: {len(rows)} 件 → {OUT_CSV}", flush=True)


if __name__ == "__main__":
    main()
