"""Tests for session_tagger.py — Session Tag/Label System."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from session_tagger import SessionTagger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tagger(tmp_path) -> SessionTagger:
    """Return a SessionTagger using a temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return SessionTagger(log_dir=log_dir)


# ---------------------------------------------------------------------------
# TestSessionTagger
# ---------------------------------------------------------------------------

class TestSessionTagger:
    def test_tag_adds_tags(self, tagger):
        result = tagger.tag("session.csv", "good_run", "boss_fight")
        assert result == ["good_run", "boss_fight"]

    def test_tag_deduplicates(self, tagger):
        tagger.tag("session.csv", "good_run")
        result = tagger.tag("session.csv", "good_run")
        assert result == ["good_run"]

    def test_tag_normalizes(self, tagger):
        result = tagger.tag("session.csv", "  Good_Run ", "FAILED")
        assert result == ["good_run", "failed"]

    def test_untag_removes(self, tagger):
        tagger.tag("session.csv", "good_run", "boss_fight", "failed")
        result = tagger.untag("session.csv", "boss_fight")
        assert result == ["good_run", "failed"]

    def test_untag_missing_tag(self, tagger):
        tagger.tag("session.csv", "good_run")
        result = tagger.untag("session.csv", "nonexistent")
        assert result == ["good_run"]

    def test_untag_removes_empty_entry(self, tagger):
        tagger.tag("session.csv", "good_run")
        tagger.untag("session.csv", "good_run")
        data = tagger.list_tags()
        assert "session.csv" not in data

    def test_get_tags(self, tagger):
        tagger.tag("session.csv", "good_run", "boss_fight")
        assert tagger.get_tags("session.csv") == ["good_run", "boss_fight"]

    def test_get_tags_empty(self, tagger):
        assert tagger.get_tags("nonexistent.csv") == []

    def test_list_tags(self, tagger):
        tagger.tag("a.csv", "good_run")
        tagger.tag("b.csv", "failed")
        data = tagger.list_tags()
        assert data == {"a.csv": ["good_run"], "b.csv": ["failed"]}

    def test_sessions_with_tag(self, tagger):
        tagger.tag("a.csv", "good_run", "boss_fight")
        tagger.tag("b.csv", "good_run")
        tagger.tag("c.csv", "failed")
        result = tagger.sessions_with_tag("good_run")
        assert sorted(result) == ["a.csv", "b.csv"]

    def test_sessions_with_tag_none(self, tagger):
        tagger.tag("a.csv", "good_run")
        assert tagger.sessions_with_tag("nonexistent") == []

    def test_all_known_tags(self, tagger):
        tagger.tag("a.csv", "good_run", "boss_fight")
        tagger.tag("b.csv", "failed", "good_run")
        result = tagger.all_known_tags()
        assert result == ["boss_fight", "failed", "good_run"]

    def test_persistence(self, tagger):
        tagger.tag("session.csv", "good_run", "boss_fight")
        # Create a new instance pointing at the same directory
        tagger2 = SessionTagger(log_dir=tagger.log_dir)
        assert tagger2.get_tags("session.csv") == ["good_run", "boss_fight"]

    def test_tags_path(self, tagger):
        expected = tagger.log_dir / "session_tags.json"
        assert tagger._tags_path == expected


# ---------------------------------------------------------------------------
# TestSessionTaggerCLI
# ---------------------------------------------------------------------------

class TestSessionTaggerCLI:
    def _run_cli(self, *args, log_dir: str | None = None):
        """Run the session_tagger CLI and return the result."""
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "session_tagger.py"),
        ]
        if log_dir:
            cmd.extend(["--log-dir", log_dir])
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_cli_tag(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        result = self._run_cli("tag", "session.csv", "good_run", "boss_fight",
                               log_dir=str(log_dir))
        assert result.returncode == 0
        assert "good_run" in result.stdout
        assert "boss_fight" in result.stdout
        # Verify JSON was written
        tags_file = log_dir / "session_tags.json"
        assert tags_file.exists()
        data = json.loads(tags_file.read_text())
        assert data["session.csv"] == ["good_run", "boss_fight"]

    def test_cli_untag(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        # First tag, then untag
        self._run_cli("tag", "session.csv", "good_run", "boss_fight",
                       log_dir=str(log_dir))
        result = self._run_cli("untag", "session.csv", "boss_fight",
                               log_dir=str(log_dir))
        assert result.returncode == 0
        data = json.loads((log_dir / "session_tags.json").read_text())
        assert data["session.csv"] == ["good_run"]

    def test_cli_list_tags(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._run_cli("tag", "a.csv", "good_run", log_dir=str(log_dir))
        self._run_cli("tag", "b.csv", "failed", log_dir=str(log_dir))
        result = self._run_cli("list-tags", log_dir=str(log_dir))
        assert result.returncode == 0
        assert "a.csv" in result.stdout
        assert "b.csv" in result.stdout

    def test_cli_show(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._run_cli("tag", "session.csv", "good_run", log_dir=str(log_dir))
        result = self._run_cli("show", "session.csv", log_dir=str(log_dir))
        assert result.returncode == 0
        assert "good_run" in result.stdout

    def test_cli_no_command(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        result = self._run_cli(log_dir=str(log_dir))
        assert result.returncode != 0
