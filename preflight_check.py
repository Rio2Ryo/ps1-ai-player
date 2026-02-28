#!/usr/bin/env python3
"""Pre-flight checks for PS1 AI Player E2E sessions.

Verifies that all required components (ISO, BIOS, DuckStation, venv,
OpenAI API key) are present before starting a real game session.

Usage:
    python preflight_check.py
    python preflight_check.py --verbose
    python preflight_check.py --fix
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log_config import get_logger

logger = get_logger(__name__)

# Default search paths
DEFAULT_ISO_DIR = Path("isos")
DEFAULT_DUCKSTATION_PATH = Path("duckstation/DuckStation.AppImage")
DEFAULT_BIOS_DIRS = [
    Path("duckstation"),
    Path.home() / ".config" / "duckstation" / "bios",
]
DEFAULT_VENV_PYTHON = Path("venv/bin/python")
DEFAULT_ENV_FILE = Path(".env")

ISO_EXTENSIONS = {".iso", ".bin", ".img"}
BIOS_PATTERN = "scph*.bin"


@dataclass
class CheckResult:
    """Result of a single pre-flight check."""

    name: str
    passed: bool
    message: str
    fix_hint: str = ""
    details: str = ""


class PreflightChecker:
    """Run pre-flight checks for E2E game sessions.

    Each check method returns a CheckResult. Call run_all_checks() to
    execute every check and get a summary.

    Args:
        base_dir: Project root directory (defaults to cwd).
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()

    def check_iso(self) -> CheckResult:
        """Check that at least one game ISO/BIN/IMG exists in isos/ directory."""
        iso_dir = self.base_dir / DEFAULT_ISO_DIR
        if not iso_dir.is_dir():
            return CheckResult(
                name="ISO file",
                passed=False,
                message=f"ISO directory not found: {iso_dir}",
                fix_hint=f"mkdir -p {iso_dir} && copy your game ISO/BIN/IMG into it",
            )

        iso_files = [
            f for f in iso_dir.iterdir()
            if f.is_file() and f.suffix.lower() in ISO_EXTENSIONS
        ]
        if not iso_files:
            return CheckResult(
                name="ISO file",
                passed=False,
                message=f"No .iso/.bin/.img files found in {iso_dir}",
                fix_hint=f"Place your PS1 game disc image (.iso, .bin, .img) in {iso_dir}/",
            )

        names = [f.name for f in iso_files]
        return CheckResult(
            name="ISO file",
            passed=True,
            message=f"Found {len(iso_files)} ISO file(s) in {iso_dir}",
            details=", ".join(names),
        )

    def check_bios(self) -> CheckResult:
        """Check that PS1 BIOS files (scph*.bin) exist."""
        bios_dirs = [
            self.base_dir / DEFAULT_BIOS_DIRS[0],
            DEFAULT_BIOS_DIRS[1],
        ]

        found_files: list[str] = []
        for bios_dir in bios_dirs:
            if bios_dir.is_dir():
                matches = list(bios_dir.glob(BIOS_PATTERN))
                found_files.extend(str(m) for m in matches)

        if not found_files:
            search_paths = ", ".join(str(d) for d in bios_dirs)
            return CheckResult(
                name="BIOS file",
                passed=False,
                message=f"No BIOS files ({BIOS_PATTERN}) found in: {search_paths}",
                fix_hint=(
                    "Download PS1 BIOS (e.g. scph1001.bin) and place in "
                    f"{bios_dirs[0]}/ or {bios_dirs[1]}/"
                ),
            )

        return CheckResult(
            name="BIOS file",
            passed=True,
            message=f"Found {len(found_files)} BIOS file(s)",
            details=", ".join(found_files),
        )

    def check_duckstation(self) -> CheckResult:
        """Check that DuckStation AppImage exists and is executable."""
        env_path = os.environ.get("DUCKSTATION_PATH")
        if env_path:
            ds_path = Path(env_path)
        else:
            ds_path = self.base_dir / DEFAULT_DUCKSTATION_PATH

        if not ds_path.exists():
            return CheckResult(
                name="DuckStation",
                passed=False,
                message=f"DuckStation not found: {ds_path}",
                fix_hint=(
                    "Download DuckStation AppImage from "
                    "https://github.com/stenzek/duckstation/releases "
                    f"and place at {ds_path}, or set DUCKSTATION_PATH env var"
                ),
            )

        if not os.access(ds_path, os.X_OK):
            return CheckResult(
                name="DuckStation",
                passed=False,
                message=f"DuckStation is not executable: {ds_path}",
                fix_hint=f"chmod +x {ds_path}",
            )

        return CheckResult(
            name="DuckStation",
            passed=True,
            message=f"DuckStation found: {ds_path}",
        )

    def check_venv(self) -> CheckResult:
        """Check that Python venv exists at ./venv/bin/python."""
        venv_python = self.base_dir / DEFAULT_VENV_PYTHON
        if not venv_python.exists():
            return CheckResult(
                name="Python venv",
                passed=False,
                message=f"venv Python not found: {venv_python}",
                fix_hint=f"python3 -m venv {self.base_dir / 'venv'} && source {self.base_dir / 'venv/bin/activate'} && pip install .",
            )

        return CheckResult(
            name="Python venv",
            passed=True,
            message=f"venv Python found: {venv_python}",
        )

    def check_openai_api_key(self) -> CheckResult:
        """Check that OPENAI_API_KEY is set via env var or .env file."""
        # Check environment variable first
        if os.environ.get("OPENAI_API_KEY"):
            return CheckResult(
                name="OpenAI API key",
                passed=True,
                message="OPENAI_API_KEY is set in environment",
            )

        # Check .env file
        env_file = self.base_dir / DEFAULT_ENV_FILE
        if env_file.is_file():
            content = env_file.read_text()
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                if key.strip() == "OPENAI_API_KEY" and value.strip():
                    return CheckResult(
                        name="OpenAI API key",
                        passed=True,
                        message="OPENAI_API_KEY found in .env file",
                    )

        return CheckResult(
            name="OpenAI API key",
            passed=False,
            message="OPENAI_API_KEY not found in environment or .env file",
            fix_hint="export OPENAI_API_KEY=sk-... or add OPENAI_API_KEY=sk-... to .env",
        )

    def run_all_checks(self) -> list[CheckResult]:
        """Run all pre-flight checks and return results.

        Returns:
            List of CheckResult for each check item.
        """
        checks = [
            self.check_iso,
            self.check_bios,
            self.check_duckstation,
            self.check_venv,
            self.check_openai_api_key,
        ]
        results: list[CheckResult] = []
        for check_fn in checks:
            result = check_fn()
            results.append(result)
            logger.debug("Check '%s': %s", result.name, "OK" if result.passed else "FAIL")
        return results


