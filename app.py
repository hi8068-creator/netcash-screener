#!/usr/bin/env python3
"""
ネットキャッシュ比率スクリーニング Web アプリ(Streamlit)。

- 起動時は同梱の results.csv(事前計算済み)を即表示
- 市場・比率でフィルタ、Excel/CSV ダウンロード
- 「最新データで再計算」ボタンでライブ取得(時間がかかる)
- 画面は3タブ構成(スクリーニング / 連動分析 / 使い方・用語)
"""

import os
from datetime import datetime

import html as htmllib

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import core


def tradingview_chart(code: str, height: int = 520, interval: str = "D") -> None:
    """選択銘柄のTradingViewチャート(リアルタイム寄り)を埋め込む。

    東証コード "7203.T" → "TSE:7203"。各 components.html は独立iframeなので
    コンテナidは銘柄ごとに変えて衝突を避ける。
    """
    code4 = str(code).replace(".T", "")
    sym = "TSE:" + code4
    cid = "tv_" + code4
    html = f"""
    <div class="tradingview-widget-container" style="height:100%;">
      <div id="{cid}" style="height:100%;"></div>
    </div>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{sym}",
        "interval": "{interval}",
        "timezone": "Asia/Tokyo",
        "theme": "light",
        "style": "1",
        "locale": "ja",
        "hide_side_toolbar": true,
        "hide_top_toolbar": false,
        "withdateranges": true,
        "allow_symbol_change": false,
        "container_id": "{cid}"
      }});
    </script>
    """
    components.html(html, height=height)


def tradingview_grid(codes, labels=None, ncols=2, height=380, interval="D") -> None:
    """複数銘柄のチャートをグリッド(既定2列)で並べて表示する。"""
    codes = [c for c in codes if c]
    labels = labels or {}
    for i in range(0, len(codes), ncols):
        row = codes[i:i + ncols]
        cols = st.columns(len(row))
        for col, c in zip(cols, row):
            with col:
                st.markdown(f"**{labels.get(c, c)}**")
                tradingview_chart(c, height=height, interval=interval)


@st.cache_data(show_spinner=False)
def load_prices():
    """同梱の日次終値(prices.parquet)を読み込む。無ければ None。"""
    p = os.path.join(os.path.dirname(__file__), "prices.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    try:
        df.index = pd.to_datetime(df.index)
    except Exception:
        pass
    return df.sort_index()


@st.cache_data(show_spinner=False, ttl=1800)
def fetch_recent_prices(codes_tuple, period="1y"):
    """選択した数銘柄ぶんの最新日次終値をその場で取得(30分キャッシュ)。

    チャート対象は数銘柄なので軽い。全銘柄の同梱データ(相関分析用)とは別系統。
    取得失敗(レート制限等)は None を返し、呼び出し側で同梱データにフォールバック。
    """
    import yfinance as yf
    tickers = [str(c) for c in codes_tuple if c]
    if not tickers:
        return None
    try:
        data = yf.download(tickers, period=period, interval="1d",
                           auto_adjust=True, progress=False, threads=True)
        close = data["Close"] if "Close" in data else data
        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])
        close.index = pd.to_datetime(close.index)
        close = close.dropna(how="all")
        return close if len(close) else None
    except Exception:
        return None


def price_chart(codes, names=None, normalize=True, height=440, live=True) -> None:
    """選択銘柄の日次終値を1枚のチャートに重ねて表示する。

    live=True なら対象銘柄の最新株価をその場取得(失敗時は同梱データ)。
    normalize=True で各銘柄を期間先頭=100に基準化(値動きの比較・連動の確認向け)。
    """
    names = names or {}
    px, src = None, "同梱データ"
    if live:
        with st.spinner("最新の株価を取得中…"):
            px = fetch_recent_prices(tuple(sorted(str(c) for c in codes)))
        if px is not None and any(c in px.columns for c in codes):
            src = "最新(自動取得)"
        else:
            px = None
    if px is None:
        px = load_prices()
    if px is None:
        st.info("価格データが見つかりません。")
        return
    cols = [c for c in codes if c in px.columns]
    if not cols:
        st.info("選択した銘柄の価格データがありません(新規上場などで未取得の場合があります)。")
        return
    sub = px[cols].dropna(how="all").copy()
    if normalize:
        for c in cols:
            s = sub[c].dropna()
            base = s.iloc[0] if len(s) else None
            if base:
                sub[c] = sub[c] / base * 100
    sub = sub.rename(columns={c: names.get(c, c) for c in cols})
    st.line_chart(sub, height=height)
    if len(sub.index):
        lo, hi = sub.index.min(), sub.index.max()
        unit = "（100基準で比較）" if normalize else "（実株価・円）"
        note = "（取引時間中は当日値が反映、〜15分程度遅延の場合あり）" if src.startswith("最新") else "（最終取得時点まで）"
        st.caption(f"📅 {lo:%Y-%m-%d} 〜 **{hi:%Y-%m-%d}**　日次終値{unit}・出典:{src}{note}")


def tv_links(codes, names=None) -> None:
    """TradingViewの個別ページ(リアルタイム/高機能)への外部リンクを並べる。"""
    names = names or {}
    parts = []
    for c in codes:
        c4 = str(c).replace(".T", "")
        parts.append(f'<a href="https://jp.tradingview.com/symbols/TSE-{c4}/" '
                     f'target="_blank" rel="noopener">{names.get(c, c)} ↗</a>')
    if parts:
        st.markdown("リアルタイム/高機能チャートはこちら: " + " ・ ".join(parts),
                    unsafe_allow_html=True)

st.set_page_config(page_title="ネットキャッシュ比率スクリーニング", layout="wide")

RESULTS_CSV = os.path.join(os.path.dirname(__file__), "results.csv")
TREND_CSV = os.path.join(os.path.dirname(__file__), "earnings_trend.csv")
QUOTES_CSV = os.path.join(os.path.dirname(__file__), "daily_quotes.csv")

# 財務数値の確認先(株探: 業績/財務を百万円表示し、決算短信へのリンクもある)
KABUTAN_BASE = "https://kabutan.jp/stock/finance?code="
# 公式の決算短信PDFへの経路(Yahoo!ファイナンス適時開示。TDnet掲載の公式PDFにリンク)
YAHOO_DISCLOSURE_BASE = "https://finance.yahoo.co.jp/quote/"
# 株主優待の確認先(みんかぶ優待ページ)。無料の一括取得は精度難のためリンク提供に留める。
MINKABU_YUTAI_BASE = "https://minkabu.jp/stock/"

# 表示時の列順(存在する列のみ採用)。金額は百万円表示にして決算短信と突き合わせやすくする。
# 並びは「指標を前に」: 識別 → 割安指標 → 株価・配当 → アナリスト予想 → 文脈(市場・業種・分類)
#   → 財務内訳 → 決算期・見通し・リンク。主役のネットキャッシュ比率を銘柄名の直後に置く。
DISPLAY_ORDER = [
    "コード", "銘柄名", "新業種",
    "ネットキャッシュ比率", "ネットキャッシュ(億円)", "時価総額(億円)",
    "PER", "業種PER中央値", "PER乖離率", "PBR", "自己資本比率(%)",
    "配当利回り(%)", "配当", "配当性向(%)", "増収増益(年)", "前日終値",
    "予想PER", "forwardEPS", "目標株価",
    "テクニカル", "RSI", "ストキャスK", "ストキャスD",
    "市場", "業種根拠", "規模",
    "流動資産(百万円)", "投資有価証券(百万円)", "負債(百万円)", "売上トレンド",
    "決算期", "来期見通し(短信抜粋)", "財務(株探)", "短信PDF", "優待",
]

# 初心者向け「主要列のみ」表示の列(存在する列のみ採用)。同じく指標を前に。
BEGINNER_COLUMNS = [
    "コード", "銘柄名", "新業種", "ネットキャッシュ比率", "時価総額(億円)", "PER", "自己資本比率(%)",
    "配当利回り(%)", "配当性向(%)", "増収増益(年)", "市場", "来期見通し(短信抜粋)", "短信PDF",
]

# 表示しない内部列(算出の元データ)
HIDE_COLS = ["純利益", "純資産", "業種大分類"]

