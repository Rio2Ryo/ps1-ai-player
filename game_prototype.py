#!/usr/bin/env python3
"""Game prototype implementing extracted mechanics as a Python simulation.

Provides VisitorAgent, RideAttraction, and ParkSimulator classes that
model the causal chains discovered from PS1 gameplay data analysis.
Thresholds can be loaded from GDD files via from_gdd() methods.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_markdown_tables(content: str) -> list[list[dict[str, str]]]:
    """Parse all Markdown tables in *content*.

    Each table is returned as a list of row dicts whose keys are the
    column headers (whitespace-stripped).  Separator rows (``|---|---|``)
    are consumed and never returned.

    Returns:
        List of tables.  Each table is a ``list[dict[str, str]]``.
    """
    tables: list[list[dict[str, str]]] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # A table header row starts and ends with ``|``.
        if line.startswith("|") and line.endswith("|") and "|" in line[1:-1]:
            # Next line must be the separator (e.g. |---|---|)
            if i + 1 < len(lines) and re.match(
                r"^\|[\s\-:|]+\|$", lines[i + 1].strip()
            ):
                headers = [h.strip() for h in line.strip("|").split("|")]
                i += 2  # skip header + separator
                rows: list[dict[str, str]] = []
                while i < len(lines):
                    row_line = lines[i].strip()
                    if not row_line.startswith("|"):
                        break
                    cells = [c.strip() for c in row_line.strip("|").split("|")]
                    row: dict[str, str] = {}
                    for j, hdr in enumerate(headers):
                        row[hdr] = cells[j] if j < len(cells) else ""
                    rows.append(row)
                    i += 1
                if rows:
                    tables.append(rows)
                continue
        i += 1
    return tables


def _find_table(
    tables: list[list[dict[str, str]]],
    *required_headers: str,
) -> list[dict[str, str]] | None:
    """Return the first table whose rows contain all *required_headers*.

    Header comparison is case-insensitive.
    """
    needed = {h.lower() for h in required_headers}
    for table in tables:
        if table:
            available = {k.lower() for k in table[0]}
            if needed <= available:
                return table
    return None


def _safe_float(value: str) -> float | None:
    """Try to parse *value* as a float, return ``None`` on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


@dataclass
class VisitorAgent:
    """A park visitor with internal state attributes."""

    visitor_id: int = 0
    satisfaction: float = 70.0
    nausea: float = 0.0
    hunger: float = 20.0
    money: float = 100.0
    preferred_rides: list[str] = field(default_factory=list)

    # Thresholds (can be overridden from GDD data)
    nausea_vomit_threshold: float = 80.0
    hunger_seek_food_threshold: float = 70.0
    vomit_satisfaction_penalty: float = 20.0
    hunger_satisfaction_penalty: float = 5.0

    def update(self, park_state: dict[str, Any]) -> list[str]:
        """Update visitor state for one tick.

        Args:
            park_state: Current park state dict.

        Returns:
            List of events that occurred.
        """
        events: list[str] = []

        # Natural hunger increase
        self.hunger = min(100.0, self.hunger + 0.2)

        # Nausea decreases slowly over time
        self.nausea = max(0.0, self.nausea - 0.1)

        # Vomit check
        if self.nausea > self.nausea_vomit_threshold:
            events.append(f"visitor_{self.visitor_id}_vomit")
            self.satisfaction = max(0.0, self.satisfaction - self.vomit_satisfaction_penalty)
            self.nausea *= 0.5  # Relief after vomiting
            # Reduce cleanliness in park
            park_state["cleanliness"] = max(
                0.0, park_state.get("cleanliness", 100.0) - 10.0
            )

        # Hunger check
        if self.hunger > self.hunger_seek_food_threshold:
            events.append(f"visitor_{self.visitor_id}_seek_food")
            self.satisfaction = max(
                0.0, self.satisfaction - self.hunger_satisfaction_penalty
            )

        # Cleanliness affects satisfaction
        cleanliness = park_state.get("cleanliness", 100.0)
        if cleanliness < 50:
            self.satisfaction = max(0.0, self.satisfaction - 0.5)

        return events

    def ride(self, attraction: RideAttraction) -> list[str]:
        """Visitor rides an attraction.

        Args:
            attraction: The ride to experience.

        Returns:
            List of events.
        """
        events: list[str] = []

        nausea_delta = attraction.get_nausea_delta(self)
        self.nausea = min(100.0, self.nausea + nausea_delta)
        self.satisfaction = min(
            100.0, self.satisfaction + attraction.satisfaction_boost
        )
        self.money -= attraction.ticket_price

        events.append(
            f"visitor_{self.visitor_id}_rode_{attraction.name}"
        )

        return events

    def eat(self, cost: float = 10.0, hunger_relief: float = 50.0) -> list[str]:
        """Visitor eats food.

        Args:
            cost: Food cost.
            hunger_relief: How much hunger decreases.

        Returns:
            List of events.
        """
        if self.money < cost:
            return [f"visitor_{self.visitor_id}_no_money_for_food"]

        self.money -= cost
        self.hunger = max(0.0, self.hunger - hunger_relief)
        self.satisfaction = min(100.0, self.satisfaction + 5.0)
        return [f"visitor_{self.visitor_id}_ate"]

    def decide_action(self, park_state: dict[str, Any]) -> str:
        """Decide the next action based on current state.

        Args:
            park_state: Current park state.

        Returns:
            Action string: 'ride', 'eat', 'wander', or 'leave'.
        """
        if self.satisfaction < 10:
            return "leave"

        if self.hunger > self.hunger_seek_food_threshold:
            return "eat"

        if self.nausea > 60:
            return "wander"  # Rest

        if self.money < 5:
            return "leave"

        return "ride"

    @classmethod
    def from_gdd(cls, gdd_params: dict[str, Any], visitor_id: int = 0) -> VisitorAgent:
        """Create a VisitorAgent with thresholds from GDD data.

        Args:
            gdd_params: Dict of parameter overrides.
            visitor_id: Visitor ID.

        Returns:
            Configured VisitorAgent.
        """
        return cls(
            visitor_id=visitor_id,
            nausea_vomit_threshold=gdd_params.get("nausea_vomit_threshold", 80.0),
            hunger_seek_food_threshold=gdd_params.get("hunger_seek_food_threshold", 70.0),
            vomit_satisfaction_penalty=gdd_params.get("vomit_satisfaction_penalty", 20.0),
            hunger_satisfaction_penalty=gdd_params.get("hunger_satisfaction_penalty", 5.0),
        )


