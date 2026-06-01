#!/usr/bin/env python3
"""直近数年(yfinanceで取得可能な範囲=概ね4年)の業績トレンドを取得する。

各銘柄について年次の売上(Total Revenue)・純利益(Net Income)を取り、
「直近で連続して増収/増益している年数」を算出して earnings_trend.csv に保存する。

出力列:
  コード, 増収(年), 増益(年), 増収増益(年), 売上トレンド
    - 増収(年)     : 直近から数えて連続で増収した年数
    - 増益(年)     : 同・連続で増益した年数
    - 増収増益(年) : 直近から数えて売上・利益が"両方"連続で増えた年数(=右肩上がりの強さ)
    - 売上トレンド : 取得できた年次売上(古い→新しい)を ' → ' で連結した文字列(目視用)

使い方:
  python3 fetch_earnings_trend.py                # 比率1.0以上を対象(既定)
  python3 fetch_earnings_trend.py --min-ratio 0.5
  python3 fetch_earnings_trend.py --resume       # 取得済みはスキップ
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf

BASE = os.path.dirname(__file__)
RESULTS_CSV = os.path.join(BASE, "results.csv")
OUT_CSV = os.path.join(BASE, "earnings_trend.csv")


def _consec_up(series):
    """古い→新しい順の数列で、末尾(直近)から連続して増加した回数。"""
    c = 0
    for i in range(len(series) - 1, 0, -1):
        if series[i] > series[i - 1]:
            c += 1
        else:
            break
    return c


def _consec_up_both(rev, ni):
    c = 0
    for i in range(len(rev) - 1, 0, -1):
        if rev[i] > rev[i - 1] and ni[i] > ni[i - 1]:
            c += 1
        else:
            break
    return c


def trend_for(code: str):
    t = yf.Ticker(code)
    fin = t.income_stmt  # 年次。列は新しい→古い
    if fin is None or fin.empty:
        return None
    if "Total Revenue" not in fin.index or "Net Income" not in fin.index:
        return None
    rev_row = fin.loc["Total Revenue"]
    ni_row = fin.loc["Net Income"]
    # 列(年度)を古い→新しいに並べ、売上・利益がともに有効な年だけ使う
    years = sorted(fin.columns)
    rev, ni = [], []
    for y in years:
        r = rev_row.get(y)
        n = ni_row.get(y)
        if pd.isna(r) or pd.isna(n):
            continue
        rev.append(float(r))
        ni.append(float(n))
    if len(rev) < 2:
        return None
    up_rev = _consec_up(rev)
    up_ni = _consec_up(ni)
    both = _consec_up_both(rev, ni)
    sales_trend = " → ".join(f"{v / 1e8:.0f}" for v in rev) + "(億)"
    return {
        "コード": code,
        "増収(年)": up_rev,
        "増益(年)": up_ni,
        "増収増益(年)": both,
        "売上トレンド": sales_trend,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ratio", type=float, default=1.0,
                    help="この比率以上の銘柄のみ取得(既定1.0)")
    ap.add_argument("--resume", action="store_true", help="取得済みはスキップ")
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    df = pd.read_csv(RESULTS_CSV)
    ratio = pd.to_numeric(df.get("ネットキャッシュ比率"), errors="coerce")
    codes = df.loc[ratio >= args.min_ratio, "コード"].astype(str).tolist()

    done = {}
    if args.resume and os.path.exists(OUT_CSV):
        prev = pd.read_csv(OUT_CSV, dtype={"コード": str})
        done = {r["コード"]: r.to_dict() for _, r in prev.iterrows()}

    rows = list(done.values())
    todo = [c for c in codes if c not in done]
    print(f"対象 {len(codes)} 件 / 取得済み {len(done)} / これから {len(todo)}", flush=True)

    for i, code in enumerate(todo, 1):
        try:
            r = trend_for(code)
        except Exception as e:
            r = None
            print(f"  {code} ERR {e!r}", flush=True)
        if r:
            rows.append(r)
        if i % 10 == 0:
            print(f"  {i}/{len(todo)} (取得 {len(rows)})", flush=True)
        if i % args.save_every == 0:
            pd.DataFrame(rows).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
        time.sleep(args.sleep)

    pd.DataFrame(rows).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"完了: {len(rows)} 件を {OUT_CSV} に保存", flush=True)


if __name__ == "__main__":
    main()
