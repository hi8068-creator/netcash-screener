#!/usr/bin/env python3
"""
ネットキャッシュ比率スクリーニングの共通ロジック。
CLI(screen.py)と Web アプリ(app.py)の両方から使う。

ネットキャッシュ比率 = (流動資産 + 投資有価証券*0.7 - 負債) / 時価総額
比率 >= 1.0 で「会社がただで買えるほど割安」(清原達郎氏の基準)。
"""

import csv
import io
import os
from dataclasses import dataclass, asdict
from typing import Optional, Callable

import pandas as pd
import requests
import yfinance as yf

# 手動の時価総額上書き(Yahooの発行株数破損などで時価総額が壊れる銘柄の救済)。
# marketcap_overrides.csv: コード,時価総額円,メモ
_MC_OVERRIDES = {}
_mc_path = os.path.join(os.path.dirname(__file__), "marketcap_overrides.csv")
if os.path.exists(_mc_path):
    try:
        with open(_mc_path, encoding="utf-8-sig") as _f:
            for _row in csv.DictReader(_f):
                _code = str(_row.get("コード", "")).strip().zfill(4)
                _val = str(_row.get("時価総額円", "")).strip()
                if _code and _val:
                    _MC_OVERRIDES[_code] = float(_val)
    except Exception:
        pass

JPX_XLS_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)

# 投資有価証券に対応しうる yfinance フィールド(上から優先採用)
INVESTMENT_SECURITY_KEYS = [
    "Available For Sale Securities",
    "Investmentin Financial Assets",
    "Long Term Equity Investment",
]

COLUMNS_JP = [
    "コード", "銘柄名", "ネットキャッシュ比率",
    "ネットキャッシュ(億円)", "時価総額(億円)",
    "流動資産", "投資有価証券", "負債", "決算期",
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


def to_ticker(code: str) -> str:
    code = str(code).strip().upper()
    if not code:
        return ""
    if "." not in code:
        code = f"{code}.T"
    return code


def _bs_value(bs, col, keys) -> Optional[float]:
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


def _market_cap_and_name(t) -> tuple:
    """時価総額と銘柄名を取得。軽量な fast_info を優先し、欠ける場合のみ info にフォールバック。

    t.info は多数フィールドを取得しに行き Yahoo のレート制限を誘発しやすいため、
    まず fast_info(価格・発行株数ベースの軽量取得)で時価総額を取る。
    fast_info に銘柄名は無いので、軽量パスでは name は空になる
    (呼び出し側で JPX 一覧の日本語名を補完する想定)。info フォールバック時のみ名前も得る。
    """
    market_cap = None
    name = ""
    try:
        # FastInfo は属性が snake_case(market_cap)、dictキーは camelCase(marketCap)。
        # 属性アクセスが安定するためそちらを使う。
        market_cap = getattr(t.fast_info, "market_cap", None)
    except Exception:
        market_cap = None
    if not market_cap:
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        market_cap = info.get("marketCap")
        name = info.get("shortName") or info.get("longName") or ""
    return market_cap, name


def evaluate(code: str) -> Optional[Result]:
    """1銘柄を評価。取得不可なら None。"""
    ticker = to_ticker(code)
    if not ticker:
        return None
    t = yf.Ticker(ticker)
    bs = t.balance_sheet
    if bs is None or bs.empty:
        return None
    col = bs.columns[0]
    current_assets = _bs_value(bs, col, "Current Assets")
    total_liabilities = _bs_value(bs, col, "Total Liabilities Net Minority Interest")
    if current_assets is None or total_liabilities is None:
        return None
    inv = _bs_value(bs, col, INVESTMENT_SECURITY_KEYS) or 0.0
    code4 = ticker.replace(".T", "")
    override_mc = _MC_OVERRIDES.get(code4)
    if override_mc:
        market_cap, name = override_mc, ""
    else:
        market_cap, name = _market_cap_and_name(t)
        if not market_cap:
            return None
        # 時価総額データの健全性チェック。
        # Yahooがまれに発行済株式数を壊れた値(例: 3株)で返し、時価総額が極端に小さくなる。
        # 実在の上場企業で時価総額が流動資産の1%未満はあり得ないため、壊れデータとして除外する
        # (marketcap_overrides.csv で正しい値を与えれば救済できる)。
        if market_cap < 1e7 or (current_assets > 0 and market_cap < current_assets * 0.01):
            return None
    net_cash = current_assets + inv * 0.7 - total_liabilities
    return Result(
        code=ticker,
        name=name,
        market_cap=float(market_cap),
        current_assets=current_assets,
        investment_securities=inv,
        total_liabilities=total_liabilities,
        net_cash=net_cash,
        ratio=net_cash / market_cap,
        fiscal_date=str(col.date()) if hasattr(col, "date") else str(col),
    )


def fetch_jpx_universe(markets=None, exclude_etf=True) -> pd.DataFrame:
    """JPX上場銘柄一覧を取得して DataFrame で返す。

    列: コード, 銘柄名, 市場, 業種(33業種区分), 業種大分類(17業種区分), 規模(規模区分)
    """
    resp = requests.get(JPX_XLS_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content))
    code_col = next(c for c in df.columns if "コード" in str(c))
    name_col = next((c for c in df.columns if "銘柄名" in str(c)), None)
    market_col = next((c for c in df.columns if "市場" in str(c)), None)
    sec33_col = next((c for c in df.columns if "33業種区分" in str(c)), None)
    sec17_col = next((c for c in df.columns if "17業種区分" in str(c)), None)
    size_col = next((c for c in df.columns if "規模区分" in str(c)), None)
    if markets and market_col:
        df = df[df[market_col].astype(str).apply(lambda v: any(m in v for m in markets))]
    if exclude_etf and market_col:
        df = df[df[market_col].astype(str).str.contains("株式", na=False)]

    def col(c):
        return df[c].astype(str) if c else ""

    out = pd.DataFrame({
        "コード": df[code_col].astype(str).str.replace(r"\.0$", "", regex=True).str.strip(),
        "銘柄名": col(name_col),
        "市場": col(market_col),
        "業種": col(sec33_col),
        "業種大分類": col(sec17_col),
        "規模": col(size_col),
    })
    # 2024年以降の英数字コード(例: 285A キオクシア)も含める。
    # TSEコードは4文字で先頭が数字、以降は数字または英大文字。
    out = out[out["コード"].str.fullmatch(r"[0-9][0-9A-Z]{3}")]
    return out.reset_index(drop=True)


