#!/usr/bin/env python3
"""日次株価から連動(相関)を計算して事前計算データを作る。

- returns.parquet : 日次リターン(アプリのオンデマンド計算用に同梱)
- peers_adj.csv   : 各銘柄の連動上位(市場調整後・上位N)
- peers_raw.csv   : 各銘柄の連動上位(素の相関・上位N)
- cross_industry.csv : 別業種なのに高相関の意外なペア(市場調整後)

市場調整: 各日の全銘柄平均リターンを差し引いた残差で相関を取る
          (地合いの共通変動を除いた『本当の連動』)。
"""
import argparse

import numpy as np
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", default="prices.parquet")
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--min-days", type=int, default=120, help="必要な有効営業日数")
    ap.add_argument("--topn", type=int, default=20)
    ap.add_argument("--cross-th", type=float, default=0.6, help="別業種高相関の閾値")
    args = ap.parse_args()

    px = pd.read_parquet(args.prices).sort_index()
    ret = px.pct_change().iloc[1:]
    # 有効日数が少ない銘柄を除外
    valid = ret.columns[ret.notna().sum() >= args.min_days]
    ret = ret[valid]
    # 欠損は0(その日動かなかった扱い)で埋める
    ret = ret.fillna(0.0)
    print(f"対象 {ret.shape[1]} 銘柄 × {ret.shape[0]} 営業日")

    ret.to_parquet("returns.parquet")

    # 市場調整: 各日の銘柄横断平均を引く
    adj = ret.sub(ret.mean(axis=1), axis=0)

    codes = list(ret.columns)
    # 業種マップ
    meta = pd.read_csv(args.results, dtype={"コード": str})
    sec = dict(zip(meta["コード"].astype(str), meta.get("業種", pd.Series())))
    name = dict(zip(meta["コード"].astype(str), meta.get("銘柄名", pd.Series())))

    def corr_matrix(df):
        a = df.values
        a = a - a.mean(0)
        std = a.std(0)
        std[std == 0] = 1e-9
        a = a / std
        return (a.T @ a) / a.shape[0]

    print("相関行列(市場調整後)を計算中...")
    C_adj = corr_matrix(adj).astype(np.float32)
    print("相関行列(素)を計算中...")
    C_raw = corr_matrix(ret).astype(np.float32)

    def top_peers(C, label):
        rows = []
        n = len(codes)
        for i in range(n):
            v = C[i].copy()
            v[i] = -2
            idx = np.argpartition(-v, args.topn)[:args.topn]
            idx = idx[np.argsort(-v[idx])]
            for j in idx:
                rows.append({
                    "コード": codes[i],
                    "連動銘柄": codes[j],
                    "連動銘柄名": name.get(codes[j], ""),
                    "相関": round(float(v[j]), 3),
                })
        df = pd.DataFrame(rows)
        df.to_csv(f"peers_{label}.csv", index=False, encoding="utf-8-sig")
        print(f"  peers_{label}.csv: {len(df)}行")

    top_peers(C_adj, "adj")
    top_peers(C_raw, "raw")

    # 別業種の意外な高相関ペア(市場調整後)
    print("別業種の意外な連動を抽出中...")
    n = len(codes)
    pairs = []
    iu = np.triu_indices(n, k=1)
    cv = C_adj[iu]
    mask = cv >= args.cross_th
    for k in np.where(mask)[0]:
        i, j = iu[0][k], iu[1][k]
        si, sj = sec.get(codes[i], ""), sec.get(codes[j], "")
        if si and sj and si != sj:
            pairs.append({
                "コードA": codes[i], "銘柄A": name.get(codes[i], ""), "業種A": si,
                "コードB": codes[j], "銘柄B": name.get(codes[j], ""), "業種B": sj,
                "相関": round(float(C_adj[i, j]), 3),
            })
    cross = pd.DataFrame(pairs).sort_values("相関", ascending=False).head(300)
    cross.to_csv("cross_industry.csv", index=False, encoding="utf-8-sig")
    print(f"  cross_industry.csv: {len(cross)}行")
    print("完了")


if __name__ == "__main__":
    main()
