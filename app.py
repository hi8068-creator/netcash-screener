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


def tradingview_chart(code: str, height: int = 420) -> None:
    """選択銘柄のTradingViewチャート(リアルタイム寄り)を埋め込む。

    東証コード "7203.T" → "TSE:7203"。各 components.html は独立iframeなので
    コンテナidは固定で衝突しない。
    """
    sym = "TSE:" + str(code).replace(".T", "")
    html = f"""
    <div class="tradingview-widget-container">
      <div id="tvchart"></div>
    </div>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{sym}",
        "interval": "D",
        "timezone": "Asia/Tokyo",
        "theme": "light",
        "style": "1",
        "locale": "ja",
        "hide_side_toolbar": true,
        "allow_symbol_change": false,
        "container_id": "tvchart"
      }});
    </script>
    """
    components.html(html, height=height)

st.set_page_config(page_title="ネットキャッシュ比率スクリーニング", layout="wide")

RESULTS_CSV = os.path.join(os.path.dirname(__file__), "results.csv")
TREND_CSV = os.path.join(os.path.dirname(__file__), "earnings_trend.csv")

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
}
NUM_FMT = {
    "ネットキャッシュ比率": "{:.2f}", "PBR": "{:.2f}", "配当利回り(%)": "{:.2f}",
    "PER": "{:.1f}", "業種PER中央値": "{:.1f}", "予想PER": "{:.1f}", "配当": "{:.1f}",
    "自己資本比率(%)": "{:.1f}", "配当性向(%)": "{:.1f}", "増収増益(年)": "{:.0f}",
    "PER乖離率": "{:.1%}",
    "時価総額(億円)": "{:,.1f}", "ネットキャッシュ(億円)": "{:,.1f}",
    "前日終値": "{:,.0f}", "forwardEPS": "{:,.1f}", "目標株価": "{:,.0f}",
    "流動資産(百万円)": "{:,.0f}", "投資有価証券(百万円)": "{:,.0f}", "負債(百万円)": "{:,.0f}",
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
                txt = "" if pd.isna(x) else NUM_FMT[c].format(x)
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
        "業種PER中央値", format="%.1f", help="同じ33業種の黒字銘柄のPER中央値＝その業種の目安。"),
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
        return merge_trend(add_derived(pd.read_csv(RESULTS_CSV)))
    return pd.DataFrame(columns=core.COLUMNS_JP)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def evaluate_cached(code: str):
    """1銘柄評価をキャッシュ(6時間)。再描画や再実行での重複取得を防ぐ。"""
    r = core.evaluate(code)
    return core.asdict(r) if r is not None else None


if "df" not in st.session_state:
    st.session_state.df = load_bundled()

st.title("📊 ネットキャッシュ比率スクリーニング")
st.caption(
    "ネットキャッシュ比率 = (流動資産 + 投資有価証券×0.7 − 負債) ÷ 時価総額。"
    "1.0以上＝割安の目安。　"
    f"データ取得日: {data_updated_str()}（出典: Yahoo Finance）"
)

