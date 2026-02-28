#!/usr/bin/env python3
"""Generate synthetic RPG dungeon crawl data for testing."""
from __future__ import annotations
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

def generate(output_path: Path | None = None, num_rows: int = 720, seed: int = 42) -> Path:
    if output_path is None:
        output_path = Path(__file__).parent / "rpg_sample_log.csv"
    random.seed(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2025, 1, 1, 12, 0, 0)
    hp = 100.0
    mp = 50.0
    gold = 200.0
    level = 1
    exp = 0.0
    # Level thresholds
    level_thresholds = [100, 250, 500, 800, 1200, 1800, 2600, 3600, 5000, 7000]

    enemy_strength_history: list[float] = []
    rows: list[list] = []

    for frame in range(num_rows):
        ts = base_time + timedelta(seconds=frame * 5)

        # enemy_strength: oscillates like dungeon depth, range 10-100
        enemy_strength = 40.0 + 35.0 * math.sin(frame * 0.015) + 15.0 * math.sin(frame * 0.004) + random.gauss(0, 5)
        enemy_strength = max(10.0, min(100.0, enemy_strength))
        enemy_strength_history.append(enemy_strength)

        # Combat every ~3 ticks
        in_combat = (frame % 3 != 2)

        # Lagged enemy strength for damage (3 step lag)
        lag_es = enemy_strength_history[max(0, frame - 3)]

        # Determine action and apply effects
        action = "explore"

        if in_combat:
            damage = lag_es * random.uniform(0.08, 0.2) + random.gauss(0, 2)

            if hp < 30:
                # Low HP: use potion
                if gold >= 30:
                    action = "use_potion"
                    hp = min(100.0, hp + 40 + random.gauss(0, 3))
                    gold -= 30
                else:
                    action = "defend"
                    damage *= 0.3  # reduced damage when defending
                    hp -= max(0, damage)
            elif mp > 8 and enemy_strength > 50:
                # Strong enemy + have MP: use magic
                action = "magic_attack"
                mp -= random.uniform(5, 8)
                exp_gain = enemy_strength * random.uniform(0.3, 0.5)
                exp += exp_gain
                gold += enemy_strength * random.uniform(0.2, 0.5)
                hp -= max(0, damage * 0.6)  # less damage taken when attacking magically
            elif mp < 10 and mp > 0:
                # Low MP: use ether if available
                if random.random() < 0.3:
                    action = "use_ether"
                    mp = min(50.0, mp + 20 + random.gauss(0, 2))
                else:
                    action = "attack"
                    exp_gain = enemy_strength * random.uniform(0.15, 0.35)
                    exp += exp_gain
                    gold += enemy_strength * random.uniform(0.2, 0.4)
                    hp -= max(0, damage)
            else:
                if enemy_strength > 80 and hp < 50 and random.random() < 0.2:
                    action = "flee"
                    hp -= max(0, damage * 0.3)
                else:
                    action = "attack"
                    exp_gain = enemy_strength * random.uniform(0.15, 0.35)
                    exp += exp_gain
                    gold += enemy_strength * random.uniform(0.2, 0.4)
                    hp -= max(0, damage)
        else:
            # Out of combat tick
            mp = min(50.0, mp + 0.5 + random.gauss(0, 0.2))

            if gold > 500 and random.random() < 0.15:
                action = "buy_equipment"
                gold -= 200
            elif hp < 60 and random.random() < 0.3:
                action = "rest"
                hp = min(100.0, hp + 15 + random.gauss(0, 2))
            else:
                action = "explore"

        # Level up check
        next_level_idx = level - 1
        if next_level_idx < len(level_thresholds) and exp >= level_thresholds[next_level_idx]:
            level += 1
            hp = 100.0
            mp = 50.0
            action = "level_up"

        # Clamp values
        hp = max(1.0, min(100.0, hp))
        mp = max(0.0, min(50.0, mp))
        gold = max(0.0, gold)

        rows.append([
            ts.isoformat(), frame,
            round(hp, 1), round(mp, 1), round(gold, 0),
            level, round(exp, 0), round(enemy_strength, 1),
            action,
        ])

    header = ["timestamp", "frame", "hp", "mp", "gold", "level", "exp", "enemy_strength", "action"]
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"Generated {num_rows} RPG rows -> {output_path}")
    return output_path

if __name__ == "__main__":
    generate()
