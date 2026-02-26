"""Tests for game_prototype.py."""

from __future__ import annotations

from game_prototype import ParkSimulator, RideAttraction, VisitorAgent


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
