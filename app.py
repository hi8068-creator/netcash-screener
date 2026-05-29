#!/usr/bin/env python3
"""
ネットキャッシュ比率スクリーニング Web アプリ(Streamlit)。

- 起動時は同梱の results.csv(事前計算済み)を即表示
- 市場・比率でフィルタ、Excel/CSV ダウンロード
- 「最新データで再計算」ボタンでライブ取得(時間がかかる)
"""

import os
from datetime import datetime

import pandas as pd
import streamlit as st

import core

st.set_page_config(page_title="ネットキャッシュ比率スクリーニング", layout="wide")

RESULTS_CSV = os.path.join(os.path.dirname(__file__), "results.csv")

# 財務数値の確認先(株探: 業績/財務を百万円表示し、決算短信へのリンクもある)
KABUTAN_BASE = "https://kabutan.jp/stock/finance?code="
# 公式の決算短信PDFへの経路(Yahoo!ファイナンス適時開示。TDnet掲載の公式PDFにリンク)
YAHOO_DISCLOSURE_BASE = "https://finance.yahoo.co.jp/quote/"

# 表示時の列順(存在する列のみ採用)。金額は百万円表示にして決算短信と突き合わせやすくする。
DISPLAY_ORDER = [
    "コード", "銘柄名", "市場", "ネットキャッシュ比率",
    "ネットキャッシュ(億円)", "時価総額(億円)",
    "流動資産(百万円)", "投資有価証券(百万円)", "負債(百万円)",
    "決算期", "来期見通し(短信抜粋)", "財務(株探)", "短信PDF",
]


def to_display(df: pd.DataFrame) -> pd.DataFrame:
    """表示・ダウンロード用に整形。

    - 流動資産/投資有価証券/負債(円)を百万円に換算(決算短信の一般的な単位)
    - 右端に財務確認リンク(株探)と公式の決算短信PDFリンクを追加
      (個別PDFのURLが分かる銘柄は直リンク、なければ適時開示一覧へ)
    """
    d = df.copy()
    for col in ["流動資産", "投資有価証券", "負債"]:
        if col in d.columns:
            d[f"{col}(百万円)"] = (
                pd.to_numeric(d[col], errors="coerce") / 1e6
            ).round().astype("Int64")
            d = d.drop(columns=[col])
    if "コード" in d.columns:
        code = d["コード"].astype(str)
        code4 = code.str.replace(".T", "", regex=False)
        d["財務(株探)"] = KABUTAN_BASE + code4
        disclosure = YAHOO_DISCLOSURE_BASE + code + "/disclosure"
        if "短信PDF直URL" in d.columns:
            direct = d["短信PDF直URL"].fillna("").astype(str)
            d["短信PDF"] = [
                dr if dr.strip() else ds for dr, ds in zip(direct, disclosure)
            ]
            d = d.drop(columns=["短信PDF直URL"])
        else:
            d["短信PDF"] = disclosure
    ordered = [c for c in DISPLAY_ORDER if c in d.columns]
    rest = [c for c in d.columns if c not in ordered]
    return d[ordered + rest]

st.title("📊 ネットキャッシュ比率スクリーニング")
st.caption(
    "清原達郎式: ネットキャッシュ比率 = (流動資産 + 投資有価証券×0.7 − 負債) ÷ 時価総額。"
    " 1.0以上なら『会社がただで買えるほど割安』。データ元: Yahoo Finance(無料)。"
)


@st.cache_data(show_spinner=False)
def load_bundled() -> pd.DataFrame:
    if os.path.exists(RESULTS_CSV):
        return pd.read_csv(RESULTS_CSV)
    return pd.DataFrame(columns=core.COLUMNS_JP)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def evaluate_cached(code: str):
    """1銘柄評価をキャッシュ(6時間)。再描画や再実行での重複取得を防ぐ。"""
    r = core.evaluate(code)
    return core.asdict(r) if r is not None else None


if "df" not in st.session_state:
    st.session_state.df = load_bundled()

with st.sidebar:
    st.header("表示フィルタ")
    min_ratio = st.slider("ネットキャッシュ比率の下限", 0.0, 3.0, 1.0, 0.05)
    markets_all = sorted(
        m for m in st.session_state.df.get("市場", pd.Series(dtype=str)).dropna().unique()
    ) if "市場" in st.session_state.df.columns else []
    sel_markets = st.multiselect("市場区分", markets_all, default=markets_all)

    st.divider()
    st.header("最新データで再計算")
    st.warning(
        "Yahoo Financeから取得し直します。**共有サーバー(クラウド)ではレート制限で途中停止しやすい**ため、"
        "通常は同梱の事前計算データの閲覧で十分です。再計算は少数銘柄での確認向けです。"
    )
    market_choice = st.multiselect(
        "対象市場", ["プライム", "スタンダード", "グロース"], default=["グロース"]
    )
    max_n = st.number_input("最大銘柄数(クラウドでは50以下推奨)", 1, 5000, 50, 10)
    run = st.button("🔄 再計算する", type="primary")