# 列名の直下に出す「短い注釈」と、その時の数値書式
SHORT_DESC = {
    "コード": "証券コード", "銘柄名": "会社名",
    "ネットキャッシュ比率": "1.0以上で割安の目安",
    "ネットキャッシュ(億円)": "現金等−負債",
    "時価総額(億円)": "会社の規模",
    "PER": "15倍前後が標準/低いほど割安",
    "業種PER中央値": "同業の標準PER", "PER乖離率": "−で同業より割安",
    "PBR": "1倍割れは割安の目安",
    "自己資本比率(%)": "50%以上で健全",
    "配当利回り(%)": "3〜4%で高配当", "配当": "1株年間配当",
    "配当性向(%)": "50%以下が目安",
    "増収増益(年)": "連続年数/3以上で右肩上がり",
    "前日終値": "直近株価", "予想PER": "予想ベースPER",
    "forwardEPS": "予想1株利益", "目標株価": "アナリスト目標",
    "市場": "プライム/スタンダード/グロース", "業種": "東証33業種",
    "新業種": "独自67業種", "業種根拠": "分類の信頼度", "規模": "TOPIX規模区分",
    "流動資産(百万円)": "1年内に現金化", "投資有価証券(百万円)": "保有株/債券(0.7掛け)",
    "負債(百万円)": "総負債", "決算期": "基準の決算期末",
    "来期見通し(短信抜粋)": "短信の次期見通し", "売上トレンド": "年次売上(古→新)",
    "短信PDF": "公式決算短信", "財務(株探)": "財務ページ", "優待": "株主優待",
    "テクニカル": "RSI×ストキャスの売買サイン",
    "RSI": "30以下=売られすぎ/70以上=買われすぎ",
    "ストキャスK": "%K(20以下=売られすぎ)", "ストキャスD": "%D(%Kの平滑線)",
}
NUM_FMT = {
    "ネットキャッシュ比率": "{:.2f}", "PBR": "{:.2f}", "配当利回り(%)": "{:.2f}",
    "PER": "{:.1f}", "業種PER中央値": "{:.1f}", "予想PER": "{:.1f}", "配当": "{:.1f}",
    "自己資本比率(%)": "{:.1f}", "配当性向(%)": "{:.1f}", "増収増益(年)": "{:.0f}",
    "PER乖離率": "{:.1%}",
    "時価総額(億円)": "{:,.1f}", "ネットキャッシュ(億円)": "{:,.1f}",
    "前日終値": "{:,.0f}", "forwardEPS": "{:,.1f}", "目標株価": "{:,.0f}",
    "流動資産(百万円)": "{:,.0f}", "投資有価証券(百万円)": "{:,.0f}", "負債(百万円)": "{:,.0f}",
    "RSI": "{:.1f}", "ストキャスK": "{:.1f}", "ストキャスD": "{:.1f}",
}
LINK_COLS = ["短信PDF", "財務(株探)", "優待"]


def with_desc_row(disp_view: pd.DataFrame):
    """ヘッダー直下に説明行を入れた表示用DataFrameと、リンク列のみのcolumn_configを返す。

    数値は文字列に整形(=並べ替え/桁揃えは簡易表示に)。リンク列はクリック可能を維持。
    """
    d = disp_view.copy()
    for c in d.columns:
        if c in LINK_COLS:
            continue
        if c in NUM_FMT:
            num = pd.to_numeric(d[c], errors="coerce")
            d[c] = [("" if pd.isna(x) else NUM_FMT[c].format(x)) for x in num]
        else:
            d[c] = d[c].apply(lambda x: "" if pd.isna(x) else str(x))
    desc = {c: ("" if c in LINK_COLS else SHORT_DESC.get(c, "")) for c in d.columns}
    out = pd.concat([pd.DataFrame([desc]), d], ignore_index=True)
    cc = {c: COLUMN_CONFIG[c] for c in d.columns if c in LINK_COLS and c in COLUMN_CONFIG}
    return out, cc


# 表(HTML描画)用のヘッダー表記とリンク文言
HEADER_LABELS = {
    "来期見通し(短信抜粋)": "来期見通し", "短信PDF": "短信PDF(公式)", "新業種": "業種(67)",
    "PER": "PER(倍)", "PBR": "PBR(倍)", "前日終値": "前日終値(円)", "配当": "配当(円)",
    "予想PER": "予想PER(倍)", "forwardEPS": "予想EPS(円)", "目標株価": "目標株価(円)",
    "財務(株探)": "財務(株探)", "優待": "優待(みんかぶ)",
}
LINK_TEXT = {"財務(株探)": "開く", "短信PDF": "開く", "優待": "確認"}


def _full_desc(c: str) -> str:
    """LEGEND から説明(全文)を取り出す(『**名** … 説明』の説明部分)。"""
    t = LEGEND.get(c, "")
    return t.split("…", 1)[1].strip() if "…" in t else ""


def build_html_table(disp_view: pd.DataFrame, show_desc: bool = False, height: int = 600):
    """結果表をHTMLで描画する。

    - 列の説明(show_desc)はヘッダー直下の『固定行』として全文・折り返し表示
    - 「来期見通し」は折り返し表示でその場で全文が読める
    - コード/銘柄名は左端に固定、ヘッダーも固定
    """
    cols = list(disp_view.columns)

    def cell_stick(i):
        return ("stick0" if i == 0 else "stick1" if i == 1
                else "stick2" if i == 2 else "")

    ths = "".join(
        f'<th class="{cell_stick(i)}">{htmllib.escape(HEADER_LABELS.get(c, c))}</th>'
        for i, c in enumerate(cols))
    thead = "<thead><tr>" + ths + "</tr>"
    if show_desc:
        dtds = "".join(
            f'<td class="descrow-cell {cell_stick(i)}">{htmllib.escape(_full_desc(c))}</td>'
            for i, c in enumerate(cols))
        thead += '<tr class="descrow">' + dtds + "</tr>"
    thead += "</thead>"

    rows_html = []
    for _, row in disp_view.iterrows():
        tds = []
        for i, c in enumerate(cols):
            v = row[c]
            stk = cell_stick(i)
            if c in LINK_COLS:
                url = "" if pd.isna(v) else str(v)
                inner = (f'<a href="{htmllib.escape(url, quote=True)}" target="_blank" '
                         f'rel="noopener">{LINK_TEXT.get(c, "開く")}</a>') if url.strip() else ""
                tds.append(f'<td class="{stk}">{inner}</td>')
            elif c in NUM_FMT:
                x = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
                if pd.notna(x):
                    txt = NUM_FMT[c].format(x)
                else:
                    # 非数値の表示語(赤字/—など)はそのまま見せる
                    sv = "" if pd.isna(v) else str(v)
                    txt = sv if sv not in ("", "nan", "None") else ""
                tds.append(f'<td class="num {stk}">{txt}</td>')
            elif c == "来期見通し(短信抜粋)":
                txt = "" if pd.isna(v) else str(v)
                tds.append(f'<td class="outlook {stk}">{htmllib.escape(txt)}</td>')
            else:
                txt = "" if pd.isna(v) else str(v)
                tds.append(f'<td class="wrap {stk}">{htmllib.escape(txt)}</td>')
        rows_html.append("<tr>" + "".join(tds) + "</tr>")
    tbody = "<tbody>" + "".join(rows_html) + "</tbody>"

    css = """
<style>
.twrap{max-height:__H__px;overflow:auto;border:1px solid #e6e6e6;border-radius:6px;}
table.nc{border-collapse:separate;border-spacing:0;font-family:-apple-system,'Hiragino Sans',Meiryo,sans-serif;font-size:13px;width:max-content;min-width:100%;}
table.nc th,table.nc td{padding:6px 10px;border-bottom:1px solid #eee;border-right:1px solid #f2f2f2;text-align:left;vertical-align:top;white-space:nowrap;background:#fff;}
table.nc td.num{text-align:right;font-variant-numeric:tabular-nums;}
table.nc td.wrap{white-space:normal;}
table.nc td.outlook{min-width:260px;max-width:360px;white-space:normal;line-height:1.45;color:#333;}
table.nc thead th{position:sticky;top:0;background:#eef1f6;font-weight:600;z-index:5;}
table.nc tr.descrow td{position:sticky;top:33px;background:#f4f7ff;color:#555;font-size:12px;white-space:normal;min-width:120px;line-height:1.4;z-index:3;}
table.nc .stick0{position:sticky;left:0;z-index:2;}
table.nc .stick1{position:sticky;left:64px;z-index:2;}
table.nc .stick2{position:sticky;left:214px;z-index:2;}
table.nc th.stick0,table.nc th.stick1,table.nc th.stick2{z-index:6;background:#eef1f6;}
table.nc tr.descrow td.stick0,table.nc tr.descrow td.stick1,table.nc tr.descrow td.stick2{z-index:4;background:#f4f7ff;}
table.nc td.stick0,table.nc td.stick1,table.nc td.stick2{background:#fff;}
table.nc th.stick0,table.nc td.stick0,table.nc tr.descrow td.stick0{min-width:64px;max-width:64px;}
table.nc th.stick1,table.nc td.stick1,table.nc tr.descrow td.stick1{min-width:150px;max-width:150px;white-space:normal;}
table.nc th.stick2,table.nc td.stick2,table.nc tr.descrow td.stick2{min-width:140px;max-width:140px;white-space:normal;border-right:2px solid #d7dbe3;}
table.nc a{color:#1a73e8;text-decoration:none;}
table.nc tbody tr:hover td{background:#fbfcff;}
table.nc tbody tr:hover td.stick0,table.nc tbody tr:hover td.stick1,table.nc tbody tr:hover td.stick2{background:#fbfcff;}
</style>
""".replace("__H__", str(max(200, height - 12)))
    components.html(css + f'<div class="twrap"><table class="nc">{thead}{tbody}</table></div>',
                    height=height, scrolling=False)


# 連動分析の比較表: ヘッダー直下に★選択銘柄を貼り付け(リストをスクロールしても固定)
CORR_HEADERS = {
    "前日終値": "前日終値(円)", "業種(67)": "業種(67)", "PER": "PER(倍)",
    "予想PER": "予想PER(倍)", "forwardEPS": "予想EPS(円)", "配当": "年間配当(円)",
}
CORR_FMT = {
    "前日終値": "{:,.1f}", "相関": "{:.3f}", "PER": "{:.1f}", "予想PER": "{:.1f}",
    "forwardEPS": "{:.1f}", "配当": "{:.1f}", "配当利回り(%)": "{:.2f}",
    "時価総額(億円)": "{:,.1f}",
}


