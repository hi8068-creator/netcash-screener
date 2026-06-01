#!/usr/bin/env python3
"""OHLCからRSI(14)とストキャスティクス(%K14/%D3)を計算し、売られすぎ/買われすぎ判定を付ける。

リール準拠ロジック:
  買い検討: RSI<=30(売られすぎ) かつ %K<20 かつ %Kが%Dを下→上に抜け(反転)
  売り検討: RSI>=80(買われすぎ) かつ %K>80 かつ %Kが%Dを上→下に抜け(反転)
出力: technical.csv (コード, RSI, ストキャスK, ストキャスD, テクニカル)。最後に results へマージ。
"""
import argparse
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf


def indicators(high, low, close):
    """終値・高値・安値の系列から (RSI, %K, %D, %K前, %D前) の最新値を返す。

    高値・安値・終値を同一インデックスに揃えてから計算する(末尾NaNでのズレ防止)。
    """
    df = pd.DataFrame({"h": high, "l": low, "c": close}).apply(
        pd.to_numeric, errors="coerce").dropna()
    if len(df) < 20:
        return None
    c, h, l = df["c"], df["h"], df["l"]
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    ag = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    al = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rsi = (100 - 100 / (1 + ag / al.replace(0, np.nan))).dropna()
    low14 = l.rolling(14).min()
    high14 = h.rolling(14).max()
    k = ((c - low14) / (high14 - low14).replace(0, np.nan) * 100).dropna()
    d = k.rolling(3).mean().dropna()
    if len(rsi) < 1 or len(k) < 2 or len(d) < 2:
        return None
    return (float(rsi.iloc[-1]), float(k.iloc[-1]), float(d.iloc[-1]),
            float(k.iloc[-2]), float(d.iloc[-2]))


def signal(rsi, k, d, kp, dp):
    if any(pd.isna(x) for x in (rsi, k, d)):
        return ""
    cross_up = (not pd.isna(kp) and not pd.isna(dp)) and kp <= dp and k > d
    cross_dn = (not pd.isna(kp) and not pd.isna(dp)) and kp >= dp and k < d
    if rsi <= 30 and k < 20:
        return "🟢売られすぎ＋反転(買い検討)" if cross_up else "🟢売られすぎ"
    if rsi >= 80 and k > 80:
        return "🔴買われすぎ＋反転(売り検討)" if cross_dn else "🔴買われすぎ"
    if rsi <= 35:
        return "売られ気味"
    if rsi >= 70:
        return "買われ気味"
    return "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--out", default="technical.csv")
    ap.add_argument("--batch", type=int, default=120)
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    res = pd.read_csv(args.results)
    tickers = [f"{str(c).replace('.T','')}.T" for c in res["コード"]]

    done = {}
    if args.resume and os.path.exists(args.out):
        prev = pd.read_csv(args.out, dtype={"コード": str})
        done = {str(r["コード"]): r for _, r in prev.iterrows()}
        print(f"レジューム: 既存 {len(done)}")

    rows = list(done.values())
    todo = [t for t in tickers if t not in done]
    print(f"テクニカル計算対象 {len(todo)} 銘柄(全{len(tickers)})")

    def flush():
        pd.DataFrame(rows).to_csv(args.out, index=False, encoding="utf-8-sig")

    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        try:
            data = yf.download(chunk, period="1y", interval="1d",
                               auto_adjust=True, progress=False, threads=True,
                               group_by="ticker")
        except Exception as e:
            print(f"  batch {i} DLエラー: {e}")
            continue
        for t in chunk:
            try:
                if len(chunk) == 1:
                    sub = data
                else:
                    sub = data[t]
                ind = indicators(sub["High"], sub["Low"], sub["Close"])
            except Exception:
                ind = None
            if ind:
                rsi, k, d, kp, dp = ind
                rows.append({"コード": t, "RSI": round(rsi, 1),
                             "ストキャスK": round(k, 1), "ストキャスD": round(d, 1),
                             "テクニカル": signal(rsi, k, d, kp, dp)})
            else:
                rows.append({"コード": t, "RSI": None, "ストキャスK": None,
                             "ストキャスD": None, "テクニカル": ""})
        flush()
        print(f"  [{min(i + args.batch, len(todo))}/{len(todo)}]")
        if args.sleep:
            time.sleep(args.sleep)

    flush()

    # results へマージ
    tdf = pd.read_csv(args.out, dtype={"コード": str})
    tmap = {str(r["コード"]): r for _, r in tdf.iterrows()}
    for col in ["RSI", "ストキャスK", "ストキャスD", "テクニカル"]:
        res[col] = res["コード"].astype(str).map(lambda c: tmap.get(c, {}).get(col))
    res.to_csv(args.results, index=False, encoding="utf-8-sig")
    got = res["RSI"].notna().sum()
    print(f"\n完了: RSI付与 {got}/{len(res)} 社 → {args.results}")
    print(res["テクニカル"].value_counts().to_string())


if __name__ == "__main__":
    main()
