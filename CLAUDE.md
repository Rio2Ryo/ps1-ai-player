## 🤖 マルチエージェント【確定版・動作確認済み 2026-02-28】

**kin で3エージェント並列実行を確認済み。必ずこのパターンを使うこと。**

CLAUDE_BIN=/home/kiiocbot/.npm-global/bin/claude

並列起動パターン（env -u CLAUDECODE が必須）:
  env -u CLAUDECODE $CLAUDE_BIN --dangerously-skip-permissions -p 'タスク1' > /tmp/agent1.log 2>&1 &
  PID1=$!
  env -u CLAUDECODE $CLAUDE_BIN --dangerously-skip-permissions -p 'タスク2' > /tmp/agent2.log 2>&1 &
  PID2=$!
  env -u CLAUDECODE $CLAUDE_BIN --dangerously-skip-permissions -p 'タスク3' > /tmp/agent3.log 2>&1 &
  PID3=$!
  wait $PID1 $PID2 $PID3
  cat /tmp/agent1.log /tmp/agent2.log /tmp/agent3.log

なぜenv -u CLAUDECODEが必要か:
Claude CodeはCLAUDECODE環境変数をセットする。子プロセスに残るとネスト起動が拒否される。
env -u CLAUDECODEでその変数を除去してから起動することで解決。

タスク分解パターン:
- agent1: フロントエンド（UIコンポーネント・ページ）
- agent2: バックエンド（API・DB・ビジネスロジック）
- agent3: テスト（ユニット・E2E）
→ wait → 統合 → commit

ルール:
1. 複数ファイルにまたがる実装は必ず並列起動
2. 単独実行は1ファイル以内の小修正のみ
3. プロンプトは具体的に（ファイルパス・実装内容・コードスタイルを含める）
4. 完了報告に「何エージェントで並列実行したか」を明記

---

# CLAUDE.md — PS1 AI Player & Logic Extraction System

## Project Overview

Autonomous PS1 game player using DuckStation emulator + GPT-4o Vision.
Reads game memory via `/proc/PID/mem`, extracts causal chains from gameplay data,
and auto-generates Game Design Documents (GDD). Features adaptive strategy switching,
game state tracking, and real-time parameter trend analysis.

## Architecture

```
run.sh (orchestrator)
  ├── Xvfb :99           (virtual display)
  ├── DuckStation         (PS1 emulator, AppImage)
  ├── memory_logger.py    (CSV logging from /proc/PID/mem)
  ├── ai_agent.py         (GPT-4o Vision → keyboard input)
  │   ├── GameStateTracker      (screen classification: menu/gameplay/dialog/loading/pause)
  │   ├── ParameterTrendAnalyzer (rising/falling/stable/volatile detection)
  │   └── AdaptiveStrategyEngine (dynamic strategy switching on param thresholds)
  └── pipeline.py         (auto-runs after session: analysis → GDD → charts)

pipeline.py (post-session analysis)
  ├── data_analyzer.py    (correlation + lag analysis → causal chains JSON)
  ├── gdd_generator.py    (causal chains → GDD markdown, local or LLM)
  │   ├── from_csv() direct CSV input + from_chains JSON input
  │   ├── Descriptive statistics, correlation matrix, data quality, event analysis
  │   ├── Feedback loop detection (positive/negative loop analysis)
  │   ├── Game state analysis + adaptive strategy docs
  │   └── JSON export (to_dict / save_gdd fmt="json")
  ├── visualizer.py       (matplotlib: heatmap, time-series, causal graph)
  └── game_prototype.py   (GDD → Python simulation → CSV export)
```

## Key Files

