# Strategy Guide — Genre-Specific Setup for PS1 AI Player

This guide explains how to configure memory addresses and strategy thresholds for each supported game genre. Every PS1 game is different, but the patterns below cover the most common parameter types per genre.

## Table of Contents

- [Overview](#overview)
- [Memory Address Setup Basics](#memory-address-setup-basics)
- [RPG](#rpg)
- [Action / Platformer](#action--platformer)
- [Sports / Racing](#sports--racing)
- [Puzzle](#puzzle)
- [Theme Park / Management](#theme-park--management)
- [Custom Strategy Configuration](#custom-strategy-configuration)
- [Threshold Tuning Tips](#threshold-tuning-tips)

---

## Overview

The PS1 AI Player reads game parameters from PS1 RAM via `/proc/PID/mem` and feeds them to the `AdaptiveStrategyEngine`, which dynamically switches the AI agent's behavior based on configurable thresholds.

The two things you need to set up for a new game:

1. **Memory addresses** — Which RAM locations hold the game parameters (via `address_manager.py` or a JSON file)
2. **Strategy config** — Threshold rules that trigger strategy switches (via `config/strategies/*.json` or `--strategy-config`)

```
Memory Addresses (what to read)     Strategy Config (how to react)
       address_manager.py     →     config/strategies/<genre>.json
              ↓                              ↓
       memory_logger.py        →     AdaptiveStrategyEngine
              ↓                              ↓
          CSV logs             →     AI Agent behavior
```

---

## Memory Address Setup Basics

### Finding Addresses

Use the interactive memory scanner to locate parameters:

```bash
# Start DuckStation with your game, then:
sudo python memory_scanner.py
```

Scanner workflow:
1. `scan <value>` — Initial scan for a known value (e.g., your current HP)
2. Change the value in-game
3. `filter changed` or `filter <new_value>` — Narrow results
4. Repeat until 1-3 addresses remain

### Supported Data Types

| Type | Size | Range | Typical Use |
|------|------|-------|-------------|
| `int8` | 1 byte | -128 to 127 | Small percentages (satisfaction, hunger) |
| `uint8` | 1 byte | 0 to 255 | HP, MP, levels in many PS1 games |
| `int16` | 2 bytes | -32768 to 32767 | Moderate counters, signed values |
| `uint16` | 2 bytes | 0 to 65535 | Score, time, item counts |
| `int32` | 4 bytes | -2B to 2B | Money, large counters |
| `uint32` | 4 bytes | 0 to 4B | Large scores, experience points |
| `float32` | 4 bytes | IEEE 754 | Positions, physics values (rare in PS1) |

### Address JSON Format

Save discovered addresses as a JSON file for `address_manager.py`:

```json
{
  "game_id": "SLPM-86023",
  "parameters": {
    "parameter_name": {
      "address": "0x001000",
      "type": "int32",
      "description": "Human-readable description"
    }
  }
}
```

Import into the address manager:

```bash
python address_manager.py import --game SLPM-86023 --file my_addresses.json
```

---

## RPG

**Examples**: Final Fantasy VII (SCUS-94163), Dragon Quest VII (SLPM-87379), Vagrant Story (SLUS-01040)

### Key Parameters to Scan

| Parameter | What to Look For | Typical Type | Scan Tip |
|-----------|-----------------|--------------|----------|
| `hp` | Current HP of lead character | `uint16` | Scan current HP, take damage, filter changed |
| `mp` | Current MP / magic points | `uint16` | Cast a spell, scan for the difference |
| `gold` | Party gold/currency | `int32` | Buy/sell an item, track the change |
| `level` | Character level | `uint8` | Usually near EXP address |
| `exp` | Experience points | `int32` or `uint32` | Kill an enemy, scan for gain amount |
| `enemy_strength` | Current enemy HP or encounter difficulty | `uint16` | Scan during battle |

### Address JSON Example

```json
{
  "game_id": "SCUS-94163",
  "parameters": {
    "hp": {
      "address": "0x0C06A8",
      "type": "uint16",
      "description": "Cloud current HP"
    },
    "mp": {
      "address": "0x0C06AA",
      "type": "uint16",
      "description": "Cloud current MP"
    },
    "gold": {
      "address": "0x0C0594",
      "type": "int32",
      "description": "Party gil"
    },
    "level": {
      "address": "0x0C0681",
      "type": "uint8",
      "description": "Cloud level"
    },
    "exp": {
      "address": "0x0C0684",
      "type": "uint32",
      "description": "Cloud total EXP"
    }
  }
}
```

### Strategy Config

Built-in preset: `config/strategies/rpg.json`

```json
{
  "genre": "rpg",
  "description": "Role-playing games (e.g., Final Fantasy, Dragon Quest)",
  "thresholds": [
    {"parameter": "hp",    "operator": "lt", "value": 30,   "target_strategy": "defensive",        "priority": 10},
    {"parameter": "mp",    "operator": "lt", "value": 10,   "target_strategy": "conservation",     "priority": 9},
    {"parameter": "hp",    "operator": "gt", "value": 80,   "target_strategy": "aggressive",       "priority": 5},
    {"parameter": "level", "operator": "lt", "value": 5,    "target_strategy": "exploration",      "priority": 7},
    {"parameter": "gold",  "operator": "gt", "value": 5000, "target_strategy": "equipment_upgrade", "priority": 6}
  ]
}
```

**How it works:**
- HP drops below 30 → `defensive` (highest priority): heal, use items, retreat
- MP below 10 → `conservation`: avoid magic, use physical attacks
- Level below 5 → `exploration`: seek out enemies to level up
- Gold above 5000 → `equipment_upgrade`: visit shops
- HP above 80 → `aggressive`: press the attack

### Usage

```bash
# Using built-in preset
./run.sh --game SCUS-94163 --iso isos/ff7.iso --strategy balanced --strategy-config rpg

# Using custom config
./run.sh --game SCUS-94163 --iso isos/ff7.iso --strategy-config my_rpg_config.json
```

### RPG-Specific Tips

- **HP/MP addresses are often adjacent** in memory. If you find HP, check nearby addresses for MP, max HP, and max MP.
- **Party member data** is usually stored in fixed-size structs. If Cloud's HP is at `0x0C06A8` with a struct size of 0x84, Barret's HP is likely at `0x0C072C`.
- **Battle vs. field values**: Some games use different RAM locations for battle HP and field HP. Scan during battle for battle values.
- **EXP thresholds vary widely**: Adjust `level` and `gold` threshold values based on the specific game's economy.

---

## Action / Platformer

**Examples**: Crash Bandicoot (SCUS-94900), Mega Man X4 (SLUS-00561), Castlevania: SOTN (SLUS-00067)

### Key Parameters to Scan

| Parameter | What to Look For | Typical Type | Scan Tip |
|-----------|-----------------|--------------|----------|
| `lives` | Remaining lives / continues | `uint8` | Die once, scan for decrease |
| `hp` | Current health / hit points | `uint8` or `uint16` | Take one hit, filter changed |
| `score` | Player score | `int32` or `uint32` | Defeat an enemy, scan increase |
| `time` | Stage timer (countdown) | `uint16` | Wait a few seconds, scan decreasing values |

### Address JSON Example

```json
{
  "game_id": "SCUS-94900",
  "parameters": {
    "lives": {
      "address": "0x05D174",
      "type": "uint8",
      "description": "Remaining lives"
    },
    "hp": {
      "address": "0x05D170",
      "type": "uint8",
      "description": "Crash health (0=dead, Aku Aku masks)"
    },
    "score": {
      "address": "0x05D1A0",
      "type": "int32",
      "description": "Wumpa fruit / score counter"
    },
    "time": {
      "address": "0x05D1B0",
      "type": "uint16",
      "description": "Stage time remaining (seconds)"
    }
  }
}
```

### Strategy Config

Built-in preset: `config/strategies/action.json`

```json
{
  "genre": "action",
  "description": "Action/platformer games (e.g., Crash Bandicoot, Mega Man)",
  "thresholds": [
    {"parameter": "lives", "operator": "lt", "value": 2,     "target_strategy": "cautious",   "priority": 10},
    {"parameter": "hp",    "operator": "lt", "value": 25,    "target_strategy": "defensive",  "priority": 9},
    {"parameter": "score", "operator": "gt", "value": 50000, "target_strategy": "aggressive", "priority": 5},
    {"parameter": "time",  "operator": "lt", "value": 30,    "target_strategy": "rush",       "priority": 8}
  ]
}
```

**How it works:**
- Last life (lives < 2) → `cautious`: avoid risks, play safe
- Low HP → `defensive`: dodge first, attack when safe
- Timer running out (< 30s) → `rush`: skip enemies, head for the exit
- High score → `aggressive`: go for combos and bonuses

### Usage

```bash
./run.sh --game SCUS-94900 --iso isos/crash.iso --strategy-config action
```

### Action-Specific Tips

- **Lives are almost always `uint8`** and stored near the top of the game's data block.
- **Timer values**: Some games store time as frames (multiply by ~16.67ms for NTSC), others as seconds. Scan both.
- **Health representation varies**: Crash uses Aku Aku masks (0-2), Mega Man uses a 0-32 bar, Castlevania uses larger values. Adjust the `hp` threshold accordingly.
- **Score often has a display vs. internal value**: The game may display `12300` but store `123` internally (multiplied for display).

---

## Sports / Racing

**Examples**: Gran Turismo (SCUS-94194), Winning Eleven (SLPM-86835), NBA Jam (SLUS-00022)

### Key Parameters to Scan

| Parameter | What to Look For | Typical Type | Scan Tip |
|-----------|-----------------|--------------|----------|
| `score_diff` | Score difference (your team - opponent) | `int16` | Calculate manually, or scan for your score and opponent score separately |
| `stamina` | Player stamina / energy gauge | `uint8` or `uint16` | Sprint until it drains, track the decrease |
| `time_remaining` | Match/race timer | `uint16` | Scan a known timer value |
| `lap` | Current lap (racing) | `uint8` | Complete a lap, filter |
| `position` | Race position (1st/2nd/...) | `uint8` | Overtake or fall back, filter |

### Address JSON Example

```json
{
  "game_id": "SLPM-86835",
  "parameters": {
    "my_score": {
      "address": "0x0A2100",
      "type": "uint8",
      "description": "My team goals"
    },
    "opponent_score": {
      "address": "0x0A2104",
      "type": "uint8",
      "description": "Opponent goals"
    },
    "stamina": {
      "address": "0x0A3200",
      "type": "uint16",
      "description": "Selected player stamina"
    },
    "time_remaining": {
      "address": "0x0A1000",
      "type": "uint16",
      "description": "Match time remaining (seconds)"
    }
  }
}
```

Note: For `score_diff`, you can either scan for a single "difference" address (some games store it) or compute it from two separate addresses. The memory logger will record both, and you can add a derived column in analysis.

### Strategy Config

Built-in preset: `config/strategies/sports.json`

```json
{
  "genre": "sports",
  "description": "Sports/racing games (e.g., Gran Turismo, Winning Eleven)",
  "thresholds": [
    {"parameter": "score_diff",     "operator": "lt", "value": -2, "target_strategy": "aggressive",   "priority": 10},
    {"parameter": "stamina",        "operator": "lt", "value": 20, "target_strategy": "conservation", "priority": 9},
    {"parameter": "time_remaining", "operator": "lt", "value": 60, "target_strategy": "rush",         "priority": 8},
    {"parameter": "score_diff",     "operator": "gt", "value": 3,  "target_strategy": "defensive",    "priority": 7}
  ]
}
```

**How it works:**
- Losing by 3+ → `aggressive`: take more shots, push forward
- Stamina low → `conservation`: short passes, slow down
- Under 60 seconds left → `rush`: all-out attack
- Winning by 3+ → `defensive`: hold possession, run out the clock

### Usage

```bash
./run.sh --game SLPM-86835 --iso isos/we.iso --strategy-config sports
```

### Sports-Specific Tips

- **Score addresses are usually separate** for each team. Use `memory_logger.py` to log both, then compute `score_diff` in post-analysis.
- **Stamina refills at halftime/pit stop** in many games — this creates interesting patterns in the causal analysis.
- **Racing games**: Scan for lap count, position, and speed. Speed is sometimes stored as `float32` or a scaled `uint16`.
- **Timer format**: Some sports games count up (elapsed time), others count down. Both work, but threshold operators need to match (use `gt` for elapsed timers, `lt` for countdown timers).

---

## Puzzle

**Examples**: Puyo Puyo (SLPS-00530), Tetris Plus (SLUS-00338), Puzzle Bobble (SLPS-00530)

### Key Parameters to Scan

| Parameter | What to Look For | Typical Type | Scan Tip |
|-----------|-----------------|--------------|----------|
| `stack_height` | How high pieces have stacked (% or row count) | `uint8` | Place a few pieces, scan increasing values |
| `combo` | Current chain/combo counter | `uint8` | Trigger a combo, scan for the number |
| `speed` | Drop speed / level-based speed increase | `uint8` | Advances with level; watch for step increases |
| `score` | Player score | `int32` | Clear a line/chain, scan the difference |

### Address JSON Example

```json
{
  "game_id": "SLPS-00530",
  "parameters": {
    "stack_height": {
      "address": "0x081200",
      "type": "uint8",
      "description": "Stack height (rows filled, 0-12)"
    },
    "combo": {
      "address": "0x081210",
      "type": "uint8",
      "description": "Current chain count"
    },
    "speed": {
      "address": "0x081220",
      "type": "uint8",
      "description": "Drop speed level (1-15)"
    },
    "score": {
      "address": "0x081230",
      "type": "int32",
      "description": "Player score"
    }
  }
}
```

### Strategy Config

Built-in preset: `config/strategies/puzzle.json`

```json
{
  "genre": "puzzle",
  "description": "Puzzle games (e.g., Puyo Puyo, Tetris)",
  "thresholds": [
    {"parameter": "stack_height", "operator": "gt", "value": 80,     "target_strategy": "emergency_clear", "priority": 10},
    {"parameter": "combo",        "operator": "gt", "value": 5,      "target_strategy": "chain_extend",    "priority": 8},
    {"parameter": "speed",        "operator": "gt", "value": 8,      "target_strategy": "defensive",       "priority": 9},
    {"parameter": "score",        "operator": "gt", "value": 100000, "target_strategy": "aggressive",      "priority": 5}
  ]
}
```

**How it works:**
- Stack near the top (>80%) → `emergency_clear`: flatten immediately
- High drop speed (>8) → `defensive`: place safely, avoid gaps
- Active combo (>5 chain) → `chain_extend`: keep the chain going
- High score → `aggressive`: go for bigger chains and combos

### Usage

```bash
./run.sh --game SLPS-00530 --iso isos/puyo.iso --strategy-config puzzle
```

### Puzzle-Specific Tips

- **Stack height can be represented differently**: row count (0-12 for Tetris), percentage (0-100), or number of filled cells. Adjust `stack_height` threshold to match.
- **Combo counters reset to 0 between chains** — the data will be very spiky. The causal analysis will detect the relationship between combo size and score gain.
- **Speed/level typically only increases**, making it a good monotonic parameter for the GDD analysis.
- **Board state as a grid**: Some advanced setups scan the entire board grid (12x6 = 72 bytes for Puyo Puyo). This is beyond single-parameter scanning but possible with batch address import.

---

## Theme Park / Management

**Examples**: Theme Park (SLES-00014), Sim City 2000 (SLUS-00113), Populous (SLPS-00tried)

### Key Parameters to Scan

| Parameter | What to Look For | Typical Type | Scan Tip |
|-----------|-----------------|--------------|----------|
| `money` | Park/city funds | `int32` | Build something, track the cost |
| `visitors` | Current visitor/population count | `int16` or `uint16` | Watch the counter on screen |
| `satisfaction` | Guest happiness (0-100) | `uint8` or `int8` | Build amenities, watch it change |
| `nausea` | Guest nausea level (0-100) | `uint8` | Build intense rides, track increase |
| `hunger` | Guest hunger level (0-100) | `uint8` | Wait without food stalls, track increase |
| `ride_intensity` | Ride excitement/intensity rating | `uint8` | Modify a ride, scan for the change |

### Address JSON Example

```json
{
  "game_id": "SLES-00014",
  "parameters": {
    "money": {
      "address": "0x001000",
      "type": "int32",
      "description": "Park funds"
    },
    "visitors": {
      "address": "0x001004",
      "type": "int16",
      "description": "Current visitor count"
    },
    "satisfaction": {
      "address": "0x001008",
      "type": "int8",
      "description": "Average guest satisfaction (0-100)"
    },
    "nausea": {
      "address": "0x00100C",
      "type": "int8",
      "description": "Average guest nausea (0-100)"
    },
    "hunger": {
      "address": "0x001010",
      "type": "int8",
      "description": "Average guest hunger (0-100)"
    },
    "ride_intensity": {
      "address": "0x001014",
      "type": "int8",
      "description": "Average ride intensity (0-100)"
    }
  }
}
```

### Strategy Config

Built-in preset: `config/strategies/themepark.json`

```json
{
  "genre": "themepark",
  "description": "Theme park management games (e.g., Theme Park, RollerCoaster Tycoon)",
  "thresholds": [
    {"parameter": "money",        "operator": "lt", "value": 1000, "target_strategy": "cost_reduction", "priority": 10},
    {"parameter": "satisfaction", "operator": "lt", "value": 30,   "target_strategy": "satisfaction",   "priority": 9},
    {"parameter": "visitors",    "operator": "lt", "value": 15,   "target_strategy": "expansion",      "priority": 7},
    {"parameter": "nausea",      "operator": "gt", "value": 70,   "target_strategy": "satisfaction",   "priority": 8},
    {"parameter": "hunger",      "operator": "gt", "value": 80,   "target_strategy": "satisfaction",   "priority": 6},
    {"parameter": "money",       "operator": "gt", "value": 8000, "target_strategy": "expansion",      "priority": 5}
  ]
}
```

**How it works:**
- Running out of money (<1000) → `cost_reduction`: stop building, raise prices
- Low satisfaction (<30) → `satisfaction`: add benches, lower ride intensity, clean up
- High nausea (>70) → `satisfaction`: reduce ride intensity, add first aid
- Few visitors (<15) → `expansion`: advertise, build attractions
- Surplus money (>8000) → `expansion`: invest in new rides and facilities

### Usage

```bash
./run.sh --game SLES-00014 --iso isos/themepark.iso --strategy-config themepark
```

### Theme Park-Specific Tips

- **Aggregate vs. individual values**: Some games store per-guest stats and aggregate stats separately. Aggregate values (average satisfaction) are more useful for the AI agent.
- **Money can go negative** in some games — use `int32`, not `uint32`.
- **Satisfaction is often a derived value** that the game recalculates periodically. It may not change every frame — set the polling interval accordingly (5-10 seconds works well).

---

## Custom Strategy Configuration

### Creating Your Own Config

Copy a built-in preset and modify it:

```bash
cp config/strategies/rpg.json config/strategies/my_game.json
```

Edit the thresholds to match your game's parameters and desired behavior:

```json
{
  "genre": "custom",
  "description": "My custom game strategy",
  "thresholds": [
    {
      "parameter": "health",
      "operator": "lt",
      "value": 20,
      "target_strategy": "survive",
      "priority": 10
    },
    {
      "parameter": "ammo",
      "operator": "lt",
      "value": 5,
      "target_strategy": "melee",
      "priority": 8
    }
  ]
}
```

### Threshold Fields

| Field | Description |
|-------|-------------|
| `parameter` | Must match a parameter name in your address JSON |
| `operator` | `lt` (less than), `gt` (greater than), `le` (<=), `ge` (>=) |
| `value` | Numeric threshold value |
| `target_strategy` | Strategy name sent to GPT-4o (any string — it becomes part of the prompt) |
| `priority` | Higher number = evaluated first. When multiple thresholds fire, the highest priority wins |

### Using Custom Config

```bash
# Pass a file path
python ai_agent.py --game SLPM-12345 --strategy-config config/strategies/my_game.json

# Or via run.sh (add --strategy-config to ai_agent invocation)
./run.sh --game SLPM-12345 --iso isos/my_game.iso --strategy-config config/strategies/my_game.json
```

### Programmatic Usage

```python
from ai_agent import AdaptiveStrategyEngine
from pathlib import Path

# From built-in genre
engine = AdaptiveStrategyEngine.from_genre("rpg")

# From custom JSON file
engine = AdaptiveStrategyEngine.from_json(Path("config/strategies/my_game.json"))

# From inline thresholds
engine = AdaptiveStrategyEngine(
    default_strategy="balanced",
    thresholds=[
        {"parameter": "hp", "operator": "lt", "value": 25, "target_strategy": "heal", "priority": 10},
    ],
)
```

---

## Threshold Tuning Tips

1. **Start with the built-in preset** for your genre and adjust values based on the specific game.

2. **Priority matters**: When multiple thresholds fire simultaneously (e.g., low HP *and* low MP), only the highest-priority one triggers. Put survival conditions (HP, lives) at priority 10.

3. **Use the demo to test**: Run `python demo_run.py --genre rpg` to see how the analysis pipeline handles your genre's parameter types before running on real games.

4. **Check the GDD output**: After a real game session, the generated GDD will show detected correlations and feedback loops. Use these to refine your thresholds — if the GDD shows "money and satisfaction are strongly correlated", you might add a combined threshold.

5. **Threshold values are game-specific**: HP < 30 is critical in a game with max HP 100, but meaningless in a game with max HP 9999. Always calibrate to the actual value ranges in your target game.

6. **The `balanced` fallback**: When no threshold fires, the engine reverts to the default strategy (usually `balanced`). This is normal idle behavior — the agent will play conservatively until a threshold triggers.
