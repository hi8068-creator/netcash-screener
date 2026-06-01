#!/usr/bin/env python3
"""決算短信の見通し全文(outlook_full.csv)から、読みやすい要約を作る。

方針: 原文の文を選んで組み立てる(言い換えなし=ハルシネーションなし)。
  - 定型の注意書き文は除外
  - 次期業績予想(売上高・利益+数値)の文を最優先で採用
  - 経営環境・方針の文を1つ補助的に採用
  - 文末(。)で揃え、約160字以内に整える
出力: outlook_summary.csv (コード, 来期見通し要約)
"""
import re

import pandas as pd

BOILER = ["将来に関する記述", "約束する趣旨", "入手可能な情報", "ご利用", "本資料",
          "前提となる条件", "適切な利用", "予想数値と異なる", "とは異なる可能性",
          "ご覧ください", "記載しており", "様々な要因により", "大きく異なる可能性",
          "実際の業績", "現時点で入手", "判断したものであり"]

LABELS = ["今後の見通し", "次期の見通し", "業績見通し", "通期の見通し",
          "次期の業績見通し", "次年度の見通し", "翌期の見通し", "(4)今後の見通し",
          "（４）今後の見通し"]

FORECAST_KEY = ["売上高", "営業利益", "経常利益", "純利益", "営業損失", "経常損失"]
FORECAST_HINT = ["見込", "予想", "計画", "見通し", "目指", "想定", "とおり", "通り"]
ENV_KEY = ["経済", "景気", "環境", "情勢", "業界", "市場", "需要", "当社", "当グループ",
           "当社グループ", "引き続き", "セグメント"]
NEXT_KEY = ["次期", "翌期", "通期", "次年度", "来期", "次連結会計年度", "20"]


def split_sentences(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    parts = re.split(r"(?<=。)", text)
    return [p.strip() for p in parts if len(p.strip()) >= 8]


def _strip_label(s):
    for lb in LABELS:
        if s.startswith(lb):
            s = s[len(lb):].lstrip("　 :：")
    return s


def summarize(text, limit=170):
    sents = split_sentences(text)
    sents = [_strip_label(s) for s in sents]
    # 目次・見出し羅列(ドットリーダー等)や定型注意書きを除外
    sents = [s for s in sents
             if s and "…" not in s and "目次" not in s
             and "決算短信" not in s
             and not any(b in s for b in BOILER)]
    if not sents:
        return ""

    def is_forecast(s):
        return any(k in s for k in FORECAST_KEY) and (
            any(h in s for h in FORECAST_HINT) or any(n in s for n in NEXT_KEY))

    forecast = next((s for s in sents if is_forecast(s)), "")
    env = next((s for s in sents if any(k in s for k in ENV_KEY) and s != forecast), "")

    # 予想数値の文を最優先。次に環境/方針の文を、limit内に収まる範囲で前置き。
    if forecast:
        out = forecast
        if env and len(env) + len(out) <= limit and text.find(env) < text.find(forecast):
            out = env + out
        elif env and len(env) + len(out) <= limit:
            out = out + env
    else:
        out = env or sents[0]

    if len(out) > limit:
        # 文の途中で切らず、最初の1文に収める
        first = re.split(r"(?<=。)", out)[0]
        out = first if first else out[:limit]
    # 文頭の助詞断片を整える(ラベル除去で「につきましては…」等になった場合)
    # 長い候補を先に並べる(最長一致させる)
    out = re.sub(r"^(につきましては|につきまして|については|について|においては|としましては|としまして)[はをが、]*",
                 "次期は", out.strip())
    out = re.sub(r"^次期は次期", "次期は", out)
    # PDF抽出由来の不要な空白(日本語の語中スペース)を除去
    out = re.sub(r"\s+(?=[^\x00-\x7F])", "", out)
    out = re.sub(r"(?<=[^\x00-\x7F])\s+", "", out)
    return out.strip()


def main():
    full = pd.read_csv("outlook_full.csv", dtype={"コード": str})
    rows = []
    for _, r in full.iterrows():
        rows.append({
            "コード": str(r["コード"]).zfill(4),
            "来期見通し要約": summarize(r.get("見通し原文", "")),
        })
    out = pd.DataFrame(rows)
    out.to_csv("outlook_summary.csv", index=False, encoding="utf-8-sig")
    got = out["来期見通し要約"].fillna("").str.strip().ne("").sum()
    print(f"要約完了: {got}/{len(out)} 社 → outlook_summary.csv")
    print(f"平均文字数: {int(out['来期見通し要約'].fillna('').str.len().mean())}")


if __name__ == "__main__":
    main()