def render_corr_table(comp: pd.DataFrame, order, height: int = 520) -> None:
    """連動する銘柄の比較表をHTMLで描画する。

    1行目(★選択銘柄)を position:sticky でヘッダー直下に固定し、
    連動リストをスクロールしても選択銘柄と常に並べて比較できるようにする。
    """
    def fmt(c, v):
        if pd.isna(v):
            return ""
        if c in CORR_FMT:
            try:
                s = CORR_FMT[c].format(float(v))
                return s[:-2] if s.endswith(".0") else s
            except Exception:
                return htmllib.escape(str(v))
        return htmllib.escape(str(v))

    num_cols = set(CORR_FMT)
    ths = "".join(f"<th>{htmllib.escape(CORR_HEADERS.get(c, c))}</th>" for c in order)
    body_rows = []
    for i, (_, row) in enumerate(comp.iterrows()):
        cls = ' class="selrow"' if i == 0 else ""
        tds = "".join(
            f'<td class="{"num" if c in num_cols else "txt"}">{fmt(c, row.get(c))}</td>'
            for c in order)
        body_rows.append(f"<tr{cls}>{tds}</tr>")

    css = """
<style>
.cwrap{max-height:__H__px;overflow:auto;border:1px solid #e6e6e6;border-radius:6px;}
table.cr{border-collapse:separate;border-spacing:0;font-family:-apple-system,'Hiragino Sans',Meiryo,sans-serif;font-size:13px;width:max-content;min-width:100%;}
table.cr th,table.cr td{padding:6px 10px;border-bottom:1px solid #eee;border-right:1px solid #f2f2f2;text-align:left;white-space:nowrap;background:#fff;}
table.cr td.num{text-align:right;font-variant-numeric:tabular-nums;}
table.cr thead th{position:sticky;top:0;background:#eef1f6;font-weight:600;z-index:4;}
table.cr tr.selrow td{position:sticky;top:32px;background:#fff8e1;font-weight:600;z-index:3;border-bottom:2px solid #e8c96a;}
table.cr tbody tr:not(.selrow):hover td{background:#fbfcff;}
</style>
""".replace("__H__", str(max(200, height - 12)))
    html = (css + f'<div class="cwrap"><table class="cr"><thead><tr>{ths}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table></div>')
    components.html(html, height=height, scrolling=False)


# 列の凡例(表の上に「各列が何を見るためのものか」を表示する)。キーは内部列名。
LEGEND = {
    "コード": "**コード** … 証券コード(東証の銘柄番号＋.T)",
    "銘柄名": "**銘柄名** … 会社名",
    "市場": "**市場** … 上場区分。プライム=大型・安定 / スタンダード=中堅 / グロース=新興。小型ほど割安が放置されやすい",
    "業種": "**業種** … 東証33業種の分類",
    "新業種": "**業種(67)** … 独自の細分類(67業種)。確からしさは「業種根拠」で確認",
    "業種根拠": "**業種根拠** … 新67業種の分類の信頼度",
    "規模": "**規模** … TOPIX規模区分(会社の大きさの目安)",
    "ネットキャッシュ比率": "**ネットキャッシュ比率** … 割安度の中心指標。1.0以上で「実質タダ」級に割安",
    "ネットキャッシュ(億円)": "**ネットキャッシュ(億円)** … 現金等−負債の純現金額",
    "時価総額(億円)": "**時価総額(億円)** … 会社の市場価値(株価×株数)＝規模の目安",
    "PER": "**PER(倍)** … 株価が利益の何年分か。15倍前後が標準、低いほど割安",
    "業種PER中央値": "**業種PER中央値** … 同業の標準PER",
    "PER乖離率": "**PER乖離率** … 同業比の割安度(マイナス=割安)",
    "PBR": "**PBR(倍)** … 株価が純資産の何倍か。1倍割れは割安の目安",
    "自己資本比率(%)": "**自己資本比率(%)** … 純資産÷総資産。財務の健全性。50%以上で健全の目安",
    "配当性向(%)": "**配当性向(%)** … 配当÷利益。配当の無理のなさ。50%以下が目安(高すぎは減配リスク)。黒字のみ",
    "増収増益(年)": "**増収増益(年)** … 直近で売上と利益が両方連続で増えた年数。3以上=しっかり右肩上がりの目安",
    "売上トレンド": "**売上トレンド(億)** … 取得できた年次売上(古い→新しい)。右上がりなら増収基調",
    "前日終値": "**前日終値(円)** … 直近の株価",
    "配当利回り(%)": "**配当利回り(%)** … 年配当÷株価。3〜4%で高配当の目安",
    "配当": "**配当(円)** … 1株あたり年間配当",
    "予想PER": "**予想PER(倍)** … アナリスト予想ベースのPER(小型株は欠損あり)",
    "forwardEPS": "**予想EPS(円)** … 予想1株利益",
    "目標株価": "**目標株価(円)** … アナリスト目標株価の平均",
    "流動資産(百万円)": "**流動資産(百万円)** … 1年以内に現金化できる資産(比率計算の内訳)",
    "投資有価証券(百万円)": "**投資有価証券(百万円)** … 保有株式・債券など(比率計算で0.7掛け)",
    "負債(百万円)": "**負債(百万円)** … 返済義務のある総負債(比率計算の内訳)",
    "決算期": "**決算期** … もとにした決算の期末",
    "来期見通し(短信抜粋)": "**来期見通し(要約)** … 決算短信から抜粋した次期の見通し",
    "短信PDF": "**短信PDF(公式)** … 公式の決算短信PDF(中身を確認)",
    "財務(株探)": "**財務(株探)** … 株探の財務ページ(数値の照合に便利)",
    "優待": "**優待(みんかぶ)** … 株主優待の確認先",
}


def data_updated_str() -> str:
    """results.csv の更新日(目安)。取得できなければ '不明'。"""
    try:
        return datetime.fromtimestamp(os.path.getmtime(RESULTS_CSV)).strftime("%Y-%m-%d")
    except Exception:
        return "不明"


def quotes_date_str() -> str:
    """daily_quotes.csv の終値日付(最大値)。無ければ空文字。"""
    try:
        q = pd.read_csv(QUOTES_CSV, usecols=["日付"])
        return str(q["日付"].max())
    except Exception:
        return ""


def merge_daily(df: pd.DataFrame) -> pd.DataFrame:
    """daily_quotes.csv(毎日の終値)があれば、株価依存の指標を最新終値で引き直す。

    - 前日終値 → 最新終値に置換
    - 時価総額(億円) → 株数不変の前提で 新終値/旧終値 でスケール
    - ネットキャッシュ比率 = ネットキャッシュ(億円) ÷ 新時価総額
    - PER = 新時価総額 ÷ 純利益(黒字のみ) / PBR = 新時価総額 ÷ 純資産
    - 業種PER中央値・PER乖離率も新PERで再集計
    財務数値(流動資産・負債等)は決算由来なのでそのまま。
    """
    if not os.path.exists(QUOTES_CSV):
        return df
    try:
        q = pd.read_csv(QUOTES_CSV, dtype={"コード": str})
    except Exception:
        return df
    if "コード" not in q.columns or "終値" not in q.columns:
        return df
    d = df.copy()
    d["コード"] = d["コード"].astype(str)
    d = d.merge(q[["コード", "終値"]].drop_duplicates("コード"), on="コード", how="left")
    new_px = pd.to_numeric(d["終値"], errors="coerce")
    old_px = pd.to_numeric(d.get("前日終値"), errors="coerce")
    scale = (new_px / old_px).where((new_px > 0) & (old_px > 0))
    if "時価総額(億円)" in d.columns:
        mc = pd.to_numeric(d["時価総額(億円)"], errors="coerce")
        d["時価総額(億円)"] = (mc * scale.fillna(1.0)).round(1)
    d["前日終値"] = new_px.where(new_px > 0, old_px)
    d = d.drop(columns=["終値"])

    mc_oku = pd.to_numeric(d.get("時価総額(億円)"), errors="coerce")
    mc_yen = mc_oku * 1e8
    if "ネットキャッシュ(億円)" in d.columns:
        nc = pd.to_numeric(d["ネットキャッシュ(億円)"], errors="coerce")
        d["ネットキャッシュ比率"] = (nc / mc_oku).where(mc_oku > 0).round(2)
    if "純利益" in d.columns:
        ni = pd.to_numeric(d["純利益"], errors="coerce")
        d["PER"] = (mc_yen / ni).where(ni > 0).round(1)
    if "純資産" in d.columns:
        eq = pd.to_numeric(d["純資産"], errors="coerce")
        d["PBR"] = (mc_yen / eq).where(eq > 0).round(2)
    if "PER" in d.columns and "業種" in d.columns:
        per = pd.to_numeric(d["PER"], errors="coerce")
        med = d.loc[per.notna() & (per > 0)].groupby("業種")["PER"].median()
        d["業種PER中央値"] = pd.to_numeric(d["業種"].map(med), errors="coerce").round(1)
        d["PER乖離率"] = ((per / pd.to_numeric(d["業種PER中央値"], errors="coerce")) - 1).round(3)
    return d


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
    # PERは「数値 / 赤字 / —(データなし)」で表示(純利益で区別)。元dfは数値のまま=並べ替え可。
    if "PER" in d.columns:
        per_n = pd.to_numeric(d["PER"], errors="coerce")
        ni = (pd.to_numeric(d["純利益"], errors="coerce") if "純利益" in d.columns
              else pd.Series([float("nan")] * len(d), index=d.index))
        disp_per = []
        for p, n in zip(per_n, ni):
            if pd.notna(p) and p > 300:
                disp_per.append("300超")  # 業績急減/データ異常で実質意味なし
            elif pd.notna(p):
                disp_per.append(f"{p:.1f}")
            elif pd.notna(n) and n <= 0:
                disp_per.append("赤字")
            else:
                disp_per.append("—")
        d["PER"] = disp_per

    d = d.drop(columns=[c for c in HIDE_COLS if c in d.columns])
    ordered = [c for c in DISPLAY_ORDER if c in d.columns]
    rest = [c for c in d.columns if c not in ordered]
    return d[ordered + rest]


