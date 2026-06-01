#!/usr/bin/env python3
"""
JPX(日本取引所グループ)公開の上場銘柄一覧から証券コード一覧を生成する。

出力した tickers ファイルを screen.py の入力に使う。
データ元(無料・公開):
  https://www.jpx.co.jp/markets/statistics-equities/misc/01.html
"""

import argparse
import io
import sys

import pandas as pd
import requests

JPX_XLS_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)


def main():
    ap = argparse.ArgumentParser(description="JPX上場銘柄一覧から証券コードを抽出")
    ap.add_argument("--out", default="tickers_all.txt", help="出力ファイル")
    ap.add_argument(
        "--market",
        action="append",
        help="市場区分でフィルタ(部分一致, 複数指定可)。"
        "例: --market プライム --market スタンダード --market グロース",
    )
    ap.add_argument(
        "--exclude-etf",
        action="store_true",
        help="ETF・REIT・出資証券など株式以外を除外する",
    )
    args = ap.parse_args()

    print(f"JPX一覧をダウンロード中: {JPX_XLS_URL}", file=sys.stderr)
    resp = requests.get(JPX_XLS_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content))

    # 列名は「コード」「銘柄名」「市場・商品区分」「33業種区分」等
    code_col = next(c for c in df.columns if "コード" in str(c))
    market_col = next((c for c in df.columns if "市場" in str(c)), None)

    n_before = len(df)

    if args.market and market_col:
        mask = df[market_col].astype(str).apply(
            lambda v: any(m in v for m in args.market)
        )
        df = df[mask]

    if args.exclude_etf and market_col:
        # 「内国株式」「外国株式」など"株式"を含む区分のみ残す
        df = df[df[market_col].astype(str).str.contains("株式", na=False)]

    codes = (
        df[code_col]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    # 4文字コード(先頭数字＋数字/英大文字)。2024年以降の英数字コードも採用。
    import re as _re
    codes = [c for c in codes if _re.fullmatch(r"[0-9][0-9A-Z]{3}", c)]

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# JPX上場銘柄一覧から生成\n")
        for c in codes:
            f.write(c + "\n")

    print(
        f"{n_before}件中 {len(codes)}件のコードを {args.out} に書き出しました。",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
