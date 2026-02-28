"""Tests for setup_duckstation.py — DuckStation settings.ini generation."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from setup_duckstation import generate_settings_ini


@pytest.fixture()
def cfg_dir(tmp_path: Path) -> Path:
    return tmp_path / "duckstation_config"


@pytest.fixture()
def script_dir(tmp_path: Path) -> Path:
    return tmp_path / "project"


# ------------------------------------------------------------------
# Basic generation
# ------------------------------------------------------------------


class TestGenerateSettingsIni:
    """Core behaviour of generate_settings_ini()."""

    def test_returns_settings_path(self, cfg_dir: Path, script_dir: Path) -> None:
        result = generate_settings_ini(config_dir=cfg_dir, script_dir=script_dir)
        assert result == cfg_dir / "settings.ini"

    def test_creates_settings_file(self, cfg_dir: Path, script_dir: Path) -> None:
        path = generate_settings_ini(config_dir=cfg_dir, script_dir=script_dir)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_creates_config_dir(self, cfg_dir: Path, script_dir: Path) -> None:
        assert not cfg_dir.exists()
        generate_settings_ini(config_dir=cfg_dir, script_dir=script_dir)
        assert cfg_dir.is_dir()

    def test_creates_bios_dir(self, cfg_dir: Path, script_dir: Path) -> None:
        generate_settings_ini(config_dir=cfg_dir, script_dir=script_dir)
        assert (cfg_dir / "bios").is_dir()

    def test_idempotent(self, cfg_dir: Path, script_dir: Path) -> None:
        """Running twice should not raise."""
        generate_settings_ini(config_dir=cfg_dir, script_dir=script_dir)
        p = generate_settings_ini(config_dir=cfg_dir, script_dir=script_dir)
        assert p.exists()


# ------------------------------------------------------------------
# INI content — parsable & key sections present
# ------------------------------------------------------------------


class TestSettingsContent:
    """Verify the generated INI is well-formed and contains expected sections."""

    @pytest.fixture(autouse=True)
    def _gen(self, cfg_dir: Path, script_dir: Path) -> None:
        self.path = generate_settings_ini(config_dir=cfg_dir, script_dir=script_dir)
        self.cfg_dir = cfg_dir
        self.script_dir = script_dir
        self.text = self.path.read_text()
        # configparser for structured checks
        self.ini = configparser.ConfigParser()
        self.ini.read_string(self.text)

    def test_parsable_ini(self) -> None:
        assert len(self.ini.sections()) > 0

    @pytest.mark.parametrize(
        "section",
        [
            "Main",
            "Console",
            "CPU",
            "GPU",
            "Display",
            "BIOS",
            "Controller1",
            "Controller2",
            "MemoryCards",
            "Logging",
            "Scripting",
            "Cheats",
            "TextureReplacements",
            "GameList",
        ],
    )
    def test_section_exists(self, section: str) -> None:
        assert self.ini.has_section(section), f"Missing section [{section}]"

    # --- Controller key mappings ---------------------------------

    EXPECTED_KEYS = {
        "Up": "Keyboard/Up",
        "Down": "Keyboard/Down",
        "Left": "Keyboard/Left",
        "Right": "Keyboard/Right",
        "Circle": "Keyboard/Z",
        "Cross": "Keyboard/X",
        "Square": "Keyboard/A",
        "Triangle": "Keyboard/S",
        "Start": "Keyboard/Return",
        "Select": "Keyboard/Space",
        "L1": "Keyboard/Q",
        "R1": "Keyboard/W",
        "L2": "Keyboard/E",
        "R2": "Keyboard/R",
    }

    @pytest.mark.parametrize("key,value", EXPECTED_KEYS.items())
    def test_controller1_mapping(self, key: str, value: str) -> None:
        assert self.ini.get("Controller1", key) == value

    def test_controller1_type_digital(self) -> None:
        assert self.ini.get("Controller1", "Type") == "DigitalController"

    def test_controller2_disabled(self) -> None:
        assert self.ini.get("Controller2", "Type") == "None"

    # --- Paths use config_dir / script_dir -----------------------

    def test_bios_search_dir(self) -> None:
        bios = self.ini.get("BIOS", "SearchDirectory")
        assert bios == str(self.cfg_dir / "bios")

    def test_memcard_path(self) -> None:
        card = self.ini.get("MemoryCards", "Card1Path")
        assert card == str(self.script_dir / "saves" / "memcard1.mcd")

    def test_scripts_directory(self) -> None:
        sd = self.ini.get("Scripting", "ScriptsDirectory")
        assert sd == str(self.script_dir)

    def test_game_list_paths(self) -> None:
        rp = self.ini.get("GameList", "RecursivePaths")
        assert rp == str(self.script_dir / "isos")

    # --- GPU / Display sanity ------------------------------------

    def test_gpu_renderer(self) -> None:
        assert self.ini.get("GPU", "Renderer") == "OpenGL"

    def test_display_not_fullscreen(self) -> None:
        assert self.ini.get("Display", "Fullscreen") == "false"

    def test_display_show_fps(self) -> None:
        assert self.ini.get("Display", "ShowFPS") == "true"


# ------------------------------------------------------------------
# Default paths (config_dir=None, script_dir=None)
# ------------------------------------------------------------------


class TestDefaultPaths:
    """When no args are passed, defaults to ~/.config/duckstation and ~/ps1-ai-player."""

    def test_default_config_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        result = generate_settings_ini()
        expected = tmp_path / ".config" / "duckstation" / "settings.ini"
        assert result == expected
        assert result.exists()

    def test_default_script_dir_in_content(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        result = generate_settings_ini()
        text = result.read_text()
        assert str(tmp_path / "ps1-ai-player") in text


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------


class TestCLI:
    """Verify main() parses args and delegates to generate_settings_ini."""

    def test_main_with_args(self, tmp_path: Path) -> None:
        import sys

        cfg = tmp_path / "cli_cfg"
        sd = tmp_path / "cli_proj"
        argv = [
            "setup_duckstation.py",
            "--config-dir",
            str(cfg),
            "--script-dir",
            str(sd),
        ]
        from setup_duckstation import main

        old_argv = sys.argv
        try:
            sys.argv = argv
            main()
        finally:
            sys.argv = old_argv

        assert (cfg / "settings.ini").exists()
