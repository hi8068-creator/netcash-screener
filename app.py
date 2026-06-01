#!/usr/bin/env python3
"""
ネットキャッシュ比率スクリーニング Web アプリ(Streamlit)。

- 起動時は同梱の results.csv(事前計算済み)を即表示
- 市場・比率でフィルタ、Excel/CSV ダウンロード
- 「最新データで再計算」ボタンでライブ取得(時間がかかる)
"""

import os
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

import core

st.set_page_config(page_title="ネットキャッシュ比率スクリーニング", layout="wide")

RESULTS_CSV = os.path.join(os.path.dirname(__file__), "results.csv")

# 財務数値の確認先(株探: 業績/財務を百万円表示し、決算短信へのリンクもある)
KABUTAN_BASE = "https://kabutan.jp/stock/finance?code="
# 公式の決算短信PDFへの経路(Yahoo!ファイナンス適時開示。TDnet掲載の公式PDFにリンク)
YAHOO_DISCLOSURE_BASE = "https://finance.yahoo.co.jp/quote/"
# 株主優待の確認先(みんかぶ優待ページ)。無料の一括取得は精度難のためリンク提供に留める。
MINKABU_YUTAI_BASE = "https://minkabu.jp/stock/"

# 表示時の列順(存在する列のみ採用)。金額は百万円表示にして決算短信と突き合わせやすくする。
DISPLAY_ORDER = [
    "コード", "銘柄名", "市場", "業種", "新業種", "業種根拠", "規模", "ネットキャッシュ比率",
    "ネットキャッシュ(億円)", "時価総額(億円)",
    "PER", "業種PER中央値", "PER乖離率", "PBR",
    "前日終値", "配当利回り(%)", "配当", "予想PER", "forwardEPS", "目標株価",
    "流動資産(百万円)", "投資有価証券(百万円)", "負債(百万円)",
    "決算期", "来期見通し(短信抜粋)", "財務(株探)", "短信PDF", "優待",
]

# 表示しない内部列(算出の元データ)
HIDE_COLS = ["純利益", "純資産", "業種大分類"]


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
        d["優待"] = MINKABU_YUTAI_BASE + code4 + "/yutai"
        disclosure = YAHOO_DISCLOSURE_BASE + code + "/disclosure"
        if "短信PDF直URL" in d.columns:
            direct = d["短信PDF直URL"].fillna("").astype(str)
            d["短信PDF"] = [
                dr if dr.strip() else ds for dr, ds in zip(direct, disclosure)
            ]
            d = d.drop(columns=["短信PDF直URL"])
        else:
            d["短信PDF"] = disclosure
    d = d.drop(columns=[c for c in HIDE_COLS if c in d.columns])
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

    # 業種(33業種)フィルタ
    sectors_all = sorted(
        s for s in st.session_state.df.get("業種", pd.Series(dtype=str)).dropna().unique()
        if str(s).strip() and str(s) != "nan"
    ) if "業種" in st.session_state.df.columns else []
    sel_sectors = st.multiselect("業種(33業種)", sectors_all, default=[])

    # 新60業種フィルタ
    sectors60_all = sorted(
        s for s in st.session_state.df.get("新業種", pd.Series(dtype=str)).dropna().unique()
        if str(s).strip() and str(s) != "nan"
    ) if "新業種" in st.session_state.df.columns else []
    sel_sectors60 = st.multiselect("業種(新60業種・試験版)", sectors60_all, default=[])

    cheap_only = False
    if "PER乖離率" in st.session_state.df.columns:
        cheap_only = st.checkbox(
            "同業比で割安のみ(PERが業種中央値より低い)", value=False,
            help="PER乖離率 < 0 の銘柄に絞り込みます。",
        )

    min_yield = 0.0
    if "配当利回り(%)" in st.session_state.df.columns:
        min_yield = st.slider("配当利回りの下限(%)", 0.0, 6.0, 0.0, 0.25)

    max_per = 0
    if "PER" in st.session_state.df.columns:
        max_per = st.number_input("PER上限(0=制限なし)", 0, 200, 0, 5)

    max_pbr = 0.0
    if "PBR" in st.session_state.df.columns:
        max_pbr = st.number_input("PBR上限(0=制限なし)", 0.0, 20.0, 0.0, 0.5)

    # 時価総額(億円)レンジ。小型株(清原流)に絞りやすく。
    max_cap = 0
    if "時価総額(億円)" in st.session_state.df.columns:
        cap_series = pd.to_numeric(st.session_state.df["時価総額(億円)"], errors="coerce")
        cap_hi = int(min(5000, (cap_series.max() if cap_series.notna().any() else 1000)))
        max_cap = st.number_input("時価総額の上限(億円, 0=制限なし)", 0, cap_hi, 0, 50,
                                  help="小型株に絞るなら例: 300")

    sort_key = "ネットキャッシュ比率"
    sort_opts = [c for c in ["ネットキャッシュ比率", "配当利回り(%)", "PER乖離率", "PER", "時価総額(億円)"]
                 if c in st.session_state.df.columns]
    sort_key = st.selectbox("並び替え", sort_opts, index=0)
    sort_asc = st.checkbox("昇順", value=(sort_key in ("PER", "PER乖離率")))

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
if sel_sectors and "業種" in df.columns:
    df = df[df["業種"].isin(sel_sectors)]
