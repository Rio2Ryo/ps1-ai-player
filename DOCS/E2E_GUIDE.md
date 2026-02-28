# End-to-End 動作確認ガイド

`run.sh` が実行するフロー全体（Xvfb → DuckStation → memory_logger → ai_agent → pipeline）を
ステップごとに手動で確認する手順と、よくあるエラーの対処法をまとめる。

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

# アドレス定義（memory_loggerに必要）
python address_manager.py --game SLPM-86023 --list
# パラメータが1つ以上登録されていること

# OpenAI APIキー
echo "$OPENAI_API_KEY"
# sk-... が出力されること
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

## ステップ3: memory_logger

### 何をするか

`address_manager` に登録済みのメモリアドレスを定期的にポーリングし、値をCSVに記録する。
DuckStationの `/proc/PID/mem` を直接読む。

### 確認コマンド

```bash
# 前提: DuckStationが起動中であること

# アドレスが登録されているか
source venv/bin/activate
python address_manager.py --game SLPM-86023 --list
# name: money, address: 0x1F800000, type: int32 のような出力

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
# [1] money=1000 | satisfaction=75 のような出力が出ること
# logs/ にCSVファイルが作成されること

# ログファイル確認
ls -lt ~/ps1-ai-player/logs/
# 最新のCSVファイルが存在すること
head -3 ~/ps1-ai-player/logs/*_SLPM-86023*.csv
# timestamp,frame,money,satisfaction,... のようなヘッダ+データ行
```

### よくあるエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `DuckStation process not found` | DuckStationが未起動 or PID検出失敗 | `--pid PID` で手動指定 |
| `PermissionError: /proc/PID/mem` | 別ユーザーでDuckStationを起動している | 同一ユーザーで起動するか `sudo` を使う |
| `No parameters defined for game XXX` | アドレス未登録 | `python address_manager.py --game XXX --add name addr type desc` |
| `Could not read XXX at 0x...: OSError` | base_offset計算ミス or ゲームがロード完了前 | ゲームがメインメニューまで到達してから再試行。`memory_scanner.py` でインタラクティブに確認 |
| CSVに全て `-1` が記録される | アドレスが間違っている | `memory_scanner.py` で対話的にスキャンし直す |

### メモリスキャンの事前準備

memory_loggerを使うには、ゲーム固有のアドレスを事前に発見しておく必要がある:

```bash
# DuckStationを起動した状態で
sudo python memory_scanner.py

# 対話セッション例:
#   > scan 1000 int32        （所持金が1000のとき）
#   Found 847 addresses
#   > （ゲーム内で金額を変更）
#   > filter 950 int32       （金額が950に変わった）
#   Found 3 addresses
#   > filter 900 int32       （さらに変更）
#   Found 1 address: 0x1A3400
#   > save money 0x1A3400 int32

# 発見したアドレスを登録
python address_manager.py --game SLPM-86023 --add money 0x1A3400 int32 "Player money"
```

---

## ステップ4: ai_agent

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

### 戦略の選択基準

| 戦略 | 用途 |
|------|------|
| `balanced` | デフォルト。パラメータ閾値に応じて自動切替 |
| `exploration` | ゲーム序盤。マップ探索、未知のアクション試行を優先 |
| `expansion` | 資金に余裕があるとき。施設建設等を優先 |
| `satisfaction` | 顧客満足度が低下しているとき |
| `cost_reduction` | 資金不足時。コスト削減を優先 |

---

## ステップ5: pipeline（自動分析）

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

### サンプルデータで事前検証

実ゲームのデータがなくても、サンプルデータでパイプラインの動作を確認できる:

```bash
source venv/bin/activate

# サンプルデータ生成
python sample_data/generate_sample.py

# パイプライン実行
python pipeline.py \
    --logs sample_data/sample_log.csv \
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