@dataclass
class RideAttraction:
    """A ride attraction in the park."""

    name: str = "Roller Coaster"
    intensity: float = 50.0  # 0-100
    capacity: int = 20
    maintenance_cost: float = 5.0  # per tick
    satisfaction_boost: float = 15.0
    ticket_price: float = 10.0
    current_riders: int = 0

    def get_nausea_delta(self, visitor: VisitorAgent) -> float:
        """Calculate nausea increase from this ride for a visitor.

        Args:
            visitor: The visitor riding.

        Returns:
            Nausea increase value.
        """
        base = self.intensity * 0.1
        # More susceptible visitors get more nauseous
        susceptibility = 1.0 + (visitor.nausea / 100.0) * 0.5
        return base * susceptibility

    @classmethod
    def from_gdd(cls, gdd_params: dict[str, Any]) -> RideAttraction:
        """Create a RideAttraction with parameters from GDD data.

        Args:
            gdd_params: Dict of parameter overrides.

        Returns:
            Configured RideAttraction.
        """
        return cls(
            name=gdd_params.get("name", "Ride"),
            intensity=gdd_params.get("intensity", 50.0),
            capacity=gdd_params.get("capacity", 20),
            maintenance_cost=gdd_params.get("maintenance_cost", 5.0),
            satisfaction_boost=gdd_params.get("satisfaction_boost", 15.0),
            ticket_price=gdd_params.get("ticket_price", 10.0),
        )


