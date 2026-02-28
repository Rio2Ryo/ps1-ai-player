# End-to-End 動作確認ガイド

`run.sh` が実行するフロー全体（Xvfb → DuckStation → memory_logger → ai_agent → pipeline）を
ステップごとに手動で確認する手順と、よくあるエラーの対処法をまとめる。

---

## 目次

1. [前提条件](#前提条件)
2. [クイックスタート（実ゲームE2E）](#クイックスタート実ゲームe2e)
3. [ステップ1: Xvfb（仮想ディスプレイ）](#ステップ1-xvfb仮想ディスプレイ)
4. [ステップ2: DuckStation](#ステップ2-duckstation)
5. [ステップ3: メモリアドレス探索](#ステップ3-メモリアドレス探索)
6. [ステップ4: memory_logger](#ステップ4-memory_logger)
7. [ステップ5: ai_agent](#ステップ5-ai_agent)
8. [ステップ6: pipeline（自動分析）](#ステップ6-pipeline自動分析)
9. [全フローを一括で実行](#全フローを一括で実行)
10. [ジャンル別E2Eワークフロー](#ジャンル別e2eワークフロー)
11. [GPT-4o APIコスト見積](#gpt-4o-apiコスト見積)
12. [E2E検証チェックリスト](#e2e検証チェックリスト)
13. [トラブルシューティングチェックリスト](#トラブルシューティングチェックリスト)

---

## 前提条件

以下が完了していること:

```bash
# セットアップ
bash setup.sh

# DuckStation設定ファイル生成
python setup_duckstation.py

# BIOSファイル配置（README.md「PS1 BIOS Setup」参照）
ls -l ~/.config/duckstation/bios/
# scph5501.bin (524288 bytes) 等が存在すること

# ISOファイル配置
ls ~/ps1-ai-player/isos/
# game.iso 等が存在すること

# OpenAI APIキー
echo "$OPENAI_API_KEY"
# sk-... が出力されること
```

### 事前チェックの自動実行

```bash
source venv/bin/activate

# 全項目を一括チェック（修正ヒント付き）
python preflight_check.py --verbose --fix

# 期待出力:
# === PS1 AI Player Pre-flight Check ===
#
#   [OK]  ISO file: Found 1 ISO file(s) in isos
#   [OK]  BIOS file: Found 1 BIOS file(s)
#   [OK]  DuckStation: DuckStation found: duckstation/DuckStation.AppImage
#   [OK]  Python venv: venv Python found: venv/bin/python
#   [OK]  OpenAI API key: OPENAI_API_KEY is set in environment
#
# Result: 5/5 checks passed.
# All checks passed. Ready for E2E session!
```

いずれかが `[FAIL]` の場合、`--fix` で表示されるヒントに従って修正する。

---

## クイックスタート（実ゲームE2E）

初めて実ゲームでテストする場合の最短手順。RPGを例にする。

```bash
source venv/bin/activate

# --- Phase 1: 準備 ---

# 1. preflightで全項目パス確認
python preflight_check.py --fix

# 2. Xvfb + DuckStation起動
Xvfb :99 -screen 0 1280x1024x24 &
export DISPLAY=:99
./duckstation/DuckStation.AppImage -- isos/game.iso &
sleep 5

# --- Phase 2: メモリアドレス探索 ---

# 3. メモリスキャナーで主要パラメータのアドレスを発見
#    （詳細は「ステップ3: メモリアドレス探索」を参照）
sudo python memory_scanner.py

# 4. 発見したアドレスを登録
python address_manager.py --game SLPM-86023 --add hp 0x0C1A28 int16 "Player HP"
python address_manager.py --game SLPM-86023 --add mp 0x0C1A2A int16 "Player MP"
python address_manager.py --game SLPM-86023 --add gold 0x0C1B40 int32 "Gold"
# ... 他のパラメータも同様

# 5. 登録確認
python address_manager.py --game SLPM-86023 --list

# --- Phase 3: 短時間テスト実行 ---

# 6. DuckStationを一旦停止して run.sh で統合起動（5分テスト）
pkill -f DuckStation
pkill -f 'Xvfb :99'

./run.sh \
    --game SLPM-86023 \
    --iso isos/game.iso \
    --strategy balanced \
    --duration 300 \
    --detail low \
    --interval 5.0

# --- Phase 4: 結果確認 ---

# 7. 出力確認
ls -la logs/*SLPM-86023*.csv          # メモリログCSV
ls -la logs/*.session.json            # セッション情報（コスト等）
ls -la reports/GDD_SLPM-86023_*.md    # GDD
ls -la reports/causal_chains_*.json   # 因果チェーン
ls -la reports/*.png                  # 可視化チャート
```

---

## ステップ1: Xvfb（仮想ディスプレイ）

### 何をするか

ヘッドレス環境（SSH接続、CI等）でX11ディスプレイを提供する。
DuckStation、mss（スクリーンキャプチャ）、pynput（キーボード入力）が全てX11を必要とする。

### 確認コマンド

```bash
# Xvfbが利用可能か
which Xvfb
# /usr/bin/Xvfb

# 起動テスト（:99番ディスプレイ、1280x1024、24bitカラー）
Xvfb :99 -screen 0 1280x1024x24 &
XVFB_PID=$!

# 起動確認
sleep 1
kill -0 $XVFB_PID 2>/dev/null && echo "OK: Xvfb running (PID=$XVFB_PID)" || echo "FAIL"

# DISPLAYを設定
export DISPLAY=:99

# Xサーバが応答するか（x11-utils必要）
xdpyinfo >/dev/null 2>&1 && echo "OK: X server responding" || echo "FAIL"

# 後片付け
kill $XVFB_PID
```

### よくあるエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `Xvfb: command not found` | Xvfbが未インストール | `sudo apt-get install xvfb` |
| `Server is already active for display 99` | 既にXvfbが:99で起動中 | `kill $(pgrep -f 'Xvfb :99')` で停止するか別の番号を使用 |
| `Fatal server error: Cannot establish any listening sockets` | ポート競合またはX11ソケット残骸 | `rm -f /tmp/.X99-lock /tmp/.X11-unix/X99` |
| `xdpyinfo: unable to open display` | DISPLAY未設定 | `export DISPLAY=:99` |

### 物理ディスプレイがある場合

```bash
# --no-xvfbフラグでXvfbをスキップ
./run.sh --game SLPM-86023 --iso isos/game.iso --no-xvfb
# 既存の$DISPLAYがそのまま使われる
```

---

## ステップ2: DuckStation

### 何をするか

PS1エミュレータを起動しISOをロードする。以降のステップでメモリ読み取りとスクリーンキャプチャの対象になる。

### 確認コマンド

```bash
export DISPLAY=:99  # Xvfbが動いていること

# AppImageの存在確認
ls -l ~/ps1-ai-player/duckstation/DuckStation.AppImage
# 実行権限があること（-rwxr-xr-x）

# BIOS認識確認（ログに "Loading BIOS" が出る）
./duckstation/DuckStation.AppImage -- ~/ps1-ai-player/isos/game.iso &
DS_PID=$!

# 起動待ち
sleep 5

# プロセスが生きているか
kill -0 $DS_PID 2>/dev/null && echo "OK: DuckStation running (PID=$DS_PID)" || echo "FAIL"

# PID自動検出テスト（memory_scannerが使う方法）
pgrep -a -i duckstation
# PIDとコマンドラインが出力されること

# /proc/PID/maps が読めるか（ptrace不要、ただしsame-user必要）
cat /proc/$DS_PID/maps | head -5
# メモリマッピング行が表示されること

# 後片付け
kill $DS_PID
```

### 設定ファイルの確認

```bash
# settings.iniの主要項目を確認
cat ~/.config/duckstation/settings.ini | grep -E '(SearchDirectory|PatchFastBoot|Region|Type|Controller1)'
# [BIOS] SearchDirectory = /home/<user>/.config/duckstation/bios
# [BIOS] PatchFastBoot = true
# [Controller1] Type = DigitalController
```

### GPU設定のヘッドレス最適化

Xvfb環境ではOpenGLがソフトウェアレンダリングになるため、GPU設定の調整が必要な場合がある:

```bash
# settings.ini を手動修正する場合
# [GPU]
# Renderer = Software          ← Xvfbで最も安定
# ResolutionScale = 1          ← ソフトウェアレンダラーは1固定
# TrueColor = false

# または setup_duckstation.py を再実行
python setup_duckstation.py
# その後 settings.ini の [GPU] Renderer を Software に手動変更
```

### よくあるエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `AppImage: FUSE is not installed` | libfuse2が未インストール | `sudo apt-get install libfuse2` |
| `dlopen: libGLX.so.0: cannot open` | OpenGLライブラリ不足 | `sudo apt-get install libgl1-mesa-glx libegl1-mesa` |
| BIOS未認識（起動直後にエラーダイアログ） | BIOSが配置されていない or 壊れている | `ls -l ~/.config/duckstation/bios/` でサイズ確認（524288 bytes） |
| `No disc inserted` | ISOパスが間違い or フォーマット非対応 | `.iso`/`.bin+.cue`/`.chd` 形式であること。パスにスペースがないこと |
| 画面が真っ黒のまま | GPU設定不適合 | `settings.ini` の `[GPU] Renderer` を `Software` に変更 |
| `pgrep` でDuckStationが見つからない | 別名でプロセスが動いている | `ps aux \| grep -i duck` で確認 |

---

## ステップ3: メモリアドレス探索

### 何をするか

ゲーム内パラメータ（HP、所持金、スコア等）が格納されているメモリアドレスを特定する。
これがE2Eテストの**最も重要な準備ステップ**であり、ゲームごとに必ず実施する必要がある。

> 詳細なジャンル別アドレス設定については `DOCS/STRATEGY_GUIDE.md` を参照。

### 基本的なスキャン手順

```bash
# 前提: DuckStationでゲームが起動中であること
# メモリスキャナーは /proc/PID/mem を読むため sudo が必要（他ユーザー起動の場合）
# 同一ユーザーなら sudo 不要

source venv/bin/activate
sudo python memory_scanner.py
```

### スキャンの流れ（例: RPGのHP探索）

```
# --- ステップ1: 初回スキャン ---
# ゲーム画面でHP = 500と表示されている状態で:

> scan 500 int16
Found 1247 candidate addresses

# --- ステップ2: ゲーム内で値を変化させる ---
# 敵から攻撃を受けてHP = 472に変化

> filter 472 int16
Found 12 candidate addresses

# --- ステップ3: さらに変化させてフィルタ ---
# ポーションを使ってHP = 500に回復

> filter 500 int16
Found 2 candidate addresses
  0x000C1A28: 500
  0x000F2100: 500

# --- ステップ4: どちらが正しいか確認 ---
# もう一度ダメージを受けてHP = 465

> filter 465 int16
Found 1 address:
  0x000C1A28: 465    ← これがHP

# --- ステップ5: アドレスを保存 ---
> save hp 0x000C1A28 int16

# セッション内アドレスのエクスポート
> export SLPM-86023
Exported 1 addresses for SLPM-86023
```

### データ型の選び方

| パラメータ | よく使われる型 | 根拠 |
|-----------|--------------|------|
| HP / MP | `int16` (0-65535) | PS1ゲームの大半は16bit整数 |
| 所持金 / スコア | `int32` (0-2147483647) | 大きな数値を扱う場合 |
| レベル / ステージ | `int8` (0-255) | 小さな値の場合 |
| 座標 / 速度 | `float32` | 小数値。toleranceオプション使用推奨 |
| フラグ（ON/OFF） | `int8` | 0 or 1 |

### float32のスキャン（座標など）

```
# float値はtolerance付きスキャン
> scan 100.5 float32 --tolerance 0.1
Found 342 addresses

# 値を変化させてフィルタ
> filter 102.3 float32 --tolerance 0.1
Found 8 addresses
```

### 複数パラメータの一括登録

```bash
# 対話セッションで複数パラメータを発見した後、一括登録
python address_manager.py --game SLPM-86023 --add hp 0x0C1A28 int16 "Player HP"
python address_manager.py --game SLPM-86023 --add mp 0x0C1A2A int16 "Player MP"
python address_manager.py --game SLPM-86023 --add gold 0x0C1B40 int32 "Gold"
python address_manager.py --game SLPM-86023 --add level 0x0C1A2C int8 "Player Level"

# または JSON/CSVからバッチインポート
python address_manager.py --game SLPM-86023 --import addresses.json
python address_manager.py --game SLPM-86023 --import addresses.csv

# 登録確認
python address_manager.py --game SLPM-86023 --list
```

### アドレス登録JSON形式の例

```json
{
  "game_id": "SLPM-86023",
  "addresses": [
    {"name": "hp",    "address": "0x0C1A28", "type": "int16", "description": "Player HP"},
    {"name": "mp",    "address": "0x0C1A2A", "type": "int16", "description": "Player MP"},
    {"name": "gold",  "address": "0x0C1B40", "type": "int32", "description": "Gold"},
    {"name": "level", "address": "0x0C1A2C", "type": "int8",  "description": "Player Level"}
  ]
}
```

### スキャンのコツ

- **まず変化しやすいパラメータから**: HP（戦闘でダメージ）、金（買い物/戦闘報酬）が最も見つけやすい
- **画面表示と完全一致する値を探す**: 内部値と表示値が異なるゲームもある（例: 内部x10）
- **3回以上フィルタする**: 2回だと偶然一致が残りやすい
- **ゲーム再起動後はスキャンをやり直す**: メモリレイアウトが変わることがある
- **最低3パラメータは登録する**: 因果分析に意味のある相関を出すには3つ以上のパラメータが必要

---

## ステップ4: memory_logger

### 何をするか

`address_manager` に登録済みのメモリアドレスを定期的にポーリングし、値をCSVに記録する。
DuckStationの `/proc/PID/mem` を直接読む。

### 確認コマンド

```bash
# 前提: DuckStationが起動中であること

# アドレスが登録されているか
source venv/bin/activate
python address_manager.py --game SLPM-86023 --list
# name: hp, address: 0x0C1A28, type: int16 のような出力

# DuckStationのPID自動検出テスト
python -c "
from memory_scanner import MemoryScanner
pid = MemoryScanner._find_duckstation_pid()
print(f'PID: {pid}')
if pid:
    import os
    maps = open(f'/proc/{pid}/maps').read()
    print(f'Maps entries: {len(maps.splitlines())}')
"

# memory_loggerを単体起動（5秒間隔でポーリング、Ctrl+Cで停止）
python memory_logger.py --game SLPM-86023 --interval 5.0
# [1] hp=500 | mp=120 | gold=3000 のような出力が出ること
# logs/ にCSVファイルが作成されること

# ログファイル確認
ls -lt ~/ps1-ai-player/logs/
# 最新のCSVファイルが存在すること
head -3 ~/ps1-ai-player/logs/*_SLPM-86023*.csv
# timestamp,frame,gold,hp,mp,... のようなヘッダ+データ行（アルファベット順）
```

### ログCSVの検証ポイント

```bash
# 1. カラム名がアルファベット順か
head -1 logs/*_SLPM-86023*.csv
# timestamp,frame,gold,hp,level,mp  ← sorted

# 2. 値が変動しているか（全行同一値ならアドレスが間違い or ゲームが停止中）
awk -F, 'NR>1 {print $3}' logs/*_SLPM-86023*.csv | sort -u | wc -l
# 2以上なら値が変動している

# 3. -1が大量にないか（-1 = 読み取り失敗）
grep -c '\-1' logs/*_SLPM-86023*.csv
# 全行数に対して10%以下が望ましい

# 4. データ行数（100行以上で因果分析が有効に動く）
wc -l logs/*_SLPM-86023*.csv
```

### よくあるエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `DuckStation process not found` | DuckStationが未起動 or PID検出失敗 | `--pid PID` で手動指定 |
| `PermissionError: /proc/PID/mem` | 別ユーザーでDuckStationを起動している | 同一ユーザーで起動するか `sudo` を使う |
| `No parameters defined for game XXX` | アドレス未登録 | `python address_manager.py --game XXX --add name addr type desc` |
| `Could not read XXX at 0x...: OSError` | base_offset計算ミス or ゲームがロード完了前 | ゲームがメインメニューまで到達してから再試行。`memory_scanner.py` でインタラクティブに確認 |
| CSVに全て `-1` が記録される | アドレスが間違っている | `memory_scanner.py` で対話的にスキャンし直す |

---

## ステップ5: ai_agent

### 何をするか

画面をキャプチャ → GPT-4o Vision で解析 → キーボード入力をDuckStationに送信、を繰り返す。
戦略エンジン、ゲーム状態追跡、パラメータトレンド分析を統合。

### 確認コマンド

```bash
# 前提: Xvfb + DuckStationが起動中、OPENAI_API_KEYが設定済み

# APIキー確認
python -c "
import os
key = os.environ.get('OPENAI_API_KEY', '')
if key:
    print(f'OK: API key set ({key[:8]}...{key[-4:]})')
else:
    print('FAIL: OPENAI_API_KEY not set')
"

# スクリーンキャプチャ単体テスト（X11が必要）
python -c "
import os
os.environ.setdefault('DISPLAY', ':99')
import mss
with mss.mss() as sct:
    img = sct.grab(sct.monitors[1])
    print(f'OK: Screenshot captured ({img.width}x{img.height})')
"

# pynput単体テスト（X11が必要）
python -c "
import os
os.environ.setdefault('DISPLAY', ':99')
from pynput.keyboard import Controller, Key
kbd = Controller()
kbd.press('z')
kbd.release('z')
print('OK: Key press sent')
"

# エージェントを短時間実行（10秒で強制終了）
timeout 10 python ai_agent.py \
    --game SLPM-86023 \
    --strategy balanced \
    --detail low \
    --interval 5.0 \
    --lang ja \
    2>&1 | head -30
# Step 1/N, screenshot captured, GPT-4o response 等のログが出ること

# セッションファイルの確認
ls -lt ~/ps1-ai-player/logs/*.session.json 2>/dev/null | head -3
# .session.jsonにコスト情報が記録されていること
```

### エージェント出力の検証ポイント

```bash
# 1. session.json でAPIコストとステップ数を確認
python -m json.tool logs/*.session.json | head -20

# 期待される内容:
# {
#   "game_id": "SLPM-86023",
#   "steps": 12,
#   "cost": {
#     "prompt_tokens": 15400,
#     "completion_tokens": 2300,
#     "total_cost_usd": 0.052
#   },
#   "game_states": {"gameplay": 8, "menu": 2, "dialog": 2},
#   "strategy_switches": [...]
# }

# 2. ゲーム状態がgameplay以外も検出されているか
#    (menu/dialog/loadingが適切に分類されているかの確認)

# 3. 戦略切り替えが発生しているか
#    (パラメータ閾値に基づくstrategy switchがログに記録される)
```

### 戦略設定の選択

ゲームジャンルに合わせた戦略設定ファイルを使用する:

```bash
# ジャンルプリセットを使用（推奨）
python ai_agent.py --game SLPM-86023 --strategy-config config/strategies/rpg.json

# または自動検出（from_genre）
# AIAgent内部でfrom_genre("rpg")が呼ばれる

# カスタム設定ファイルを作成して使用
python ai_agent.py --game SLPM-86023 --strategy-config my_custom_strategy.json
```

| ジャンル | 設定ファイル | 主要閾値 |
|---------|-------------|---------|
| RPG | `config/strategies/rpg.json` | hp < 30% → defensive, mp < 20% → conservation |
| Action | `config/strategies/action.json` | lives <= 1 → cautious, hp < 25% → defensive |
| Sports | `config/strategies/sports.json` | score_diff < -2 → aggressive, stamina < 20 → conservation |
| Puzzle | `config/strategies/puzzle.json` | stack_height > 80 → emergency_clear |
| ThemePark | `config/strategies/themepark.json` | money < 500 → cost_reduction |

### よくあるエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `RuntimeError: No display available` | DISPLAY未設定 or Xvfb未起動 | `export DISPLAY=:99` してXvfbを起動 |
| `openai.AuthenticationError` | APIキーが無効 | キーを再確認。`echo $OPENAI_API_KEY` |
| `openai.RateLimitError` | APIレート制限に到達 | `--interval` を大きくする（例: 10.0）。指数バックオフが自動で3回リトライ |
| `openai.APIConnectionError` | ネットワーク不通 | `curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"` で接続テスト |
| `mss.exception.ScreenShotError` | ディスプレイに画面がない | DuckStationがXvfb上で正しく起動しているか確認 |
| `Xlib.error.DisplayConnectionError` | pynputがX11に接続できない | `DISPLAY`変数を確認。Wayland環境なら`WAYLAND_DISPLAY`が設定されているか確認 |
| スクリーンショットが全て黒い | DuckStationのGPU設定 | `settings.ini` の `Renderer = Software` に変更。Software renderer は Xvfb で安定 |
| GPT-4o の応答が空/不正JSON | prompt が不適切 or ゲーム画面が認識不能 | `--detail high` に変更。`--lang ja` でゲーム言語を指定 |
| `Consecutive screenshot errors, stopping` | 3回連続でスクリーンキャプチャ失敗 | Xvfb/DuckStationの生存確認。`kill -0 PID` でプロセス確認 |

---

## ステップ6: pipeline（自動分析）

### 何をするか

`run.sh` はエージェント終了後に自動実行する。CSV → 因果分析 → GDD → 可視化チャート。

### 確認コマンド

```bash
# 前提: logs/ にCSVファイルがあること

# CSVファイルの存在確認
ls -lt ~/ps1-ai-player/logs/*_SLPM-86023*.csv | head -5

# CSVの中身を確認（ヘッダ + 数行）
head -5 ~/ps1-ai-player/logs/*_SLPM-86023*.csv | head -1

# パイプラインを手動実行（シミュレーションはスキップ）
source venv/bin/activate
python pipeline.py \
    --logs ~/ps1-ai-player/logs/*_SLPM-86023*.csv \
    --game SLPM-86023 \
    --skip-sim
# STEP 1: Causal Chain Analysis ... N causal chains found
# STEP 2: GDD Generation ... GDD generated: reports/GDD_SLPM-86023_*.md

# 出力ファイルの確認
ls -lt ~/ps1-ai-player/reports/
# causal_chains_*.json — 因果チェーンJSON
# GDD_SLPM-86023_*.md  — Game Design Document

# GDDの内容確認
head -30 ~/ps1-ai-player/reports/GDD_SLPM-86023_*.md

# 可視化チャート生成（CSV + チェーンJSONが必要）
FIRST_CSV=$(ls -t ~/ps1-ai-player/logs/*_SLPM-86023*.csv | head -1)
FIRST_CHAINS=$(ls -t ~/ps1-ai-player/reports/causal_chains_*.json | head -1)
python visualizer.py --csv "$FIRST_CSV" --chains "$FIRST_CHAINS" --output ~/ps1-ai-player/reports/
# reports/ にPNGファイルが生成されること

ls ~/ps1-ai-player/reports/*.png
# correlation_heatmap.png, time_series.png, lag_correlations.png, causal_graph.png
```

### パイプライン出力の検証ポイント

```bash
# 1. 因果チェーンが検出されているか
python -c "
import json
with open('$(ls -t reports/causal_chains_*.json | head -1)') as f:
    chains = json.load(f)
print(f'因果チェーン数: {len(chains)}')
for c in chains[:5]:
    print(f'  {c[\"source\"]} -> {c[\"target\"]}: r={c[\"correlation\"]:.3f}, lag={c[\"lag\"]}')
"

# 2. GDDにフィードバックループが記載されているか
grep -A3 'Feedback Loop' reports/GDD_SLPM-86023_*.md

# 3. GDDのJSON出力も生成（構造化データが欲しい場合）
python gdd_generator.py \
    --csv logs/*_SLPM-86023*.csv \
    --game SLPM-86023 \
    --local \
    --format both
# reports/ に .md と .json の両方が生成される
```

### サンプルデータで事前検証

実ゲームのデータがなくても、サンプルデータでパイプラインの動作を確認できる:

```bash
source venv/bin/activate

# ジャンル別デモ（API key不要）
python demo_run.py --genre rpg
python demo_run.py --genre action
python demo_run.py --genre themepark

# サンプルデータで手動パイプライン実行
python pipeline.py \
    --logs sample_data/rpg_sample_log.csv \
    --game DEMO \
    --skip-sim

# 出力確認
cat reports/GDD_DEMO_*.md | head -50
ls reports/*.png
```

### よくあるエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `No data loaded from log files` | CSVが空 or パスが間違い | `head -3 logs/*.csv` で中身を確認 |
| `No logs found for GAME_ID` | `run.sh` のglob `*_${GAME_ID}*.csv` にマッチしない | ファイル名パターン確認。`ls logs/` |
| `0 causal chains found` | データ行数が少ない or 相関がない | 最低100行以上のデータが望ましい。`wc -l logs/*.csv` |
| `Pipeline analysis failed (non-fatal)` | パイプライン内部エラー（ログ不足等） | エージェント実行時間を伸ばす（`--duration 7200`） |
| `matplotlib: display not found` | Xvfbが停止済み | `run.sh` はパイプライン完了前にXvfbを停止しない。手動実行時は`MPLBACKEND=Agg python pipeline.py ...` |

---

## 全フローを一括で実行

全ステップの確認が完了したら `run.sh` で一括実行:

```bash
export OPENAI_API_KEY="sk-..."

./run.sh \
    --game SLPM-86023 \
    --iso ~/ps1-ai-player/isos/game.iso \
    --strategy balanced \
    --duration 3600 \
    --detail low \
    --interval 5.0
```

### run.sh のオプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--game` | (必須) | ゲームID（例: `SLPM-86023`） |
| `--iso` | (必須) | PS1 ISOファイルパス |
| `--strategy` | `balanced` | AI戦略 |
| `--duration` | `3600` | 実行秒数 |
| `--detail` | `low` | GPT-4o Vision 詳細度（`low`/`high`） |
| `--interval` | `5.0` | エージェントループ間隔（秒） |
| `--openai-key` | `$OPENAI_API_KEY` | APIキー |
| `--no-xvfb` | false | 物理ディスプレイを使用 |

### 実行中のプロセス監視

```bash
# 別ターミナルで監視
watch -n 2 'ps aux | grep -E "(Xvfb|duckstation|memory_logger|ai_agent|pipeline)" | grep -v grep'

# ログをリアルタイムで追跡
tail -f ~/ps1-ai-player/logs/*_SLPM-86023*.csv

# コスト追跡（セッション中にjsonが随時更新される）
cat ~/ps1-ai-player/logs/*.session.json 2>/dev/null | python -m json.tool | grep -A5 cost
```

### 推奨テスト実行パターン

| 段階 | duration | interval | detail | 目的 |
|------|----------|----------|--------|------|
| 動作確認 | 60 | 5.0 | low | 各コンポーネントが起動するか確認 |
| 短時間テスト | 300 | 5.0 | low | メモリログ + AI操作が記録されるか確認 |
| 因果分析テスト | 1800 | 3.0 | low | 100行以上のデータで因果チェーン検出を確認 |
| 本番セッション | 3600+ | 3.0 | low | 完全なGDD生成 |
| 高品質分析 | 3600+ | 5.0 | high | GPT-4o detail=highでの精密分析（コスト増） |

---

## ジャンル別E2Eワークフロー

### RPG（例: FF7, ドラクエ）

```bash
# 1. 推奨メモリパラメータ: hp, mp, gold, level, exp, enemy_strength
# 2. 戦略設定
python ai_agent.py --game SLPS-01057 \
    --strategy-config config/strategies/rpg.json \
    --lang ja --detail low --interval 3.0

# 3. スキャンのコツ
#    - HPはバトル中に変化するのでバトルに入ってからスキャン
#    - 所持金は店で買い物して変化させる
#    - 経験値はバトル勝利で増加
#    - レベルは経験値がたまるまで変化しないので最後に確認

# 4. 期待される因果チェーン
#    enemy_strength → hp (lag 2-5): 敵の強さがHPに影響
#    hp → action (lag 1): HP低下が回復行動を誘発
#    exp → level (lag 1): 経験値蓄積によるレベルアップ
```

### アクション（例: クラッシュ・バンディクー, ロックマン）

```bash
# 1. 推奨メモリパラメータ: lives, hp, score, time_remaining, speed
# 2. 戦略設定
python ai_agent.py --game SCPS-10031 \
    --strategy-config config/strategies/action.json \
    --lang ja --detail low --interval 2.0

# 3. スキャンのコツ
#    - 残機はミスして変化させる
#    - スコアは敵撃破やアイテムで増加
#    - タイマーは時間経過で自然に変化するため探しやすい

# 4. 期待される因果チェーン
#    speed → hp (lag 1-3): スピード上昇が被ダメージに影響
#    time_remaining → speed (lag 2): 残り時間がスピード変化を誘発
#    lives → play_style (lag 1): 残機減少が慎重なプレイを誘発
```

### テーマパーク経営（例: テーマパーク, シムシティ）

```bash
# 1. 推奨メモリパラメータ: money, satisfaction, visitors, nausea, hunger
# 2. 戦略設定
python ai_agent.py --game SLPS-00228 \
    --strategy-config config/strategies/themepark.json \
    --lang ja --detail low --interval 5.0

# 3. スキャンのコツ
#    - 所持金はゲーム時間経過で変動するため待つだけでOK
#    - 満足度は数値表示がない場合、パーセンテージ推定が必要
#    - 来場者数は画面UIの数字をそのままスキャン
```

---

## GPT-4o APIコスト見積

### コスト計算式

```
1ステップあたりのコスト（detail=low）:
  入力: ~800 tokens (system prompt + screenshot 85 tokens + memory data)
  出力: ~200 tokens (action JSON)
  コスト: (800 * $2.50 + 200 * $10.00) / 1M = $0.004/step

1ステップあたりのコスト（detail=high）:
  入力: ~1700 tokens (screenshot 765 tokens at high detail)
  出力: ~200 tokens
  コスト: (1700 * $2.50 + 200 * $10.00) / 1M = $0.006/step
```

### セッション別コスト目安

| セッション | duration | interval | steps | detail=low | detail=high |
|-----------|----------|----------|-------|-----------|------------|
| 動作確認 | 60s | 5s | ~12 | ~$0.05 | ~$0.07 |
| 短時間テスト | 300s | 5s | ~60 | ~$0.24 | ~$0.36 |
| 因果分析テスト | 1800s | 3s | ~600 | ~$2.40 | ~$3.60 |
| 本番（1時間） | 3600s | 3s | ~1200 | ~$4.80 | ~$7.20 |
| 長時間（2時間） | 7200s | 3s | ~2400 | ~$9.60 | ~$14.40 |

### コスト削減の方法

- `--detail low` を使用（デフォルト）: スクリーンショットのトークン数が1/9に
- `--interval` を大きくする: 5秒→10秒で半額
- 因果分析のみ行う場合: memory_loggerだけ動かし、ai_agentは手動操作（APIコスト = $0）

```bash
# コスト0でデータ収集 → 分析のみ実行
python memory_logger.py --game SLPM-86023 --interval 2.0
# (手動でゲームをプレイ。Ctrl+Cで停止)

python pipeline.py --logs logs/*_SLPM-86023*.csv --game SLPM-86023 --skip-sim
# → 因果チェーン + GDD 生成（APIコスト: $0）
```

---

## E2E検証チェックリスト

実ゲームでのE2Eテスト後、以下を確認する:

### Phase 1: 基盤動作

- [ ] `preflight_check.py --verbose --fix` が 5/5 パス
- [ ] Xvfbが起動し `xdpyinfo` が応答する
- [ ] DuckStationがISOをロードし、ゲーム画面が表示される
- [ ] `pgrep -a -i duckstation` でPIDが取得できる
- [ ] `/proc/PID/maps` が読める

### Phase 2: メモリアクセス

- [ ] `memory_scanner.py` でDuckStationのPS1 RAMが検出される
- [ ] 最低3つのパラメータのアドレスを発見・登録済み
- [ ] `address_manager.py --list` で登録内容を確認
- [ ] `memory_logger.py` で値がCSVに記録される
- [ ] CSV内の値が -1 ばかりでなく、ゲーム内の変化と一致する

### Phase 3: AIエージェント

- [ ] スクリーンキャプチャがDuckStationの画面を正しく取得（黒い画像でない）
- [ ] GPT-4o Visionが画面を認識し、有効なJSON応答を返す
- [ ] pynputのキー入力がDuckStationに届く（ゲーム内でキャラが動く等）
- [ ] `GameStateTracker` がgameplay/menu/dialogを区別している
- [ ] `AdaptiveStrategyEngine` がパラメータ変化に応じて戦略を切り替えている
- [ ] `.session.json` にコスト情報が記録されている

### Phase 4: 分析パイプライン

- [ ] CSVログが100行以上ある
- [ ] `data_analyzer.py` が1つ以上の因果チェーンを検出
- [ ] `gdd_generator.py` がGDD markdown/JSONを生成
- [ ] GDD内にフィードバックループの分析が含まれている
- [ ] `visualizer.py` が4つのPNGチャートを生成
- [ ] 因果チェーンの内容がゲームの仕組みと整合する

### Phase 5: 統合

- [ ] `run.sh` で全ステップが自動的に順序通り実行される
- [ ] Ctrl+Cで全プロセスが正常停止する
- [ ] `reports/` に最終成果物（GDD + チャート + 因果チェーンJSON）が揃っている

---

## トラブルシューティングチェックリスト

何か問題が起きたときに順番に確認する:

```bash
# 1. Xvfb
pgrep -a Xvfb
echo "DISPLAY=$DISPLAY"
xdpyinfo >/dev/null 2>&1 && echo "X: OK" || echo "X: FAIL"

# 2. DuckStation
pgrep -a -i duckstation
ls -l duckstation/DuckStation.AppImage
ls -l ~/.config/duckstation/bios/

# 3. メモリアクセス
DS_PID=$(pgrep -i duckstation | head -1)
[ -n "$DS_PID" ] && cat /proc/$DS_PID/maps | wc -l || echo "DuckStation not running"

# 4. Python環境
source venv/bin/activate
python -c "import mss, pynput, openai, pandas, matplotlib, scipy" 2>&1

# 5. APIキー
[ -n "$OPENAI_API_KEY" ] && echo "API key: set" || echo "API key: NOT SET"

# 6. アドレス登録
python address_manager.py --game SLPM-86023 --list 2>/dev/null || echo "No addresses"

# 7. ディスク容量
df -h ~/ps1-ai-player/

# 8. ネットワーク（API接続）
curl -s -o /dev/null -w "%{http_code}" https://api.openai.com/v1/models \
    -H "Authorization: Bearer $OPENAI_API_KEY"
# 200ならOK
```

### プロセスの手動停止

`run.sh` は `Ctrl+C` で全プロセスを停止するが、孤立プロセスが残る場合:

```bash
# 全関連プロセスを停止
pkill -f 'Xvfb :99'
pkill -f DuckStation
pkill -f memory_logger
pkill -f ai_agent
pkill -f pipeline

# ロックファイル削除
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
```

### ログ・レポートのクリーンアップ

```bash
# 古いログを削除（7日以上前）
find logs/ -name "*.csv" -mtime +7 -delete
find logs/ -name "*.session.json" -mtime +7 -delete

# レポートを削除して再生成
rm -f reports/*.png reports/*.md reports/*.json
python pipeline.py --logs logs/*_SLPM-86023*.csv --game SLPM-86023 --skip-sim
```
