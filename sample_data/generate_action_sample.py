#!/usr/bin/env python3
"""Generate synthetic action/platformer gameplay data for testing."""
from __future__ import annotations
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

def generate(output_path: Path | None = None, num_rows: int = 720, seed: int = 42) -> Path:
    if output_path is None:
        output_path = Path(__file__).parent / "action_sample_log.csv"
    random.seed(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2025, 1, 1, 12, 0, 0)
    lives = 3
    hp = 100.0
    score = 0
    time_remaining = 300.0
    speed = 5.0
    enemies_defeated = 0

    rows: list[list] = []

    for frame in range(num_rows):
        ts = base_time + timedelta(seconds=frame * 5)

        # Time counts down
        time_remaining -= random.uniform(3.0, 7.0) * (speed / 5.0)

        # Level completion when time hits a cycle (every ~60 frames)
        if time_remaining <= 0 or (frame > 0 and frame % 65 == 0):
            score += 1000
            time_remaining = 300.0
            hp = 100.0
            action = "checkpoint"
        else:
            # Speed: influenced by lives and time pressure
            target_speed = 5.0
            if time_remaining < 60:
                target_speed = 8.0  # rush when time is low
            if lives <= 1:
                target_speed = 3.0  # cautious when low lives
            speed = speed + 0.3 * (target_speed - speed) + random.gauss(0, 0.5)
            speed = max(1.0, min(10.0, speed))

            # Encounter probability increases with speed
            encounter_chance = 0.3 + speed * 0.04

            if random.random() < encounter_chance:
                # Combat encounter
                if random.random() < 0.6:
                    # Successfully defeat enemy
                    action = "defeat_enemy"
                    enemies_defeated += 1
                    score += int(random.uniform(100, 500))
                else:
                    # Take damage
                    damage = random.uniform(10, 30) + speed * 2  # more damage at high speed
                    hp -= damage
                    action = "take_damage"

                    if hp <= 0:
                        lives -= 1
                        action = "die"
                        if lives > 0:
                            hp = 100.0
                            time_remaining = min(300.0, time_remaining + 30)
                        else:
                            # Game over: reset
                            lives = 3
                            hp = 100.0
                            score = max(0, score - 500)
                            time_remaining = 300.0
            elif random.random() < 0.2:
                action = "collect_item"
                score += 50
                if random.random() < 0.3:
                    hp = min(100.0, hp + 20)
            elif random.random() < 0.3:
                action = "jump"
            elif speed > 6:
                action = "run"
            else:
                action = random.choice(["dodge", "jump", "run"])

        hp = max(0.0, min(100.0, hp))
        speed = max(1.0, min(10.0, speed))

        rows.append([
            ts.isoformat(), frame,
            lives, round(hp, 1), score,
            round(time_remaining, 1), round(speed, 1),
            enemies_defeated, action,
        ])

    header = ["timestamp", "frame", "lives", "hp", "score", "time_remaining", "speed", "enemies_defeated", "action"]
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"Generated {num_rows} action rows -> {output_path}")
    return output_path

if __name__ == "__main__":
    generate()
