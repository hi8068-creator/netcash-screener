#!/usr/bin/env python3
"""60業種分類 v2: 事業説明文(英語)を最優先信号に使う高精度版。

優先順位(精度の高い順):
  1) 33業種が1対1            -> 確定 (det)
  2) 事業説明文のキーワード    -> summary
  3) GICS業種                -> gics
  4) 社名キーワード           -> keyword
  5) 各業種の既定バケツ        -> default

出力: industry60_decisions.csv (コード, 新業種, source)
      source列で信頼度(det/summary/gics > keyword > default)を可視化できる。
"""
import re

import pandas as pd

import industry60 as I60
from classify_rules import classify as kw_classify, RULES
from classify_gics import GICS_MAP, CONTEXT

# ---- 事業説明文(英語, 小文字化して照合) -> 60業種 ----
# (keywords, bucket)。具体的なものを先に。候補に含まれる場合のみ採用。
SUMMARY_RULES = [
    # ---- 追加7業種(優先) ----
    (["car dealer", "automobile dealer", "automobile dealership", "car dealership",
      "used cars", "used and new car", "new and used car", "sale of new and used",
      "automobile sales", "vehicle dealer", "motorcycle", "auto repair",
      "automobile maintenance", "car and motorcycle", "service station"],
     "自動車・バイク販売／整備"),
    (["printing", "printing business", "printing services", "commercial printing",
      "gravure printing", "offset"], "印刷・紙加工"),
    (["funeral", "cemetery", "wedding", "bridal", "ceremony hall", "guesthouse"],
     "冠婚葬祭・セレモニー"),
    (["hair salon", "beauty salon", "hairdressing", "barber", "hair and beauty",
      "hair and make"], "美容・理容・パーソナルケア"),
    (["rental and sale", "rents and sells", "rental of", "leasing of", "rental business",
      "rents and leases", "equipment rental"], "レンタル・リース"),
    (["medical device", "medical instrument", "medical equipment", "diagnostic instrument",
      "diagnostic", "surgical", "dental", "cardiac", "orthodontic", "regenerative medicine"],
     "医療機器・ヘルスケア機器"),
    (["apparel", "clothing", "footwear", "jewelry", "garment", "textile product",
      "kimono", "socks", "underwear", "shoes", "fashion product", "accent fashion",
      "bags and wallets", "gemstone"], "繊維・アパレル・服飾"),
    # 化学
    (["paint", "coating", "cosmetic", "toiletr", "detergent", "adhesive",
      "printing ink", "fragrance", "soap", " dye"], "日用化学品・化粧品"),
    (["petrochemical", "soda ash", "caustic", "sulfuric", "ammonia",
      "fertilizer", "industrial gas", "inorganic chemical"], "基礎化学・石油化学"),
    # 機械
    (["construction machinery", "agricultural machinery", "excavat", "tractor",
      "forklift", "mining equipment", "hydraulic"], "建設機械・農業機械"),
    (["robot", "automation", "factory automation", "conveyor", "servo",
      "motion control", "automated"], "自動化・ロボティクス"),
    (["machine tool", "pump", "compressor", "bearing", "industrial machinery",
      "valves", "machining"], "産業機械・工作機械"),
    # 電気機器
    (["semiconductor", "wafer", "lithography", " memory ", "solid-state drive",
      "integrated circuit"], "半導体・半導体製造装置"),
    (["electronic component", "capacitor", "connector", " sensor",
      "printed circuit", "circuit board", "electronic device"], "電子部品・デバイス"),
    (["transformer", "heavy electric", "power equipment", "switchgear",
      "electric motor", "generator", "electric wire", "power cable"], "重電・産業用電機"),
    (["home appliance", "consumer electronic", "audio", "television set"],
     "民生電機・情報端末"),
    # 建設
    (["electrical construction", "air conditioning", "hvac", "plumbing",
      "piping", "facility installation", "equipment installation",
      "telecommunications construction", "insulation"], "設備工事・専門工事"),
    (["general contractor", "civil engineering", "building construction",
      "construction of", "general construction"], "ゼネコン・総合建設"),
    # 不動産
    (["property management", "real estate broker", "leasing", "rental",
      "apartment management", "rent ", "subleas", "real estate agency"],
     "不動産管理・仲介・賃貸"),
    (["real estate develop", "develops", "development of", "condominium",
      "urban development"], "不動産開発・デベロッパー"),
    # 食料品
    (["confection", "candy", "seasoning", "soy sauce", "miso", "frozen food",
      "snack", "chocolate", "spice", "noodle"], "調味料・菓子・冷凍食品"),
    (["beverage", "dairy", "meat", "bakery", "brewery", "sake", "food product",
      "processed food", "seafood"], "食品製造・飲料・酒類"),
    # その他製品
    (["toy", "sporting goods", "stationery", "musical instrument", "bicycle",
      "fishing", "amusement machine"], "玩具・スポーツ・文具・雑貨"),
    (["furniture", "household goods", "building material", "sanitary",
      "housing equipment", "interior"], "住宅設備・家具・生活用品"),
    # 陸運
    (["railway", "railroad", " bus ", "passenger transport", "taxi"],
     "鉄道・バス・旅客運輸"),
    (["logistics", "freight", "trucking", "warehouse", "distribution",
      "delivery", "transport of"], "貨物・物流・倉庫"),
    # 情報通信
    (["telecommunication", "broadcast", "television", "cable tv", "newspaper",
      "telephone carrier", "radio station"], "通信キャリア・放送"),
    (["game", "gaming", "anime", "comic", "entertainment content",
      "music content", "esports"], "ゲーム・デジタルコンテンツ"),
    (["e-commerce", "online marketplace", "online shopping", "internet portal",
      "e commerce", "online platform", "web media", "comparison site"],
     "Webプラットフォーム・EC"),
    (["cybersecurity", "security software", "data center", "cloud infrastructure",
      "information security"], "サイバーセキュリティ・クラウド"),
    (["artificial intelligence", "machine learning", "data analytics",
      "internet of things", " iot", "ai solution", "big data"], "AI・データ・IoT"),
    (["digital transformation", "it consulting"], "DX支援・ITコンサルティング"),
    (["saas", "software as a service", "cloud-based", "software solution",
      "application software"], "ソフトウェア・SaaS"),
    (["system integration", "system development", "information technology services",
      "it services", "software development"], "SI・受託開発(中堅)"),
    # 卸売
    (["trading company", "general trading", "import and export"], "総合商社・貿易"),
    (["food wholesale", "food distribution", "agricultural product", "wholesale of food"],
     "食品・農産物卸"),
    (["electronics distribution", "semiconductor distribution", "machinery wholesale",
      "distributes electronic"], "機械・電子部品卸"),
    (["pharmaceutical wholesale", "drug distribution", "chemical distribution",
      "distributes pharmaceutical"], "医薬品卸・その他専門卸"),
    (["building materials", "steel wholesale", "fuel", "energy distribution",
      "lumber"], "建材・資材・エネルギー卸"),
    # 小売
    (["supermarket", "grocery store", "convenience store"], "食品スーパー・コンビニ"),
    (["department store", "general merchandise store"], "百貨店・総合スーパー"),
    (["drugstore", "drug store", "pharmacy", "home center", "home improvement"],
     "ドラッグストア・HC"),
    (["restaurant", "dining", "food service", "izakaya", "cafe"], "飲食チェーン・中食"),
    (["mail order", "online retail", "catalog", "e-commerce"], "EC・通販・無店舗販売"),
    (["apparel", "clothing", "electronics retail", "specialty store", "eyewear",
      "footwear", "retail of"], "衣料・家電・専門店"),
    # サービス
    (["staffing", "recruitment", "temporary staff", "human resources",
      "employment", "dispatch", "placement of"], "人材サービス・派遣"),
    (["advertising", "marketing services", "public relations", "promotion agency"],
     "広告・PR・マーケティング"),
    (["consulting", "business process outsourcing", "bpo", "advisory services"],
     "コンサルティング・BPO"),
    (["education", "training services", "tutoring", "e-learning", "cram school",
      "academy", "preparatory school"], "教育・研修・資格"),
    (["nursing care", "medical care", "healthcare service", "welfare",
      "elderly care", "home care", "long-term care"], "医療・介護・福祉サービス"),
    (["hotel", "travel agency", "resort", "leisure", "tourism", "amusement",
      "theme park", "golf course", "fitness", "karaoke", "lodging"],
     "ホテル・旅行・レジャー"),
    (["waste", "recycling", "environmental", "cleaning services",
      "building management", "facility management", "security services",
      "maintenance services"], "環境・リサイクル・ビル管理"),
]


