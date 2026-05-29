#!/usr/bin/env python3
"""results.csv に『日々大きく変わらない』ファンダ一式を付与する。

取得項目(yfinance):
  前日終値, 配当(年額), 配当利回り(%), forwardEPS(予想EPS), 予想PER, 目標株価
※ アナリスト・コンセンサスは有料のため対象外。会社予想は別途短信から取得。
※ info は重くレート制限を受けやすいので、レジューム＋リトライ＋低速で取得する。

例:
  python3 enrich_fundamentals.py --resume
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf

FIELDS = ["前日終値", "配当", "配当利回り(%)", "forwardEPS", "予想PER", "目標株価"]


def fetch_one(code: str) -> dict:
    t = yf.Ticker(f"{code}.T")
    out = {k: None for k in FIELDS}
    # 前日終値は軽量な fast_info を優先
    try:
        out["前日終値"] = getattr(t.fast_info, "previous_close", None)
    except Exception:
        pass
    try:
        info = t.info or {}
    except Exception:
        info = {}
    if out["前日終値"] is None:
        out["前日終値"] = info.get("previousClose")
    out["配当"] = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
    dy = info.get("dividendYield")
    if dy is None:
        dy = info.get("trailingAnnualDividendYield")
    # yfinanceは利回りを比率(0.025)で返す版と%(2.5)で返す版があるため正規化
    if dy is not None:
        out["配当利回り(%)"] = round(dy * 100, 2) if dy < 1 else round(dy, 2)
    out["forwardEPS"] = info.get("forwardEps")
    out["予想PER"] = info.get("forwardPE")
    out["目標株価"] = info.get("targetMeanPrice")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--cache", default="fund_raw.csv")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--save-every", type=int, default=25)
    args = ap.parse_args()

    res = pd.read_csv(args.results)
    res["_code4"] = res["コード"].astype(str).str.replace(".T", "", regex=False)
    codes = res["_code4"].tolist()

    cache = {}
    if args.resume and os.path.exists(args.cache):
        prev = pd.read_csv(args.cache, dtype={"コード": str})
        for _, r in prev.iterrows():
            cache[str(r["コード"]).zfill(4)] = {k: r.get(k) for k in FIELDS}
        print(f"キャッシュ {len(cache)} 件を読み込み")

    todo = [c for c in codes if c not in cache]
    print(f"ファンダ取得対象 {len(todo)} 社(全{len(codes)})...")

    def flush():
        rows = [dict(コード=c, **{k: cache[c].get(k) for k in FIELDS}) for c in cache]
        pd.DataFrame(rows).to_csv(args.cache, index=False, encoding="utf-8-sig")

    for i, code in enumerate(todo, 1):
        try:
            cache[code] = fetch_one(code)
        except Exception as e:
            cache[code] = {k: None for k in FIELDS}
            print(f"  [{i}/{len(todo)}] {code} エラー: {e}")
        if i % 50 == 0:
            print(f"  [{i}/{len(todo)}] ...")
        if args.save_every and i % args.save_every == 0:
            flush()
        if args.sleep:
            time.sleep(args.sleep)
    flush()

    # results.csv へ反映
    for k in FIELDS:
        res[k] = res["_code4"].map(lambda c: cache.get(c, {}).get(k))
    res = res.drop(columns=["_code4"])
    res.to_csv(args.results, index=False, encoding="utf-8-sig")
    got = res["前日終値"].notna().sum()
    print(f"\n完了: 前日終値取得 {got}社 / 全{len(res)}社 → {args.results}")


if __name__ == "__main__":
    main()
