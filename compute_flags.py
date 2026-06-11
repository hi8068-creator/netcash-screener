#!/usr/bin/env python3
"""results.csv に「注意」列(罠フラグ)を付与する。

フラグの種類:
  ⚠整理(上場廃止決定) / ⚠監理(上場廃止審査中) / 監理(TOB等確認中) … jpx_alerts.csv より
  ⚠暗号資産保有 … 事業内容・短信見通しのキーワード検出 ＋ flags_overrides.csv
                   (借金や増資で暗号資産を買う企業は「流動資産」が現金の顔をした
                    値動きの激しい投機資産であり、ネットキャッシュ比率が割安の証にならない)

手動指定: flags_overrides.csv (コード, 注意, メモ) があればマージする。
"""
import argparse
import os
import re

import pandas as pd

BASE = os.path.dirname(__file__)

ALERT_LABEL = {
    "整理": "⚠整理(上場廃止決定)",
    "監理(審査中)": "⚠監理(上場廃止審査中)",
    "監理(確認中)": "監理(TOB等確認中)",
}
CRYPTO_PAT = re.compile(r"ビットコイン|暗号資産|仮想通貨|イーサリアム|BTC保有|クリプト")


def code4(s):
    return str(s).replace(".T", "").strip().zfill(4)[:4] if str(s).strip() else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(BASE, "results.csv"))
    args = ap.parse_args()

    df = pd.read_csv(args.results, dtype={"コード": str})
    c4 = df["コード"].map(code4)
    flags = {c: [] for c in c4}

    alerts_path = os.path.join(BASE, "jpx_alerts.csv")
    if os.path.exists(alerts_path):
        al = pd.read_csv(alerts_path, dtype=str, encoding="utf-8-sig")
        amap = {code4(r["コード"]): ALERT_LABEL.get(str(r["区分"]), str(r["区分"]))
                for _, r in al.iterrows()}
        for c in flags:
            if c in amap:
                flags[c].append(amap[c])

    # 暗号資産トレジャリーのキーワード検出(事業内容＋短信見通し)
    texts = {}
    biz_path = os.path.join(BASE, "business_ja.csv")
    if os.path.exists(biz_path):
        biz = pd.read_csv(biz_path, dtype=str, encoding="utf-8-sig")
        for _, r in biz.iterrows():
            texts[code4(r["コード"])] = str(r.get("事業内容", ""))
    if "来期見通し(短信抜粋)" in df.columns:
        for c, t in zip(c4, df["来期見通し(短信抜粋)"].fillna("")):
            texts[c] = texts.get(c, "") + " " + str(t)
    for c in flags:
        if CRYPTO_PAT.search(texts.get(c, "")):
            flags[c].append("⚠暗号資産保有")

    ov_path = os.path.join(BASE, "flags_overrides.csv")
    if os.path.exists(ov_path):
        ov = pd.read_csv(ov_path, dtype=str, encoding="utf-8-sig")
        for _, r in ov.iterrows():
            c = code4(r["コード"])
            v = str(r.get("注意", "")).strip()
            if c in flags and v and v not in flags[c]:
                flags[c].append(v)

    df["注意"] = [ "・".join(dict.fromkeys(flags[c])) for c in c4 ]
    df.to_csv(args.results, index=False, encoding="utf-8-sig")
    n = int((df["注意"] != "").sum())
    hits = df.loc[df["注意"] != "", ["コード", "銘柄名", "注意"]]
    print(f"注意フラグ付与: {n}/{len(df)}銘柄")
    if n:
        print(hits.to_string(index=False))


if __name__ == "__main__":
    main()
