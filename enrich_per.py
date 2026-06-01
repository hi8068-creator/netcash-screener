#!/usr/bin/env python3
"""results.csv に業種(33業種)・PER・PBR・業種別中央値PERを付与する。

- 業種(33業種区分)/業種大分類(17)/規模区分: JPX一覧から無料で付与(per-stock通信なし)
- 純利益: yfinanceの損益計算書から取得 -> PER = 時価総額 / 純利益(黒字のみ)
- 純資産: yfinanceの貸借対照表から取得 -> PBR = 時価総額 / 純資産
- 業種PER中央値 と PER乖離率(=PER/業種中央値-1) を算出
  (中央値は外れ値・赤字に強く、PER>0のみで集計)

大量銘柄を順次取得するため --resume 対応。

例:
  python3 enrich_per.py --resume
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf

import core

NET_INCOME_KEYS = [
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income Including Noncontrolling Interests",
]
EQUITY_KEYS = [
    "Stockholders Equity",
    "Common Stock Equity",
    "Total Equity Gross Minority Interest",
]


def _pick(df, col, keys):
    for k in keys:
        try:
            v = df.loc[k, col]
        except KeyError:
            continue
        if v is not None and v == v:
            return float(v)
    return None


def fetch_fundamentals(code: str):
    """(純利益, 純資産) を返す。取得不可は None。"""
    t = yf.Ticker(f"{code}.T")
    ni = eq = None
    inc = t.income_stmt
    if inc is not None and not inc.empty:
        ni = _pick(inc, inc.columns[0], NET_INCOME_KEYS)
    bs = t.balance_sheet
    if bs is not None and not bs.empty:
        eq = _pick(bs, bs.columns[0], EQUITY_KEYS)
    return ni, eq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--cache", default="per_raw.csv", help="純利益・純資産の取得キャッシュ")
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--retry-empty", action="store_true",
                    help="純利益が欠損(NaN)の銘柄だけ再取得する")
    ap.add_argument("--save-every", type=int, default=25)
    args = ap.parse_args()

    res = pd.read_csv(args.results)
    res["_code4"] = res["コード"].astype(str).str.replace(".T", "", regex=False)
    codes = res["_code4"].tolist()

    # キャッシュ(レジューム)
    cache = {}
    if (args.resume or args.retry_empty) and os.path.exists(args.cache):
        prev = pd.read_csv(args.cache, dtype={"コード": str})
        for _, r in prev.iterrows():
            cache[str(r["コード"]).zfill(4)] = (r.get("純利益"), r.get("純資産"))
        print(f"キャッシュ {len(cache)} 件を読み込み")

    def _empty_ni(c):
        v = cache.get(c, (None, None))[0]
        return v is None or (isinstance(v, float) and v != v)  # None/NaN

    if args.retry_empty:
        # 純利益が欠損(NaN)の銘柄だけ再取得
        todo = [c for c in codes if c not in cache or _empty_ni(c)]
    else:
        todo = [c for c in codes if c not in cache]
    print(f"財務取得対象 {len(todo)} 社(全{len(codes)})...")

    def flush_cache():
        rows = [{"コード": c, "純利益": v[0], "純資産": v[1]} for c, v in cache.items()]
        pd.DataFrame(rows).to_csv(args.cache, index=False, encoding="utf-8-sig")

    for i, code in enumerate(todo, 1):
        ni = eq = None
        try:
            ni, eq = fetch_fundamentals(code)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {code} エラー: {e}")
        cache[code] = (ni, eq)
        if i % 50 == 0:
            print(f"  [{i}/{len(todo)}] ...")
        if args.save_every and i % args.save_every == 0:
            flush_cache()
        if args.sleep:
            time.sleep(args.sleep)
    flush_cache()

    # ---- 結果へ反映 ----
    res["純利益"] = res["_code4"].map(lambda c: cache.get(c, (None, None))[0])
    res["純資産"] = res["_code4"].map(lambda c: cache.get(c, (None, None))[1])
    mc = pd.to_numeric(res["時価総額(億円)"], errors="coerce") * 1e8
    ni = pd.to_numeric(res["純利益"], errors="coerce")
    eq = pd.to_numeric(res["純資産"], errors="coerce")
    res["PER"] = (mc / ni).where(ni > 0).round(1)
    res["PBR"] = (mc / eq).where(eq > 0).round(2)

    # 業種(33業種)を付与
    uni = core.fetch_jpx_universe(
        markets=["プライム", "スタンダード", "グロース"], exclude_etf=True
    )
    res = core.attach_universe_meta(res, uni)

    # 業種別PER中央値 と 乖離率
    valid = res[res["PER"].notna() & (res["PER"] > 0)]
    med = valid.groupby("業種")["PER"].median()
    res["業種PER中央値"] = res["業種"].map(med).round(1)
    res["PER乖離率"] = ((res["PER"] / res["業種PER中央値"]) - 1).round(3)

    res = res.drop(columns=["_code4"])
    res.to_csv(args.results, index=False, encoding="utf-8-sig")

    got_per = res["PER"].notna().sum()
    print(f"\n完了: PER付与 {got_per}社 / 全{len(res)}社 → {args.results}")
    print("業種数:", res["業種"].nunique())


if __name__ == "__main__":
    main()
