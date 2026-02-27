#!/usr/bin/env python3
"""Generate 1 hour of synthetic theme park gameplay data for testing.

Produces a CSV with correlated parameters that mimic real PS1 game behavior:
  - ride_intensity oscillates (player building/upgrading rides)
  - nausea follows ride_intensity with ~5-step lag
  - satisfaction degrades when nausea is high (lag ~10 steps)
  - hunger increases steadily, resets on food purchase
  - money tracks income from visitors minus expenses
  - visitors fluctuate based on satisfaction
  - action column records what the player did each tick

Output: sample_data/sample_log.csv (720 rows = 1 hour at 5s intervals)
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path


def generate(
    output_path: Path | None = None,
    num_rows: int = 720,
    seed: int = 42,
) -> Path:
    """Generate correlated gameplay data and write to CSV.

    Args:
        output_path: Output CSV path. Defaults to sample_data/sample_log.csv.
        num_rows: Number of data rows (720 = 1 hour at 5s intervals).
        seed: Random seed for reproducibility.

    Returns:
        Path to the generated CSV.
    """
    if output_path is None:
        output_path = Path(__file__).parent / "sample_log.csv"

    random.seed(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # State variables
    base_time = datetime(2025, 1, 1, 12, 0, 0)
    money = 5000.0
    satisfaction = 70.0
    nausea = 0.0
    hunger = 15.0
    visitors = 50

    # History buffers for lag effects
    ride_intensity_history: list[float] = []
    nausea_history: list[float] = []

    rows: list[list[str | int | float]] = []

    for frame in range(num_rows):
        ts = base_time + timedelta(seconds=frame * 5)

        # --- ride_intensity: sinusoidal + noise (player cycles through building) ---
        ride_intensity = 50.0 + 30.0 * math.sin(frame * 0.025) + random.gauss(0, 4)
        ride_intensity = max(0.0, min(100.0, ride_intensity))
        ride_intensity_history.append(ride_intensity)

        # --- nausea: follows ride_intensity with lag of ~5 steps ---
        lag_ri = ride_intensity_history[max(0, frame - 5)]
        nausea_target = lag_ri * 0.55
        nausea = nausea + 0.3 * (nausea_target - nausea) + random.gauss(0, 2)
        nausea = max(0.0, min(100.0, nausea))
        nausea_history.append(nausea)

        # --- satisfaction: degrades when lagged nausea is high ---
        lag_nausea = nausea_history[max(0, frame - 10)]
        nausea_penalty = -0.12 * max(0.0, lag_nausea - 35.0)
        # Visitors being happy adds slow recovery
        recovery = 0.05 if nausea < 30 else 0.0
        satisfaction = satisfaction + nausea_penalty + recovery + random.gauss(0, 0.8)
        satisfaction = max(5.0, min(95.0, satisfaction))

        # --- hunger: ramps up, resets when food is purchased ---
        hunger += 0.4 + random.gauss(0, 0.2)
        food_purchased = False
        if hunger > 75.0:
            hunger = 10.0 + random.gauss(0, 3)
            food_purchased = True
        hunger = max(0.0, min(100.0, hunger))

        # --- visitors: influenced by satisfaction ---
        visitor_drift = 0.1 * (satisfaction - 50.0) + random.gauss(0, 2)
        visitors = max(10, min(100, int(visitors + visitor_drift)))

        # --- money: income from visitors, costs from rides & food ---
        income = visitors * random.uniform(0.15, 0.25)
        ride_cost = ride_intensity * 0.03
        food_cost = 12.0 if food_purchased else 0.0
        money = money + income - ride_cost - food_cost + random.gauss(0, 5)

        # --- action: what the player did this tick ---
        if food_purchased:
            action = "buy_food"
        elif ride_intensity > 70:
            action = random.choice(["build_ride", "upgrade_ride", "adjust_intensity"])
        elif satisfaction < 30:
            action = random.choice(["lower_price", "clean_park", "add_bench"])
        elif nausea > 60:
            action = random.choice(["reduce_intensity", "add_first_aid"])
        elif money > 7000:
            action = random.choice(["build_ride", "build_shop", "expand_park"])
        else:
            action = random.choice([
                "observe", "observe", "observe",  # most common
                "adjust_intensity", "set_price", "hire_staff",
                "check_finances", "inspect_ride",
            ])

        rows.append([
            ts.isoformat(),
            frame,
            round(money, 0),
            visitors,
            round(satisfaction, 1),
            round(nausea, 1),
            round(hunger, 1),
            round(ride_intensity, 1),
            action,
        ])

    # Write CSV
    header = ["timestamp", "frame", "money", "visitors", "satisfaction",
              "nausea", "hunger", "ride_intensity", "action"]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"Generated {num_rows} rows ({num_rows * 5 / 3600:.1f} hours) -> {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate sample gameplay CSV data")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output CSV path (default: sample_data/sample_log.csv)",
    )
    parser.add_argument(
        "--rows", "-n",
        type=int,
        default=720,
        help="Number of rows to generate (default: 720 = 1 hour)",
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    args = parser.parse_args()
    generate(output_path=args.output, num_rows=args.rows, seed=args.seed)
