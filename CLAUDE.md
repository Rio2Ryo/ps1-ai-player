# CLAUDE.md — PS1 AI Player & Logic Extraction System

## Project Overview

Autonomous PS1 game player using DuckStation emulator + GPT-4o Vision.
Reads game memory via `/proc/PID/mem`, extracts causal chains from gameplay data,
and auto-generates Game Design Documents (GDD).

## Architecture

```
run.sh (orchestrator)
  ├── Xvfb :99           (virtual display)
  ├── DuckStation         (PS1 emulator, AppImage)
  ├── memory_logger.py    (CSV logging from /proc/PID/mem)
  └── ai_agent.py         (GPT-4o Vision → keyboard input)

pipeline.py (post-session analysis)
  ├── data_analyzer.py    (correlation + lag analysis → causal chains JSON)
  ├── gdd_generator.py    (causal chains → GDD markdown)
  └── game_prototype.py   (GDD → Python simulation)
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
| `game_prototype.py` | Theme park simulator with from_gdd() loading |
| `pipeline.py` | End-to-end: logs → analysis → GDD → prototype |
| `run.sh` | Master launcher (Xvfb + DuckStation + logger + agent) |
| `sample_data/generate_sample.py` | Standalone synthetic data generator (stdlib-only) |

## Dev Commands

```bash
# Setup
bash setup.sh

# Generate sample data (no dependencies needed)
python3 sample_data/generate_sample.py

# Run analysis on sample data
source venv/bin/activate
python data_analyzer.py --logs sample_data/sample_log.csv

# Full pipeline (analysis → GDD → simulation)
python pipeline.py --logs sample_data/sample_log.csv --game DEMO

# Run simulation prototype
python game_prototype.py --frames 3600 --verbose

# Memory scanning (requires DuckStation running)
sudo python memory_scanner.py

# Full session (requires DuckStation + ISO + API key)
./run.sh --game SLPM-86023 --iso isos/game.iso --strategy balanced
```

## Key Technical Patterns

- **PS1 RAM**: 2MB at 0x00000000-0x001FFFFF, accessed via `/proc/PID/mem`
- **Memory detection**: 4-pass strategy in `_find_ps1_ram_offset()` parsing `/proc/PID/maps`
- **API retry**: Exponential backoff (2s base, 3 retries) in `GPT4VAnalyzer.analyze_screen()`
- **Action history**: Sliding window of last 10 actions sent as context to GPT-4o
- **Cost tracking**: Token usage tracked per step, summary saved to logs/
- **Key mapping**: Arrow=D-pad, Z=Circle, X=Cross, A=Square, S=Triangle, Enter=Start, Space=Select
- **pynput caveat**: Requires X11 at import time — use `importlib.util.find_spec()` for headless checks

## Environment

- Python 3.10+ with venv at `./venv/`
- Ubuntu/Debian with Xvfb for headless display
- DuckStation AppImage at `./duckstation/DuckStation.AppImage`
- OpenAI API key via `OPENAI_API_KEY` env var

## GitHub

- Repo: https://github.com/Rio2Ryo/ps1-ai-player
- Branch: master