# ---- サイドバー(基本フィルタ＋折りたたみ) ----
with st.sidebar:
    st.header("表示フィルタ")

    # 基本フィルタ(常時表示)
    min_ratio = st.slider(
        "ネットキャッシュ比率の下限", 0.0, 3.0, 1.0, 0.05,
        help="1.0以上＝理屈上は現金等で時価総額をまかなえる割安水準。まずは1.0でOK。",
    )

    markets_all = sorted(
        m for m in st.session_state.df.get("市場", pd.Series(dtype=str)).dropna().unique()
    ) if "市場" in st.session_state.df.columns else []
    sel_markets = st.multiselect(
        "市場区分", markets_all, default=markets_all,
        help="東証の市場区分。こだわりが無ければ全選択のままでOK。",
    )

    min_cap = 0
    max_cap = 0
    if "時価総額(億円)" in st.session_state.df.columns:
        cap_series = pd.to_numeric(st.session_state.df["時価総額(億円)"], errors="coerce")
        cap_hi = int(min(5000, (cap_series.max() if cap_series.notna().any() else 1000)))
        min_cap = st.number_input(
            "時価総額の下限(億円, 0=制限なし)", 0, cap_hi, 0, 50,
            help="一定規模以上に絞る。例:500で中型以上(プロが見る規模)(0=制限なし)。",
        )
        max_cap = st.number_input(
            "時価総額の上限(億円, 0=制限なし)", 0, cap_hi, 0, 50,
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
    sort_key = "ネットキャッシュ比率"
    sort_asc = False

    with st.expander("詳細フィルタ", expanded=False):
        sectors60_all = sorted(
            s for s in st.session_state.df.get("新業種", pd.Series(dtype=str)).dropna().unique()
            if str(s).strip() and str(s) != "nan"
        ) if "新業種" in st.session_state.df.columns else []
        sel_sectors60 = st.multiselect("業種(67分類)", sectors60_all, default=[])

        if "PER乖離率" in st.session_state.df.columns:
            cheap_only = st.checkbox(
                "同業比で割安のみ(PERが業種中央値より低い)", value=False,
                help="PER乖離率 < 0 の銘柄に絞り込みます。",
            )

        if "配当利回り(%)" in st.session_state.df.columns:
            min_yield = st.slider(
                "配当利回りの下限(%)", 0.0, 6.0, 0.0, 0.25,
                help="年配当÷株価。3〜4%で高配当の目安。",
            )

        if "PER" in st.session_state.df.columns:
            st.caption("PERのレンジ(下限〜上限。0=制限なし)。例: 10〜15倍")
            pcol1, pcol2 = st.columns(2)
            min_per = pcol1.number_input(
                "PER下限", 0, 200, 0, 5,
                help="低すぎる(業績悪化の織り込み等)を除きたいときに。10前後が一例。",
            )
            max_per = pcol2.number_input(
                "PER上限", 0, 200, 0, 5,
                help="一般に15倍前後が標準、低いほど割安。",
            )

        if "PBR" in st.session_state.df.columns:
            max_pbr = st.number_input(
                "PBR上限(0=制限なし)", 0.0, 20.0, 0.0, 0.5,
                help="1倍＝解散価値。1倍割れは割安の目安。",
            )

        if "自己資本比率(%)" in st.session_state.df.columns:
            min_equity = st.slider(
                "自己資本比率の下限(%)", 0, 100, 0, 5,
                help="純資産÷総資産。50%以上で財務が健全の目安。",
            )

        if "配当性向(%)" in st.session_state.df.columns:
            max_payout = st.number_input(
                "配当性向の上限(%, 0=制限なし)", 0, 200, 0, 5,
                help="配当÷利益。50%以下で無理のない配当の目安(高すぎは減配リスク)。",
            )

        if "増収増益(年)" in st.session_state.df.columns:
            min_growth = st.number_input(
                "増収増益(連続)の下限(年, 0=制限なし)", 0, 5, 0, 1,
                help="例:3で「直近3期連続の増収増益」に絞る。データは比率1.0以上の銘柄に付与。",
            )

        sort_opts = [c for c in ["ネットキャッシュ比率", "配当利回り(%)", "配当性向(%)",
                                 "自己資本比率(%)", "増収増益(年)", "PER乖離率", "PER", "時価総額(億円)"]
                     if c in st.session_state.df.columns]
        if sort_opts:
            sort_key = st.selectbox("並び替え", sort_opts, index=0)
        sort_asc = st.checkbox("昇順", value=(sort_key in ("PER", "PER乖離率")))

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


# ============================ タブ構成 ============================
tab_screen, tab_corr, tab_help = st.tabs(
    ["🔍 スクリーニング", "🔗 連動分析", "❓ 使い方・用語"]
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

    with st.expander("📈 リアルタイム株価チャート（TradingView）", expanded=False):
        if len(df):
            chart_codes = df["コード"].astype(str).tolist()
            chart_names = {str(r["コード"]): f"{r.get('銘柄名', '')}（{r['コード']}）"
                           for _, r in df.iterrows()}
            pick = st.selectbox(
                "銘柄を選ぶ", chart_codes,
                format_func=lambda c: chart_names.get(c, c), key="screen_chart")
            tradingview_chart(pick)
            st.caption("TradingViewの埋め込み。取引所により表示が遅延する場合があり、"
                       "一部の小型株は未対応のことがあります。")
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

    # 業種別PER中央値の一覧
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

        # メタ情報(連動分析では 67業種・PER・配当利回り・時価総額 のみ。ネットキャッシュ比率/PBRは出さない)
        META = [c for c in ["新業種", "PER", "配当利回り(%)", "時価総額(億円)"]
                if c in base.columns]
        bmeta = base.set_index("コード")

        # 選択銘柄の情報を上部に表示
        if sel in bmeta.index:
            si = bmeta.loc[sel]
            st.markdown(f"### {code_name.get(sel, sel)}")
            mcols = st.columns(4)

            def _fmt(v, f):
                try:
                    x = float(v)
                    if x != x:  # NaN
                        return "—"
                    return f.format(x)
                except Exception:
                    return "—"
            mcols[0].metric("時価総額", _fmt(si.get("時価総額(億円)"), "{:,.0f}億"))
            mcols[1].metric("PER", _fmt(si.get("PER"), "{:.1f}"))
            mcols[2].metric("配当利回り", _fmt(si.get("配当利回り(%)"), "{:.2f}%"))
            mcols[3].metric("業種(67)", str(si.get("新業種", "—")))

        with st.expander("📈 リアルタイム株価チャート（TradingView）", expanded=False):
            tradingview_chart(sel)
            st.caption("TradingViewの埋め込み。取引所により表示が遅延する場合があり、"
                       "一部の小型株は未対応のことがあります。")

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
        order = [c for c in ["銘柄名", "相関", "先行/遅行", "業種(67)",
                             "PER", "配当利回り(%)", "時価総額(億円)"]
                 if c in comp.columns]

        st.markdown(f"**連動する銘柄（{mode}・上位15）** ＋ 先頭は選択銘柄（並べて比較）")
        st.dataframe(
            comp[order], width="stretch", hide_index=True,
            column_config={
                "相関": st.column_config.NumberColumn(format="%.3f"),
                "PER": st.column_config.NumberColumn(format="%.1f"),
                "配当利回り(%)": st.column_config.NumberColumn(format="%.2f"),
                "時価総額(億円)": st.column_config.NumberColumn(format="localized"),
            },
        )

        with st.expander("🎭 別業種なのに連動する『意外なペア』(市場調整後・上位300)", expanded=False):
            st.caption("業種が違うのに高相関＝隠れたテーマ/共通要因の可能性。小型株は偶然の相関も混じるため要検証。")
            st.dataframe(cross, width="stretch", hide_index=True,
                         column_config={"相関": st.column_config.NumberColumn(format="%.3f")})

# ---- タブ3: 使い方・用語 ----
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
