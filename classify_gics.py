#!/usr/bin/env python3
"""60業種を GICS業種(yfinance) + キーワード + 既定 の優先順で割り当てる。

精度の高い順:
  1) 33業種が1対1 -> 確定
  2) GICS業種(industry_raw.csv)が候補内のサブ業種に対応 -> 採用
  3) 社名キーワード(classify_rules) -> 採用
  4) 各業種の既定バケツ

出力: industry60_decisions.csv (コード, 新業種)  ※確定分・上書きは apply 側で処理
"""
import pandas as pd

import industry60 as I60
from classify_rules import classify as kw_classify, RULES

# GICS industry(部分一致) -> 60業種名。候補に含まれる場合のみ採用される。
# (longest/具体的なキーを先に評価)
GICS_MAP = [
    # 不動産
    ("Real Estate Services", "不動産管理・仲介・賃貸"),
    ("Real Estate - Development", "不動産開発・デベロッパー"),
    ("Real Estate - Diversified", "不動産開発・デベロッパー"),
    ("REIT", "不動産管理・仲介・賃貸"),
    # 小売
    ("Grocery Stores", "食品スーパー・コンビニ"),
    ("Discount Stores", "百貨店・総合スーパー"),
    ("Department Stores", "百貨店・総合スーパー"),
    ("Pharmaceutical Retailers", "ドラッグストア・HC"),
    ("Home Improvement Retail", "ドラッグストア・HC"),
    ("Apparel Retail", "衣料・家電・専門店"),
    ("Specialty Retail", "衣料・家電・専門店"),
    ("Luxury Goods", "衣料・家電・専門店"),
    ("Internet Retail", "EC・通販・無店舗販売"),
    ("Restaurants", "飲食チェーン・中食"),
    # 卸売
    ("Food Distribution", "食品・農産物卸"),
    ("Electronics & Computer Distribution", "機械・電子部品卸"),
    ("Industrial Distribution", "機械・電子部品卸"),
    ("Trading Companies", "総合商社・貿易"),
    # 運輸
    ("Railroads", "鉄道・バス・旅客運輸"),
    ("Airlines", "鉄道・バス・旅客運輸"),
    ("Trucking", "貨物・物流・倉庫"),
    ("Integrated Freight", "貨物・物流・倉庫"),
    ("Marine Shipping", "貨物・物流・倉庫"),
    # 情報通信
    ("Electronic Gaming", "ゲーム・デジタルコンテンツ"),
    ("Internet Content", "Webプラットフォーム・EC"),
    ("Software - Application", "ソフトウェア・SaaS"),
    ("Software - Infrastructure", "ソフトウェア・SaaS"),
    ("Telecom Services", "通信キャリア・放送"),
    ("Broadcasting", "通信キャリア・放送"),
    ("Publishing", "ゲーム・デジタルコンテンツ"),
    # 電気機器
    ("Semiconductor", "半導体・半導体製造装置"),
    ("Electronic Components", "電子部品・デバイス"),
    ("Consumer Electronics", "民生電機・情報端末"),
    ("Electrical Equipment", "重電・産業用電機"),
    # 化学
    ("Specialty Chemicals", "機能性化学・先端材料"),
    ("Chemicals", "基礎化学・石油化学"),
    ("Agricultural Inputs", "基礎化学・石油化学"),
    ("Household & Personal Products", "日用化学品・化粧品"),
    # 食料品
    ("Packaged Foods", "食品製造・飲料・酒類"),
    ("Confectioners", "調味料・菓子・冷凍食品"),
    ("Beverages", "食品製造・飲料・酒類"),
    ("Farm Products", "食品製造・飲料・酒類"),
    # 機械
    ("Farm & Heavy Construction Machinery", "建設機械・農業機械"),
    # 建設
    ("Engineering & Construction", "ゼネコン・総合建設"),
    ("Building Products", "設備工事・専門工事"),
    # サービス
    ("Staffing & Employment", "人材サービス・派遣"),
    ("Advertising Agencies", "広告・PR・マーケティング"),
    ("Consulting Services", "コンサルティング・BPO"),
    ("Specialty Business Services", "コンサルティング・BPO"),
    ("Education & Training", "教育・研修・資格"),
    ("Medical Care Facilities", "医療・介護・福祉サービス"),
    ("Health Information Services", "医療・介護・福祉サービス"),
    ("Travel Services", "ホテル・旅行・レジャー"),
    ("Resorts & Casinos", "ホテル・旅行・レジャー"),
    ("Lodging", "ホテル・旅行・レジャー"),
    ("Leisure", "ホテル・旅行・レジャー"),
    ("Gambling", "ホテル・旅行・レジャー"),
    ("Waste Management", "環境・リサイクル・ビル管理"),
    ("Pollution & Treatment Controls", "環境・リサイクル・ビル管理"),
    # 追加7業種
    ("Auto & Truck Dealership", "自動車・バイク販売／整備"),
    ("Auto Dealership", "自動車・バイク販売／整備"),
    ("Auto - Dealerships", "自動車・バイク販売／整備"),
    ("Medical Devices", "医療機器・ヘルスケア機器"),
    ("Medical Instruments", "医療機器・ヘルスケア機器"),
    ("Medical Distribution", "医療機器・ヘルスケア機器"),
    ("Diagnostics & Research", "医療機器・ヘルスケア機器"),
    ("Apparel Manufacturing", "繊維・アパレル・服飾"),
    ("Textile Manufacturing", "繊維・アパレル・服飾"),
    ("Footwear & Accessories", "繊維・アパレル・服飾"),
    ("Rental & Leasing", "レンタル・リース"),
    # その他製品
    ("Furnishings", "住宅設備・家具・生活用品"),
    ("Packaging & Containers", "住宅設備・家具・生活用品"),
    ("Recreational Vehicles", "玩具・スポーツ・文具・雑貨"),
]


