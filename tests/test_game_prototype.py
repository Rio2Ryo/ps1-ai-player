"""Tests for game_prototype.py."""

from __future__ import annotations

from pathlib import Path

from game_prototype import (
    ParkSimulator,
    RideAttraction,
    VisitorAgent,
    _find_table,
    _parse_markdown_tables,
    _safe_float,
)


def test_visitor_agent_update() -> None:
    """Visitor internal state updates correctly."""
    v = VisitorAgent(visitor_id=1, hunger=20.0, nausea=0.0)
    park_state = {"cleanliness": 100.0}
    events = v.update(park_state)
    # Hunger should increase
    assert v.hunger > 20.0
    # Nausea should decrease slightly
    assert v.nausea == 0.0  # Can't go below 0


def test_visitor_ride_increases_nausea() -> None:
    """Riding a high-intensity ride increases nausea."""
    v = VisitorAgent(visitor_id=1, nausea=10.0, money=100.0)
    ride = RideAttraction(intensity=80.0, ticket_price=10.0)
    v.ride(ride)
    assert v.nausea > 10.0
    assert v.money < 100.0


def test_visitor_eat_reduces_hunger() -> None:
    """Eating food reduces hunger."""
    v = VisitorAgent(visitor_id=1, hunger=80.0, money=50.0)
    events = v.eat(cost=10.0, hunger_relief=50.0)
    assert v.hunger < 80.0
    assert v.money == 40.0
    assert any("ate" in e for e in events)


def test_visitor_eat_no_money() -> None:
    """Cannot eat without money."""
    v = VisitorAgent(visitor_id=1, hunger=80.0, money=5.0)
    events = v.eat(cost=10.0)
    assert any("no_money" in e for e in events)


def test_visitor_decide_action_leave() -> None:
    """Visitor decides to leave when satisfaction is very low."""
    v = VisitorAgent(satisfaction=5.0)
    assert v.decide_action({}) == "leave"


def test_visitor_decide_action_eat() -> None:
    """Visitor decides to eat when hungry."""
    v = VisitorAgent(satisfaction=50.0, hunger=80.0, money=100.0)
    assert v.decide_action({}) == "eat"


def test_park_simulator_tick() -> None:
    """Simulation tick runs without error and advances state."""
    sim = ParkSimulator(
        visitors=[VisitorAgent(visitor_id=i) for i in range(5)],
        attractions=[RideAttraction(intensity=50)],
    )
    events = sim.tick()
    assert sim.tick_count == 1
    assert isinstance(events, list)


def test_park_simulator_run() -> None:
    """Simulation runs for specified frames."""
    sim = ParkSimulator(
        visitors=[VisitorAgent(visitor_id=i) for i in range(3)],
        attractions=[RideAttraction(intensity=40)],
    )
    state = sim.run(frames=100)
    assert state["tick"] == 100
    assert "park_money" in state
    assert "avg_satisfaction" in state


def test_park_simulator_get_state() -> None:
    """get_state returns expected keys."""
    sim = ParkSimulator(
        visitors=[VisitorAgent(visitor_id=0)],
        attractions=[RideAttraction()],
    )
    state = sim.get_state()
    for key in ["tick", "park_money", "cleanliness", "visitor_count",
                "avg_satisfaction", "avg_nausea", "avg_hunger", "attraction_count"]:
        assert key in state


# ====================================================================
# Markdown table parser
# ====================================================================

STATS_TABLE_MD = """\
## Descriptive Statistics

| Parameter | Min | Max | Mean | Std | Range |
|-----------|-----|-----|------|-----|-------|
| money | 5003.0 | 6432.0 | 6194.4 | 276.3 | 1429.0 |
| visitors | 10.0 | 100.0 | 18.8 | 23.4 | 90.0 |
| ride_intensity | 11.5 | 87.3 | 50.6 | 22.1 | 75.8 |
"""

STRATEGY_TABLE_MD = """\
## Strategy Modes

| Strategy | Trigger Condition | Focus |
|----------|-------------------|-------|
| expansion | money > 8000, visitors < 15 | Build new attractions |
| satisfaction | satisfaction < 30, nausea > 70 | Improve visitor comfort |
| cost_reduction | money < 1000 | Reduce expenses |
"""


def test_parse_markdown_tables_single() -> None:
    """Parse a single Markdown table into a list of row dicts."""
    tables = _parse_markdown_tables(STATS_TABLE_MD)
    assert len(tables) == 1
    table = tables[0]
    assert len(table) == 3
    assert table[0]["Parameter"] == "money"
    assert table[0]["Mean"] == "6194.4"
    assert table[2]["Parameter"] == "ride_intensity"
    assert table[2]["Min"] == "11.5"


def test_parse_markdown_tables_multiple() -> None:
    """Multiple tables are returned in document order."""
    combined = STATS_TABLE_MD + "\n" + STRATEGY_TABLE_MD
    tables = _parse_markdown_tables(combined)
    assert len(tables) == 2
    # First table is Descriptive Statistics
    assert "Mean" in tables[0][0]
    # Second table is Strategy Modes
    assert "Trigger Condition" in tables[1][0]


