#!/usr/bin/env python3
"""新60業種マスタの読み込みと、33業種→候補60業種の解決。

60業種は33業種の細分なので、ある会社の60業種は「その会社の33業種に対応する
候補(2〜4個)」の中から選べばよい。これにより:
  - 候補が1つだけの33業種 → 機械的に確定(AI不要、100%正確)
  - 候補が複数の33業種     → AIが社名・事業内容から候補内で選択
"""
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "industry60.json")

with open(_PATH, encoding="utf-8") as f:
    _DATA = json.load(f)

INDUSTRIES = _DATA["industries"]
NAMES60 = [x["name"] for x in INDUSTRIES]

# 33業種キー -> 候補60業種名リスト
_MAP = {}
for it in INDUSTRIES:
    for src in it["from33"]:
        _MAP.setdefault(src, [])
        if it["name"] not in _MAP[src]:
            _MAP[src].append(it["name"])


def candidates(sec33: str):
    """JPXの33業種区分文字列から候補60業種を返す。

    JPXの表記ゆれ(例: 「証券、商品先物取引業」)に対応するため部分一致で解決。
    """
    s = str(sec33 or "").strip()
    if not s or s == "-" or s == "nan":
        return []
    if s in _MAP:
        return _MAP[s]
    for key, vals in _MAP.items():
        if key in s or s in key:
            return vals
    return []


def is_deterministic(sec33: str) -> bool:
    """候補が1つ(=AI判定不要で確定)か。"""
    return len(candidates(sec33)) == 1


def assign_deterministic(sec33: str):
    """候補が1つなら確定値、複数/該当なしなら None。"""
    c = candidates(sec33)
    return c[0] if len(c) == 1 else None


if __name__ == "__main__":
    # 自己診断: 全60業種が網羅され、分割/確定の内訳を表示
    det = [k for k in _MAP if len(_MAP[k]) == 1]
    split = {k: v for k, v in _MAP.items() if len(v) > 1}
    print(f"60業種数: {len(NAMES60)} / 33業種キー数: {len(_MAP)}")
    print(f"確定(1対1)業種: {len(det)}")
    print("分割業種(AI判定対象):")
    for k, v in split.items():
        print(f"  {k} -> {len(v)}候補: {v}")
