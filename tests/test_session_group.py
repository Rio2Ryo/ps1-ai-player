"""Tests for session_group.py — session group management."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from session_group import SessionGroup, SessionGroupManager, main as group_main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_session(log_dir: Path, timestamp: str = "20250101_120000",
                    game_id: str = "DEMO", rows: int = 30) -> Path:
    stem = f"{timestamp}_{game_id}_agent"
    csv_path = log_dir / f"{stem}.csv"
    session_path = log_dir / f"{stem}.session.json"
    history_path = log_dir / f"{stem}.history.json"

    actions = ["attack", "defend", "heal", "observe"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "step", "action", "reasoning", "observations",
                         "hp", "gold", "score"])
        for i in range(rows):
            act = actions[i % len(actions)]
            hp = max(10, 100 + sum([-2, 0, 3, 0][j % 4] for j in range(i)))
            score_val = 10 + sum([5, 1, 0, 0][j % 4] for j in range(i))
            writer.writerow([
                f"2025-01-01T12:00:{i:02d}", i, act,
                "testing", "ok",
                hp, 50 + i * 2, score_val,
            ])

    session_path.write_text(json.dumps({"cost": {"total_cost_usd": 0.01}}))
    history_path.write_text(json.dumps([]))
    return csv_path


@pytest.fixture
def log_dir(tmp_path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def mgr(log_dir) -> SessionGroupManager:
    return SessionGroupManager(log_dir=log_dir)


@pytest.fixture
def populated_mgr(log_dir) -> SessionGroupManager:
    """Manager with 3 sessions and 2 groups."""
    _create_session(log_dir, "20250101_120000")
    _create_session(log_dir, "20250102_120000")
    _create_session(log_dir, "20250103_120000")
    mgr = SessionGroupManager(log_dir=log_dir)
    mgr.create_group("Experiment A", description="Test group A")
    mgr.add_sessions("Experiment A",
                     "20250101_120000_DEMO_agent.csv",
                     "20250102_120000_DEMO_agent.csv")
    mgr.create_group("Experiment B", description="Test group B")
    mgr.add_sessions("Experiment B", "20250103_120000_DEMO_agent.csv")
    return mgr


# ---------------------------------------------------------------------------
# TestSessionGroup dataclass
# ---------------------------------------------------------------------------

class TestSessionGroup:

    def test_to_dict(self):
        g = SessionGroup(name="Test", description="desc", members=["a.csv"])
        d = g.to_dict()
        assert d["name"] == "Test"
        assert d["description"] == "desc"
        assert d["members"] == ["a.csv"]

    def test_from_dict(self):
        d = {"name": "G1", "description": "d1", "members": ["a.csv", "b.csv"]}
        g = SessionGroup.from_dict(d)
        assert g.name == "G1"
        assert g.description == "d1"
        assert len(g.members) == 2

    def test_from_dict_defaults(self):
        g = SessionGroup.from_dict({"name": "G2"})
        assert g.description == ""
        assert g.members == []


# ---------------------------------------------------------------------------
# TestSessionGroupManager
# ---------------------------------------------------------------------------

class TestSessionGroupManager:

    def test_create_group(self, mgr):
        group = mgr.create_group("Test Group", description="A test")
        assert group.name == "Test Group"
        assert group.description == "A test"
        assert group.members == []

    def test_create_duplicate_raises(self, mgr):
        mgr.create_group("Dup")
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_group("Dup")

    def test_create_empty_name_raises(self, mgr):
        with pytest.raises(ValueError, match="must not be empty"):
            mgr.create_group("")

    def test_delete_group(self, mgr):
        mgr.create_group("Temp")
        mgr.delete_group("Temp")
        assert len(mgr.list_groups()) == 0

    def test_delete_nonexistent_raises(self, mgr):
        with pytest.raises(KeyError, match="not found"):
            mgr.delete_group("NoSuchGroup")

    def test_get_group(self, mgr):
        mgr.create_group("MyGroup", description="hello")
        g = mgr.get_group("MyGroup")
        assert g.name == "MyGroup"
        assert g.description == "hello"

    def test_get_nonexistent_raises(self, mgr):
        with pytest.raises(KeyError, match="not found"):
            mgr.get_group("NoSuchGroup")

    def test_list_groups_empty(self, mgr):
        assert mgr.list_groups() == []

    def test_list_groups_sorted(self, mgr):
        mgr.create_group("Zebra")
        mgr.create_group("Alpha")
        groups = mgr.list_groups()
        assert groups[0].name == "Alpha"
        assert groups[1].name == "Zebra"

    def test_add_sessions(self, mgr):
        mgr.create_group("G1")
        g = mgr.add_sessions("G1", "a.csv", "b.csv")
        assert g.members == ["a.csv", "b.csv"]

    def test_add_sessions_no_duplicates(self, mgr):
        mgr.create_group("G1")
        mgr.add_sessions("G1", "a.csv")
        g = mgr.add_sessions("G1", "a.csv", "b.csv")
        assert g.members == ["a.csv", "b.csv"]

    def test_add_sessions_nonexistent_group(self, mgr):
        with pytest.raises(KeyError, match="not found"):
            mgr.add_sessions("NoGroup", "a.csv")

    def test_remove_sessions(self, mgr):
        mgr.create_group("G1")
        mgr.add_sessions("G1", "a.csv", "b.csv", "c.csv")
        g = mgr.remove_sessions("G1", "b.csv")
        assert g.members == ["a.csv", "c.csv"]

    def test_remove_sessions_missing_ignored(self, mgr):
        mgr.create_group("G1")
        mgr.add_sessions("G1", "a.csv")
        g = mgr.remove_sessions("G1", "z.csv")
        assert g.members == ["a.csv"]

    def test_remove_sessions_nonexistent_group(self, mgr):
        with pytest.raises(KeyError, match="not found"):
            mgr.remove_sessions("NoGroup", "a.csv")

    def test_rename_group(self, mgr):
        mgr.create_group("OldName")
        mgr.add_sessions("OldName", "a.csv")
        g = mgr.rename_group("OldName", "NewName")
        assert g.name == "NewName"
        assert g.members == ["a.csv"]
        with pytest.raises(KeyError):
            mgr.get_group("OldName")

    def test_rename_to_existing_raises(self, mgr):
        mgr.create_group("A")
        mgr.create_group("B")
        with pytest.raises(ValueError, match="already exists"):
            mgr.rename_group("A", "B")

    def test_rename_empty_raises(self, mgr):
        mgr.create_group("A")
        with pytest.raises(ValueError, match="must not be empty"):
            mgr.rename_group("A", "  ")

    def test_persistence(self, log_dir):
        mgr1 = SessionGroupManager(log_dir=log_dir)
        mgr1.create_group("Persistent", description="survives reload")
        mgr1.add_sessions("Persistent", "a.csv")

        mgr2 = SessionGroupManager(log_dir=log_dir)
        g = mgr2.get_group("Persistent")
        assert g.description == "survives reload"
        assert g.members == ["a.csv"]


# ---------------------------------------------------------------------------
# TestGroupStats
# ---------------------------------------------------------------------------

class TestGroupStats:

    def test_stats_basic(self, populated_mgr):
        stats = populated_mgr.group_stats("Experiment A")
        assert stats["member_count"] == 2
        assert stats["sessions_found"] == 2
        assert stats["avg_score"] is not None
        assert stats["avg_steps"] > 0
        assert isinstance(stats["param_comparison"], dict)

    def test_stats_has_member_details(self, populated_mgr):
        stats = populated_mgr.group_stats("Experiment A")
        assert len(stats["member_details"]) == 2
        for d in stats["member_details"]:
            assert "csv_filename" in d
            assert "score" in d
            assert "steps" in d
            assert "params" in d

    def test_stats_param_comparison(self, populated_mgr):
        stats = populated_mgr.group_stats("Experiment A")
        pc = stats["param_comparison"]
        assert "hp" in pc
        assert "mean" in pc["hp"]
        assert "min" in pc["hp"]
        assert "max" in pc["hp"]
        assert "std" in pc["hp"]

    def test_stats_empty_group(self, mgr):
        mgr.create_group("Empty")
        stats = mgr.group_stats("Empty")
        assert stats["member_count"] == 0
        assert stats["sessions_found"] == 0
        assert stats["avg_score"] is None
        assert stats["param_comparison"] == {}

    def test_stats_missing_files(self, mgr):
        mgr.create_group("Ghost")
        mgr.add_sessions("Ghost", "nonexistent.csv")
        stats = mgr.group_stats("Ghost")
        assert stats["member_count"] == 1
        assert stats["sessions_found"] == 0

    def test_stats_nonexistent_group(self, mgr):
        with pytest.raises(KeyError):
            mgr.group_stats("NoGroup")


# ---------------------------------------------------------------------------
# TestOutput
# ---------------------------------------------------------------------------

class TestOutput:

    def test_to_dict(self, populated_mgr):
        d = populated_mgr.to_dict()
        assert "groups" in d
        assert "total_groups" in d
        assert d["total_groups"] == 2

    def test_to_markdown_list(self, populated_mgr):
        md = populated_mgr.to_markdown()
        assert "# Session Groups" in md
        assert "Experiment A" in md
        assert "Experiment B" in md

    def test_to_markdown_empty(self, mgr):
        md = mgr.to_markdown()
        assert "No groups defined" in md

    def test_to_markdown_group_stats(self, populated_mgr):
        md = populated_mgr.to_markdown("Experiment A")
        assert "# Group: Experiment A" in md
        assert "Average Score" in md
        assert "Parameter Comparison" in md
        assert "Members" in md


# ---------------------------------------------------------------------------
# TestSessionGroupCLI
# ---------------------------------------------------------------------------

class TestSessionGroupCLI:

    def test_cli_no_command(self):
        with pytest.raises(SystemExit):
            group_main([])

    def test_cli_create(self, log_dir, capsys):
        group_main(["--log-dir", str(log_dir), "create", "Test", "--description", "hello"])
        captured = capsys.readouterr()
        assert "Created group: Test" in captured.out

    def test_cli_list(self, log_dir, capsys):
        group_main(["--log-dir", str(log_dir), "create", "G1"])
        group_main(["--log-dir", str(log_dir), "list"])
        captured = capsys.readouterr()
        assert "G1" in captured.out

    def test_cli_add_remove(self, log_dir, capsys):
        group_main(["--log-dir", str(log_dir), "create", "G1"])
        group_main(["--log-dir", str(log_dir), "add", "G1", "a.csv", "b.csv"])
        captured = capsys.readouterr()
        assert "2 members" in captured.out

        group_main(["--log-dir", str(log_dir), "remove", "G1", "a.csv"])
        captured = capsys.readouterr()
        assert "1 members" in captured.out

    def test_cli_delete(self, log_dir, capsys):
        group_main(["--log-dir", str(log_dir), "create", "ToDelete"])
        group_main(["--log-dir", str(log_dir), "delete", "ToDelete"])
        captured = capsys.readouterr()
        assert "Deleted" in captured.out

    def test_cli_show_markdown(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000")
        group_main(["--log-dir", str(log_dir), "create", "G1"])
        group_main(["--log-dir", str(log_dir), "add", "G1", "20250101_120000_DEMO_agent.csv"])
        group_main(["--log-dir", str(log_dir), "show", "G1"])
        captured = capsys.readouterr()
        assert "Group: G1" in captured.out

    def test_cli_show_json(self, log_dir, capsys):
        _create_session(log_dir, "20250101_120000")
        group_main(["--log-dir", str(log_dir), "create", "G1"])
        group_main(["--log-dir", str(log_dir), "add", "G1", "20250101_120000_DEMO_agent.csv"])
        capsys.readouterr()  # clear previous output
        group_main(["--log-dir", str(log_dir), "show", "G1", "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["member_count"] == 1
        assert "param_comparison" in data

    def test_cli_delete_nonexistent(self, log_dir, capsys):
        with pytest.raises(SystemExit):
            group_main(["--log-dir", str(log_dir), "delete", "NoGroup"])
