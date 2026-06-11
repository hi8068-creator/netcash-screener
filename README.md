# ネットキャッシュ比率スクリーニング

清原達郎氏の「割安小型成長株投資」で使われる**ネットキャッシュ比率**で日本株を抽出するツールです。

```
ネットキャッシュ比率 = (流動資産 + 投資有価証券 × 0.7 − 負債 − 非支配株主持分) ÷ 時価総額
```

比率が **1.0 以上**なら「会社がただで買えるほど割安」という判断基準。データは Yahoo Finance（無料）から取得します。

非支配株主持分（連結ファンド等の"他人の取り分"）を控除するほか、「注意」列で
**監理・整理銘柄**（JPX公式・上場廃止の決定/審査中）と**暗号資産保有企業**に⚠を付け、
既定で除外します（サイドバーで表示に切替可）。割安に見えるだけの"罠"対策です。

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `app.py` | Web アプリ本体（Streamlit）。ブラウザで動く |
| `core.py` | スクリーニングの共通ロジック |
| `build_results.py` | 同梱用 `results.csv`（初期表示データ）を生成 |
| `screen.py` | コマンドライン版スクリーニング |
| `fetch_universe.py` | JPX 上場銘柄一覧から銘柄リストを生成 |
| `fetch_alerts.py` | JPX 公式の監理・整理銘柄一覧を取得（`jpx_alerts.csv`） |
| `compute_flags.py` | 「注意」列（監理・整理/暗号資産保有の⚠）を付与 |
| `flags_overrides.csv` | 注意フラグの手動指定（キーワード検出の補完） |
| `recompute_netcash.py` | 比率上位の銘柄を新計算式で再計算（週次更新で使用） |
| `requirements.txt` | 依存ライブラリ |
| `runtime.txt` | クラウドの Python バージョン指定（`3.11`） |
| `.streamlit/config.toml` | アプリのテーマ等の設定 |
| `results.csv` | 事前計算済みの結果（アプリ起動時に即表示） |

---

## ローカルで動かす

```bash
pip install -r requirements.txt
streamlit run app.py
```

ブラウザが開きます。サイドバーで市場・比率を選び、Excel/CSV でダウンロードできます。
「再計算」ボタンで最新データを取り直せます（数百銘柄だと数分かかります）。

---

## 無料クラウド公開（Streamlit Community Cloud）

相手は **URL を開くだけ**で使えます（Windows / Mac / スマホ可・インストール不要）。

1. **GitHub アカウント**を作る（無料）: https://github.com/signup
2. 新しいリポジトリを作り、このフォルダ一式（`app.py` `core.py` `requirements.txt` `results.csv` など）をアップロードする
   - 画面からドラッグ&ドロップでアップロード可。または下記の git コマンド：
     ```bash
     git init
     git add app.py core.py build_results.py screen.py fetch_universe.py requirements.txt results.csv README.md .gitignore
     git commit -m "ネットキャッシュ比率スクリーニング"
     git branch -M main
     git remote add origin https://github.com/<あなたのID>/<リポジトリ名>.git
     git push -u origin main
     ```
3. **Streamlit Community Cloud** にサインイン（GitHub 連携・無料）: https://share.streamlit.io
4. 「New app」→ リポジトリと `app.py` を選んで **Deploy**
5. 発行された URL（例: `https://<名前>.streamlit.app`）を共有する

### 更新のしかた
データを新しくしたいときは、手元で `python3 build_results.py --market グロース --max 300` を実行して
`results.csv` を作り直し、GitHub に push すれば公開アプリも自動で更新されます。

---

## 注意点

- **投資有価証券**は Yahoo の `Available For Sale Securities` 等を充当。企業ごとに分類のブレがあり、記事の数値と完全一致しないことがあります。
- 時価総額は軽量な `fast_info`（価格×発行株数）を優先取得し、欠ける場合のみ `info` にフォールバックします。これによりレート制限を受けにくくしています。銘柄名は JPX 上場一覧の日本語名で補完します。
- Yahoo Finance はレート制限があり、共有サーバー（クラウド）上では「再計算」が途中で止まることがあります。中断しても取得済み分は表示され、閲覧者には**事前計算済みデータ**が即表示されるので通常は問題ありません。
- `runtime.txt` でクラウドの Python を 3.11 に固定しています（yfinance/pandas/streamlit の安定組み合わせ）。
- 直近本決算ベースの数値です。投資判断は自己責任で。
