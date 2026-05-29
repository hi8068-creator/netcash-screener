#!/usr/bin/env python3
"""outlook_raw.csv(短信の見通し抜粋)を results.csv にマージする。

results.csv のコードは "4387.T"、outlook_raw.csv は "4387" のため、
4桁コードで突合して「来期見通し(短信抜粋)」「短信PDF直URL」列を付与する。
"""
import argparse
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--outlook", default="outlook_raw.csv")
    ap.add_argument("--out", default="results.csv")
    args = ap.parse_args()

    res = pd.read_csv(args.results)
    out = pd.read_csv(args.outlook, dtype={"コード": str})

    res["_code4"] = res["コード"].astype(str).str.replace(".T", "", regex=False)
    out["_code4"] = out["コード"].astype(str).str.zfill(4)

    m = out[["_code4", "来期見通し(短信抜粋)", "短信PDF_URL"]].rename(
        columns={"短信PDF_URL": "短信PDF直URL"}
    )
    # 既存の見通し列があれば一旦落としてから付け直す(再マージ対応)
    for col in ["来期見通し(短信抜粋)", "短信PDF直URL"]:
        if col in res.columns:
            res = res.drop(columns=[col])

    merged = res.merge(m, on="_code4", how="left").drop(columns=["_code4"])
    merged.to_csv(args.out, index=False, encoding="utf-8-sig")

    got = merged["来期見通し(短信抜粋)"].fillna("").astype(str).str.strip().ne("").sum()
    print(f"マージ完了: 全{len(merged)}行中 {got}行に見通しを付与 → {args.out}")


if __name__ == "__main__":
    main()
