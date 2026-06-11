#!/usr/bin/env python3
"""results.csv のネットキャッシュを新計算式(非支配株主持分の控除)で再計算する。

全銘柄の再取得(build_results --full)は重いため、表示対象になりやすい
「現在の比率が閾値以上」の銘柄だけ Yahoo Finance から貸借対照表を取り直し、
ネットキャッシュ(億円)・財務内訳・非支配株主持分・比率を更新する。

比率は results.csv の時価総額(億円)で計算し直す(日々の終値スケーリングと整合)。
取得に失敗した銘柄は元の値を維持する。
"""
import argparse
import os
import time

import pandas as pd

import core

BASE = os.path.dirname(__file__)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(BASE, "results.csv"))
    ap.add_argument("--min-ratio", type=float, default=0.8)
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    df = pd.read_csv(args.results, dtype={"コード": str})
    if "非支配株主持分" not in df.columns:
        df["非支配株主持分"] = pd.NA

    ratio = pd.to_numeric(df["ネットキャッシュ比率"], errors="coerce")
    target = df.index[ratio >= args.min_ratio].tolist()
    print(f"再計算対象: {len(target)}銘柄 (比率>={args.min_ratio})")

    updated = failed = 0
    for n, i in enumerate(target, 1):
        code = str(df.at[i, "コード"])
        try:
            r = core.evaluate(code)
        except Exception:
            r = None
        if r is None:
            failed += 1
        else:
            mc_oku = pd.to_numeric(df.at[i, "時価総額(億円)"], errors="coerce")
            nc_oku = round(r.net_cash / 1e8, 1)
            df.at[i, "流動資産"] = round(r.current_assets)
            df.at[i, "投資有価証券"] = round(r.investment_securities)
            df.at[i, "負債"] = round(r.total_liabilities)
            df.at[i, "非支配株主持分"] = round(r.minority_interest)
            df.at[i, "ネットキャッシュ(億円)"] = nc_oku
            df.at[i, "決算期"] = r.fiscal_date
            if pd.notna(mc_oku) and mc_oku > 0:
                df.at[i, "ネットキャッシュ比率"] = round(nc_oku / mc_oku, 3)
            else:
                df.at[i, "ネットキャッシュ比率"] = round(r.ratio, 3)
            updated += 1
        if n % 25 == 0:
            print(f"  {n}/{len(target)} 処理済み (更新{updated}/失敗{failed})")
        if args.sleep:
            time.sleep(args.sleep)

    df.to_csv(args.results, index=False, encoding="utf-8-sig")
    print(f"完了: 更新{updated} / 失敗{failed} (失敗分は元の値を維持)")


if __name__ == "__main__":
    main()
