# sample_data/

デモ・テスト用のサンプルデータ。実際の PS1 エミュレータなしでパイプライン全体を試せる。

## ファイル一覧

### sample_log.csv
テーマパーク経営ゲームを模した合成データ（720行、5秒間隔 = 1時間分）。

| パラメータ | 説明 | 範囲 |
|-----------|------|------|
| money | 所持金 | 増減あり（初期5000） |
| visitors | 来場者数 | 10-100 |
| satisfaction | 満足度 | 5-95 |
| nausea | 吐き気 | 0-100 |
| hunger | 空腹度 | 0-100（閾値超えでリセット） |
| ride_intensity | ライドの激しさ | 0-100（正弦波+ノイズ） |
| action | プレイヤー操作 | observe, build_ride, buy_food 等 |

### 因果関係（lag構造）
```
ride_intensity --(5step lag)--> nausea --(10step lag)--> satisfaction(低下)
satisfaction --> visitors(増減)
visitors --> money(収入)
hunger --> buy_food(閾値リセット)
```

### DEMO.json
デモ用のダミーメモリアドレス定義。`address_manager.py` の `GameAddresses` フォーマットに準拠。
実際の PS1 メモリアドレスではなく、パイプラインの動作確認用。

### generate_sample.py
サンプルCSVを再生成するスクリプト（標準ライブラリのみ、依存なし）。

```bash
# デフォルト（720行、seed=42）
python3 sample_data/generate_sample.py

# カスタム
python3 sample_data/generate_sample.py --rows 1440 --seed 123 -o custom_output.csv
```

### expected_output/
`sample_log.csv` に対してパイプラインを実行した際の期待結果。
実行しなくても出力フォーマットを確認できる。