def format_results(
    results: list[CheckResult],
    *,
    verbose: bool = False,
    fix: bool = False,
) -> str:
    """Format check results for console output.

    Args:
        results: List of CheckResult objects.
        verbose: Show extra detail information.
        fix: Show fix hints for failed checks.

    Returns:
        Formatted multi-line string.
    """
    lines: list[str] = []
    lines.append("=== PS1 AI Player Pre-flight Check ===")
    lines.append("")

    for result in results:
        tag = "[OK]" if result.passed else "[FAIL]"
        lines.append(f"  {tag}  {result.name}: {result.message}")
        if verbose and result.details:
            lines.append(f"         Details: {result.details}")
        if fix and not result.passed and result.fix_hint:
            lines.append(f"         Fix: {result.fix_hint}")

    lines.append("")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    lines.append(f"Result: {passed}/{total} checks passed.")

    if passed < total:
        lines.append("Some checks failed. Fix the issues above before running E2E.")
    else:
        lines.append("All checks passed. Ready for E2E session!")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 if all checks pass, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Pre-flight checks for PS1 AI Player E2E sessions.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information for each check",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Show fix hints for failed checks",
    )
    args = parser.parse_args(argv)

    checker = PreflightChecker()
    results = checker.run_all_checks()

    output = format_results(results, verbose=args.verbose, fix=args.fix)
    print(output)

    all_passed = all(r.passed for r in results)
    if all_passed:
        logger.info("All pre-flight checks passed.")
    else:
        failed = [r.name for r in results if not r.passed]
        logger.warning("Pre-flight checks failed: %s", ", ".join(failed))

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
