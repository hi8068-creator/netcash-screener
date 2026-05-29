#!/usr/bin/env python3
"""
清原達郎式「ネットキャッシュ比率」による日本株スクリーニングツール。

ネットキャッシュ比率 = ネットキャッシュ / 時価総額
ネットキャッシュ      = 流動資産 + 投資有価証券 * 0.7 - 負債

比率が 1.0 以上なら「会社がただで買えるほど割安」という清原氏の判断基準。
データは yfinance(Yahoo Finance, 無料)から取得する。
"""

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from typing import Optional

import yfinance as yf


# 投資有価証券に対応しうる yfinance のフィールド(上から優先的に採用)
INVESTMENT_SECURITY_KEYS = [
    "Available For Sale Securities",
    "Investmentin Financial Assets",
    "Long Term Equity Investment",
]


@dataclass
class Result:
    code: str
    name: str
    market_cap: float
    current_assets: float
    investment_securities: float
    total_liabilities: float
    net_cash: float
    ratio: float
    fiscal_date: str

    @property
    def net_cash_oku(self) -> float:
        return self.net_cash / 1e8

    @property
    def market_cap_oku(self) -> float:
        return self.market_cap / 1e8


def _to_ticker(code: str) -> str:
    code = code.strip().upper()
    if not code:
        return ""
    # 4桁の証券コードには .T を付与(既に .T などが付いていればそのまま)
    if "." not in code:
        code = f"{code}.T"
    return code


def _bs_value(bs, col, keys) -> Optional[float]:
    """貸借対照表(DataFrame)から、キー候補のうち最初に値が取れたものを返す。"""
    if isinstance(keys, str):
        keys = [keys]
    for k in keys:
        try:
            v = bs.loc[k, col]
        except KeyError:
            continue
        if v is not None and v == v:  # NaN 除外
            return float(v)
    return None


def evaluate(code: str) -> Optional[Result]:
    ticker = _to_ticker(code)
    if not ticker:
        return None

    t = yf.Ticker(ticker)
    bs = t.balance_sheet
    if bs is None or bs.empty:
        return None

    col = bs.columns[0]  # 最新期

    current_assets = _bs_value(bs, col, "Current Assets")
    total_liabilities = _bs_value(bs, col, "Total Liabilities Net Minority Interest")
    if current_assets is None or total_liabilities is None:
        return None

    inv = _bs_value(bs, col, INVESTMENT_SECURITY_KEYS) or 0.0

    info = t.info or {}
    market_cap = info.get("marketCap")
    if not market_cap:
        return None

    net_cash = current_assets + inv * 0.7 - total_liabilities
    ratio = net_cash / market_cap

    return Result(
        code=ticker,
        name=info.get("shortName") or info.get("longName") or "",
        market_cap=float(market_cap),
        current_assets=current_assets,
        investment_securities=inv,
        total_liabilities=total_liabilities,
        net_cash=net_cash,
        ratio=ratio,
        fiscal_date=str(col.date()) if hasattr(col, "date") else str(col),
    )


def load_codes(path: str) -> list:
    codes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # カンマ区切りの先頭をコードとして扱う(CSVにも対応)
            codes.append(line.split(",")[0])
    return codes


def main():
    ap = argparse.ArgumentParser(
        description="ネットキャッシュ比率で日本株をスクリーニングする"
    )
    ap.add_argument(
        "tickers_file",
        help="証券コードを1行1件で記載したファイル(例: 7203 または 7203.T)",
    )
    ap.add_argument(
        "--min-ratio",
        type=float,
        default=1.0,
        help="抽出するネットキャッシュ比率の下限(既定: 1.0)",
    )
    ap.add_argument(
        "--out",
        default="results.csv",
        help="結果CSVの出力先(既定: results.csv)",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="銘柄ごとのリクエスト間隔(秒, 既定: 0.5)",
    )
    args = ap.parse_args()

    codes = load_codes(args.tickers_file)
    print(f"対象 {len(codes)} 銘柄を評価します...\n", file=sys.stderr)

    results = []
    for i, code in enumerate(codes, 1):
        try:
            r = evaluate(code)
        except Exception as e:
            print(f"  [{i}/{len(codes)}] {code}: エラー {e}", file=sys.stderr)
            r = None
        if r is None:
            print(f"  [{i}/{len(codes)}] {code}: データ取得不可・スキップ", file=sys.stderr)
        else:
            mark = "★" if r.ratio >= args.min_ratio else " "
            print(
                f"  [{i}/{len(codes)}] {mark} {r.code} {r.name[:20]:<20} 比率={r.ratio:6.2f}",
                file=sys.stderr,
            )
            results.append(r)
        if args.sleep:
            time.sleep(args.sleep)

    hits = [r for r in results if r.ratio >= args.min_ratio]
    hits.sort(key=lambda r: r.ratio, reverse=True)

    # CSV 出力(抽出された全銘柄を比率降順で)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "コード",
                "銘柄名",
                "ネットキャッシュ比率",
                "ネットキャッシュ(億円)",
                "時価総額(億円)",
                "流動資産",
                "投資有価証券",
                "負債",
                "決算期",
            ]
        )
        for r in hits:
            w.writerow(
                [
                    r.code,
                    r.name,
                    f"{r.ratio:.3f}",
                    f"{r.net_cash_oku:.1f}",
                    f"{r.market_cap_oku:.1f}",
                    f"{r.current_assets:.0f}",
                    f"{r.investment_securities:.0f}",
                    f"{r.total_liabilities:.0f}",
                    r.fiscal_date,
                ]
            )

    print(
        f"\n=== ネットキャッシュ比率 >= {args.min_ratio} の銘柄: {len(hits)}件 ===",
        file=sys.stderr,
    )
    for r in hits:
        print(
            f"  {r.code} {r.name[:24]:<24} 比率={r.ratio:6.2f}  "
            f"ネットキャッシュ={r.net_cash_oku:8.1f}億  時価総額={r.market_cap_oku:8.1f}億",
            file=sys.stderr,
        )
    print(f"\n結果を {args.out} に保存しました。", file=sys.stderr)


if __name__ == "__main__":
    main()