def test_parse_markdown_tables_empty() -> None:
    """No tables in content returns empty list."""
    assert _parse_markdown_tables("# Just a heading\n\nSome text.") == []


def test_parse_markdown_tables_no_data_rows() -> None:
    """Header + separator with no data rows is skipped."""
    md = "| A | B |\n|---|---|\n"
    assert _parse_markdown_tables(md) == []


def test_find_table_match() -> None:
    """_find_table returns the table matching all required headers."""
    tables = _parse_markdown_tables(STATS_TABLE_MD + "\n" + STRATEGY_TABLE_MD)
    result = _find_table(tables, "Strategy", "Trigger Condition")
    assert result is not None
    assert result[0]["Strategy"] == "expansion"


def test_find_table_case_insensitive() -> None:
    """Header matching is case-insensitive."""
    tables = _parse_markdown_tables(STATS_TABLE_MD)
    assert _find_table(tables, "parameter", "mean") is not None


def test_find_table_no_match() -> None:
    """Returns None when no table matches."""
    tables = _parse_markdown_tables(STATS_TABLE_MD)
    assert _find_table(tables, "Nonexistent", "Column") is None


def test_safe_float_valid() -> None:
    assert _safe_float("3.14") == 3.14
    assert _safe_float("42") == 42.0


def test_safe_float_invalid() -> None:
    assert _safe_float("abc") is None
    assert _safe_float("") is None
    assert _safe_float(None) is None  # type: ignore[arg-type]


# ====================================================================
# ParkSimulator.from_gdd — table-based parsing
# ====================================================================

def _write_gdd(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test_gdd.md"
    p.write_text(content)
    return p


def test_from_gdd_descriptive_stats(tmp_path: Path) -> None:
    """ride_intensity Mean from Descriptive Statistics sets Roller Coaster intensity."""
    gdd = _write_gdd(tmp_path, STATS_TABLE_MD)
    sim = ParkSimulator.from_gdd(gdd)
    rc = sim.attractions[0]
    assert rc.name == "Roller Coaster"
    assert rc.intensity == 50.6  # Mean of ride_intensity


def test_from_gdd_visitor_count_from_stats(tmp_path: Path) -> None:
    """visitors Mean from Descriptive Statistics → initial visitor count."""
    gdd = _write_gdd(tmp_path, STATS_TABLE_MD)
    sim = ParkSimulator.from_gdd(gdd)
    # int(18.8) == 18
    assert len(sim.visitors) == 18


def test_from_gdd_strategy_thresholds(tmp_path: Path) -> None:
    """Threshold conditions from Strategy Modes table set visitor thresholds."""
    combined = STATS_TABLE_MD + "\n" + STRATEGY_TABLE_MD
    gdd = _write_gdd(tmp_path, combined)
    sim = ParkSimulator.from_gdd(gdd)
    # nausea > 70 from satisfaction strategy row
    assert sim.visitors[0].nausea_vomit_threshold == 70.0


def test_from_gdd_empty_file(tmp_path: Path) -> None:
    """GDD with no tables falls back to all defaults."""
    gdd = _write_gdd(tmp_path, "# Empty GDD\n\nNo tables here.\n")
    sim = ParkSimulator.from_gdd(gdd)
    assert len(sim.visitors) == 20  # default
    assert sim.attractions[0].intensity == 80.0  # default
    assert sim.visitors[0].nausea_vomit_threshold == 80.0  # default


def test_from_gdd_real_generated_gdd(tmp_path: Path) -> None:
    """from_gdd works end-to-end on a GDD generated by gdd_generator."""
    from gdd_generator import GDDGenerator

    gen = GDDGenerator.from_csv([Path("sample_data/sample_log.csv")])
    gdd_content = gen.generate_local_gdd(game_id="DEMO")
    gdd_path = _write_gdd(tmp_path, gdd_content)
    sim = ParkSimulator.from_gdd(gdd_path)

    # ride_intensity Mean should be parsed from the stats table
    rc = sim.attractions[0]
    assert 10.0 < rc.intensity < 90.0  # reasonable range from sample data

    # Visitors derived from visitors Mean, not a random number
    assert 5 <= len(sim.visitors) <= 100

    # Nausea threshold should come from strategy table (nausea > 70)
    assert sim.visitors[0].nausea_vomit_threshold == 70.0


def test_from_gdd_interactions_table_parsed(tmp_path: Path) -> None:
    """Parameter Interactions table is found but does not crash from_gdd."""
    md = STATS_TABLE_MD + """
## Balance Design

| Source | Target | Lag | Correlation |
|--------|--------|-----|-------------|
| money | visitors | 10 | -0.829 |
| nausea | ride_intensity | 1 | 0.930 |
"""
    gdd = _write_gdd(tmp_path, md)
    sim = ParkSimulator.from_gdd(gdd)
    assert len(sim.attractions) == 3  # no crash