def run_screen(
    codes,
    min_ratio: float = 1.0,
    sleep: float = 0.3,
    progress: Optional[Callable[[int, int, Optional[Result]], None]] = None,
) -> pd.DataFrame:
    """銘柄コードのリストを評価し、比率降順の DataFrame を返す。

    progress(i, total, result) を渡すと進捗コールバックされる。
    """
    import time
    results = []
    total = len(codes)
    for i, code in enumerate(codes, 1):
        r = None
        try:
            r = evaluate(code)
        except Exception:
            r = None
        if r is not None:
            results.append(r)
        if progress:
            progress(i, total, r)
        if sleep:
            time.sleep(sleep)
    df = results_to_df(results)
    if not df.empty:
        df = df[df["ネットキャッシュ比率"] >= min_ratio]
        df = df.sort_values("ネットキャッシュ比率", ascending=False).reset_index(drop=True)
    return df


def attach_universe_meta(df: pd.DataFrame, uni: pd.DataFrame) -> pd.DataFrame:
    """スクリーニング結果に JPX 一覧の市場区分と日本語銘柄名を補完する。

    evaluate() の軽量パス(fast_info)では銘柄名が空になるため、ここで JPX の
    日本語名で補完(空のときのみ上書き)し、市場列も付与する。
    """
    if df.empty:
        return df
    cols = ["コード", "銘柄名", "市場"]
    for extra in ["業種", "業種大分類", "規模"]:
        if extra in uni.columns:
            cols.append(extra)
    meta = uni.assign(コード=uni["コード"].astype(str) + ".T")[cols]
    meta = meta.rename(columns={"銘柄名": "_銘柄名_jpx"})
    # 既存の同名列があれば付け直しのため一旦落とす(市場含む。_x/_y衝突を防ぐ)
    drop = [c for c in ["市場", "業種", "業種大分類", "規模"]
            if c in df.columns and c in meta.columns]
    out = df.drop(columns=drop).merge(meta, on="コード", how="left")
    jp = out["_銘柄名_jpx"].fillna("")
    cur = out["銘柄名"].fillna("") if "銘柄名" in out.columns else ""
    out["銘柄名"] = [c if str(c).strip() else j for c, j in zip(cur, jp)]
    return out.drop(columns=["_銘柄名_jpx"])


def results_to_df(results) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "コード": r.code,
            "銘柄名": r.name,
            "ネットキャッシュ比率": round(r.ratio, 3),
            "ネットキャッシュ(億円)": round(r.net_cash / 1e8, 1),
            "時価総額(億円)": round(r.market_cap / 1e8, 1),
            "流動資産": round(r.current_assets),
            "投資有価証券": round(r.investment_securities),
            "負債": round(r.total_liabilities),
            "決算期": r.fiscal_date,
        })
    return pd.DataFrame(rows, columns=COLUMNS_JP)


def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """結果 DataFrame を整形済み Excel(.xlsx)のバイト列にする。"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="screening")
        ws = writer.sheets["screening"]
        # 列幅自動調整
        for col_cells in ws.columns:
            length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
            ws.column_dimensions[col_cells[0].column_letter].width = min(length + 2, 40)
        # ヘッダ太字＋フィルタ
        from openpyxl.styles import Font
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"
    return buf.getvalue()