| File | Purpose |
|------|---------|
| `setup.sh` | Install deps, download DuckStation, create venv |
| `setup_duckstation.py` | Generate DuckStation settings.ini + key mappings |
| `memory_scanner.py` | Interactive /proc/PID/mem scanner (4-pass RAM detection) |
| `address_manager.py` | JSON storage for discovered memory addresses per game |
| `memory_logger.py` | Periodic memory polling → CSV |
| `lua_logger_template.lua` | DuckStation Lua script for in-emulator logging |
| `lua_generator.py` | Auto-generate Lua scripts from address JSON |
| `ai_agent.py` | Main agent: screenshot → GPT-4o → keyboard input loop |
| `data_analyzer.py` | Pearson + bidirectional lag cross-correlation → causal chains |
| `gdd_generator.py` | Causal chains or CSV → GDD (local + GPT-4), JSON export |
| `game_prototype.py` | Multi-genre game simulator (ThemePark/RPG/Action) with from_gdd() + CSV export |
| `pipeline.py` | End-to-end: logs → analysis → GDD → prototype |
| `visualizer.py` | Matplotlib charts: heatmap, time-series, lag bars, causal graph |
| `log_config.py` | Shared Python logging configuration |
| `run.sh` | Master launcher (Xvfb → DuckStation → logger → agent → pipeline) |
| `sample_data/generate_sample.py` | Theme park synthetic data generator (stdlib-only) |
| `sample_data/generate_rpg_sample.py` | RPG dungeon crawl synthetic data generator |
| `sample_data/generate_action_sample.py` | Action/platformer synthetic data generator |
| `preflight_check.py` | E2E pre-flight checker (ISO/BIOS/DuckStation/venv/API key) |
| `session_replay.py` | Session replay viewer: load, view, compare, analyze past agent sessions. ActionAnalyzer for action frequency/transitions/streaks/parameter-impact/heatmap. CLI: list/show/timeline/compare/events/replay |
| `cross_session_analyzer.py` | Cross-session learning: aggregate multi-session data for strategy effectiveness scoring, parameter trend evolution, action-outcome correlations, and actionable recommendations. CLI: analyze |
| `session_exporter.py` | Session ZIP export/import: bundle CSV + session.json + history.json + analysis reports into ZIP. CLI: export/import/list |
| `anomaly_detector.py` | Anomaly detection: parameter spike detection (z-score), action pattern deviation, cross-session regression detection. CLI: detect |
| `strategy_optimizer.py` | Strategy auto-tuner: threshold value tuning (percentile-based), priority rebalancing (strategy score), new threshold suggestions. CLI: optimize |
| `memory_watcher.py` | Real-time parameter watcher: threshold alerts (lt/gt/le/ge), sliding-window spike detection (z-score), strategy config interop (from_strategy_config), SSE-ready alert accumulation. CLI: check |
| `replay_diff.py` | Step-level diff between two sessions: StepDiff/ParamDelta dataclasses, divergence point detection, per-parameter trajectory comparison, markdown/JSON reports. CLI: diff |
| `session_tagger.py` | Session tag/label + notes system: add/remove/list tags per session (persisted in `session_tags.json`), free-text notes per session (persisted in `session_notes.json`). CLI: tag/untag/list-tags/show/note/show-note/delete-note |
| `session_scorer.py` | Session scoring & ranking: SessionScorer with configurable weights (steps/param_improvement/action_diversity/cost_efficiency), ScoreBreakdown per criterion (0-100), score() for single session, rank_sessions() for sorted ranking. CLI: score/rank |
| `session_search.py` | Session search & filter: ParamCondition (parameter/aggregator/operator/value), SessionSearch with param conditions (last/first/mean/min/max/std + >/>=/</<=/==/!=), step count range, date range, tag filter, note full-text search. CLI: search |
| `parameter_predictor.py` | Parameter trend prediction: linear regression + moving average for session parameters. ParameterPredictor class with threshold-arrival estimation, forecast series, prediction charts. CLI: predict/forecast |
| `batch_report.py` | Batch report generator: unified report integrating CrossSessionAnalyzer + AnomalyDetector + StrategyOptimizer + ParameterPredictor results. BatchReportGenerator class with Markdown/JSON/HTML output. CLI: generate |
| `alert_notifier.py` | Alert webhook notification: send WatcherAlert/Anomaly alerts to Slack, Discord, Telegram. WebhookConfig, AlertMessage, per-platform formatting, severity filtering, batch sends. CLI: send/test/show-config |
| `dashboard.py` | FastAPI web dashboard: browse sessions, charts, GDD docs, JSON API, action replay + action analysis pages, live monitoring (/monitor + /api/monitor), cross-analysis + anomaly alerts, session ZIP export, strategy optimizer (/optimize + /api/optimize), memory watcher (/watcher + /api/watcher/alerts + /api/watcher/events SSE), session diff (/session/diff + /api/session/diff), session tags (/api/session/{name}/tags GET+POST, tag filter on home page), session notes (/api/session/{name}/notes GET+POST), parameter predictions (/session/{name}/predict + /api/session/{name}/predict), alert notifier (/notifier + /api/notifier/config GET+POST + /api/notifier/test), session comparison overlay charts (/compare/result with per-parameter color-coded overlay plots + stats tables), session search (home page search form + /api/sessions/search JSON API), action heatmap chart on /session/{name}/actions page, session scoring (Score column on home page + /api/sessions/ranking JSON API), batch reports (/reports page + POST /api/reports/generate with Markdown/JSON/HTML output), parameter dashboard (/parameters page with correlation heatmap + distribution histograms + trend lines + lag correlations, /api/parameters/correlations JSON API) |
| `demo_run.py` | E2E demo: --genre rpg/action/themepark → analysis → GDD → charts (no API key needed) |
| `sample_data/DEMO.json` | Demo memory address definitions (GameAddresses format) |
| `sample_data/expected_output/` | Pre-generated pipeline outputs (GDD, causal chains) |
| `config/strategies/` | Genre-specific strategy configs (rpg, action, sports, puzzle, themepark) |
| `tests/` | pytest suite (~845 tests) |
| `DOCS/E2E_GUIDE.md` | run.sh E2E flow verification guide (step-by-step commands + troubleshooting) |
| `DOCS/STRATEGY_GUIDE.md` | Genre-specific memory address + strategy config setup guide |
| `pyproject.toml` | Project metadata + pytest configuration |