# 結果テーブルの列設定(全列ぶん定義。存在しない列キーは無視される)
# コード・銘柄名は pinned=True で左端に固定し、横スクロールしても見えるようにする。
COLUMN_CONFIG = {
    "コード": st.column_config.TextColumn(
        "コード", help="証券コード(東証の銘柄番号＋.T)。", pinned=True),
    "銘柄名": st.column_config.TextColumn(
        "銘柄名", help="会社名。", pinned=True),
    "市場": st.column_config.TextColumn(
        "市場", help="上場区分。プライム=大型・安定 / スタンダード=中堅 / グロース=新興。"
        "小型・新興ほど割安が放置されやすい傾向。"),
    "業種": st.column_config.TextColumn("業種", help="東証33業種の分類。"),
    "規模": st.column_config.TextColumn("規模", help="TOPIX規模区分(会社の大きさの目安)。"),
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
    "ネットキャッシュ比率": st.column_config.NumberColumn(
        format="%.2f", help="1.0以上＝理屈上は現金等で時価総額をまかなえる割安の目安。"),
    "新業種": st.column_config.TextColumn(
        "業種(67)",
        help="ユーザー定義の新67業種。事業説明文(英語)を最優先に、GICS業種・社名で自動分類。"
        "「業種根拠」列で信頼度が分かります。",
    ),
    "業種根拠": st.column_config.TextColumn(
        "業種根拠",
        help="新67業種の分類根拠＝信頼度。確定/説明文/GICS＝高信頼、社名＝中、"
        "既定(要確認)＝低信頼(その業種の代表区分に既定割当)、手動＝個別修正。",
    ),
    "PER": st.column_config.NumberColumn(
        "PER(倍)", format="%.1f",
        help="時価総額÷純利益(黒字のみ)。一般に15倍前後が標準、低いほど割安(業種差大)。"),
    "業種PER中央値": st.column_config.NumberColumn(
        "業種PER中央値", format="%.1f", help="同じ業種(67分類)の黒字銘柄のPER中央値＝その業種の目安。"),
    "PER乖離率": st.column_config.NumberColumn(
        "PER乖離率", format="percent",
        help="PER÷業種PER中央値−1。マイナス=同業比で割安。"),
    "PBR": st.column_config.NumberColumn(
        "PBR(倍)", format="%.2f", help="1倍＝解散価値。1倍割れは割安の目安。"),
    "自己資本比率(%)": st.column_config.NumberColumn(
        "自己資本比率(%)", format="%.1f",
        help="純資産÷総資産。財務の健全性。50%以上で健全の目安。"),
    "配当性向(%)": st.column_config.NumberColumn(
        "配当性向(%)", format="%.1f",
        help="配当÷利益(=配当利回り×PER)。配当の無理のなさ。50%以下が目安(高すぎは減配リスク)。黒字のみ算出。"),
    "増収増益(年)": st.column_config.NumberColumn(
        "増収増益(年)", format="%d",
        help="直近で売上と利益が両方連続で増えた年数。3以上=しっかり右肩上がりの目安。"
        "データはyfinanceの範囲(概ね4年)で、比率1.0以上の銘柄に付与。"),
    "売上トレンド": st.column_config.TextColumn(
        "売上トレンド(億)", help="取得できた年次売上(古い→新しい)。右上がりなら増収基調。"),
    "時価総額(億円)": st.column_config.NumberColumn(
        "時価総額(億円)", format="localized", help="会社の市場価値(株価×株数)＝規模の目安。"),
    "ネットキャッシュ(億円)": st.column_config.NumberColumn(
        "ネットキャッシュ(億円)", format="localized", help="現金等−負債の純現金額。"),
    "流動資産(百万円)": st.column_config.NumberColumn(
        "流動資産(百万円)", format="localized", help="1年以内に現金化できる資産(比率計算の内訳)。"),
    "投資有価証券(百万円)": st.column_config.NumberColumn(
        "投資有価証券(百万円)", format="localized", help="保有株式・債券など(比率計算で0.7掛け)。"),
    "負債(百万円)": st.column_config.NumberColumn(
        "負債(百万円)", format="localized", help="返済義務のある総負債(比率計算の内訳)。"),
    "前日終値": st.column_config.NumberColumn("前日終値(円)", format="localized", help="直近の株価。"),
    "配当利回り(%)": st.column_config.NumberColumn(
        "配当利回り(%)", format="%.2f", help="年配当÷株価。3〜4%で高配当の目安。"),
    "配当": st.column_config.NumberColumn("配当(円)", format="%.1f", help="1株あたり年間配当。"),
    "予想PER": st.column_config.NumberColumn("予想PER(倍)", format="%.1f",
                                         help="forwardPE(yfinance)。小型株は欠損あり。"),
    "forwardEPS": st.column_config.NumberColumn("予想EPS(円)", format="localized"),
    "目標株価": st.column_config.NumberColumn("目標株価(円)", format="localized",
                                         help="アナリスト目標株価平均(yfinance)。小型株は欠損あり。"),
}


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """既存データから派生指標を算出して列を足す(計算ロジックは不変・表示用)。

    - 自己資本比率(%) = 純資産 ÷ (純資産 + 負債) ×100  … 財務の健全性
    - 配当性向(%)     = 配当利回り(%) × PER             … 配当の無理のなさ(黒字のみ)
    """
    d = df.copy()
    if "純資産" in d.columns and "負債" in d.columns:
        eq = pd.to_numeric(d["純資産"], errors="coerce")
        li = pd.to_numeric(d["負債"], errors="coerce")
        tot = eq + li
        d["自己資本比率(%)"] = (eq / tot * 100).where(tot > 0).round(1)
    # 配当利回り(%)は終値ベースで再計算(= 予想年間配当 ÷ 前日終値 ×100)。
    # 元データの yfinance dividendYield 由来の値は低利回り銘柄で誤りが出るため上書きする。
    if "配当" in d.columns and "前日終値" in d.columns:
        haito = pd.to_numeric(d["配当"], errors="coerce")
        px = pd.to_numeric(d["前日終値"], errors="coerce")
        d["配当利回り(%)"] = (haito.fillna(0) / px * 100).where(px > 0).round(2)
    # 予想PERも自前計算(= 前日終値 ÷ 予想EPS)。yfinanceのforwardPEは株価が古いことがあるため。
    if "forwardEPS" in d.columns and "前日終値" in d.columns:
        eps = pd.to_numeric(d["forwardEPS"], errors="coerce")
        px = pd.to_numeric(d["前日終値"], errors="coerce")
        d["予想PER"] = (px / eps).where((eps > 0) & (px > 0)).round(1)
    if "配当利回り(%)" in d.columns and "PER" in d.columns:
        y = pd.to_numeric(d["配当利回り(%)"], errors="coerce")
        per = pd.to_numeric(d["PER"], errors="coerce")
        d["配当性向(%)"] = (y * per).where(per > 0).round(1)
    return d


def merge_trend(df: pd.DataFrame) -> pd.DataFrame:
    """業績トレンド(earnings_trend.csv)があればコードで結合する(無ければ素通り)。"""
    if not os.path.exists(TREND_CSV):
        return df
    try:
        tr = pd.read_csv(TREND_CSV, dtype={"コード": str})
    except Exception:
        return df
    cols = [c for c in ["コード", "増収増益(年)", "増収(年)", "増益(年)", "売上トレンド"]
            if c in tr.columns]
    if "コード" not in cols:
        return df
    tr = tr[cols].drop_duplicates("コード")
    d = df.copy()
    d["コード"] = d["コード"].astype(str)
    return d.merge(tr, on="コード", how="left")


@st.cache_data(show_spinner=False)
def load_bundled() -> pd.DataFrame:
    if os.path.exists(RESULTS_CSV):
        # 毎日の終値→株価依存指標の引き直し→派生指標→業績トレンド の順で組み立てる
        return merge_trend(add_derived(merge_daily(pd.read_csv(RESULTS_CSV))))
    return pd.DataFrame(columns=core.COLUMNS_JP)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def evaluate_cached(code: str):
    """1銘柄評価をキャッシュ(6時間)。再描画や再実行での重複取得を防ぐ。"""
    r = core.evaluate(code)
    return core.asdict(r) if r is not None else None


if "df" not in st.session_state:
    st.session_state.df = load_bundled()

st.title("📊 ネットキャッシュ比率スクリーニング")
_qd = quotes_date_str()
st.caption(
    "ネットキャッシュ比率 = (流動資産 + 投資有価証券×0.7 − 負債) ÷ 時価総額。"
    "1.0以上＝割安の目安。　"
    + (f"株価終値: {_qd}　／　" if _qd else "")
    + f"財務データ取得日: {data_updated_str()}（出典: Yahoo Finance）"
)

