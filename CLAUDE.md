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
  │   ├── Feedback loop detection (positive/negative loop analysis)
  │   ├── Game state analysis section
  │   └── Adaptive strategy configuration docs
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
| `data_analyzer.py` | Pearson + lag cross-correlation → causal chains |
| `gdd_generator.py` | Causal chains → GDD (local + GPT-4 generation) |
| `game_prototype.py` | Theme park simulator with from_gdd() + CSV export |
| `pipeline.py` | End-to-end: logs → analysis → GDD → prototype |
| `visualizer.py` | Matplotlib charts: heatmap, time-series, lag bars, causal graph |
| `log_config.py` | Shared Python logging configuration |
| `run.sh` | Master launcher (Xvfb → DuckStation → logger → agent → pipeline) |
| `sample_data/generate_sample.py` | Standalone synthetic data generator (stdlib-only) |
| `tests/` | pytest suite (70 tests) |
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

# Run simulation with CSV export
python game_prototype.py --frames 3600 --verbose --csv-output reports/sim_output.csv

# Memory scanning (requires DuckStation running)
sudo python memory_scanner.py

# Generate Lua logger script from addresses
python lua_generator.py --game SLPM-86023

# Full session (requires DuckStation + ISO + API key)
./run.sh --game SLPM-86023 --iso isos/game.iso --strategy balanced
```

## Key Technical Patterns

- **Logging**: `from log_config import get_logger` — structured logging in all modules
- **PS1 RAM**: 2MB at 0x00000000-0x001FFFFF, accessed via `/proc/PID/mem`
- **Memory detection**: 4-pass strategy in `_find_ps1_ram_offset()` parsing `/proc/PID/maps`
- **API retry**: Exponential backoff (2s base, 3 retries) in `GPT4VAnalyzer.analyze_screen()`
- **Action history**: Sliding window of last 10 actions sent as context to GPT-4o
- **Cost tracking**: Token usage tracked per step, .session.json saved alongside logs
- **Key mapping**: Arrow=D-pad, Z=Circle, X=Cross, A=Square, S=Triangle, Enter=Start, Space=Select
- **pynput caveat**: Requires X11 at import time — use `importlib.util.find_spec()` for headless checks
- **Local GDD**: pipeline.py can generate full GDD without API key (statistical analysis only)
- **Auto-pipeline**: run.sh automatically runs analysis + visualization after agent session
- **Game state tracking**: `GameStateTracker` classifies screens (menu/gameplay/dialog/loading/pause) via keyword matching on GPT-4o observations + parameter change detection
- **Parameter trends**: `ParameterTrendAnalyzer` with sliding window (20 steps) detects rising/falling/stable/volatile trends and significant jumps
- **Adaptive strategy**: `AdaptiveStrategyEngine` switches strategy based on parameter thresholds (e.g., money<1000 → cost_reduction). Priority-ordered evaluation, JSON-configurable per game
- **Loading state skip**: Agent skips keyboard input during GAME_STATE_LOADING to avoid wasted actions
- **GDD feedback loops**: `gdd_generator.py` detects positive/negative feedback loops from lag correlation adjacency
- **Session summary**: Agent saves .session.json with cost, game_state transitions, and strategy switch history

## Environment

- Python 3.10+ with venv at `./venv/`
- Ubuntu/Debian with Xvfb for headless display
- DuckStation AppImage at `./duckstation/DuckStation.AppImage`
- OpenAI API key via `OPENAI_API_KEY` env var

## GitHub

- Repo: https://github.com/Rio2Ryo/ps1-ai-player
- Branch: master
