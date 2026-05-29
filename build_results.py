#!/usr/bin/env python3
"""同梱用 results.csv を生成する。アプリ起動時の初期表示データになる。

例:
  python3 build_results.py --market グロース --market スタンダード --resume

--resume を付けると、既存の --out を読み込み、未取得のコードだけを評価して追記する。
途中でレート制限や中断が起きても進捗を失わない。
"""
import argparse
import os

import pandas as pd

import core


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", action="append", default=None,
                    help="プライム/スタンダード/グロース(複数可)")
    ap.add_argument("--max", type=int, default=0,
                    help="最大銘柄数(0で全件)")
    ap.add_argument("--min-ratio", type=float, default=0.0,
                    help="保存する比率下限(0なら全件保存しアプリ側で絞る)")
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--resume", action="store_true",
                    help="既存outを読み、未取得コードのみ追記する")
    ap.add_argument("--save-every", type=int, default=20,
                    help="この件数ごとに途中保存する")
    ap.add_argument("--out", default="results.csv")
    args = ap.parse_args()

    markets = args.market or ["グロース"]
    uni = core.fetch_jpx_universe(markets=markets, exclude_etf=True)
    all_codes = uni["コード"].tolist()
    if args.max and args.max > 0:
        all_codes = all_codes[: args.max]

    # レジューム: 既存 out に含まれるコードはスキップ
    existing = pd.DataFrame(columns=core.COLUMNS_JP)
    done = set()
    if args.resume and os.path.exists(args.out):
        existing = pd.read_csv(args.out)
        done = set(existing["コード"].astype(str)) if "コード" in existing.columns else set()
        print(f"レジューム: 既存 {len(done)} 件をスキップします。")

    todo = [c for c in all_codes if f"{c}.T" not in done]
    print(f"対象 {len(todo)} 銘柄(全{len(all_codes)})を取得します...")

    collected = []

    def flush():
        if not collected and existing.empty:
            return
        new_df = core.results_to_df([r for r in collected])
        merged = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
        merged = merged.drop_duplicates(subset=["コード"], keep="last")
        merged = core.attach_universe_meta(merged, uni)
        merged = merged.sort_values("ネットキャッシュ比率", ascending=False).reset_index(drop=True)
        if args.min_ratio:
            merged = merged[merged["ネットキャッシュ比率"] >= args.min_ratio]
        merged.to_csv(args.out, index=False, encoding="utf-8-sig")

    def prog(i, total, r):
        if r is not None:
            collected.append(r)
            print(f"  [{i}/{total}] {r.code} 比率={r.ratio:.2f}")
        elif i % 25 == 0:
            print(f"  [{i}/{total}] ...")
        if args.save_every and i % args.save_every == 0:
            flush()

    core.run_screen(todo, min_ratio=0.0, sleep=args.sleep, progress=prog)
    flush()

    final = pd.read_csv(args.out) if os.path.exists(args.out) else pd.DataFrame()
    hits = int((final["ネットキャッシュ比率"] >= 1.0).sum()) if len(final) else 0
    print(f"\n保存完了: {len(final)}銘柄 → {args.out}  比率1.0以上: {hits}件")


if __name__ == "__main__":
    main()
