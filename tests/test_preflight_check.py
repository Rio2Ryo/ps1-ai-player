"""Tests for preflight_check.py — PreflightChecker and CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from preflight_check import (
    CheckResult,
    PreflightChecker,
    format_results,
    main,
)


# ---------------------------------------------------------------------------
# ISO checks
# ---------------------------------------------------------------------------

class TestCheckISO:
    def test_iso_found(self, tmp_path: Path) -> None:
        """ISO check passes when .iso file exists in isos/."""
        iso_dir = tmp_path / "isos"
        iso_dir.mkdir()
        (iso_dir / "game.iso").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_iso()
        assert result.passed is True
        assert "1 ISO" in result.message

    def test_iso_bin_extension(self, tmp_path: Path) -> None:
        """ISO check passes for .bin files."""
        iso_dir = tmp_path / "isos"
        iso_dir.mkdir()
        (iso_dir / "game.bin").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_iso()
        assert result.passed is True

    def test_iso_img_extension(self, tmp_path: Path) -> None:
        """ISO check passes for .img files."""
        iso_dir = tmp_path / "isos"
        iso_dir.mkdir()
        (iso_dir / "game.img").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_iso()
        assert result.passed is True

    def test_iso_dir_missing(self, tmp_path: Path) -> None:
        """ISO check fails when isos/ directory does not exist."""
        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_iso()
        assert result.passed is False
        assert "not found" in result.message

    def test_iso_dir_empty(self, tmp_path: Path) -> None:
        """ISO check fails when isos/ exists but has no valid files."""
        iso_dir = tmp_path / "isos"
        iso_dir.mkdir()
        (iso_dir / "readme.txt").write_text("not an iso")

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_iso()
        assert result.passed is False
        assert "No .iso" in result.message


# ---------------------------------------------------------------------------
# BIOS checks
# ---------------------------------------------------------------------------

class TestCheckBIOS:
    def test_bios_found_in_duckstation_dir(self, tmp_path: Path) -> None:
        """BIOS check passes when scph*.bin exists in duckstation/ dir."""
        bios_dir = tmp_path / "duckstation"
        bios_dir.mkdir()
        (bios_dir / "scph1001.bin").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_bios()
        assert result.passed is True
        assert "1 BIOS" in result.message

    def test_bios_not_found(self, tmp_path: Path) -> None:
        """BIOS check fails when no scph*.bin files exist."""
        # Create duckstation dir but with no matching files
        bios_dir = tmp_path / "duckstation"
        bios_dir.mkdir()
        (bios_dir / "other.bin").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_bios()
        assert result.passed is False
        assert "No BIOS" in result.message

    def test_bios_found_in_home_config(self, tmp_path: Path) -> None:
        """BIOS check passes when scph*.bin exists in ~/.config/duckstation/bios/."""
        # This test patches DEFAULT_BIOS_DIRS to use tmp_path as the home config dir
        config_bios = tmp_path / "config_bios"
        config_bios.mkdir(parents=True)
        (config_bios / "scph5500.bin").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        # Patch the second default dir
        with mock.patch(
            "preflight_check.DEFAULT_BIOS_DIRS",
            [Path("duckstation"), config_bios],
        ):
            result = checker.check_bios()
        assert result.passed is True


# ---------------------------------------------------------------------------
# DuckStation checks
# ---------------------------------------------------------------------------

class TestCheckDuckStation:
    def test_duckstation_found_and_executable(self, tmp_path: Path) -> None:
        """DuckStation check passes when AppImage exists and is executable."""
        ds_dir = tmp_path / "duckstation"
        ds_dir.mkdir()
        ds_path = ds_dir / "DuckStation.AppImage"
        ds_path.write_bytes(b"\x00")
        ds_path.chmod(0o755)

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_duckstation()
        assert result.passed is True

    def test_duckstation_missing(self, tmp_path: Path) -> None:
        """DuckStation check fails when AppImage does not exist."""
        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_duckstation()
        assert result.passed is False
        assert "not found" in result.message

    def test_duckstation_not_executable(self, tmp_path: Path) -> None:
        """DuckStation check fails when AppImage exists but is not executable."""
        ds_dir = tmp_path / "duckstation"
        ds_dir.mkdir()
        ds_path = ds_dir / "DuckStation.AppImage"
        ds_path.write_bytes(b"\x00")
        ds_path.chmod(0o644)

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_duckstation()
        assert result.passed is False
        assert "not executable" in result.message

    def test_duckstation_env_override(self, tmp_path: Path) -> None:
        """DuckStation check uses DUCKSTATION_PATH env var when set."""
        custom_path = tmp_path / "custom_ds" / "DuckStation.AppImage"
        custom_path.parent.mkdir()
        custom_path.write_bytes(b"\x00")
        custom_path.chmod(0o755)

        checker = PreflightChecker(base_dir=tmp_path)
        with mock.patch.dict(os.environ, {"DUCKSTATION_PATH": str(custom_path)}):
            result = checker.check_duckstation()
        assert result.passed is True
        assert str(custom_path) in result.message


# ---------------------------------------------------------------------------
# venv checks
# ---------------------------------------------------------------------------

class TestCheckVenv:
    def test_venv_found(self, tmp_path: Path) -> None:
        """venv check passes when venv/bin/python exists."""
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_venv()
        assert result.passed is True

    def test_venv_missing(self, tmp_path: Path) -> None:
        """venv check fails when venv/bin/python does not exist."""
        checker = PreflightChecker(base_dir=tmp_path)
        result = checker.check_venv()
        assert result.passed is False
        assert "not found" in result.message


# ---------------------------------------------------------------------------
# OpenAI API key checks
# ---------------------------------------------------------------------------

class TestCheckOpenAIKey:
    def test_api_key_from_env(self, tmp_path: Path) -> None:
        """API key check passes when OPENAI_API_KEY env var is set."""
        checker = PreflightChecker(base_dir=tmp_path)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            result = checker.check_openai_api_key()
        assert result.passed is True
        assert "environment" in result.message

    def test_api_key_from_env_file(self, tmp_path: Path) -> None:
        """API key check passes when OPENAI_API_KEY is in .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-test-key-from-file\n")

        checker = PreflightChecker(base_dir=tmp_path)
        with mock.patch.dict(os.environ, {}, clear=True):
            # Ensure env var is not set (clear all, then restore essentials)
            env_clean = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
            with mock.patch.dict(os.environ, env_clean, clear=True):
                result = checker.check_openai_api_key()
        assert result.passed is True
        assert ".env" in result.message

    def test_api_key_missing(self, tmp_path: Path) -> None:
        """API key check fails when key is not set anywhere."""
        checker = PreflightChecker(base_dir=tmp_path)
        env_clean = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with mock.patch.dict(os.environ, env_clean, clear=True):
            result = checker.check_openai_api_key()
        assert result.passed is False
        assert "not found" in result.message

    def test_api_key_env_file_with_comments(self, tmp_path: Path) -> None:
        """API key check ignores commented-out lines in .env."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# OPENAI_API_KEY=sk-commented-out\n"
            "OTHER_VAR=foo\n"
        )

        checker = PreflightChecker(base_dir=tmp_path)
        env_clean = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with mock.patch.dict(os.environ, env_clean, clear=True):
            result = checker.check_openai_api_key()
        assert result.passed is False


# ---------------------------------------------------------------------------
# Integration: run_all_checks
# ---------------------------------------------------------------------------

class TestRunAllChecks:
    def test_all_checks_pass(self, tmp_path: Path) -> None:
        """run_all_checks returns all OK when everything is present."""
        # Set up ISO
        iso_dir = tmp_path / "isos"
        iso_dir.mkdir()
        (iso_dir / "game.iso").write_bytes(b"\x00")

        # Set up BIOS
        bios_dir = tmp_path / "duckstation"
        bios_dir.mkdir()
        (bios_dir / "scph1001.bin").write_bytes(b"\x00")

        # Set up DuckStation AppImage
        ds_path = bios_dir / "DuckStation.AppImage"
        ds_path.write_bytes(b"\x00")
        ds_path.chmod(0o755)

        # Set up venv
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_bytes(b"\x00")

        # Set up .env
        (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\n")

        checker = PreflightChecker(base_dir=tmp_path)
        env_clean = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with mock.patch.dict(os.environ, env_clean, clear=True):
            results = checker.run_all_checks()

        assert len(results) == 5
        assert all(r.passed for r in results), (
            f"Expected all checks to pass, but got: "
            f"{[(r.name, r.passed, r.message) for r in results]}"
        )

    def test_partial_fail(self, tmp_path: Path) -> None:
        """run_all_checks returns mix of OK/FAIL when some items are missing."""
        # Only set up ISO — everything else is missing
        iso_dir = tmp_path / "isos"
        iso_dir.mkdir()
        (iso_dir / "game.iso").write_bytes(b"\x00")

        checker = PreflightChecker(base_dir=tmp_path)
        env_clean = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with mock.patch.dict(os.environ, env_clean, clear=True):
            results = checker.run_all_checks()

        passed_count = sum(1 for r in results if r.passed)
        failed_count = sum(1 for r in results if not r.passed)
        assert passed_count >= 1  # At least ISO should pass
        assert failed_count >= 1  # At least some should fail


# ---------------------------------------------------------------------------
# CLI and format_results
# ---------------------------------------------------------------------------

class TestFormatResults:
    def test_fix_flag_shows_hints(self) -> None:
        """--fix flag causes fix hints to appear in output."""
        results = [
            CheckResult(
                name="ISO file",
                passed=False,
                message="No ISO found",
                fix_hint="Place your ISO in isos/",
            ),
            CheckResult(
                name="Python venv",
                passed=True,
                message="venv found",
            ),
        ]
        output = format_results(results, fix=True)
        assert "Fix: Place your ISO in isos/" in output

    def test_fix_flag_no_hint_for_passed(self) -> None:
        """Fix hints are only shown for failed checks."""
        results = [
            CheckResult(
                name="Python venv",
                passed=True,
                message="venv found",
                fix_hint="should not show",
            ),
        ]
        output = format_results(results, fix=True)
        assert "should not show" not in output

    def test_verbose_shows_details(self) -> None:
        """--verbose flag causes detail info to appear."""
        results = [
            CheckResult(
                name="ISO file",
                passed=True,
                message="Found 2 ISO files",
                details="game1.iso, game2.iso",
            ),
        ]
        output = format_results(results, verbose=True)
        assert "game1.iso, game2.iso" in output

    def test_all_pass_message(self) -> None:
        """Output shows success message when all checks pass."""
        results = [
            CheckResult(name="ISO", passed=True, message="ok"),
            CheckResult(name="BIOS", passed=True, message="ok"),
        ]
        output = format_results(results)
        assert "2/2 checks passed" in output
        assert "All checks passed" in output

    def test_fail_message(self) -> None:
        """Output shows failure message when some checks fail."""
        results = [
            CheckResult(name="ISO", passed=True, message="ok"),
            CheckResult(name="BIOS", passed=False, message="missing"),
        ]
        output = format_results(results)
        assert "1/2 checks passed" in output
        assert "Some checks failed" in output


class TestMainCLI:
    def test_main_returns_zero_when_all_pass(self, tmp_path: Path) -> None:
        """main() returns 0 when all checks pass."""
        # Set up all required files
        iso_dir = tmp_path / "isos"
        iso_dir.mkdir()
        (iso_dir / "game.iso").write_bytes(b"\x00")

        bios_dir = tmp_path / "duckstation"
        bios_dir.mkdir()
        (bios_dir / "scph1001.bin").write_bytes(b"\x00")
        ds_path = bios_dir / "DuckStation.AppImage"
        ds_path.write_bytes(b"\x00")
        ds_path.chmod(0o755)

        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_bytes(b"\x00")

        (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\n")

        env_clean = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with (
            mock.patch("preflight_check.PreflightChecker.__init__", lambda self, base_dir=None: setattr(self, "base_dir", tmp_path) or None),
            mock.patch.dict(os.environ, env_clean, clear=True),
        ):
            exit_code = main([])
        assert exit_code == 0

    def test_main_returns_one_on_failure(self, tmp_path: Path) -> None:
        """main() returns 1 when any check fails."""
        env_clean = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with (
            mock.patch("preflight_check.PreflightChecker.__init__", lambda self, base_dir=None: setattr(self, "base_dir", tmp_path) or None),
            mock.patch.dict(os.environ, env_clean, clear=True),
        ):
            exit_code = main([])
        assert exit_code == 1