# ---- サイドバー(基本フィルタ＋折りたたみ) ----
with st.sidebar:
    st.header("表示フィルタ")

    # URL(クエリ)に絞り込みを保存/復元するためのヘルパ。
    _qp = st.query_params

    def Q(k, d, t=str):
        v = _qp.get(k)
        if v in (None, ""):
            return d
        try:
            if t is float:
                return float(v)
            if t is int:
                return int(float(v))
            if t is bool:
                return str(v) in ("1", "true", "True")
            if t is list:
                return [x for x in str(v).split("|") if x]
            return v
        except Exception:
            return d

    # 基本フィルタ(常時表示)
    min_ratio = st.slider(
        "ネットキャッシュ比率の下限", 0.0, 3.0, min(3.0, max(0.0, Q("ratio", 1.0, float))), 0.05,
        help="1.0以上＝理屈上は現金等で時価総額をまかなえる割安水準。まずは1.0でOK。",
    )

    markets_all = sorted(
        m for m in st.session_state.df.get("市場", pd.Series(dtype=str)).dropna().unique()
    ) if "市場" in st.session_state.df.columns else []
    sel_markets = st.multiselect(
        "市場区分", markets_all,
        default=([m for m in Q("mkt", [], list) if m in markets_all] or markets_all),
        help="東証の市場区分。こだわりが無ければ全選択のままでOK。",
    )

    min_cap = 0
    max_cap = 0
    if "時価総額(億円)" in st.session_state.df.columns:
        cap_series = pd.to_numeric(st.session_state.df["時価総額(億円)"], errors="coerce")
        cap_hi = int(min(5000, (cap_series.max() if cap_series.notna().any() else 1000)))
        min_cap = st.number_input(
            "時価総額の下限(億円, 0=制限なし)", 0, cap_hi, min(cap_hi, Q("capmin", 0, int)), 50,
            help="一定規模以上に絞る。例:500で中型以上(プロが見る規模)(0=制限なし)。",
        )
        max_cap = st.number_input(
            "時価総額の上限(億円, 0=制限なし)", 0, cap_hi, min(cap_hi, Q("capmax", 0, int)), 50,
            help="小さいほど小型株。例:300で中小型に絞れる(0=制限なし)。",
        )

    # 既定値(詳細フィルタ未操作でも変数が存在するように先に初期化)
    sel_sectors = []
    sel_sectors60 = []
    cheap_only = False
    min_yield = 0.0
    min_per = 0
    max_per = 0
    max_pbr = 0.0
    min_equity = 0
    max_payout = 0
    min_growth = 0
    max_rsi = 0
    tech_buy = False
    sort_key = "ネットキャッシュ比率"
    sort_asc = False

    with st.expander("詳細フィルタ", expanded=False):
        sectors60_all = sorted(
            s for s in st.session_state.df.get("新業種", pd.Series(dtype=str)).dropna().unique()
            if str(s).strip() and str(s) != "nan"
        ) if "新業種" in st.session_state.df.columns else []
        sel_sectors60 = st.multiselect(
            "業種(67分類)", sectors60_all,
            default=[s for s in Q("sec", [], list) if s in sectors60_all])

        if "PER乖離率" in st.session_state.df.columns:
            cheap_only = st.checkbox(
                "同業比で割安のみ(PERが業種中央値より低い)", value=Q("cheap", False, bool),
                help="PER乖離率 < 0 の銘柄に絞り込みます。",
            )

        if "配当利回り(%)" in st.session_state.df.columns:
            min_yield = st.slider(
                "配当利回りの下限(%)", 0.0, 6.0, min(6.0, max(0.0, Q("ymin", 0.0, float))), 0.25,
                help="年配当÷株価。3〜4%で高配当の目安。",
            )

        if "PER" in st.session_state.df.columns:
            st.caption("PERのレンジ(下限〜上限。0=制限なし)。例: 10〜15倍")
            pcol1, pcol2 = st.columns(2)
            min_per = pcol1.number_input(
                "PER下限", 0, 200, min(200, Q("permin", 0, int)), 5,
                help="低すぎる(業績悪化の織り込み等)を除きたいときに。10前後が一例。",
            )
            max_per = pcol2.number_input(
                "PER上限", 0, 200, min(200, Q("permax", 0, int)), 5,
                help="一般に15倍前後が標準、低いほど割安。",
            )

        if "PBR" in st.session_state.df.columns:
            max_pbr = st.number_input(
                "PBR上限(0=制限なし)", 0.0, 20.0, min(20.0, max(0.0, Q("pbr", 0.0, float))), 0.5,
                help="1倍＝解散価値。1倍割れは割安の目安。",
            )

        if "自己資本比率(%)" in st.session_state.df.columns:
            min_equity = st.slider(
                "自己資本比率の下限(%)", 0, 100, min(100, Q("eqmin", 0, int)), 5,
                help="純資産÷総資産。50%以上で財務が健全の目安。",
            )

        if "配当性向(%)" in st.session_state.df.columns:
            max_payout = st.number_input(
                "配当性向の上限(%, 0=制限なし)", 0, 200, min(200, Q("paymax", 0, int)), 5,
                help="配当÷利益。50%以下で無理のない配当の目安(高すぎは減配リスク)。",
            )

        if "増収増益(年)" in st.session_state.df.columns:
            min_growth = st.number_input(
                "増収増益(連続)の下限(年, 0=制限なし)", 0, 5, min(5, Q("grow", 0, int)), 1,
                help="例:3で「直近3期連続の増収増益」に絞る。データは比率1.0以上の銘柄に付与。",
            )

        if "RSI" in st.session_state.df.columns:
            st.caption("テクニカル（タイミング）")
            max_rsi = st.number_input(
                "RSI上限(0=制限なし。例:30で売られすぎ＝押し目候補)", 0, 100,
                min(100, Q("rsimax", 0, int)), 5,
                help="RSIが低い＝売られすぎ。割安(ファンダ)×売られすぎ(タイミング)の合わせ技に。",
            )
            tech_buy = st.checkbox(
                "反転サインのみ(買い検討)", value=Q("techbuy", False, bool),
                help="RSI≤30かつストキャスが下→上にクロスした「売られすぎ＋反転」銘柄に絞る。",
            )

        sort_opts = [c for c in ["ネットキャッシュ比率", "配当利回り(%)", "配当性向(%)",
                                 "自己資本比率(%)", "増収増益(年)", "PER乖離率", "PER", "時価総額(億円)"]
                     if c in st.session_state.df.columns]
        if sort_opts:
            _si = sort_opts.index(Q("sort", sort_opts[0])) if Q("sort", sort_opts[0]) in sort_opts else 0
            sort_key = st.selectbox("並び替え", sort_opts, index=_si)
        sort_asc = st.checkbox("昇順", value=Q("asc", (sort_key in ("PER", "PER乖離率")), bool))

    # ---- 現在の絞り込みをURLに保存(ブックマーク/共有で再現) ----
    _params = {}
    if abs(min_ratio - 1.0) > 1e-9:
        _params["ratio"] = str(round(min_ratio, 2))
    if sel_markets and sorted(sel_markets) != sorted(markets_all):
        _params["mkt"] = "|".join(sel_markets)
    if sel_sectors60:
        _params["sec"] = "|".join(sel_sectors60)
    if min_cap:
        _params["capmin"] = str(min_cap)
    if max_cap:
        _params["capmax"] = str(max_cap)
    if cheap_only:
        _params["cheap"] = "1"
    if min_yield:
        _params["ymin"] = str(min_yield)
    if min_per:
        _params["permin"] = str(min_per)
    if max_per:
        _params["permax"] = str(max_per)
    if max_pbr:
        _params["pbr"] = str(max_pbr)
    if min_equity:
        _params["eqmin"] = str(min_equity)
    if max_payout:
        _params["paymax"] = str(max_payout)
    if min_growth:
        _params["grow"] = str(min_growth)
    if max_rsi:
        _params["rsimax"] = str(max_rsi)
    if tech_buy:
        _params["techbuy"] = "1"
    if sort_opts and sort_key != sort_opts[0]:
        _params["sort"] = sort_key
    if sort_asc:
        _params["asc"] = "1"
    try:
        if dict(st.query_params) != _params:
            st.query_params.clear()
            if _params:
                st.query_params.update(_params)
    except Exception:
        pass
    st.caption("🔖 いまの絞り込みはURLに保存されます。ブラウザでブックマークすれば、"
               "その条件をいつでも再現・共有できます。条件を全て既定に戻すとURLもクリアされます。")

    with st.expander("⚙️ 最新データで再計算", expanded=False):
        st.caption(
            "Yahoo Financeから取得し直します。共有サーバー(クラウド)ではレート制限で途中停止しやすいため、"
            "通常は同梱の事前計算データの閲覧で十分です。少数銘柄での確認向けです。"
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
        df = merge_trend(add_derived(df))
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

# ---- フィルタ適用 ----
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
if min_per and "PER" in df.columns:
    per_lo = pd.to_numeric(df["PER"], errors="coerce")
    df = df[(per_lo > 0) & (per_lo >= min_per)]
if max_per and "PER" in df.columns:
    per_v = pd.to_numeric(df["PER"], errors="coerce")
    df = df[(per_v > 0) & (per_v <= max_per)]
if max_pbr and "PBR" in df.columns:
    pbr_v = pd.to_numeric(df["PBR"], errors="coerce")
    df = df[(pbr_v > 0) & (pbr_v <= max_pbr)]
if min_equity and "自己資本比率(%)" in df.columns:
    eq_v = pd.to_numeric(df["自己資本比率(%)"], errors="coerce")
    df = df[eq_v >= min_equity]
if max_payout and "配当性向(%)" in df.columns:
    pay_v = pd.to_numeric(df["配当性向(%)"], errors="coerce")
    df = df[pay_v.notna() & (pay_v <= max_payout)]
if min_growth and "増収増益(年)" in df.columns:
    g_v = pd.to_numeric(df["増収増益(年)"], errors="coerce")
    df = df[g_v.notna() & (g_v >= min_growth)]
if max_rsi and "RSI" in df.columns:
    rsi_v = pd.to_numeric(df["RSI"], errors="coerce")
    df = df[rsi_v.notna() & (rsi_v <= max_rsi)]
if tech_buy and "テクニカル" in df.columns:
    df = df[df["テクニカル"].astype(str).str.contains("反転\\(買い", na=False)]
if min_cap and "時価総額(億円)" in df.columns:
    cap_lo = pd.to_numeric(df["時価総額(億円)"], errors="coerce")
    df = df[cap_lo >= min_cap]
if max_cap and "時価総額(億円)" in df.columns:
    cap_v = pd.to_numeric(df["時価総額(億円)"], errors="coerce")
    df = df[cap_v <= max_cap]
if sort_key in df.columns:
    df = df.sort_values(sort_key, ascending=sort_asc,
                        key=lambda s: pd.to_numeric(s, errors="coerce")).reset_index(drop=True)
else:
    df = df.sort_values("ネットキャッシュ比率", ascending=False).reset_index(drop=True)


# ---- 連動分析用のデータ・ヘルパ(タブ2で使用するため先に定義) ----
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


# ---- クラウドウォッチリスト(GitHub保存) ----
# 保存先は main ではなく専用ブランチ(watchlists)。main に書くと保存のたびに
# Streamlit Cloud の再デプロイが走ってしまうため分離している。
GH_REPO = "hi8068-creator/netcash-screener"
WL_BRANCH = "watchlists"
BIZJA_CSV = os.path.join(os.path.dirname(__file__), "business_ja.csv")


def _gh_token() -> str:
    """保存用トークン。Streamlit Secrets か環境変数 GITHUB_TOKEN から取得。"""
    try:
        tok = st.secrets.get("GITHUB_TOKEN", "")
        if tok:
            return tok
    except Exception:
        pass
    return os.environ.get("GITHUB_TOKEN", "")


@st.cache_data(show_spinner=False)
def load_bizja() -> dict:
    """日本語の事業内容(事前生成 business_ja.csv)。コード→説明文。"""
    if os.path.exists(BIZJA_CSV):
        try:
            b = pd.read_csv(BIZJA_CSV, dtype={"コード": str})
            return dict(zip(b["コード"], b["事業内容"].fillna("")))
        except Exception:
            pass
    return {}


@st.cache_data(show_spinner=False, ttl=60)
def cloud_list_users() -> list:
    """クラウド保存済みのユーザー名一覧(公開リポジトリのため認証不要)。"""
    import requests
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GH_REPO}/contents/watchlists",
            params={"ref": WL_BRANCH}, timeout=10)
        if r.status_code != 200:
            return []
        return sorted(f["name"][:-5] for f in r.json()
                      if isinstance(f, dict) and f.get("name", "").endswith(".json"))
    except Exception:
        return []


