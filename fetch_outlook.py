#!/usr/bin/env python3
"""決算短信から「今後の見通し」本文を抽出して列データを作る。

ファクトチェック目的のため、LLMによる言い換え(ハルシネーション懸念)はせず、
短信PDF本文の該当箇所を**そのまま抜粋**する。

データ経路(無料):
  Yahoo!ファイナンス適時開示ページ(銘柄コードで固定URL)
    -> 「決算短信」のPDF URLを取得(TDnet掲載の公式PDF)
    -> PDF本文をpypdfで抽出 -> 「今後の見通し」段落を抜粋

例:
  python3 fetch_outlook.py --min-ratio 1.0 --resume
"""
import argparse
import io
import os
import re
import time

import pandas as pd
import requests
from pdfminer.high_level import extract_text as pdf_extract_text

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_SESSION = requests.Session()
_SESSION.headers.update(UA)


def _get(url, retries=4, want_html=True, timeout=40):
    """リトライ＋指数バックオフ付きGET。

    Yahoo!ファイナンスはレート制限時に HTTP 500 や極端に短いスタブHTML(約5KB)を返す。
    その場合は失敗扱いにして待機・再試行する。取得できなければ None を返す。
    """
    delay = 5
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, timeout=timeout)
            ok = r.status_code == 200
            if ok and want_html and len(r.text) < 50000:
                ok = False  # スタブページ(レート制限)とみなす
            if ok:
                return r
        except Exception:
            pass
        time.sleep(delay)
        delay = min(delay * 2, 60)
    return None

# 見通し本文の見出し候補
HEADS = ["今後の見通し", "次期の見通し", "業績見通し", "通期の見通し",
         "次期の業績見通し", "次年度の見通し", "翌期の見通し"]

# 短信候補から除外するタイトル(補足資料・訂正・お知らせ等)
EXCLUDE_TITLE = ["訂正", "修正", "補足", "説明資料", "プレゼン", "ファクト",
                 "配当", "取得", "分割", "予想の修正", "延期", "お知らせ", "に関する"]

# 業績予想の注意書き(定型文)。本文より優先度を下げるための減点語。
BOILERPLATE = ["将来に関する記述", "約束する趣旨", "入手可能な情報", "ご利用に当たって",
               "ご利用にあた", "前提となる条件", "本資料に記載", "適切な利用"]


def latest_tanshin(code: str):
    """銘柄コードから最新の決算短信PDFの(URL, タイトル)を返す。通期を優先。"""
    url = f"https://finance.yahoo.co.jp/quote/{code}.T/disclosure"
    r = _get(url, want_html=True)
    if r is None:
        raise RuntimeError("適時開示ページ取得失敗(レート制限の可能性)")
    html = r.text
    pairs = re.findall(
        r'href="(https://[^"]+?\.pdf)"[^>]*>\s*<h3[^>]*>([^<]+)</h3>', html
    )
    cand = [
        (u, t) for u, t in pairs
        if "決算短信" in t and not any(x in t for x in EXCLUDE_TITLE)
    ]
    if not cand:
        return None, None
    tsu = [(u, t) for u, t in cand if "四半期" not in t]  # 通期優先
    return (tsu or cand)[0]


def extract_outlook(pdf_url: str) -> str:
    """短信PDFから「今後の見通し」本文を抜粋(整形済みテキスト)。

    本文抽出は pdfminer.six を使用(CIDフォントの短信PDFにも強い)。
    """
    r = _get(pdf_url, want_html=False, timeout=60)
    if r is None:
        return ""
    full = pdf_extract_text(io.BytesIO(r.content)) or ""
    best, best_score = "", -99
    for head in HEADS:
        for m in re.finditer(head, full):
            seg = full[m.start():m.start() + 650]
            score = sum(k in seg for k in ["につきまし", "見込", "予想", "次期", "当社", "百万円"])
            score -= sum(k in seg[:40] for k in ["……", "ご覧ください", "Ｐ.", "目次"]) * 3
            score -= sum(k in seg for k in BOILERPLATE) * 2  # 注意書きを下げる
            if score > best_score:
                best_score, best = score, seg
    text = re.sub(r"\s+", " ", best).strip()
    # 見出し語の重複(「今後の見通し 今後の見通しにつきまして」)のみ整理。
    # 単独見出しは残す(削ると「につきましては…」と不自然になるため)。
    for head in HEADS:
        text = re.sub(rf"^{head}[\s　]*(?={head})", "", text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="results.csv")
    ap.add_argument("--out", default="outlook_raw.csv")
    ap.add_argument("--min-ratio", type=float, default=1.0)
    ap.add_argument("--max-chars", type=int, default=200, help="抜粋の最大文字数")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--retry-empty", action="store_true",
                    help="既存outの見通しが空の行を再処理する(保存済みPDF URLを再利用)")
    ap.add_argument("--save-every", type=int, default=10)
    args = ap.parse_args()

    src = pd.read_csv(args.infile)
    src = src[src["ネットキャッシュ比率"] >= args.min_ratio]
    codes = [str(c).replace(".T", "") for c in src["コード"].tolist()]

    done = {}
    if (args.resume or args.retry_empty) and os.path.exists(args.out):
        prev = pd.read_csv(args.out, dtype={"コード": str})
        done = {str(r["コード"]).zfill(4): dict(r) for _, r in prev.iterrows()}
        print(f"既存 {len(done)} 件を読み込み")

    def _clean(v):
        if v is None:
            return ""
        s = str(v).strip()
        return "" if s.lower() == "nan" else s

    def has_outlook(rec):
        return bool(_clean(rec.get("来期見通し(短信抜粋)", "")))

    result = dict(done)  # code -> record

    def needs_processing(code):
        if code not in done:
            return True
        if args.retry_empty and not has_outlook(done[code]):
            return True
        return False

    todo = [c for c in codes if needs_processing(c)]
    print(f"対象 {len(todo)} 社(全{len(codes)})の見通しを抽出します...")

    def flush():
        pd.DataFrame([result[c] for c in codes if c in result]).to_csv(
            args.out, index=False, encoding="utf-8-sig"
        )

    for i, code in enumerate(todo, 1):
        title = pdf = outlook = ""
        # 空欄の再処理では保存済みPDF URLを再利用(適時開示の再スクレイプを省略)
        prev_url = _clean(done.get(code, {}).get("短信PDF_URL", ""))
        prev_title = _clean(done.get(code, {}).get("短信タイトル", ""))
        try:
            if prev_url:
                pdf, title = prev_url, prev_title
            else:
                pdf, title = latest_tanshin(code)
            if pdf:
                outlook = extract_outlook(pdf)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {code} エラー: {e}")
        excerpt = outlook[: args.max_chars]
        if outlook and len(outlook) > args.max_chars:
            excerpt += "…"
        result[code] = {
            "コード": code,
            "短信タイトル": title or "",
            "短信PDF_URL": pdf or "",
            "来期見通し(短信抜粋)": excerpt,
        }
        mark = "○" if excerpt else "×"
        print(f"  [{i}/{len(todo)}] {mark} {code} {(title or '')[:24]}")
        if args.save_every and i % args.save_every == 0:
            flush()
        if args.sleep:
            time.sleep(args.sleep)

    flush()
    final = pd.DataFrame([result[c] for c in codes if c in result])
    got = final["来期見通し(短信抜粋)"].fillna("").astype(str).str.strip().ne("").sum()
    print(f"\n完了: {len(final)}社中 {got}社で見通しを取得 → {args.out}")


if __name__ == "__main__":
    main()
