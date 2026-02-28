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

## Quick Start (5-Minute Demo)

Try the analysis pipeline **without** DuckStation, PS1 ISOs, or an OpenAI API key.
The only prerequisite is **Python 3.10+**.

### Setup

```bash
git clone https://github.com/Rio2Ryo/ps1-ai-player.git
cd ps1-ai-player
pip install .
```

### Run the demo

```bash
python demo_run.py
```

### What happens

1. Generates sample data (720 steps of a theme-park management game simulation)
2. Extracts causal chains automatically (e.g. `ride_intensity → nausea → satisfaction`)
3. Produces a full Game Design Document (GDD) in Markdown
4. Renders visualizations — correlation heatmap, time-series, lag correlations, causal graph
5. Runs a theme-park simulator driven by the extracted mechanics

### Expected output

All artifacts are written to `reports/demo/`:

```
reports/demo/
  GDD_DEMO_*.md              — Game Design Document
  causal_chains_*.json       — Extracted causal chains
  correlation_heatmap.png    — Parameter correlation heatmap
  time_series.png            — Parameter time-series plot
  lag_correlations.png       — Lag correlation bar chart
  causal_graph.png           — Causal relationship graph
  sim_output.csv             — Simulation results (3 600 frames)
```

Sample console output:

```
[INFO] Generating sample data (720 steps)...
[INFO] Running causal chain extraction...
[INFO] Discovered 8 causal chains
[INFO] Generating GDD (local mode)...
[INFO] Rendering visualizations...
[INFO] Running simulation (3600 frames)...
[INFO] All outputs saved to reports/demo/
```

### Next steps

To play real PS1 games with the AI agent you will need:

- A **PS1 BIOS** image (see [PS1 BIOS Setup](#ps1-bios-setup))
- A **game ISO** (see [ISO Preparation](#iso-preparation))
- An **OpenAI API key** (see [AI Agent Execution](#ai-agent-execution))

## PS1 BIOS Setup

DuckStation requires a PS1 BIOS image to run games. **BIOS files are not included
in this project.** You must extract the BIOS from a PlayStation 1 console that you
own.

### Supported BIOS files

DuckStation auto-detects the BIOS by file contents, so the filename does not
matter. However, the conventional names and their regions are listed below for
reference:

| File name        | Model     | Region     | Notes                       |
|------------------|-----------|------------|-----------------------------|
| `scph1001.bin`   | SCPH-1001 | North America (NTSC-U) | v2.2, most commonly used |
| `scph5500.bin`   | SCPH-5500 | Japan (NTSC-J)         | v3.0                  |
| `scph5501.bin`   | SCPH-5501 | North America (NTSC-U) | v3.0                  |
| `scph5502.bin`   | SCPH-5502 | Europe (PAL)           | v3.0                  |
| `scph7001.bin`   | SCPH-7001 | North America (NTSC-U) | v4.1                  |
| `scph7501.bin`   | SCPH-7501 | North America (NTSC-U) | v4.1                  |
| `scph101.bin`    | SCPH-101  | North America (NTSC-U) | PSone slim, v4.5      |

Each file should be exactly **512 KB** (524,288 bytes). If the file size differs,
the dump was likely unsuccessful.

> **Tip**: Match the BIOS region to your game disc region. Japanese games (SLPM/SLPS)
> work best with `scph5500.bin`, North American games (SLUS/SCUS) with `scph5501.bin`,
> and European games (SLES/SCES) with `scph5502.bin`. DuckStation can also use any
> region BIOS with `Region = Auto` (the default in our configuration).

### Extracting BIOS from your own PS1 console

Dumping the BIOS from a real PlayStation is the only legal method to obtain the
file. Several approaches exist:

#### Method A: Using a FreePSXBoot memory card exploit (no mod chip required)

FreePSXBoot is a softmod that boots a payload from a specially crafted memory card
save. No hardware modification is needed.

1. **Prepare a memory card image**: Download the FreePSXBoot builder from
   <https://github.com/brad-lin/FreePSXBoot> and select your console model.
2. **Write the image to a real PS1 memory card** using a USB memory card adapter
   (e.g., PS3 Memory Card Adaptor, DexDrive, or a generic USB reader) and a tool
   such as MemcardRex or the `mcdtool` CLI.
3. **Insert the memory card** into Slot 1 of your PS1 and power on. The exploit
   payload runs automatically and presents a menu.
4. **Select "Dump BIOS"** and follow on-screen instructions. The BIOS is written
   to the second memory card in Slot 2.
5. **Read the memory card** back on your PC with the USB adapter to retrieve
   the 512 KB BIOS file.

#### Method B: Using a modded console (mod chip / swap trick)

If your console has a mod chip or you can perform the disc-swap trick:

1. **Burn a BIOS dumper disc** — the `psxexe` BIOS dumper
   (<https://www.psdevwiki.com/ps1/BIOS_Dumper>) is a minimal homebrew that
   reads the BIOS ROM and writes it to a memory card.
2. **Boot the disc** on your PS1.
3. **Transfer the memory card save** to PC as described above.

#### Method C: Using a parallel port / serial cable (advanced)

Older PS1 models (SCPH-1001 through SCPH-750x) have a parallel I/O port on the
back. With a custom parallel cable and `catflap` or `nops` on the host PC, you
can upload a BIOS dumper over the wire and receive the dump directly over serial
without needing a memory card.

### Placing the BIOS file

`setup_duckstation.py` configures DuckStation to search for BIOS files in:

```
~/.config/duckstation/bios/
```

Copy your extracted BIOS file(s) into that directory:

```bash
# Create the directory (setup_duckstation.py also creates this automatically)
mkdir -p ~/.config/duckstation/bios

# Copy your BIOS file
cp /path/to/scph5501.bin ~/.config/duckstation/bios/

# Verify the file size (should be exactly 512 KB)
ls -l ~/.config/duckstation/bios/
# -rw-r--r-- 1 user user 524288 ... scph5501.bin
```

### Configuration via setup_duckstation.py

Running `python setup_duckstation.py` generates `~/.config/duckstation/settings.ini`
with the following BIOS-related settings:

```ini
[BIOS]
SearchDirectory = /home/<user>/.config/duckstation/bios
PatchFastBoot = true
```

- **SearchDirectory**: DuckStation scans this directory for valid BIOS files.
  You can override it with `--config-dir`:
  ```bash
  python setup_duckstation.py --config-dir /custom/path/duckstation
  # BIOS directory becomes: /custom/path/duckstation/bios/
  ```
- **PatchFastBoot**: Skips the PS1 boot logo animation and loads the game
  directly. This is enabled by default for faster automated sessions.

### Verifying the BIOS is recognized

After placing the file and running `setup_duckstation.py`, start DuckStation
manually to confirm:

```bash
# If using the AppImage
./duckstation/DuckStation.AppImage

# Go to Settings -> BIOS Settings
# The BIOS file should appear in the list with its region and version
```

If the BIOS does not appear, check that:
1. The file is in `~/.config/duckstation/bios/`
2. The file is exactly 512 KB (524,288 bytes)
3. The file is not corrupted (compare the MD5 hash against known good hashes)

**Legal Notice**: The PS1 BIOS is copyrighted by Sony. You may only use a BIOS
file that you have personally extracted from a console you own. Downloading BIOS
files from the internet is a copyright violation.

---

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
  pyproject.toml            # Project metadata & dependencies
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