@st.cache_data(show_spinner=False, ttl=60)
def cloud_load(user: str):
    """指定ユーザーのウォッチリストを読み込む。{updated, items:[{コード,メモ}]}"""
    import requests
    from urllib.parse import quote
    try:
        url = (f"https://raw.githubusercontent.com/{GH_REPO}/{WL_BRANCH}"
               f"/watchlists/{quote(user)}.json")
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def cloud_save(user: str, watch: dict):
    """ウォッチリストを watchlists ブランチに保存。戻り値 (成功?, メッセージ)。"""
    import base64
    import json as jsonlib

    import requests
    from urllib.parse import quote
    tok = _gh_token()
    if not tok:
        return False, ("保存用トークンが未設定です。Streamlit Cloud の "
                       "App settings → Secrets に GITHUB_TOKEN を設定してください。")
    user = user.strip().replace("/", "／")
    if not user:
        return False, "名前を入力してください。"
    api = f"https://api.github.com/repos/{GH_REPO}/contents/{quote(f'watchlists/{user}.json')}"
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    from datetime import timedelta, timezone
    jst = timezone(timedelta(hours=9))
    payload = {"updated": datetime.now(jst).strftime("%Y-%m-%d %H:%M"),
               "items": [{"コード": c, "メモ": m} for c, m in watch.items()]}
    body = jsonlib.dumps(payload, ensure_ascii=False, indent=1)
    data = {"message": f"ウォッチリスト保存: {user}",
            "content": base64.b64encode(body.encode("utf-8")).decode(),
            "branch": WL_BRANCH}
    try:
        r = requests.get(api, params={"ref": WL_BRANCH}, headers=headers, timeout=10)
        if r.status_code == 200:
            data["sha"] = r.json().get("sha")
        r = requests.put(api, json=data, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            cloud_list_users.clear()
            cloud_load.clear()
            return True, f"クラウドに保存しました（{user}）。"
        return False, f"保存に失敗しました (HTTP {r.status_code})。"
    except Exception as e:
        return False, f"保存に失敗しました: {e}"


# ============================ タブ構成 ============================
tab_screen, tab_corr, tab_watch, tab_help = st.tabs(
    ["🔍 スクリーニング", "🔗 連動分析", "⭐ ウォッチリスト", "❓ 使い方・用語"]
)

# ---- タブ1: スクリーニング ----
with tab_screen:
    c1, c2, c3 = st.columns(3)
    c1.metric("該当銘柄数", f"{len(df)} 件", help="絞り込み後に残った銘柄数。")
    if len(df):
        c2.metric("最大比率", f"{df['ネットキャッシュ比率'].max():.2f}",
                  help="この一覧で最もネットキャッシュ比率が高い値。")
        c3.metric("比率1.0以上", f"{(df['ネットキャッシュ比率'] >= 1.0).sum()} 件",
                  help="現金等で時価総額をまかなえる“割安の目安”を満たす銘柄数。")

    tg1, tg2 = st.columns(2)
    view_detail = tg1.toggle("詳細表示（全列）", value=False,
                             help="OFFでは主要列のみ。ONで全項目(財務内訳・アナリスト予想など)を表示。")
    show_desc = tg2.toggle("📋 列の説明を表示", value=False,
                           help="列名の直下に各列の説明(全文)を固定行で表示します。"
                           "スクロールしても消えません。")

    disp = to_display(df)
    if view_detail:
        disp_view = disp
    else:
        disp_view = disp[[c for c in BEGINNER_COLUMNS if c in disp.columns]]

    st.caption("💡 比率が高い銘柄は「なぜ割安か」を右端の短信PDFで確認しましょう。"
               "（コード・銘柄名とヘッダーは固定。列の意味は上の「📋列の説明を表示」で確認）")

    if len(disp_view):
        n = len(disp_view)
        tbl_h = min(720, 120 + n * 34 + (40 if show_desc else 0))
        build_html_table(disp_view, show_desc=show_desc, height=tbl_h)
    else:
        st.info("条件に合う銘柄がありません。フィルタを緩めてください。")

    with st.expander("📈 株価チャート（複数を重ねて比較）", expanded=False):
        if len(df):
            chart_codes = df["コード"].astype(str).tolist()
            chart_names = {str(r["コード"]): f"{r.get('銘柄名', '')}（{r['コード']}）"
                           for _, r in df.iterrows()}
            short_names = {str(r["コード"]): str(r.get("銘柄名", r["コード"]))
                           for _, r in df.iterrows()}
            picks = st.multiselect(
                "銘柄を選ぶ（複数可・1枚に重ねて表示）", chart_codes,
                default=chart_codes[:2],
                format_func=lambda c: chart_names.get(c, c), key="screen_chart")
            norm = st.radio("表示", ["比較(100基準)", "実株価"], horizontal=True,
                            key="screen_norm") == "比較(100基準)"
            if picks:
                price_chart(picks, names=short_names, normalize=norm)
                tv_links(picks, names=short_names)
            else:
                st.info("上で銘柄を選ぶとチャートが表示されます。")
        else:
            st.info("該当銘柄がありません。")

    if len(df):
        ts = datetime.now().strftime("%Y%m%d")
        # ダウンロードは常に全列
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

    # 業種別PER中央値の一覧(67分類ベース)
    base = st.session_state.df
    if "新業種" in base.columns and "PER" in base.columns:
        with st.expander("📚 業種別(67分類)PER中央値ランキング", expanded=False):
            per = pd.to_numeric(base["PER"], errors="coerce")
            v = base[per.notna() & (per > 0)].copy()
            v["PER"] = pd.to_numeric(v["PER"], errors="coerce")
            agg = (
                v.groupby("新業種")["PER"]
                .agg(銘柄数="count", PER中央値="median")
                .reset_index()
                .rename(columns={"新業種": "業種(67)"})
                .sort_values("PER中央値")
            )
            agg["PER中央値"] = agg["PER中央値"].round(1)
            st.markdown(
                "**業種ごとのPERの“相場(標準値)”の一覧です。** PERの普通の水準は業種で大きく違うため、"
                "個別銘柄のPERが“同業と比べて”割安か割高かを判断するモノサシになります"
                "(一覧の「業種PER中央値」「PER乖離率」列やサイドバーの「同業比で割安のみ」と同じ考え方)。"
            )
            st.caption(
                "黒字銘柄のみで集計。中央値が低い業種は市場から低めに評価されがちですが、"
                "成熟・景気敏感などの理由のことも多く、低い＝買いとは限りません。"
            )
            st.dataframe(
                agg, width="stretch", hide_index=True,
                column_config={"PER中央値": st.column_config.NumberColumn(format="%.1f")},
            )

            st.divider()
            st.markdown("**業種を選ぶと、その中の銘柄が見られます（PERの低い＝割安な順）。**")
            sec_pick = st.selectbox(
                "業種(67分類)", ["—"] + agg["業種(67)"].tolist(), key="per_drill")
            if sec_pick and sec_pick != "—":
                mem = base[base["新業種"] == sec_pick].copy()
                mem["_p"] = pd.to_numeric(mem.get("PER"), errors="coerce")
                mem = mem.sort_values("_p", na_position="last")
                ni = pd.to_numeric(mem.get("純利益"), errors="coerce") if "純利益" in mem.columns \
                    else pd.Series([float("nan")] * len(mem), index=mem.index)

                def _num(v, f):
                    v = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
                    return "—" if pd.isna(v) else f.format(v)

                rows = []
                for (_, r), n in zip(mem.iterrows(), ni):
                    p = r["_p"]
                    per_s = ("300超" if pd.notna(p) and p > 300 else
                             f"{p:.1f}" if pd.notna(p) else
                             ("赤字" if pd.notna(n) and n <= 0 else "—"))
                    c4 = str(r["コード"]).replace(".T", "")
                    direct = str(r.get("短信PDF直URL", "") or "")
                    rows.append({
                        "コード": r["コード"], "銘柄名": r.get("銘柄名", ""), "PER": per_s,
                        "PER乖離率": _num(r.get("PER乖離率"), "{:.1%}"),
                        "ネットキャッシュ比率": _num(r.get("ネットキャッシュ比率"), "{:.2f}"),
                        "配当利回り(%)": _num(r.get("配当利回り(%)"), "{:.2f}"),
                        "時価総額(億円)": _num(r.get("時価総額(億円)"), "{:,.0f}"),
                        "短信PDF": direct if direct.strip() else f"{YAHOO_DISCLOSURE_BASE}{r['コード']}/disclosure",
                    })
                memv = pd.DataFrame(rows)
                med = agg.loc[agg["業種(67)"] == sec_pick, "PER中央値"]
                st.caption(f"{sec_pick}: {len(memv)}社"
                           + (f"（PER中央値 {med.iloc[0]:.1f}倍）" if len(med) else "")
                           + "／黒字はPERの低い順、赤字・PER無しは末尾。空欄は「—」。")
                st.dataframe(
                    memv, width="stretch", hide_index=True,
                    column_config={
                        "短信PDF": st.column_config.LinkColumn("短信PDF", display_text="開く"),
                    },
                )

# ---- タブ2: 連動分析 ----
with tab_corr:
    if not _CORR_OK:
        st.info("連動分析用のデータ(returns.parquet など)が見つかりません。")
    else:
        st.subheader("🔗 連動分析(株価の連動)")
        st.caption(
            "直近1年の日次リターンの相関。『市場調整後』は各日の市場平均を差し引いた残差で計算し、"
            "地合いを除いた“本当の連動”を見ます。相関は因果ではなく、期間によって変わるスナップショットです。"
        )
        ret, peers_adj, peers_raw, cross = load_corr()

        base = st.session_state.df
        # 会社名で探せるよう「銘柄名（コード）」の順で表示(selectboxは表示名で検索可能)
        code_name = {str(r["コード"]): f"{r.get('銘柄名', '')}（{r['コード']}）"
                     for _, r in base.iterrows()}
        avail = [c for c in peers_adj["コード"].unique() if c in code_name]
        avail = sorted(avail, key=lambda c: code_name[c])

        cc1, cc2 = st.columns([2, 1])
        # 会社名を先頭に表示するので、ボックスに会社名を打てばそのまま絞り込める
        sel = cc1.selectbox(
            "銘柄を選ぶ", avail,
            format_func=lambda c: code_name.get(c, c),
            index=avail.index("7203.T") if "7203.T" in avail else 0,
        )
        mode = cc2.radio("相関の種類", ["市場調整後", "素の相関"], horizontal=False)

        peers = peers_adj if mode == "市場調整後" else peers_raw
        sub = peers[peers["コード"] == sel].head(15).copy()

        # メタ情報(前日終値・年間配当・予想EPSを保持し、PER/配当利回りの裏付けに使う。
        #  ネットキャッシュ比率/PBRは連動分析では出さない)
        META = [c for c in ["新業種", "前日終値", "配当", "forwardEPS", "予想PER",
                            "PER", "配当利回り(%)", "時価総額(億円)"]
                if c in base.columns]
        bmeta = base.set_index("コード")

        # 選択銘柄の情報を上部に表示
        if sel in bmeta.index:
            si = bmeta.loc[sel]
            st.markdown(f"### {code_name.get(sel, sel)}")
            mcols = st.columns(5)

            def _fmt(v, f):
                try:
                    x = float(v)
                    if x != x:  # NaN
                        return "—"
                    return f.format(x)
                except Exception:
                    return "—"
            mcols[0].metric("前日終値", _fmt(si.get("前日終値"), "{:,.0f}円"))
            mcols[1].metric("時価総額", _fmt(si.get("時価総額(億円)"), "{:,.0f}億"))
            mcols[2].metric("PER", _fmt(si.get("PER"), "{:.1f}"))
            mcols[3].metric("配当利回り", _fmt(si.get("配当利回り(%)"), "{:.2f}%"))
            mcols[4].metric("業種(67)", str(si.get("新業種", "—")))

        with st.expander("📈 株価チャート（選択銘柄＋連動銘柄を重ねて比較）", expanded=True):
            peer_codes = sub["連動銘柄"].astype(str).tolist()
            chart_opts = [sel] + [c for c in peer_codes if c != sel]
            scode = {c: code_name.get(c, c).split("（")[0] for c in chart_opts}
            cpicks = st.multiselect(
                "重ねる銘柄（既定=選択銘柄＋連動上位）", chart_opts, default=chart_opts[:4],
                format_func=lambda c: code_name.get(c, c), key="corr_chart")
            if cpicks:
                price_chart(cpicks, names=scode, normalize=True)
                st.caption("100基準で重ねると、連動して動いているかが一目で分かります。")
                tv_links(cpicks, names=scode)

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
        comp = comp.rename(columns={"新業種": "業種(67)"})
        order = [c for c in ["銘柄名", "前日終値", "相関", "先行/遅行", "業種(67)",
                             "PER", "予想PER", "forwardEPS", "配当", "配当利回り(%)",
                             "時価総額(億円)"]
                 if c in comp.columns]

        st.markdown(f"**連動する銘柄（{mode}・上位15）** ＋ ★選択銘柄は最上段に固定（スクロールしても並べて比較）")
        render_corr_table(comp, order, height=470)
        st.caption(
            "予想PER＝前日終値÷予想EPS、配当利回り＝年間配当÷前日終値。"
            "終値は1日1回更新（場中は追いません）。配当・予想EPSは四半期決算ごとに見直されます。"
        )

        with st.expander("🎭 別業種なのに連動する『意外なペア』(市場調整後・上位300)", expanded=False):
            st.caption("業種が違うのに高相関＝隠れたテーマ/共通要因の可能性。小型株は偶然の相関も混じるため要検証。")
            st.dataframe(cross, width="stretch", hide_index=True,
                         column_config={"相関": st.column_config.NumberColumn(format="%.3f")})

# ---- タブ3: ウォッチリスト(備忘) ----
with tab_watch:
    st.subheader("⭐ ウォッチリスト（備忘）")
    st.caption(
        "気になる銘柄をメモ付きで記録できます。最新の指標は results データから自動表示。"
        "※共有サーバー上ではブラウザを閉じると消えるため、「💾 保存(CSV)」で書き出し、"
        "次回「読み込み」で復元してください（自分専用の備忘ファイルになります）。"
    )

    if "watch" not in st.session_state:
        st.session_state.watch = {}  # コード(7203.T) -> メモ

    wbase = st.session_state.df
    if "コード" not in wbase.columns:
        st.info("銘柄データが読み込まれていません。")
    else:
        wname = dict(zip(wbase["コード"].astype(str), wbase.get("銘柄名", "")))
        wopts = list(wbase["コード"].astype(str))

        def _wlabel(c):
            return f"{c}　{wname.get(c, '')}"

        # 追加 + 読み込み
        c1, c2, c3 = st.columns([3, 4, 1.2])
        add_code = c1.selectbox("銘柄を追加", wopts, format_func=_wlabel, key="wl_add")
        add_memo = c2.text_input("メモ(任意)", key="wl_memo",
                                 placeholder="例: 決算後に再確認 / 配当目当て など")
        if c3.button("➕ 追加", use_container_width=True):
            if add_code:
                st.session_state.watch[add_code] = add_memo or ""
                st.rerun()

        up = st.file_uploader("保存したウォッチリスト(CSV)を読み込み", type="csv", key="wl_up")
        if up is not None:
            try:
                wdf_up = pd.read_csv(up, dtype=str)
                n = 0
                for _, r in wdf_up.iterrows():
                    code = str(r.get("コード", "")).strip()
                    if code:
                        st.session_state.watch[code] = str(r.get("メモ", "") or "")
                        n += 1
                st.success(f"{n}件を読み込みました。")
            except Exception as e:
                st.error(f"読み込みに失敗しました: {e}")

        watch = st.session_state.watch
        st.divider()
        if not watch:
            st.info("まだ登録がありません。上の「銘柄を追加」から登録してください。")
        else:
            METAW = [c for c in ["新業種", "ネットキャッシュ比率", "PER", "PER乖離率",
                                 "配当利回り(%)", "時価総額(億円)", "来期見通し(短信抜粋)",
                                 "短信PDF直URL"] if c in wbase.columns]
            wmeta = wbase.set_index("コード")
            _bizja = load_bizja()
            rows = []
            for code, memo in watch.items():
                r = wmeta.loc[code] if code in wmeta.index else None
                row = {"削除": False, "コード": code, "銘柄名": wname.get(code, ""),
                       "メモ": memo, "事業内容": _bizja.get(code, "")}
                for m in METAW:
                    row[m] = (r.get(m) if r is not None else None)
                rows.append(row)
            wview = pd.DataFrame(rows)
            wview = wview.rename(columns={"新業種": "業種(67)",
                                          "来期見通し(短信抜粋)": "来期見通し"})
            # 短信PDFリンク列(直URLが無ければ適時開示一覧)
            if "短信PDF直URL" in wview.columns:
                disc = YAHOO_DISCLOSURE_BASE + wview["コード"].astype(str) + "/disclosure"
                direct = wview["短信PDF直URL"].fillna("").astype(str)
                wview["短信PDF"] = [d if d.strip() else s for d, s in zip(direct, disc)]
                wview = wview.drop(columns=["短信PDF直URL"])
            order = [c for c in ["削除", "コード", "銘柄名", "業種(67)", "メモ", "事業内容",
                                 "ネットキャッシュ比率", "PER", "PER乖離率", "配当利回り(%)",
                                 "時価総額(億円)", "来期見通し", "短信PDF"] if c in wview.columns]

            edited = st.data_editor(
                wview[order], hide_index=True, use_container_width=True,
                column_config={
                    "削除": st.column_config.CheckboxColumn("削除", help="チェックで削除"),
                    "コード": st.column_config.TextColumn("コード", disabled=True),
                    "銘柄名": st.column_config.TextColumn("銘柄名", disabled=True),
                    "業種(67)": st.column_config.TextColumn("業種(67)", disabled=True),
                    "事業内容": st.column_config.TextColumn(
                        "事業内容", width="large", disabled=True,
                        help="何の会社か(日本語要約)。比率0.9以上の銘柄に付与。"),
                    "メモ": st.column_config.TextColumn("メモ", width="large"),
                    "ネットキャッシュ比率": st.column_config.NumberColumn(format="%.2f", disabled=True),
                    "PER": st.column_config.NumberColumn(format="%.1f", disabled=True),
                    "PER乖離率": st.column_config.NumberColumn(format="percent", disabled=True),
                    "配当利回り(%)": st.column_config.NumberColumn(format="%.2f", disabled=True),
                    "時価総額(億円)": st.column_config.NumberColumn(format="localized", disabled=True),
                    "来期見通し": st.column_config.TextColumn("来期見通し", width="large", disabled=True),
                    "短信PDF": st.column_config.LinkColumn("短信PDF", display_text="開く", disabled=True),
                },
                key="wl_editor",
            )

            # 編集(メモ)を保持しつつ、削除チェックの行を除外
            new_watch = {}
            deleted = False
            for _, r in edited.iterrows():
                if r.get("削除"):
                    deleted = True
                    continue
                new_watch[str(r["コード"])] = str(r.get("メモ", "") or "")
            st.session_state.watch = new_watch
            if deleted:
                st.rerun()

            save_df = pd.DataFrame(
                [{"コード": c, "メモ": m} for c, m in st.session_state.watch.items()])
            st.download_button(
                "💾 保存(CSV)", save_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="watchlist.csv", mime="text/csv")
            st.caption(f"登録数: {len(st.session_state.watch)}件。"
                       "メモ欄はその場で編集できます（編集後は念のため保存を）。")

        # ---- ☁️ みんなのウォッチリスト(クラウド保存・共有) ----
        st.divider()
        st.subheader("☁️ みんなのウォッチリスト")
        st.caption(
            "名前を付けて保存すると、別の端末・別の日でも呼び出せます。"
            "保存したリストは**公開**され、人を選んでお互いのリストを見られます（見せ合い用）。"
        )
        bizja = load_bizja()
        wmeta_c = wbase.set_index("コード")

        cs1, cs2 = st.columns([2, 1.2])
        save_name = cs1.text_input("名前(ニックネーム)", key="wl_cloud_name",
                                   placeholder="例: じょー")
        if cs2.button("☁️ いまのリストをクラウドに保存", use_container_width=True):
            if not st.session_state.watch:
                st.warning("ウォッチリストが空です。先に上で銘柄を追加してください。")
            else:
                ok, msg = cloud_save(save_name, st.session_state.watch)
                (st.success if ok else st.error)(msg)

        users = cloud_list_users()
        if not users:
            st.info("まだクラウドに保存されたリストはありません。最初の1人になりましょう。")
        else:
            cu1, cu2 = st.columns([2, 1.2])
            view_user = cu1.selectbox("人を選んで閲覧", users, key="wl_cloud_user")
            if cu2.button("🔄 一覧を更新", use_container_width=True):
                cloud_list_users.clear()
                cloud_load.clear()
                st.rerun()
            cdata = cloud_load(view_user) if view_user else None
            if cdata and cdata.get("items"):
                st.markdown(f"**{view_user} さんのウォッチリスト**　"
                            f"(更新: {cdata.get('updated', '—')}・{len(cdata['items'])}銘柄)")
                crows = []
                for it in cdata["items"]:
                    code = str(it.get("コード", ""))
                    r = wmeta_c.loc[code] if code in wmeta_c.index else None
                    crow = {"コード": code, "銘柄名": wname.get(code, ""),
                            "メモ": it.get("メモ", ""), "事業内容": bizja.get(code, "")}
                    for m in ["新業種", "前日終値", "ネットキャッシュ比率", "PER",
                              "配当利回り(%)", "時価総額(億円)"]:
                        if m in wbase.columns:
                            crow[m] = (r.get(m) if r is not None else None)
                    crows.append(crow)
                cdf = pd.DataFrame(crows).rename(columns={"新業種": "業種(67)"})
                st.dataframe(
                    cdf, hide_index=True, use_container_width=True,
                    column_config={
                        "事業内容": st.column_config.TextColumn("事業内容", width="large"),
                        "メモ": st.column_config.TextColumn("メモ", width="medium"),
                        "前日終値": st.column_config.NumberColumn("前日終値(円)", format="localized"),
                        "ネットキャッシュ比率": st.column_config.NumberColumn(format="%.2f"),
                        "PER": st.column_config.NumberColumn("PER(倍)", format="%.1f"),
                        "配当利回り(%)": st.column_config.NumberColumn(format="%.2f"),
                        "時価総額(億円)": st.column_config.NumberColumn(format="localized"),
                    },
                )
                ci1, ci2 = st.columns([1.4, 2.6])
                if ci1.button("⬇️ このリストを自分に取り込む",
                              help="自分のウォッチリストに追加します(同じ銘柄は上書きしません)"):
                    n_add = 0
                    for it in cdata["items"]:
                        code = str(it.get("コード", ""))
                        if code and code not in st.session_state.watch:
                            st.session_state.watch[code] = str(it.get("メモ", "") or "")
                            n_add += 1
                    st.success(f"{n_add}件を取り込みました。")
                    st.rerun()
                ccodes = [str(it.get("コード", "")) for it in cdata["items"]][:8]
                with st.expander("📈 このリストの銘柄を重ねて比較（株価・100基準）", expanded=False):
                    price_chart(ccodes, names={c: wname.get(c, c) for c in ccodes},
                                normalize=True)
            else:
                st.info("このリストはまだ空か、読み込みに失敗しました。")


# ---- タブ4: 使い方・用語 ----
with tab_help:
    st.subheader("使い方（3ステップ）")
    st.markdown(
        "1. **比率の下限で割安度を決める** … サイドバーの「ネットキャッシュ比率の下限」。まずは1.0のままでOK。\n"
        "2. **対象を絞る** … 市場区分・時価総額の上限（例:300億で中小型）で範囲をしぼる。\n"
        "3. **中身を確認** … 一覧右端の「短信PDF(公式)」や「財務(株探)」で実際の決算を確認する。"
    )

    st.subheader("用語と数値の目安")
    st.markdown(
        "- **ネットキャッシュ比率** … (流動資産＋投資有価証券×0.7−負債)÷時価総額。"
        "**1.0以上＝理屈上は“実質タダ”級に割安**。0.5以上でも現金が潤沢な目安。\n"
        "- **PER（株価収益率）** … 利益の何年分の株価か。**一般に15倍前後が標準**、低いほど割安（業種差が大きい）。\n"
        "- **PBR（株価純資産倍率）** … **1倍＝解散価値**。1倍割れは割安の目安。\n"
        "- **配当利回り** … 年配当÷株価。**3〜4%で高配当の目安**。\n"
        "- **時価総額** … 会社の規模。数百億円以下は小型株で、値動きが荒くなりやすい。\n"
        "- **業種PER中央値 / PER乖離率** … 業種によって標準PERは違う。"
        "乖離率がマイナス＝同業より割安。PERの絶対値の目安と合わせて見る。"
    )

    st.subheader("データについて")
    st.markdown(
        f"- 出典: **Yahoo Finance（無料）**　／　データ取得日（目安）: **{data_updated_str()}**\n"
        "- 株価は前営業日終値ベース、財務は直近の決算（数か月前のことがあります）。\n"
        "- PERは黒字企業のみ算出（赤字は空欄）。\n"
        "- 金額は百万円表示（決算短信の一般的な単位）。業種(67)は事業説明文ベースで分類。"
    )
    st.caption("※ データ取得日はファイル更新日が目安です（配備環境によりズレる場合があります）。")
