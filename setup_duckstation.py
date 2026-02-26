#!/usr/bin/env python3
"""Generate DuckStation configuration file with appropriate settings."""

from __future__ import annotations

import os
from pathlib import Path


def generate_settings_ini(
    config_dir: Path | None = None,
    script_dir: Path | None = None,
) -> Path:
    """Generate DuckStation settings.ini with window mode and key mappings.

    Args:
        config_dir: DuckStation config directory. Defaults to ~/.config/duckstation.
        script_dir: Path to Lua/script folder. Defaults to ~/ps1-ai-player.

    Returns:
        Path to the generated settings.ini file.
    """
    if config_dir is None:
        config_dir = Path.home() / ".config" / "duckstation"
    if script_dir is None:
        script_dir = Path.home() / "ps1-ai-player"

    config_dir.mkdir(parents=True, exist_ok=True)
    settings_path = config_dir / "settings.ini"

    # Key mappings: Arrow keys = D-pad, Z=Circle, X=Cross, A=Square, S=Triangle,
    # Enter=Start, Space=Select
    settings_content = f"""\
[Main]
SettingsVersion = 3
EmulationSpeed = 1.0
FastForwardSpeed = 0.0
TurboSpeed = 0.0
SyncToHostRefreshRate = false

[Console]
Region = Auto
Enable8MBRAM = false

[CPU]
ExecutionMode = Recompiler
OverclockEnable = false

[GPU]
Renderer = OpenGL
ResolutionScale = 2
TrueColor = true
ScaledDithering = true
TextureFilter = Nearest
WidescreenHack = false
PGXPEnable = true
PGXPCulling = true
PGXPTextureCorrection = true

[Display]
CropMode = Overscan
ActiveStartOffset = 0
ActiveEndOffset = 0
LineStartOffset = 0
LineEndOffset = 0
AspectRatio = Auto
LinearFiltering = true
IntegerScaling = false
Stretch = false
PostProcessing = false
ShowOSDMessages = true
ShowFPS = true
ShowSpeed = true
ShowResolution = false
Fullscreen = false
VSync = true

[BIOS]
SearchDirectory = {config_dir / "bios"}
PatchFastBoot = true

[Controller1]
Type = DigitalController
Up = Keyboard/Up
Down = Keyboard/Down
Left = Keyboard/Left
Right = Keyboard/Right
Circle = Keyboard/Z
Cross = Keyboard/X
Square = Keyboard/A
Triangle = Keyboard/S
Start = Keyboard/Return
Select = Keyboard/Space
L1 = Keyboard/Q
R1 = Keyboard/W
L2 = Keyboard/E
R2 = Keyboard/R

[Controller2]
Type = None

[MemoryCards]
Card1Type = Shared
Card1Path = {script_dir / "saves" / "memcard1.mcd"}
Card2Type = None

[Logging]
LogLevel = Info
LogToConsole = true
LogToFile = true

[Scripting]
ScriptsDirectory = {script_dir}
AutoLoadScripts = true

[Cheats]
EnableCheats = false

[TextureReplacements]
EnableTextureReplacements = false

[GameList]
RecursivePaths = {script_dir / "isos"}
"""

    settings_path.write_text(settings_content)
    print(f"DuckStation settings written to: {settings_path}")
    print()
    print("Key mappings configured:")
    print("  Arrow keys -> D-pad (Up/Down/Left/Right)")
    print("  Z          -> Circle (O)")
    print("  X          -> Cross (X)")
    print("  A          -> Square ([])")
    print("  S          -> Triangle (/\\)")
    print("  Enter      -> Start")
    print("  Space      -> Select")
    print("  Q/W        -> L1/R1")
    print("  E/R        -> L2/R2")

    # Create BIOS directory
    bios_dir = config_dir / "bios"
    bios_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nBIOS directory: {bios_dir}")
    print("Place your PS1 BIOS files (e.g., scph1001.bin) in that directory.")

    return settings_path


def main() -> None:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate DuckStation configuration")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="DuckStation config directory (default: ~/.config/duckstation)",
    )
    parser.add_argument(
        "--script-dir",
        type=Path,
        default=None,
        help="Script/project directory (default: ~/ps1-ai-player)",
    )
    args = parser.parse_args()

    generate_settings_ini(config_dir=args.config_dir, script_dir=args.script_dir)


if __name__ == "__main__":
    main()