def summary_pick(summary, candidates):
    s = str(summary or "").lower()
    if not s or s == "nan":
        return None
    for keys, bucket in SUMMARY_RULES:
        if bucket in candidates and any(k in s for k in keys):
            return bucket
    return None


def gics_pick(gics, candidates, sec33):
    g = str(gics or "")
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
    gmap = {}
    try:
        g = pd.read_csv("industry_raw.csv", dtype={"コード": str})
        gmap = {str(r["コード"]).zfill(4): r.get("industry") for _, r in g.iterrows()}
    except Exception:
        pass
    smap = {}
    try:
        sm = pd.read_csv("summary_raw.csv", dtype={"コード": str})
        smap = {str(r["コード"]).zfill(4): r.get("summary") for _, r in sm.iterrows()}
    except Exception:
        pass

    rows, cnt = [], {"det": 0, "summary": 0, "gics": 0, "keyword": 0, "default": 0}
    for _, r in res.iterrows():
        sec = r.get("業種", "")
        cands = I60.candidates(sec)
        if not cands:
            continue
        if len(cands) == 1:
            sub, src = cands[0], "det"
        else:
            sub = summary_pick(smap.get(r["_c4"]), cands)
            src = "summary"
            if not sub:
                sub = gics_pick(gmap.get(r["_c4"]), cands, sec)
                src = "gics"
            if not sub:
                sub = kw_classify(r.get("銘柄名"), sec, r.get("規模"), cands)
                default = RULES.get(sec, ([], None))[1]
                isdef = (sub == default) or (sec == "情報・通信業" and "SI・受託開発" in str(sub))
                src = "default" if isdef else "keyword"
        cnt[src] += 1
        rows.append({"コード": r["_c4"], "新業種": sub, "source": src})

    pd.DataFrame(rows).to_csv("industry60_decisions.csv", index=False, encoding="utf-8-sig")
    print(f"分類完了: {sum(cnt.values())}社")
    print("内訳:", cnt)
    spec = cnt["summary"] + cnt["gics"] + cnt["keyword"]
    print(f"  具体分類(summary/gics/keyword): {spec}社 / 既定送り: {cnt['default']}社")


if __name__ == "__main__":
    main()
