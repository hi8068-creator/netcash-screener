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

    LABEL = {"det": "確定", "summary": "説明文", "gics": "GICS",
             "keyword": "社名", "default": "既定(要確認)"}
    amap, smap = {}, {}  # コード -> 新業種, 業種根拠

    def _load(path, src_label, col_src=False):
        if not os.path.exists(path):
            return 0
        df = pd.read_csv(path, dtype={"コード": str})
        n = 0
        for _, r in df.iterrows():
            v = str(r.get("新業種", "")).strip()
            if v and v != "nan":
                c = str(r["コード"]).zfill(4)
                amap[c] = v
                smap[c] = LABEL.get(str(r.get("source", "")), "") if col_src else src_label
                n += 1
        return n

    _load("industry60_assigned.csv", "確定")
    n_dec = _load("industry60_decisions.csv", None, col_src=True)
    print(f"AI判定 {n_dec}件を取り込み")
    n_man = _load("industry60_manual.csv", "精査")      # 説明文精査(532社)
    n_ov = _load("industry60_overrides.csv", "手動")    # 個別上書き(最優先)
    print(f"精査 {n_man}件 / 手動上書き {n_ov}件を適用")

    d["新業種"] = d["_code4"].map(amap)
    d["業種根拠"] = d["_code4"].map(smap)
    d = d.drop(columns=["_code4"])

    # 業種別PER中央値・PER乖離率を新業種(67分類)で再計算する。
    if "PER" in d.columns and "新業種" in d.columns:
        per = pd.to_numeric(d["PER"], errors="coerce")
        valid = d[per.notna() & (per > 0)]
        med = valid.groupby("新業種")["PER"].apply(
            lambda s: pd.to_numeric(s, errors="coerce").median())
        d["業種PER中央値"] = d["新業種"].map(med).round(1)
        d["PER乖離率"] = ((per / d["業種PER中央値"]) - 1).round(3)
        print("業種PER中央値/PER乖離率を新業種(67分類)で再計算")

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