def _build_df(dict_results, uni):
    results = [core.Result(**d) for d in dict_results if d]
    df = core.results_to_df(results)
    if not df.empty:
        df = core.attach_universe_meta(df, uni)
        df = df.sort_values("ネットキャッシュ比率", ascending=False).reset_index(drop=True)
    return df


if run:
    import time
    collected = []
    uni = None
    try:
        uni = core.fetch_jpx_universe(markets=market_choice, exclude_etf=True)
        codes = uni["コード"].tolist()[: int(max_n)]
        bar = st.progress(0.0, text="取得中...")
        log = st.empty()
        total = len(codes)
        for i, code in enumerate(codes, 1):
            try:
                d = evaluate_cached(code)
            except Exception:
                d = None
            if d:
                collected.append(d)
                log.write(f"{d['code']} 比率={d['net_cash'] / d['market_cap']:.2f}")
            bar.progress(i / total, text=f"{i}/{total} 取得中...")
            time.sleep(0.3)
        bar.empty()
        st.session_state.df = _build_df(collected, uni)
        st.success(f"再計算完了: {len(st.session_state.df)}銘柄を取得しました。")
    except Exception as e:
        # レート制限などで中断しても、取得済み分は表示する
        if uni is not None and collected:
            st.session_state.df = _build_df(collected, uni)
            st.warning(f"途中で中断しました（{len(collected)}件まで取得）。表示は取得済み分です。詳細: {e}")
        else:
            st.error(f"再計算でエラー: {e}")

df = st.session_state.df.copy()
if "ネットキャッシュ比率" in df.columns:
    df = df[df["ネットキャッシュ比率"] >= min_ratio]
if sel_markets and "市場" in df.columns:
    df = df[df["市場"].isin(sel_markets)]
df = df.sort_values("ネットキャッシュ比率", ascending=False).reset_index(drop=True)

c1, c2, c3 = st.columns(3)
c1.metric("該当銘柄数", f"{len(df)} 件")
if len(df):
    c2.metric("最大比率", f"{df['ネットキャッシュ比率'].max():.2f}")
    c3.metric("比率1.0以上", f"{(df['ネットキャッシュ比率'] >= 1.0).sum()} 件")

disp = to_display(df)

st.dataframe(
    disp,
    width="stretch",
    hide_index=True,
    column_config={
        "財務(株探)": st.column_config.LinkColumn(
            "財務(株探)",
            help="株探の財務ページ。業績・財務が百万円表示で、数値の照合に便利です。",
            display_text="開く",
        ),
        "短信PDF": st.column_config.LinkColumn(
            "短信PDF(公式)",
            help="公式の決算短信PDF(TDnet掲載)。比率1.0以上の銘柄は個別PDFへ直リンク、"
            "それ以外はYahoo!ファイナンスの適時開示一覧へ。",
            display_text="開く",
        ),
        "来期見通し(短信抜粋)": st.column_config.TextColumn(
            "来期見通し(短信抜粋)",
            help="決算短信の「今後の見通し」本文をそのまま抜粋(言い換えなし)。比率1.0以上の銘柄に付与。",
            width="large",
        ),
        "ネットキャッシュ比率": st.column_config.NumberColumn(format="%.2f"),
    },
)
st.caption(
    "金額は百万円表示（決算短信の一般的な単位）。データ元のYahoo Financeは決算短信の千円/百万円表記に関わらず"
    "「円」の絶対額に正規化されるため、銘柄間で単位は揃っています。"
    "右端の「短信PDF(公式)」から実際の決算短信PDF（TDnet掲載）と照合できます。"
    "「来期見通し(短信抜粋)」は比率1.0以上の銘柄に、短信本文の該当箇所をそのまま抜粋（言い換えなし）して掲載しています。"
)

if len(df):
    ts = datetime.now().strftime("%Y%m%d")
    st.download_button(
        "⬇️ Excelでダウンロード",
        data=core.df_to_excel_bytes(disp),
        file_name=f"netcash_screening_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.download_button(
        "⬇️ CSVでダウンロード",
        data=disp.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"netcash_screening_{ts}.csv",
        mime="text/csv",
    )
