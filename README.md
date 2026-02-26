# PS1 AI Player & Logic Extraction System

## System Overview

An autonomous system that plays PS1 games via DuckStation emulator, collects in-game
parameters through memory scanning, extracts causal relationships from gameplay data,
and auto-generates Game Design Documents (GDD).

```
Architecture
============

 +------------------+      +-------------------+      +------------------+
 |   DuckStation    |<---->|   Memory Scanner  |----->|  Memory Logger   |
 |  (PS1 Emulator)  |      |  /proc/PID/mem    |      |  CSV output      |
 +--------+---------+      +-------------------+      +--------+---------+
          |                                                     |
          | screen capture (mss)                                |
          v                                                     v
 +------------------+      +-------------------+      +------------------+
 |   AI Agent       |----->|  GPT-4o Vision    |      | Data Analyzer    |
 |  (pynput input)  |      |  analyze screen   |      | causal chains    |
 +------------------+      +-------------------+      +--------+---------+
                                                                |
                                                                v
                                                      +------------------+
                                                      |  GDD Generator   |
                                                      |  Markdown output |
                                                      +--------+---------+
                                                                |
                                                                v
                                                      +------------------+
                                                      | Game Prototype   |
                                                      | Python simulator |
                                                      +------------------+
```

## Requirements

- Ubuntu 22.04+
- Python 3.10+
- X11 or Wayland display server
- OpenAI API key (set as `OPENAI_API_KEY` environment variable)

## Installation

```bash
# 1. Clone or copy the project
cd ~/ps1-ai-player

# 2. Run the setup script
chmod +x setup.sh
./setup.sh

# 3. Configure DuckStation
python setup_duckstation.py
```

## ISO Preparation

You must provide your own PS1 game ISOs. Place them in `~/ps1-ai-player/isos/`.

### Dumping ISOs from your own discs

Use a tool like `cdrdao` on Linux:

```bash
cdrdao read-cd --read-raw --datafile game.bin --device /dev/cdrom game.toc
bchunk game.bin game.toc game.iso
```

**Legal Notice**: Only dump games you legally own. Distribution of copyrighted
game data is illegal. This project is for educational and research purposes only.

## Memory Scanner Usage

### Interactive session

```bash
python memory_scanner.py

# Example workflow:
# 1. Start DuckStation with your game
# 2. Run the scanner
# 3. "What is the current money value?" -> scan_value(1000, "int32")
# 4. Spend some money in-game
# 5. "What is the new value?" -> filter_changed(addresses, 800)
# 6. Repeat until a single address remains
```

### Managing discovered addresses

```bash
# List known addresses for a game
python address_manager.py --game SLPM-86023 --list

# Add a new address
python address_manager.py --game SLPM-86023 --add money 0x1F800000 int32 "Player money"

# Remove an address
python address_manager.py --game SLPM-86023 --remove money
```

## AI Agent Execution

```bash
# Basic run
python ai_agent.py --game SLPM-86023 --strategy balanced

# Strategy options:
#   expansion    - prioritize building attractions when funds allow
#   satisfaction - prioritize visitor comfort (nausea, hunger)
#   cost_reduction - minimize staff and maintenance costs
#   exploration  - prefer unvisited areas and untried actions
#   balanced     - switch strategy based on parameter thresholds

# Use low detail for cost savings
python ai_agent.py --game SLPM-86023 --strategy balanced --detail low
```

### Using the master run script

```bash
chmod +x run.sh

# Run everything (Xvfb + DuckStation + logger + agent)
./run.sh --game SLPM-86023 --iso ~/ps1-ai-player/isos/game.iso \
         --strategy balanced --duration 3600
```

## Cost Estimates (GPT-4o Vision)

| Mode         | Cost/call | Calls/hour (5s interval) | Cost/hour |
|------------- |-----------|--------------------------|-----------|
| detail=high  | ~$0.01    | 720                      | ~$7.20    |
| detail=low   | ~$0.005   | 720                      | ~$3.60    |

Recommendation: Start with `detail=low` for exploration, switch to `detail=high`
for fine-grained analysis of specific game states.

## Causal Chain Extraction

After collecting gameplay data:

```bash
python data_analyzer.py --logs ~/ps1-ai-player/logs/*.csv --output ~/ps1-ai-player/reports/

# Output: causal_chains_{timestamp}.json
```

The analyzer computes:
1. **Correlation matrix** between all tracked parameters
2. **Lag correlations** (up to 10 time steps) to find delayed cause-effect
3. **Causal graph** from strong correlations
4. **LLM inference** - sends statistical summary to GPT-4 for narrative interpretation

Example discovered chain:
```
ride_intensity > 80
  -> nausea +15/min (lag: 300 frames)
    -> vomit event (lag: 450 frames)
      -> cleanliness -10 (lag: 460 frames)
        -> satisfaction -5/min (lag: 600 frames)
```

## GDD Generation

```bash
python gdd_generator.py --chains ~/ps1-ai-player/reports/causal_chains_*.json \
                         --game SLPM-86023

# Output: ~/ps1-ai-player/reports/GDD_{game_id}_{timestamp}.md
```

Generated GDD sections:
- Overview
- Core Mechanics
- Parameter Definitions
- Causal Relationships
- Balance Design
- Implementation Priority

### Sample GDD Output

```markdown
# Game Design Document: Theme Park Simulator

## Core Mechanics
Visitors enter the park and interact with attractions. Each interaction
modifies internal visitor states (satisfaction, nausea, hunger) which
cascade into emergent behaviors...

## Parameter Definitions
| Parameter    | Range  | Effect                              |
|------------- |--------|-------------------------------------|
| satisfaction | 0-100  | Determines revisit probability      |
| nausea       | 0-100  | Triggers vomit at >80, reduces sat. |
| hunger       | 0-100  | Drives food stall visits at >70     |
```

## Game Prototype

Run the extracted mechanics as a standalone Python simulation:

```bash
python game_prototype.py --frames 3600

# Or load thresholds from a GDD
python game_prototype.py --from-gdd ~/ps1-ai-player/reports/GDD_SLPM-86023_*.md
```

## Project Structure

```
~/ps1-ai-player/
  setup.sh                  # Environment setup
  setup_duckstation.py      # DuckStation configuration
  run.sh                    # Master launch script
  requirements.txt          # Python dependencies
  memory_scanner.py         # /proc/PID/mem based scanner
  address_manager.py        # Address JSON management
  memory_logger.py          # Periodic CSV logger
  lua_logger_template.lua   # DuckStation Lua script template
  ai_agent.py               # AI agent with GPT-4o Vision
  data_analyzer.py          # Causal chain extraction
  gdd_generator.py          # GDD auto-generation
  game_prototype.py         # Simulation prototype
  isos/                     # Game ISOs (user-provided)
  saves/                    # Save states
  captures/                 # Screenshots
  logs/                     # CSV gameplay logs
  reports/                  # Analysis results and GDDs
  addresses/                # Per-game address JSON files
```

## License

This project is for educational and research purposes only.
