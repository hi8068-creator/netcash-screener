#!/usr/bin/env python3
"""連動分析用に、全銘柄の日次終値(1年)をまとめてダウンロードする。

yfinanceの複数銘柄一括DLをバッチで実行し、prices.parquet(日付×銘柄の終値行列)に保存。
--resume で既存銘柄をスキップして追記。

例:
  python3 download_prices.py --period 1y --batch 150
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--out", default="prices.parquet")
    ap.add_argument("--period", default="1y")
    ap.add_argument("--batch", type=int, default=150)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    res = pd.read_csv(args.results)
    tickers = [f"{str(c).replace('.T','')}.T" for c in res["コード"]]

    existing = None
    done = set()
    if args.resume and os.path.exists(args.out):
        existing = pd.read_parquet(args.out)
        done = set(existing.columns)
        print(f"レジューム: 既存 {len(done)} 銘柄をスキップ")

    todo = [t for t in tickers if t not in done]
    print(f"DL対象 {len(todo)} 銘柄(全{len(tickers)})/ period={args.period}")

    frames = [existing] if existing is not None else []
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        try:
            data = yf.download(
                chunk, period=args.period, interval="1d",
                auto_adjust=True, progress=False, threads=True,
            )
            close = data["Close"] if "Close" in data else data
            if isinstance(close, pd.Series):
                close = close.to_frame(name=chunk[0])
            frames.append(close)
        except Exception as e:
            print(f"  batch {i}-{i+len(chunk)} エラー: {e}")
        # 途中保存
        merged = pd.concat(frames, axis=1)
        merged = merged.loc[:, ~merged.columns.duplicated()]
        merged.to_parquet(args.out)
        print(f"  [{min(i+args.batch, len(todo))}/{len(todo)}] 保存 (列数 {merged.shape[1]})")
        if args.sleep:
            time.sleep(args.sleep)

    final = pd.read_parquet(args.out)
    print(f"\n完了: {final.shape[0]}営業日 × {final.shape[1]}銘柄 → {args.out}")


if __name__ == "__main__":
    main()
