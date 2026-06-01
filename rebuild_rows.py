#!/usr/bin/env python3
"""marketcap_overrides.csv の銘柄について、全列を揃えた行を再構築して
results.csv / results_all.csv に upsert する。

時価総額の上書きで evaluate が有効な値を返せるようになった銘柄を、
既存のキャッシュ(per_raw/fund_raw/outlook_raw)と業種分類を使って完全な行に復元する。
"""
import os

import pandas as pd

import core


def load_cache(path, keys, code_col="コード"):
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path, dtype={code_col: str})
    out = {}
    for _, r in df.iterrows():
        out[str(r[code_col]).zfill(4)] = {k: r.get(k) for k in keys}
    return out


def main():
    ov = pd.read_csv("marketcap_overrides.csv", dtype={"コード": str})
    codes = [str(c).zfill(4) for c in ov["コード"]]

    uni = core.fetch_jpx_universe(
        markets=["プライム", "スタンダード", "グロース"], exclude_etf=True)
    per_cache = load_cache("per_raw.csv", ["純利益", "純資産"])
    fund_cache = load_cache("fund_raw.csv",
                            ["前日終値", "配当", "配当利回り(%)", "forwardEPS", "予想PER", "目標株価"])
    ol = pd.read_csv("outlook_raw.csv", dtype={"コード": str}) if os.path.exists("outlook_raw.csv") else None

    base = pd.read_csv("results.csv")
    new_rows = []
    for code in codes:
        r = core.evaluate(code)
        if r is None:
            print(f"  {code}: evaluate None(スキップ)")
            continue
        row = core.results_to_df([r]).iloc[0].to_dict()
        # 業種・規模・市場・日本語名
        df1 = core.attach_universe_meta(core.results_to_df([r]), uni).iloc[0].to_dict()
        row.update({k: df1.get(k) for k in ["銘柄名", "市場", "業種", "業種大分類", "規模"]})
        # PER/PBR
        pc = per_cache.get(code, {})
        ni = pd.to_numeric(pd.Series([pc.get("純利益")]), errors="coerce").iloc[0]
        eq = pd.to_numeric(pd.Series([pc.get("純資産")]), errors="coerce").iloc[0]
        mc = r.market_cap
        row["純利益"], row["純資産"] = pc.get("純利益"), pc.get("純資産")
        row["PER"] = round(mc / ni, 1) if ni and ni > 0 else None
        row["PBR"] = round(mc / eq, 2) if eq and eq > 0 else None
        # 業種PER中央値 / 乖離率(同業の既存中央値を流用)
        med = base.loc[base["業種"] == row["業種"], "業種PER中央値"].dropna()
        row["業種PER中央値"] = float(med.iloc[0]) if len(med) else None
        if row["PER"] and row["業種PER中央値"]:
            row["PER乖離率"] = round(row["PER"] / row["業種PER中央値"] - 1, 3)
        # ファンダ
        row.update(fund_cache.get(code, {}))
        # 見通し
        if ol is not None:
            o = ol[ol["コード"].astype(str).str.zfill(4) == code]
            if len(o):
                row["来期見通し(短信抜粋)"] = o.iloc[0].get("来期見通し(短信抜粋)")
                row["短信PDF直URL"] = o.iloc[0].get("短信PDF_URL")
        new_rows.append(row)
        print(f"  {code} {row.get('銘柄名')}: 比率={r.ratio:.3f} 時価総額={mc/1e8:.1f}億 復元")

    if not new_rows:
        print("対象なし")
        return

    # 新60業種を後で apply するので、ここでは仮に空
    for f in ["results.csv", "results_all.csv"]:
        d = pd.read_csv(f)
        d = d[~d["コード"].isin([f"{c}.T" for c in codes])]  # 既存の該当行を除去
        add = pd.DataFrame(new_rows)
        d = pd.concat([d, add], ignore_index=True)
        # 列順は既存に合わせ、足りない列は欠損
        d = d.sort_values("ネットキャッシュ比率", ascending=False).reset_index(drop=True)
        d.to_csv(f, index=False, encoding="utf-8-sig")
        print(f"{f}: {len(d)}行に更新")


if __name__ == "__main__":
    main()
