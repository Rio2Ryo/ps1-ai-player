# expected_output/

`sample_data/sample_log.csv` に対してパイプラインを実行した際の代表的な出力。
実行しなくても出力フォーマットや分析結果を確認できる。

## ファイル一覧

| ファイル | 生成コマンド | 内容 |
|---------|------------|------|
| `causal_chains.json` | `python data_analyzer.py --logs sample_data/sample_log.csv` | 因果チェーン（15相関、5チェーン） |
| `GDD_DEMO.md` | `python gdd_generator.py --csv sample_data/sample_log.csv --game DEMO --local` | GDD（Markdown形式） |
| `GDD_DEMO.json` | 同上 `--format both` | GDD（JSON形式） |

## 再生成方法

```bash
source venv/bin/activate

# 因果チェーン分析
python data_analyzer.py --logs sample_data/sample_log.csv --output sample_data/expected_output/

# GDD生成（ローカル、APIキー不要）
python gdd_generator.py --csv sample_data/sample_log.csv --game DEMO --local --output sample_data/expected_output/ --format both
```

## 主な分析結果

- **ride_intensity → nausea**: lag=5, r=0.965（最強の因果関係）
- **nausea → satisfaction**: 間接的に低下（lag nausea が高いと satisfaction が下がる）
- **satisfaction → visitors**: lag=10, r=0.929
- 5本の因果チェーンが検出される
