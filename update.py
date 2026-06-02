#!/usr/bin/env python3
"""データ更新オーケストレータ。

GitHub Actions(またはローカル)から実行し、各パイプラインを順に回して results.csv 等を最新化する。
各ステップは独立で、失敗しても次へ進む(部分更新でも前進)。

スコープ:
  既定(standard): 株価→テクニカル→相関、ファンダ(前日終値/配当/予想)、短信見通し、業種PER中央値
  --full        : さらに 全社スクリーニング(ネットキャッシュ比率) と PER/PBR を再取得(重い)

例:
  python3 update.py            # 標準更新
  python3 update.py --full     # フル更新(重い)
  python3 update.py --skip-prices   # 株価系をスキップ
"""
import argparse
import subprocess
import sys


def run(label, cmd):
    print(f"\n===== {label} =====\n>> {' '.join(cmd)}", flush=True)
    r = subprocess.run([sys.executable] + cmd)
    print(f"<< {label} exit={r.returncode}", flush=True)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="再スクリーニング＋PER再取得も行う(重い)")
    ap.add_argument("--skip-prices", action="store_true", help="株価/テクニカル/相関をスキップ")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()
    s = str(args.sleep)

    if args.full:
        run("全社スクリーニング(ネットキャッシュ比率)",
            ["build_results.py", "--market", "プライム", "--market", "スタンダード",
             "--market", "グロース", "--resume", "--sleep", "0.2", "--out", "results_all.csv"])
        # build_results は results_all へ。以降の指標は results.csv 上で回すため寄せる
        run("results へ反映", ["-c", "import shutil; shutil.copy('results_all.csv','results.csv')"])
        run("PER/PBR再取得", ["enrich_per.py", "--results", "results.csv",
                            "--cache", "per_raw.csv", "--retry-empty", "--sleep", s])

    # ファンダ(前日終値・配当・予想PER・目標株価)を最新化(resume=既存は保持、不足を補完)
    run("ファンダ更新", ["enrich_fundamentals.py", "--results", "results.csv",
                    "--cache", "fund_raw.csv", "--resume", "--sleep", s])

    # 決算短信の来期見通し(比率1.0以上)を最新化
    run("短信PDF解決＋見通し抽出", ["fetch_outlook.py", "--in", "results.csv",
                          "--out", "outlook_raw.csv", "--min-ratio", "1.0",
                          "--retry-empty", "--sleep", "1.0"])
    run("見通し全文抽出", ["extract_full_outlook.py"])
    run("見通し要約", ["summarize_outlook.py"])
    run("要約をマージ", ["-c", (
        "import pandas as pd;"
        "s=pd.read_csv('outlook_summary.csv',dtype={'コード':str});"
        "m={str(r['コード']).zfill(4):str(r['来期見通し要約']) for _,r in s.iterrows()"
        " if str(r['来期見通し要約']).strip() and str(r['来期見通し要約'])!='nan'};"
        "d=pd.read_csv('results.csv');"
        "c4=d['コード'].astype(str).str.replace('.T','',regex=False).str.zfill(4);"
        "ratio=pd.to_numeric(d['ネットキャッシュ比率'],errors='coerce');"
        "d['来期見通し(短信抜粋)']=[m.get(c,'') if r>=1.0 else '' for c,r in zip(c4,ratio)];"
        "d.to_csv('results.csv',index=False,encoding='utf-8-sig')")])

    if not args.skip_prices:
        # 株価を最新まで再取得(resumeは既存を更新しないため使わない=全件取り直し)
        run("株価ダウンロード", ["download_prices.py", "--period", "1y", "--batch", "150",
                          "--sleep", s])
        run("テクニカル算出", ["compute_technical.py", "--results", "results.csv",
                         "--out", "technical.csv", "--batch", "120", "--sleep", "0.6"])
        run("相関再計算", ["compute_correlations.py", "--topn", "20", "--cross-th", "0.6"])

    # 60業種の付与＋業種PER中央値/乖離率を再計算
    run("業種(67)・PER中央値の再計算", ["classify_industry60.py", "apply", "--results", "results.csv"])

    # results_all を同期
    run("results_all 同期", ["-c", "import shutil; shutil.copy('results.csv','results_all.csv')"])
    print("\n===== 更新完了 =====", flush=True)


if __name__ == "__main__":
    main()