# 33業種ごとの文脈補正(同じGICS語でも業種により別バケツ)。GICS_MAPより優先。
CONTEXT = {
    "小売業": [
        ("Packaged Foods", "食品スーパー・コンビニ"),
        ("Food Distribution", "食品スーパー・コンビニ"),
        ("Beverages", "食品スーパー・コンビニ"),
        ("Restaurant", "飲食チェーン・中食"),
        ("Confectioners", "食品スーパー・コンビニ"),
    ],
    "卸売業": [
        ("Drug Manufacturers", "医薬品卸・その他専門卸"),
        ("Medical Distribution", "医薬品卸・その他専門卸"),
        ("Building Products", "建材・資材・エネルギー卸"),
        ("Steel", "建材・資材・エネルギー卸"),
        ("Oil & Gas", "建材・資材・エネルギー卸"),
    ],
}


def gics_pick(gics_industry, candidates, sec33=None):
    g = str(gics_industry or "")
    if not g or g == "nan":
        return None
    for key, bucket in CONTEXT.get(sec33, []):
        if key in g and bucket in candidates:
            return bucket
    for key, bucket in GICS_MAP:
        if key in g and bucket in candidates:
            return bucket
    return None


def main():
    res = pd.read_csv("results.csv")
    res["_c4"] = res["コード"].astype(str).str.replace(".T", "", regex=False).str.zfill(4)
    gics = pd.read_csv("industry_raw.csv", dtype={"コード": str})
    gmap = {str(r["コード"]).zfill(4): r.get("industry") for _, r in gics.iterrows()}

    rows, src_count = [], {"gics": 0, "keyword": 0, "default": 0, "det": 0}
    for _, r in res.iterrows():
        sec = r.get("業種", "")
        cands = I60.candidates(sec)
        if not cands:
            continue
        if len(cands) == 1:
            sub, src = cands[0], "det"
        else:
            g = gmap.get(r["_c4"])
            sub = gics_pick(g, cands, sec)
            if sub:
                src = "gics"
            else:
                sub = kw_classify(r.get("銘柄名"), sec, r.get("規模"), cands)
                # 既定かどうか判定
                default = RULES.get(sec, ([], None))[1]
                isdef = (sub == default) or (sec == "情報・通信業" and "SI・受託開発" in str(sub))
                src = "default" if isdef else "keyword"
        src_count[src] += 1
        rows.append({"コード": r["_c4"], "新業種": sub})

    pd.DataFrame(rows).to_csv("industry60_decisions.csv", index=False, encoding="utf-8-sig")
    total = sum(src_count.values())
    print(f"分類完了: {total}社 → industry60_decisions.csv")
    print("内訳:", src_count)
    print(f"  GICS/キーワードで具体分類: {src_count['gics']+src_count['keyword']}社"
          f" / 既定送り: {src_count['default']}社")


if __name__ == "__main__":
    main()
