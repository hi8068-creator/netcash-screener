#!/usr/bin/env python3
"""60業種の割当。

- build: 33業種が1対1の銘柄を機械確定し、分割業種(AI判定対象)を todo に書き出す
- apply: AI判定結果(industry60_decisions.csv: コード,新業種)を取り込み、
         results に「新業種」列を付与する(機械確定＋AI)

使い方:
  python3 classify_industry60.py build --results results_all.csv
    -> industry60_assigned.csv(機械確定分) と industry60_todo.csv(AI対象) を生成
  # industry60_todo.csv を見てAIが industry60_decisions.csv(コード,新業種) を作成
  python3 classify_industry60.py apply --results results_all.csv
"""
import argparse
import os

import pandas as pd

import industry60 as I60


def build(args):
    d = pd.read_csv(args.results, dtype={"コード": str})
    d["_code4"] = d["コード"].astype(str).str.replace(".T", "", regex=False)

    assigned, todo = [], []
    for _, r in d.iterrows():
        sec = r.get("業種", "")
        cands = I60.candidates(sec)
        det = cands[0] if len(cands) == 1 else ""
        rec = {
            "コード": r["_code4"],
            "銘柄名": r.get("銘柄名", ""),
            "業種33": sec,
            "規模": r.get("規模", ""),
            "新業種": det,
            "method": "rule" if det else "",
        }
        assigned.append(rec)
        if not det and cands:
            todo.append({
                "コード": r["_code4"],
                "銘柄名": r.get("銘柄名", ""),
                "業種33": sec,
                "規模": r.get("規模", ""),
                "候補": " / ".join(cands),
            })

    pd.DataFrame(assigned).to_csv("industry60_assigned.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(todo).to_csv("industry60_todo.csv", index=False, encoding="utf-8-sig")
    n_rule = sum(1 for a in assigned if a["method"] == "rule")
    print(f"機械確定(rule): {n_rule}社 / AI判定対象: {len(todo)}社 / 全{len(assigned)}社")
    # 分割業種ごとのAI対象社数
    if todo:
        print("AI対象の内訳(業種33別):")
        print(pd.DataFrame(todo)["業種33"].value_counts().to_string())


def apply(args):
    d = pd.read_csv(args.results, dtype={"コード": str})
    d["_code4"] = d["コード"].astype(str).str.replace(".T", "", regex=False)

    assigned = pd.read_csv("industry60_assigned.csv", dtype={"コード": str})
    amap = {str(r["コード"]).zfill(4): r["新業種"] for _, r in assigned.iterrows()
            if str(r.get("新業種", "")).strip() and str(r["新業種"]) != "nan"}

    # AI判定結果で上書き/補完
    if os.path.exists("industry60_decisions.csv"):
        dec = pd.read_csv("industry60_decisions.csv", dtype={"コード": str})
        for _, r in dec.iterrows():
            v = str(r.get("新業種", "")).strip()
            if v and v != "nan":
                amap[str(r["コード"]).zfill(4)] = v
        print(f"AI判定 {len(dec)}件を取り込み")

    # 手動上書き(最優先)。誤分類の個別修正用。
    if os.path.exists("industry60_overrides.csv"):
        ov = pd.read_csv("industry60_overrides.csv", dtype={"コード": str})
        n = 0
        for _, r in ov.iterrows():
            v = str(r.get("新業種", "")).strip()
            if v and v != "nan":
                amap[str(r["コード"]).zfill(4)] = v
                n += 1
        print(f"手動上書き {n}件を適用")

    d["新業種"] = d["_code4"].map(amap)
    d = d.drop(columns=["_code4"])
    d.to_csv(args.results, index=False, encoding="utf-8-sig")
    got = d["新業種"].notna().sum()
    print(f"新業種付与: {got}社 / 全{len(d)}社  業種数: {d['新業種'].nunique()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "apply"])
    ap.add_argument("--results", default="results_all.csv")
    args = ap.parse_args()
    (build if args.cmd == "build" else apply)(args)


if __name__ == "__main__":
    main()
