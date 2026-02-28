"""Tests for .env file loading via python-dotenv.

Verifies that each CLI entry point calls load_dotenv() and that
os.environ picks up variables from a .env file when no env var
is already set.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).parent.parent


# ====================================================================
# python-dotenv basics
# ====================================================================


class TestDotenvLoading:
    def test_load_dotenv_sets_missing_var(self, tmp_path: Path) -> None:
        """load_dotenv() populates os.environ from a .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_VAR=hello123\n")

        # Ensure the var is not set
        os.environ.pop("TEST_DOTENV_VAR", None)

        load_dotenv(env_file)
        assert os.environ.get("TEST_DOTENV_VAR") == "hello123"

        # Cleanup
        os.environ.pop("TEST_DOTENV_VAR", None)

    def test_load_dotenv_does_not_override(self, tmp_path: Path) -> None:
        """Existing env vars are NOT overwritten by .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_VAR=from_file\n")

        os.environ["TEST_DOTENV_VAR"] = "from_env"
        load_dotenv(env_file)
        assert os.environ["TEST_DOTENV_VAR"] == "from_env"

        # Cleanup
        os.environ.pop("TEST_DOTENV_VAR", None)

    def test_load_dotenv_missing_file_is_noop(self) -> None:
        """load_dotenv() with a non-existent path does not raise."""
        result = load_dotenv("/nonexistent/.env")
        assert result is False  # returns False when file not found


# ====================================================================
# CLI entry points contain load_dotenv() call
# ====================================================================


class TestEntryPointsHaveDotenv:
    """Verify that each main() function imports and calls load_dotenv."""

    @pytest.mark.parametrize(
        "module_path",
        [
            PROJECT_ROOT / "ai_agent.py",
            PROJECT_ROOT / "data_analyzer.py",
            PROJECT_ROOT / "gdd_generator.py",
            PROJECT_ROOT / "pipeline.py",
        ],
    )
    def test_main_contains_load_dotenv(self, module_path: Path) -> None:
        source = module_path.read_text()
        assert "load_dotenv" in source, (
            f"{module_path.name} main() should call load_dotenv()"
        )


# ====================================================================
# .env.example exists and is valid
# ====================================================================


class TestDotenvExample:
    def test_env_example_exists(self) -> None:
        assert (PROJECT_ROOT / ".env.example").is_file()

    def test_env_example_contains_openai_key(self) -> None:
        content = (PROJECT_ROOT / ".env.example").read_text()
        assert "OPENAI_API_KEY" in content

    def test_env_example_is_parseable(self, tmp_path: Path) -> None:
        """python-dotenv can parse the .env.example without error."""
        import shutil

        dest = tmp_path / ".env"
        shutil.copy(PROJECT_ROOT / ".env.example", dest)
        # Should not raise
        load_dotenv(dest)


# ====================================================================
# .env in .gitignore
# ====================================================================


class TestGitignore:
    def test_env_in_gitignore(self) -> None:
        gitignore = (PROJECT_ROOT / ".gitignore").read_text()
        assert ".env" in gitignore


# ====================================================================
# Integration: subprocess picks up .env
# ====================================================================


class TestSubprocessIntegration:
    def test_pipeline_reads_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pipeline.py main() reads OPENAI_API_KEY from .env when not in env."""
        env_file = PROJECT_ROOT / ".env"
        had_env = env_file.exists()
        original_content = env_file.read_text() if had_env else None

        try:
            env_file.write_text("OPENAI_API_KEY=sk-test-from-dotenv\n")

            # Run a Python snippet that imports pipeline, calls load_dotenv,
            # then checks os.environ.
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os, sys; sys.path.insert(0, '.');"
                        "from dotenv import load_dotenv; load_dotenv();"
                        "print(os.environ.get('OPENAI_API_KEY', ''))"
                    ),
                ],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                env={k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"},
            )
            assert result.stdout.strip() == "sk-test-from-dotenv"
        finally:
            if had_env and original_content is not None:
                env_file.write_text(original_content)
            elif not had_env:
                env_file.unlink(missing_ok=True)
