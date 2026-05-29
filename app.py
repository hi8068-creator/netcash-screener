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

st.dataframe(df, use_container_width=True, hide_index=True)

if len(df):
    ts = datetime.now().strftime("%Y%m%d")
    st.download_button(
        "⬇️ Excelでダウンロード",
        data=core.df_to_excel_bytes(df),
        file_name=f"netcash_screening_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.download_button(
        "⬇️ CSVでダウンロード",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"netcash_screening_{ts}.csv",
        mime="text/csv",
    )