## Dev Commands

```bash
# Setup
bash setup.sh

# Run tests
source venv/bin/activate
pytest tests/ -v

# Generate sample data (no dependencies needed)
python3 sample_data/generate_sample.py

# Run analysis on sample data
python data_analyzer.py --logs sample_data/sample_log.csv

# Generate visualizations
python visualizer.py --csv sample_data/sample_log.csv --chains reports/demo_causal_chains.json

# Full pipeline (analysis → GDD → simulation)
python pipeline.py --logs sample_data/sample_log.csv --game DEMO

# Direct CSV → GDD (no pre-analysis needed)
python gdd_generator.py --csv sample_data/sample_log.csv --game DEMO --local

# GDD with JSON export
python gdd_generator.py --csv sample_data/sample_log.csv --game DEMO --local --format json

# GDD in both markdown + JSON
python gdd_generator.py --csv sample_data/sample_log.csv --game DEMO --local --format both

# GDD from pre-computed chains (existing workflow)
python gdd_generator.py --chains reports/demo_causal_chains.json --game DEMO --local

# Run simulation with CSV export (default: themepark)
python game_prototype.py --frames 3600 --verbose --csv-output reports/sim_output.csv

# Run RPG or Action simulation
python game_prototype.py --genre rpg --frames 3600 --verbose
python game_prototype.py --genre action --frames 3600 --verbose

# Session replay — list / show / timeline / compare / events / replay
python session_replay.py list --log-dir logs/
python session_replay.py show logs/20250101_120000_DEMO_agent.csv
python session_replay.py timeline logs/20250101_120000_DEMO_agent.csv --start 0 --end 10
python session_replay.py compare logs/session1.csv logs/session2.csv
python session_replay.py events logs/20250101_120000_DEMO_agent.csv --param hp --condition "< 50"
python session_replay.py replay logs/20250101_120000_DEMO_agent.csv            # full action analysis report
python session_replay.py replay logs/20250101_120000_DEMO_agent.csv --actions  # action frequency table only
python session_replay.py replay logs/20250101_120000_DEMO_agent.csv --step 5   # enriched step detail

# Cross-session analysis
python cross_session_analyzer.py analyze --log-dir logs/
python cross_session_analyzer.py analyze --log-dir logs/ --game DEMO --format json
python cross_session_analyzer.py analyze --log-dir logs/ --output reports/cross_analysis.md

# Session export/import
python session_exporter.py export logs/20250101_120000_DEMO_agent.csv --output exports/session.zip
python session_exporter.py import exports/session.zip --target-dir logs/
python session_exporter.py list exports/session.zip

# Anomaly detection
python anomaly_detector.py detect --log-dir logs/
python anomaly_detector.py detect --log-dir logs/ --format json --spike-threshold 3.0

# Memory watcher
python memory_watcher.py check logs/20250101_120000_DEMO_agent.csv
python memory_watcher.py check logs/20250101_120000_DEMO_agent.csv --strategy config/strategies/rpg.json
python memory_watcher.py check logs/20250101_120000_DEMO_agent.csv --rules rules.json --format json
python memory_watcher.py check logs/20250101_120000_DEMO_agent.csv --spike-threshold 3.0 --output report.md

# Session diff (step-level)
python replay_diff.py diff logs/session_a.csv logs/session_b.csv
python replay_diff.py diff logs/session_a.csv logs/session_b.csv --format json --output diff.json
python replay_diff.py diff logs/session_a.csv logs/session_b.csv --param hp

# Session tagging
python session_tagger.py tag 20250101_120000_DEMO_agent.csv good_run boss_fight
python session_tagger.py untag 20250101_120000_DEMO_agent.csv boss_fight
python session_tagger.py list-tags --log-dir logs/
python session_tagger.py show 20250101_120000_DEMO_agent.csv --log-dir logs/

# Session notes
python session_tagger.py note 20250101_120000_DEMO_agent.csv "Boss fight at step 42, low HP strategy worked"
python session_tagger.py show-note 20250101_120000_DEMO_agent.csv --log-dir logs/
python session_tagger.py delete-note 20250101_120000_DEMO_agent.csv --log-dir logs/

# Session scoring
python session_scorer.py score logs/20250101_120000_DEMO_agent.csv
python session_scorer.py score logs/20250101_120000_DEMO_agent.csv --weights steps=40,param=30,diversity=15,cost=15
python session_scorer.py rank --log-dir logs/
python session_scorer.py rank --log-dir logs/ --format json --step-target 200

# Session search
python session_search.py search --log-dir logs/
python session_search.py search --log-dir logs/ --param "hp last > 50" --steps 10-100
python session_search.py search --log-dir logs/ --date 20250101-20250201 --tag good_run
python session_search.py search --log-dir logs/ --note "boss fight" --format json

# Parameter prediction
python parameter_predictor.py predict logs/20250101_120000_DEMO_agent.csv
python parameter_predictor.py predict logs/20250101_120000_DEMO_agent.csv --format json --window 15
python parameter_predictor.py forecast logs/20250101_120000_DEMO_agent.csv --param hp --steps 30

# Batch report
python batch_report.py generate --log-dir logs/
python batch_report.py generate --log-dir logs/ --format json --output reports/batch_report.json
python batch_report.py generate --log-dir logs/ --format html --game DEMO
python batch_report.py generate --log-dir logs/ --strategy config/strategies/rpg.json

# Alert notifier
python alert_notifier.py show-config alert_notifier.json
python alert_notifier.py test alert_notifier.json
python alert_notifier.py send logs/20250101_120000_DEMO_agent.csv --config alert_notifier.json --min-severity medium

# Strategy optimisation
python strategy_optimizer.py optimize config/strategies/rpg.json --log-dir logs/
python strategy_optimizer.py optimize config/strategies/rpg.json --log-dir logs/ --format markdown
python strategy_optimizer.py optimize config/strategies/rpg.json --log-dir logs/ --output optimized_rpg.json

# Web dashboard
python dashboard.py --port 8080
python dashboard.py --host 127.0.0.1 --port 8080 --log-dir logs/ --reports-dir reports/
python dashboard.py --port 8080 --captures-dir captures/  # with screenshot captures dir

# Memory scanning (requires DuckStation running)
sudo python memory_scanner.py

# Generate Lua logger script from addresses
python lua_generator.py --game SLPM-86023

# Full session (requires DuckStation + ISO + API key)
./run.sh --game SLPM-86023 --iso isos/game.iso --strategy balanced
```