if sel_sectors60 and "新業種" in df.columns:
    df = df[df["新業種"].isin(sel_sectors60)]
if cheap_only and "PER乖離率" in df.columns:
    df = df[pd.to_numeric(df["PER乖離率"], errors="coerce") < 0]
if min_yield > 0 and "配当利回り(%)" in df.columns:
    df = df[pd.to_numeric(df["配当利回り(%)"], errors="coerce") >= min_yield]
if max_per and "PER" in df.columns:
    per_v = pd.to_numeric(df["PER"], errors="coerce")
    df = df[(per_v > 0) & (per_v <= max_per)]
if max_pbr and "PBR" in df.columns:
    pbr_v = pd.to_numeric(df["PBR"], errors="coerce")
    df = df[(pbr_v > 0) & (pbr_v <= max_pbr)]
if max_cap and "時価総額(億円)" in df.columns:
    cap_v = pd.to_numeric(df["時価総額(億円)"], errors="coerce")
    df = df[cap_v <= max_cap]
if sort_key in df.columns:
    df = df.sort_values(sort_key, ascending=sort_asc,
                        key=lambda s: pd.to_numeric(s, errors="coerce")).reset_index(drop=True)
else:
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
        "優待": st.column_config.LinkColumn(
            "優待(みんかぶ)",
            help="株主優待の確認先(みんかぶ)。無料の一括取得は精度が低いため、内容はリンク先で確認。",
            display_text="確認",
        ),
        "来期見通し(短信抜粋)": st.column_config.TextColumn(
            "来期見通し(要約)",
            help="決算短信の「今後の見通し」から、次期業績予想と経営環境の要点を原文の文で抜き出して整形(言い換えなし)。比率1.0以上の銘柄に付与。",
            width="large",
        ),
        "ネットキャッシュ比率": st.column_config.NumberColumn(format="%.2f"),
        "新業種": st.column_config.TextColumn(
            "業種(新60)",
            help="ユーザー定義の新60業種。事業説明文(英語)を最優先に、GICS業種・社名で自動分類。"
            "「業種根拠」列で信頼度が分かります。",
        ),
        "業種根拠": st.column_config.TextColumn(
            "業種根拠",
            help="新60業種の分類根拠＝信頼度。確定/説明文/GICS＝高信頼、社名＝中、"
            "既定(要確認)＝低信頼(その業種の代表区分に既定割当)、手動＝個別修正。",
        ),
        "PER": st.column_config.NumberColumn("PER(倍)", format="%.1f",
                                             help="時価総額÷純利益(黒字のみ)。"),
        "業種PER中央値": st.column_config.NumberColumn("業種PER中央値", format="%.1f",
                                              help="同じ33業種の黒字銘柄のPER中央値。"),
        "PER乖離率": st.column_config.NumberColumn(
            "PER乖離率", format="percent",
            help="PER÷業種PER中央値−1。マイナス=同業比で割安。"),
        "PBR": st.column_config.NumberColumn("PBR(倍)", format="%.2f"),
        # 大きな数値は桁区切り(localized)で見やすく
        "時価総額(億円)": st.column_config.NumberColumn("時価総額(億円)", format="localized"),
        "ネットキャッシュ(億円)": st.column_config.NumberColumn("ネットキャッシュ(億円)", format="localized"),
        "流動資産(百万円)": st.column_config.NumberColumn("流動資産(百万円)", format="localized"),
        "投資有価証券(百万円)": st.column_config.NumberColumn("投資有価証券(百万円)", format="localized"),
        "負債(百万円)": st.column_config.NumberColumn("負債(百万円)", format="localized"),
        "前日終値": st.column_config.NumberColumn("前日終値(円)", format="localized"),
        "配当利回り(%)": st.column_config.NumberColumn("配当利回り(%)", format="%.2f"),
        "配当": st.column_config.NumberColumn("配当(円)", format="%.1f"),
        "予想PER": st.column_config.NumberColumn("予想PER(倍)", format="%.1f",
                                             help="forwardPE(yfinance)。小型株は欠損あり。"),
        "forwardEPS": st.column_config.NumberColumn("予想EPS(円)", format="localized"),
        "目標株価": st.column_config.NumberColumn("目標株価(円)", format="localized",
                                             help="アナリスト目標株価平均(yfinance)。小型株は欠損あり。"),
    },
)
st.caption(
    "金額は百万円表示（決算短信の一般的な単位）。データ元のYahoo Financeは決算短信の千円/百万円表記に関わらず"
    "「円」の絶対額に正規化されるため、銘柄間で単位は揃っています。"
    "右端の「短信PDF(公式)」から実際の決算短信PDF（TDnet掲載）と照合できます。"
    "「来期見通し(要約)」は比率1.0以上の銘柄に、決算短信の次期業績予想・経営環境の要点を原文の文で抽出・整形して掲載（言い換えなし）。"
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

# ---- 業種別PER中央値の一覧 ----
base = st.session_state.df
if "業種" in base.columns and "PER" in base.columns:
    with st.expander("📚 業種別(33業種)PER中央値ランキング", expanded=False):
        per = pd.to_numeric(base["PER"], errors="coerce")
        v = base[per.notna() & (per > 0)].copy()
        v["PER"] = pd.to_numeric(v["PER"], errors="coerce")
        agg = (
            v.groupby("業種")["PER"]
            .agg(銘柄数="count", PER中央値="median")
            .reset_index()
            .sort_values("PER中央値")
        )
        agg["PER中央値"] = agg["PER中央値"].round(1)
        st.caption("黒字銘柄のみで集計。PER中央値が低い業種ほど相対的に割安に評価されている傾向。")
        st.dataframe(
            agg, width="stretch", hide_index=True,
            column_config={"PER中央値": st.column_config.NumberColumn(format="%.1f")},
        )


# ---- 連動分析(株価の連動) ----
_CORR_OK = all(os.path.exists(os.path.join(os.path.dirname(__file__), f))
               for f in ["returns.parquet", "peers_adj.csv", "peers_raw.csv", "cross_industry.csv"])


@st.cache_data(show_spinner=False)
def load_corr():
    base_dir = os.path.dirname(__file__)
    ret = pd.read_parquet(os.path.join(base_dir, "returns.parquet"))
    padj = pd.read_csv(os.path.join(base_dir, "peers_adj.csv"), dtype={"コード": str, "連動銘柄": str})
    praw = pd.read_csv(os.path.join(base_dir, "peers_raw.csv"), dtype={"コード": str, "連動銘柄": str})
    cross = pd.read_csv(os.path.join(base_dir, "cross_industry.csv"))
    return ret, padj, praw, cross


def lead_lag(ret, a, b):
    """a と b の先行・遅行。正なら a が先行(aの動きが翌日bに伝わる)。"""
    if a not in ret.columns or b not in ret.columns:
        return None
    s = ret[[a, b]].dropna()
    if len(s) < 30:
        return None
    x, y = s[a].values, s[b].values
    a_leads = np.corrcoef(x[:-1], y[1:])[0, 1]   # a(t) vs b(t+1)
    b_leads = np.corrcoef(y[:-1], x[1:])[0, 1]   # b(t) vs a(t+1)
    return a_leads - b_leads


if _CORR_OK:
    st.divider()
    st.subheader("🔗 連動分析(株価の連動)")
    st.caption(
        "直近1年の日次リターンの相関。『市場調整後』は各日の市場平均を差し引いた残差で計算し、"
        "地合いを除いた“本当の連動”を見ます。相関は因果ではなく、期間によって変わるスナップショットです。"
    )
    ret, peers_adj, peers_raw, cross = load_corr()

    base = st.session_state.df
    code_name = {str(r["コード"]): f"{r['コード']} {r.get('銘柄名', '')}"
                 for _, r in base.iterrows()}
    avail = [c for c in peers_adj["コード"].unique() if c in code_name]
    avail = sorted(avail, key=lambda c: code_name[c])

    c1, c2 = st.columns([2, 1])
    sel = c1.selectbox("銘柄を選ぶ", avail,
                       format_func=lambda c: code_name.get(c, c),
                       index=avail.index("7203.T") if "7203.T" in avail else 0)
    mode = c2.radio("相関の種類", ["市場調整後", "素の相関"], horizontal=False)

    peers = peers_adj if mode == "市場調整後" else peers_raw
    sub = peers[peers["コード"] == sel].head(15).copy()

    # メタ情報(60業種・ネットキャッシュ比率・PER・配当利回り・PBR・時価総額)
    META = [c for c in ["新業種", "ネットキャッシュ比率", "PER", "配当利回り(%)", "PBR", "時価総額(億円)"]
            if c in base.columns]
    bmeta = base.set_index("コード")

    # 選択銘柄の情報を上部に表示
    if sel in bmeta.index:
        si = bmeta.loc[sel]
        st.markdown(f"### {code_name.get(sel, sel)}")
        cols = st.columns(5)
        def _fmt(v, f):
            try:
                return f.format(float(v))
            except Exception:
                return "—"
        cols[0].metric("時価総額", _fmt(si.get("時価総額(億円)"), "{:,.0f}億"))
        cols[1].metric("ネットキャッシュ比率", _fmt(si.get("ネットキャッシュ比率"), "{:.2f}"))
        cols[2].metric("PER", _fmt(si.get("PER"), "{:.1f}"))
        cols[3].metric("配当利回り", _fmt(si.get("配当利回り(%)"), "{:.2f}%"))
        cols[4].metric("業種(60)", str(si.get("新業種", "—")))

    # 比較表: 1行目に選択銘柄、続けて連動上位
    sub = sub.rename(columns={"連動銘柄": "コード2", "連動銘柄名": "銘柄名"})
    sub["先行/遅行"] = sub["コード2"].map(
        lambda p: (lambda d: "—" if d is None else
                   ("選択銘柄が先行" if d > 0.02 else ("相手が先行" if d < -0.02 else "ほぼ同時")))(
            lead_lag(ret, sel, p)))
    sub = sub.merge(bmeta[META], left_on="コード2", right_index=True, how="left")
    sub = sub.rename(columns={"コード2": "コード"}).drop(columns=["コード"], errors="ignore")

    sel_row = {"銘柄名": f"★{bmeta.loc[sel, '銘柄名'] if sel in bmeta.index else sel}",
               "相関": None, "先行/遅行": "(選択銘柄)"}
    if sel in bmeta.index:
        for c in META:
            sel_row[c] = bmeta.loc[sel, c]
    comp = pd.concat([pd.DataFrame([sel_row]), sub], ignore_index=True)
    comp = comp.rename(columns={"新業種": "業種(60)"})
    order = [c for c in ["銘柄名", "相関", "先行/遅行", "業種(60)",
                         "ネットキャッシュ比率", "PER", "配当利回り(%)", "PBR", "時価総額(億円)"]
             if c in comp.columns]

    st.markdown(f"**連動する銘柄（{mode}・上位15）** ＋ 先頭は選択銘柄（並べて比較）")
    st.dataframe(
        comp[order], width="stretch", hide_index=True,
        column_config={
            "相関": st.column_config.NumberColumn(format="%.3f"),
            "ネットキャッシュ比率": st.column_config.NumberColumn(format="%.2f"),
            "PER": st.column_config.NumberColumn(format="%.1f"),
            "PBR": st.column_config.NumberColumn(format="%.2f"),
            "配当利回り(%)": st.column_config.NumberColumn(format="%.2f"),
            "時価総額(億円)": st.column_config.NumberColumn(format="localized"),
        },
    )

    with st.expander("🎭 別業種なのに連動する『意外なペア』(市場調整後・上位300)", expanded=False):
        st.caption("業種が違うのに高相関＝隠れたテーマ/共通要因の可能性。小型株は偶然の相関も混じるため要検証。")
        st.dataframe(cross, width="stretch", hide_index=True,
                     column_config={"相関": st.column_config.NumberColumn(format="%.3f")})