@dataclass
class ParkSimulator:
    """Theme park simulation engine."""

    visitors: list[VisitorAgent] = field(default_factory=list)
    attractions: list[RideAttraction] = field(default_factory=list)
    park_money: float = 10000.0
    cleanliness: float = 100.0
    tick_count: int = 0
    event_log: list[dict[str, Any]] = field(default_factory=list)

    def get_state(self) -> dict[str, Any]:
        """Get the current park state.

        Returns:
            Dict with all park state values.
        """
        avg_satisfaction = 0.0
        avg_nausea = 0.0
        avg_hunger = 0.0
        if self.visitors:
            avg_satisfaction = sum(v.satisfaction for v in self.visitors) / len(
                self.visitors
            )
            avg_nausea = sum(v.nausea for v in self.visitors) / len(self.visitors)
            avg_hunger = sum(v.hunger for v in self.visitors) / len(self.visitors)

        return {
            "tick": self.tick_count,
            "park_money": round(self.park_money, 2),
            "cleanliness": round(self.cleanliness, 2),
            "visitor_count": len(self.visitors),
            "avg_satisfaction": round(avg_satisfaction, 2),
            "avg_nausea": round(avg_nausea, 2),
            "avg_hunger": round(avg_hunger, 2),
            "attraction_count": len(self.attractions),
        }

    def tick(self) -> list[str]:
        """Advance the simulation by one frame/tick.

        Returns:
            List of events that occurred.
        """
        self.tick_count += 1
        all_events: list[str] = []
        park_state = self.get_state()
        park_state["cleanliness"] = self.cleanliness

        # Maintenance costs
        for attraction in self.attractions:
            self.park_money -= attraction.maintenance_cost

        # Slow cleanliness recovery
        self.cleanliness = min(100.0, self.cleanliness + 0.05)

        # Update each visitor
        visitors_to_remove: list[VisitorAgent] = []

        for visitor in self.visitors:
            # Update internal state
            events = visitor.update(park_state)
            all_events.extend(events)

            # Decide action
            action = visitor.decide_action(park_state)

            if action == "ride" and self.attractions:
                ride = random.choice(self.attractions)
                if ride.current_riders < ride.capacity and visitor.money >= ride.ticket_price:
                    ride_events = visitor.ride(ride)
                    all_events.extend(ride_events)
                    self.park_money += ride.ticket_price
                    ride.current_riders += 1

            elif action == "eat":
                eat_events = visitor.eat()
                all_events.extend(eat_events)
                if eat_events and "ate" in eat_events[0]:
                    self.park_money += 10.0  # Food revenue

            elif action == "leave":
                visitors_to_remove.append(visitor)
                all_events.append(f"visitor_{visitor.visitor_id}_left")

        # Remove departed visitors
        for v in visitors_to_remove:
            self.visitors.remove(v)

        # Reset ride counters
        for attraction in self.attractions:
            attraction.current_riders = 0

        # Update cleanliness from park_state (may have been modified by vomit events)
        self.cleanliness = park_state.get("cleanliness", self.cleanliness)

        # Occasionally spawn new visitors
        if self.tick_count % 10 == 0 and len(self.visitors) < 100:
            new_visitor = VisitorAgent(visitor_id=self.tick_count)
            self.visitors.append(new_visitor)
            all_events.append(f"visitor_{new_visitor.visitor_id}_arrived")

        # Log events
        if all_events:
            self.event_log.append(
                {"tick": self.tick_count, "events": all_events}
            )

        return all_events

    def run(
        self,
        frames: int = 3600,
        verbose: bool = False,
        csv_path: Path | None = None,
    ) -> dict[str, Any]:
        """Run the simulation for a number of frames.

        Args:
            frames: Number of ticks to simulate.
            verbose: Print state every 60 ticks.
            csv_path: If set, export per-tick state to this CSV file.

        Returns:
            Final state dict.
        """
        print(f"Running simulation for {frames} frames...")
        print(f"Starting state: {self.get_state()}")

        csv_file = None
        csv_writer = None
        if csv_path:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_file = open(csv_path, "w", newline="")
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow([
                "tick", "park_money", "cleanliness", "visitor_count",
                "avg_satisfaction", "avg_nausea", "avg_hunger",
                "attraction_count", "events",
            ])

        try:
            for _ in range(frames):
                events = self.tick()
                state = self.get_state()

                if csv_writer:
                    csv_writer.writerow([
                        state["tick"],
                        state["park_money"],
                        state["cleanliness"],
                        state["visitor_count"],
                        state["avg_satisfaction"],
                        state["avg_nausea"],
                        state["avg_hunger"],
                        state["attraction_count"],
                        ";".join(events) if events else "",
                    ])

                if verbose and self.tick_count % 60 == 0:
                    print(
                        f"[{state['tick']}] "
                        f"Visitors={state['visitor_count']} "
                        f"Sat={state['avg_satisfaction']:.1f} "
                        f"Nausea={state['avg_nausea']:.1f} "
                        f"Money={state['park_money']:.0f} "
                        f"Clean={state['cleanliness']:.1f}"
                    )
        finally:
            if csv_file:
                csv_file.close()
                print(f"Simulation CSV saved: {csv_path}")

        final = self.get_state()
        print(f"\nFinal state: {final}")
        print(f"Total events: {sum(len(e['events']) for e in self.event_log)}")
        return final

    @classmethod
    def from_gdd(cls, gdd_path: Path) -> ParkSimulator:
        """Create a ParkSimulator with parameters extracted from a GDD file.

        Parses Markdown tables in the GDD for parameter statistics and
        strategy thresholds.  Three tables are recognised by their column
        headers (case-insensitive):

        * **Descriptive Statistics** (``Parameter | Min | Max | Mean | …``):
          ``Mean`` values populate the parameter map.
        * **Parameter Interactions** (``Source | Target | Lag | Correlation``):
          stored for informational purposes; not yet wired into the sim.
        * **Strategy Modes** (``Strategy | Trigger Condition | …``):
          ``param > N`` / ``param < N`` patterns inside *Trigger Condition*
          cells are parsed as threshold overrides.

        Args:
            gdd_path: Path to GDD markdown file.

        Returns:
            Configured ParkSimulator.
        """
        content = gdd_path.read_text()
        tables = _parse_markdown_tables(content)
        params: dict[str, float] = {}

        # --- 1. Descriptive Statistics → parameter Mean values -----------
        stats_table = _find_table(tables, "Parameter", "Mean")
        if stats_table:
            for row in stats_table:
                name = row.get("Parameter", "").strip().lower()
                mean = _safe_float(row.get("Mean", ""))
                if name and mean is not None:
                    params[name] = mean

        # --- 2. Strategy Modes → threshold conditions --------------------
        strategy_table = _find_table(tables, "Strategy", "Trigger Condition")
        if strategy_table:
            for row in strategy_table:
                condition = row.get("Trigger Condition", "")
                for m in re.finditer(
                    r"(\w+)\s*[<>]=?\s*([\d.]+)", condition
                ):
                    pname = m.group(1).lower()
                    pval = _safe_float(m.group(2))
                    if pval is not None:
                        key = f"{pname}_threshold"
                        # Keep the first occurrence per parameter.
                        if key not in params:
                            params[key] = pval

        # --- 3. Parameter Interactions (informational) -------------------
        interactions_table = _find_table(
            tables, "Source", "Target", "Lag", "Correlation"
        )
        # Reserved for future use; correlations are not yet wired into
        # the simulation engine.

        # --- Build the simulation ----------------------------------------
        sim = cls()

        # Attractions — use ride_intensity mean from stats if available.
        sim.attractions = [
            RideAttraction(
                name="Roller Coaster",
                intensity=params.get("ride_intensity", 80.0),
                satisfaction_boost=params.get("satisfaction_boost", 15.0),
            ),
            RideAttraction(
                name="Ferris Wheel",
                intensity=30.0,
                satisfaction_boost=10.0,
            ),
            RideAttraction(
                name="Haunted House",
                intensity=60.0,
                satisfaction_boost=12.0,
            ),
        ]

        # Visitor thresholds — strategy-table thresholds take precedence
        # (e.g.  ``nausea > 70`` in the satisfaction strategy row), with
        # explicit param keys as first-choice overrides.
        visitor_params = {
            "nausea_vomit_threshold": params.get(
                "nausea_vomit_threshold",
                params.get("nausea_threshold", 80.0),
            ),
            "hunger_seek_food_threshold": params.get(
                "hunger_seek_food_threshold",
                params.get("hunger_threshold", 70.0),
            ),
            "vomit_satisfaction_penalty": params.get(
                "vomit_satisfaction_penalty", 20.0
            ),
        }

        # Initial visitor count — prefer explicit key, then the Mean
        # from Descriptive Statistics, then default 20.
        initial_visitors = int(
            params.get("initial_visitors", params.get("visitors", 20))
        )
        for i in range(initial_visitors):
            sim.visitors.append(VisitorAgent.from_gdd(visitor_params, visitor_id=i))

        print(
            f"Loaded from GDD: {len(sim.attractions)} attractions, "
            f"{len(sim.visitors)} visitors"
        )
        return sim


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Theme Park Simulation Prototype")
    parser.add_argument(
        "--frames",
        type=int,
        default=3600,
        help="Number of frames to simulate (default: 3600)",
    )
    parser.add_argument(
        "--from-gdd",
        type=Path,
        default=None,
        help="Load parameters from a GDD markdown file",
    )
    parser.add_argument(
        "--visitors",
        type=int,
        default=20,
        help="Initial visitor count (default: 20)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print state every 60 ticks",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=None,
        help="Export per-tick simulation state to CSV file",
    )
    args = parser.parse_args()

    if args.from_gdd:
        sim = ParkSimulator.from_gdd(args.from_gdd)
    else:
        # Default setup
        sim = ParkSimulator(
            visitors=[VisitorAgent(visitor_id=i) for i in range(args.visitors)],
            attractions=[
                RideAttraction(name="Roller Coaster", intensity=80, satisfaction_boost=15),
                RideAttraction(name="Ferris Wheel", intensity=30, satisfaction_boost=10),
                RideAttraction(name="Haunted House", intensity=60, satisfaction_boost=12),
                RideAttraction(name="Bumper Cars", intensity=40, satisfaction_boost=8),
            ],
        )

    sim.run(frames=args.frames, verbose=args.verbose, csv_path=args.csv_output)


if __name__ == "__main__":
    main()