## Key Technical Patterns

- **Logging**: `from log_config import get_logger` — structured logging in all modules (including `memory_scanner.write_address`)
- **PS1 RAM**: 2MB at 0x00000000-0x001FFFFF, accessed via `/proc/PID/mem`
- **Memory detection**: 4-pass strategy in `_find_ps1_ram_offset()` parsing `/proc/PID/maps`
- **API retry**: Exponential backoff (2s base, 3 retries) in `GPT4VAnalyzer.analyze_screen()`
- **GPT response validation**: `_parse_and_validate_response()` validates JSON structure, strips invalid key names against `VALID_KEYS`, coerces types, normalizes case, caps action count at 10
- **Action history**: Sliding window of last 10 actions sent as context to GPT-4o. `save()`/`load()` for session resume via `--resume-history`
- **Cost tracking**: Token usage tracked per step, .session.json saved alongside logs
- **Key mapping**: Arrow=D-pad, Z=Circle, X=Cross, A=Square, S=Triangle, Enter=Start, Space=Select
- **pynput caveat**: Requires X11 at import time — use `importlib.util.find_spec()` for headless checks
- **Local GDD**: pipeline.py can generate full GDD without API key (statistical analysis only)
- **Auto-pipeline**: run.sh automatically runs analysis + visualization after agent session
- **Game state tracking**: `GameStateTracker` classifies screens (menu/gameplay/dialog/loading/pause) via keyword matching on GPT-4o observations + parameter change detection
- **Parameter trends**: `ParameterTrendAnalyzer` with sliding window (20 steps) detects rising/falling/stable/volatile trends and significant jumps
- **Adaptive strategy**: `AdaptiveStrategyEngine` switches strategy based on parameter thresholds. Multi-genre support via `config/strategies/` presets (rpg/action/sports/puzzle/themepark). `--strategy-config` CLI flag or `from_genre()` / `from_json()` classmethods. Priority-ordered evaluation
- **Multi-language support**: `GPT4VAnalyzer` system prompt includes Japanese text recognition instructions (kanji/hiragana/katakana). `analyze_screen()` accepts `game_state` and `lang_hint` params. `AIAgent --lang ja/en` CLI flag
- **GDD language selection**: `generate_full_gdd(lang="ja"|"en")` and `_build_llm_prompt()` static method for language-specific LLM prompts. CLI `--lang` in both `gdd_generator.py` and `pipeline.py`
- **Loading state skip**: Agent skips keyboard input during GAME_STATE_LOADING to avoid wasted actions
- **GDD feedback loops**: `gdd_generator.py` detects positive/negative feedback loops via DFS-based elementary cycle enumeration (`_find_cycles()`). Supports 2-node and 3+ node cycles. Cycle type classified by product of edge correlations
- **GDD from CSV**: `GDDGenerator.from_csv()` accepts CSV files directly — runs CausalChainExtractor internally
- **GDD sections**: Descriptive statistics, full correlation matrix, data quality report, event/action frequency analysis
- **GDD JSON export**: `save_gdd(fmt="json"|"both")` for structured output; `to_dict()` for programmatic access
- **Parameter role inference**: `_infer_parameter_role()` uses keyword heuristics + statistical classification instead of hardcoded roles
- **Parameter classification**: `_classify_parameter()` uses 4-quartile monotonicity check to avoid U/V-shape misclassification
- **Session summary**: Agent saves .session.json with cost, game_state transitions, and strategy switch history
- **Session replay**: `session_replay.py` loads CSV + .session.json + .history.json artifacts. `SessionData` auto-discovers sidecars from CSV path. `SessionTimeline` for step-by-step replay, event search (`find_events`), and `get_step_enriched()` (merges .history.json multi-action data). `ActionAnalyzer` for action frequency, action→next transition matrix, action→parameter-delta impact, consecutive action streak detection, and step-interval × action-type heatmap (`action_heatmap(bin_size)`). `SessionComparator` for multi-session comparison with param stats, action frequency comparison (`compare_actions`), per-session transition matrices (`compare_action_transitions`), and markdown report output. CLI subcommands: list/show/timeline/compare/events/replay
- **Session export/import**: `session_exporter.py` bundles session CSV + .session.json + .history.json + generated analysis reports (action_report.md, cross_session.md/json) into a ZIP archive via `SessionExporter.export_zip()` / `export_bytes()`. `import_zip()` extracts only session artifacts (skips analysis/). Dashboard integration: `/session/{name}/export` returns ZIP download. CLI: `python session_exporter.py export|import|list`
- **Strategy optimisation**: `strategy_optimizer.py` auto-tunes strategy JSON thresholds from session data. `StrategyOptimizer` takes a strategy config + session list. `tune_thresholds()` shifts lt/gt values toward observed p25/p75. `rebalance_priorities()` boosts priorities for best-performing strategies. `suggest_new_thresholds()` proposes rules for parameters with high coefficient of variation but no existing threshold. `optimize()` runs full pipeline, `diff()` for human-readable changes, `to_markdown()` for report. Dashboard: `/optimize` page with strategy selector, `/api/optimize` JSON endpoint. CLI: `python strategy_optimizer.py optimize config/strategies/rpg.json --log-dir logs/`
- **Memory watcher**: `memory_watcher.py` provides real-time parameter monitoring. `MemoryWatcher` takes a list of `ThresholdRule` objects (parameter/operator/value/severity/message) and checks values against them + performs sliding-window z-score spike detection. `check_value(param, val, ts)` returns new alerts, `check_values(dict, ts)` checks multiple params at once. `WatcherAlert` dataclass (kind/severity/parameter/value/description/timestamp/details). `from_strategy_config(config)` classmethod converts strategy JSON thresholds (priority → severity: >=8 high, >=5 medium, else low). `alert_summary()` / `to_dict()` / `to_markdown()` for output. Dashboard: `/watcher` page with auto-refresh + SSE JavaScript, `/api/watcher/alerts` JSON, `/api/watcher/events` SSE endpoint. CLI: `python memory_watcher.py check <csv> [--rules R] [--strategy S] [--spike-threshold T]`
- **Anomaly detection**: `anomaly_detector.py` detects three anomaly types: (1) `detect_spikes()` — z-score on step-to-step deltas identifies sudden parameter changes, (2) `detect_action_deviations()` — flags sessions where action frequency proportions deviate from cross-session mean, (3) `detect_regressions()` — flags parameters that worsen in latest session vs prior average. `Anomaly` dataclass with kind/severity/session/description/details. `detect_all()` aggregates, `summary()` returns JSON-serialisable dict, `to_markdown()` for reports. Integrated into dashboard `/cross-analysis` page as alert panel. CLI: `python anomaly_detector.py detect --log-dir logs/`
- **Session diff**: `replay_diff.py` provides step-level diff between two sessions. `ReplayDiff` takes two `SessionData` objects, aligns by step number, and produces `StepDiff` entries with `ParamDelta` per parameter. `step_diffs()` returns union of all steps, `divergence_points()` filters to action-diverged steps, `param_comparison(param)` returns DataFrame with side-by-side values + diff columns, `summary()` for high-level stats (divergence rate, mean param diffs), `to_markdown()` / `to_dict()` for report output. Dashboard: `/session/diff` page with session selector and color-coded divergence table, `/api/session/diff` JSON endpoint. CLI: `python replay_diff.py diff <a.csv> <b.csv> [--format json] [--output file] [--param hp]`
- **Cross-session analysis**: `cross_session_analyzer.py` aggregates data from multiple `SessionData` objects. `CrossSessionAnalyzer` computes `merged_df()` (pooled DataFrame with session_id), `parameter_evolution()` (per-session stats with trend detection), `strategy_effectiveness()` (per-strategy param aggregation), `action_effectiveness(param)` (pooled action→delta), `session_progression()` (one-row-per-session metrics), `common_patterns()` (pooled frequencies/transitions/streaks), `recommendations()` (heuristic text advice), `to_markdown()` / `to_dict()`. CLI: `python cross_session_analyzer.py analyze --log-dir logs/ [--game GAME_ID] [--format json] [--output file]`
- **GameLogger column ordering**: CSV columns sorted alphabetically for consistent output across sessions
- **Configurable monitor**: `ScreenCapture(default_monitor=N)` and `AIAgent --monitor N` CLI flag
- **Generic simulation hierarchy**: `GenericAgent`/`GenericElement`/`GenericGameSimulator` base classes with `ThemePark`/`RPG`/`Action` subclasses. Backwards compat aliases: `ParkSimulator = ThemeParkSimulator`, `VisitorAgent = ThemeParkAgent`, `RideAttraction = ThemeParkAttraction`
- **GDD DRY sections**: `_generate_analysis_sections()` private method called by both `generate_local_gdd()` and `generate_full_gdd()` to avoid section duplication
- **Session scoring**: `session_scorer.py` — `SessionScorer` class scores sessions 0–100 on 4 configurable criteria: (1) `steps_score` — ratio of total_steps to step_target, capped at 100; (2) `param_improvement_score` — average (last-first)/|first| improvement ratio across numeric params, mapped [-1,1]→[0,100]; (3) `action_diversity_score` — unique action count scaled (1→0, 5+→100); (4) `cost_efficiency_score` — steps per dollar, 1000 steps/$=100, free=100. `ScoreBreakdown` dataclass with per-criterion scores + weighted total. `rank_sessions(sessions)` returns sorted list with rank/score/breakdown. Configurable `weights` dict (default: steps=30, param=30, diversity=20, cost=20). `to_markdown()` / `to_dict()` output. CLI: `python session_scorer.py score|rank`. Dashboard: Score column on home page table, `/api/sessions/ranking` JSON endpoint
- **Session search**: `session_search.py` — `SessionSearch` class filters sessions by multiple criteria. `ParamCondition` parses condition strings like `"hp last > 50"` — supports aggregators (last/first/mean/min/max/std) and operators (>/>=/</<=/==/!=). `SessionSearch` combines: param_conditions (all must match), min_steps/max_steps range, date_from/date_to (YYYYMMDD lexicographic comparison on session timestamp), tag filter (via SessionTagger), note full-text search (case-insensitive substring via SessionTagger). `search()` returns matching SessionData list. `to_dict()` / `to_markdown()` for output. CLI: `python session_search.py search [--param] [--steps] [--date] [--tag] [--note] [--format markdown/json]`. Dashboard: home page search form (param/steps/date/tag/note fields), `/api/sessions/search` JSON endpoint with same query params
- **Session tagging + notes**: `session_tagger.py` — `SessionTagger` class persists user-defined tags (e.g. "good_run", "boss_fight", "failed") per session CSV in `{log_dir}/session_tags.json`. Methods: `tag()`, `untag()`, `get_tags()`, `list_tags()`, `sessions_with_tag()`, `all_known_tags()`. Tags are lowercase-stripped and deduplicated. **Session notes**: free-text notes per session in `{log_dir}/session_notes.json`. Methods: `set_note(csv, text)`, `get_note(csv)`, `delete_note(csv)`, `list_notes()`. Empty text deletes note, whitespace stripped. Notes independent of tags (separate file). CLI: `python session_tagger.py tag|untag|list-tags|show|note|show-note|delete-note [--log-dir]`. Dashboard: home page Tags column + `?tag=` filter, session detail tag display + quick-tag form, note display + textarea form with save/delete, `/api/session/{name}/tags` GET+POST, `/api/session/{name}/notes` GET+POST
- **Alert notification**: `alert_notifier.py` — `AlertNotifier` class sends alerts to external webhooks (Slack/Discord/Telegram). `WebhookConfig` dataclass (backend/url/enabled/min_severity/chat_id/name). `AlertMessage` normalized alert format. `from_watcher_alerts()` / `from_anomalies()` convert from `memory_watcher.WatcherAlert` / `anomaly_detector.Anomaly`. `_format_slack()` / `_format_discord()` / `_format_telegram()` per-platform message formatting with severity emoji and structured fields. `filter_by_severity()` for min-severity gating. `send_to_webhook()` / `send_all()` for delivery via `urllib.request`. `from_config_file()` / `save_config()` for JSON persistence. `to_dict()` / `to_markdown()` output. CLI: `python alert_notifier.py send|test|show-config`. Dashboard: `/notifier` config page, `/api/notifier/config` GET+POST, `/api/notifier/test` POST
- **Parameter prediction**: `parameter_predictor.py` — `ParameterPredictor` class takes a `SessionData` + moving average window. `linear_regression(param)` returns slope/intercept/r_squared via `np.polyfit`. `moving_average(param)` returns rolling mean Series. `predict_value(param, step)` extrapolates via regression. `predict_threshold(param, threshold, direction)` estimates step at which a param crosses a threshold (returns `None` if trend opposes or already past). `predict_all_thresholds(thresholds)` batch prediction with auto-defaults (reach 0 below, 2× max above). `forecast_series(param, extra_steps)` returns DataFrame with step/actual/predicted/moving_avg columns (NaN for future actuals). `to_dict()` / `to_markdown()` for JSON/report output. `plot_prediction()` standalone function generates matplotlib chart (actual + regression + moving avg + threshold markers + forecast zone). CLI: `python parameter_predictor.py predict|forecast`. Dashboard: `/session/{name}/predict` page with per-parameter charts + regression summary + threshold table, `/api/session/{name}/predict` JSON endpoint
- **Batch reports**: `batch_report.py` — `BatchReportGenerator` class takes `list[SessionData]` + optional strategy config. Runs `CrossSessionAnalyzer.to_dict()`, `AnomalyDetector.summary()`, `ParameterPredictor.to_dict()` per session, and optionally `StrategyOptimizer.optimize()`. `generate()` returns unified dict. `to_markdown()` / `to_json()` / `to_html()` for 3 output formats. HTML output is standalone with inline CSS. Auto-discovers strategy config from `config/strategies/`. CLI: `python batch_report.py generate [--log-dir] [--format markdown/json/html] [--output] [--strategy] [--game]`. Dashboard: `/reports` page with generation form + last-report display, `POST /api/reports/generate` endpoint (accepts form or JSON, saves to REPORTS_DIR)
- **Parameter dashboard**: `/parameters` page shows cross-session correlation heatmap (Pearson via `CausalChainExtractor.compute_correlations()`), parameter distribution histograms (pooled values from all sessions), per-parameter mean-trend lines (mean per session as time series), and lag correlation table (via `detect_lag_correlations()`). `/api/parameters/correlations` JSON endpoint returns correlation matrix, lag correlations, per-parameter global/session stats. Chart helpers: `_correlation_heatmap_to_base64()` (RdBu_r cmap, cell annotations), `_histogram_to_base64()` (multi-subplot grid), `_param_trend_to_base64()` (session-mean line plot). Game filter via `?game=` query param
- **Web dashboard**: `dashboard.py` — single-file FastAPI app with inline HTML templates. Charts rendered server-side via `visualizer.py` functions (temp file → PNG bytes). JSON API at `/api/sessions`, `/api/session/{name}`, `/api/session/{name}/data`, `/api/cross-analysis`. Step-through replay page at `/session/{name}/replay?step=N` with parameter deltas and streak indicators. Action analysis page at `/session/{name}/actions` with frequency table, transition matrix, parameter impact, and top streaks. **Cross-session analysis**: `/cross-analysis` page shows session progression, parameter evolution with trend coloring, strategy effectiveness comparison, action effectiveness per parameter, and heuristic recommendations; `?game=` filter support; `/api/cross-analysis` JSON endpoint. **Live monitoring**: `/monitor` page auto-refreshes every 5s, shows active session parameters with deltas/trends, latest step card, recent actions table, and screenshot placeholder. `/api/monitor` JSON endpoint for programmatic access, `/api/monitor/screenshot` serves latest capture image (404 if none). `_find_active_session()` picks the most recently modified `*_agent.csv` in LOG_DIR. **Session comparison overlay charts**: `/compare/result` page enhanced with per-parameter overlay line charts (color-coded per session via `_comparison_chart_to_base64()`) and `compare_parameters()` stats tables (mean/min/max/std/first/last). CLI: `python dashboard.py [--host] [--port] [--log-dir] [--reports-dir] [--captures-dir]`

## Environment

- Python 3.10+ with venv at `./venv/`
- Ubuntu/Debian with Xvfb for headless display
- DuckStation AppImage at `./duckstation/DuckStation.AppImage`
- OpenAI API key via `OPENAI_API_KEY` env var or `.env` file (`python-dotenv`); see `.env.example`

## GitHub

- Repo: https://github.com/Rio2Ryo/ps1-ai-player
- Branch: master


---

## タスク完了後のプロトコル（必須・毎回実行）

タスクが完了したら、次の指示を待つ前に**必ず以下を自分で実行**すること。

### STEP 1: 自己評価
コードベース・git log・テスト結果を自分で確認し、プロジェクトのゴールに対して「完成している機能」と「まだ足りないもの・改善すべきもの」を洗い出す。アオやRyoの指示を待たない。自分で考える。

### STEP 2: status-report.md を更新
~/status-report.md を最新状態に書き直す。完成済みはチェック、未実装・改善必要はHIGH/MEDIUM/LOW優先度付きで記載。

### STEP 3: Telegramで次タスクを提案
担当トピックに送信する形式:
【[プロジェクト名] 完了 + 次タスク提案】
✅ 今回完了: [やったこと]
💡 次の提案:
🔴 HIGH: [最重要タスク・理由]
🟡 MEDIUM: [中優先・理由]
🟢 LOW: [低優先・理由]
⚠️ ブロッカー: [外部対応必要なもの]
→ アオ確認後に実装開始します

### STEP 4: 待機とフォールバック
アオからの返信を受け取ってから実装開始。ただし30分以上返信がない場合はHIGHタスクを自律判断で開始してよい。
