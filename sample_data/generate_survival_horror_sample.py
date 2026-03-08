#!/usr/bin/env python3
"""Generate synthetic survival horror gameplay data for testing."""
from __future__ import annotations
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

def generate(output_path: Path | None = None, num_rows: int = 720, seed: int = 42) -> Path:
    if output_path is None:
        output_path = Path(__file__).parent / "survival_horror_sample_log.csv"
    random.seed(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2025, 1, 1, 12, 0, 0)
    hp = 1200.0
    ammo_handgun = 30
    ammo_shotgun = 8
    herbs = 5
    ink_ribbons = 3
    room_id = 1

    # Danger level per room zone (cycles through dungeon areas)
    room_danger_map: dict[int, float] = {}

    rows: list[list] = []

    for frame in range(num_rows):
        ts = base_time + timedelta(seconds=frame * 5)

        # Room transitions every ~15 frames
        if frame > 0 and frame % 15 == 0:
            room_id = random.randint(1, 40)

        # Compute room danger (cached per room)
        if room_id not in room_danger_map:
            room_danger_map[room_id] = random.uniform(0.0, 10.0)
        room_danger = room_danger_map[room_id]

        # Determine action based on state
        action = "explore"
        reasoning = "exploring area"

        # Enemy encounter based on room danger
        encounter = random.random() < (room_danger / 15.0)

        if encounter and room_danger > 5:
            # Dangerous encounter
            enemy_damage = random.uniform(50, 250) * (room_danger / 10.0)

            if hp < 300 and herbs > 0:
                # Critical HP: use herb first
                action = "use_herb"
                reasoning = "HP critical, healing before combat"
                herbs -= 1
                hp = min(1200.0, hp + random.uniform(200, 400))
            elif ammo_shotgun > 0 and room_danger > 7:
                # Very dangerous: use shotgun
                action = "shoot_shotgun"
                reasoning = "high danger room, using shotgun"
                ammo_shotgun -= 1
                hp -= max(0, enemy_damage * 0.3)  # less damage when using shotgun
            elif ammo_handgun > 0:
                # Normal combat: use handgun
                action = "shoot_handgun"
                reasoning = "engaging enemy with handgun"
                ammo_handgun -= random.randint(1, 3)
                hp -= max(0, enemy_damage * 0.5)
            elif hp > 400:
                # No ammo but enough HP: dodge
                action = "dodge"
                reasoning = "no ammo, dodging enemy"
                hp -= max(0, enemy_damage * 0.4)
            else:
                # Low HP, no ammo: run
                action = "run"
                reasoning = "low resources, fleeing"
                hp -= max(0, enemy_damage * 0.2)
                room_id = random.randint(1, 40)
        elif encounter:
            # Mild encounter
            mild_damage = random.uniform(20, 80)
            if ammo_handgun > 0 and random.random() < 0.7:
                action = "shoot_handgun"
                reasoning = "mild threat, quick handgun shot"
                ammo_handgun -= 1
                hp -= max(0, mild_damage * 0.3)
            else:
                action = "dodge"
                reasoning = "avoiding minor threat"
                hp -= max(0, mild_damage * 0.5)
        else:
            # No encounter: exploration actions
            if hp < 600 and herbs > 0 and random.random() < 0.3:
                action = "use_herb"
                reasoning = "healing during safe moment"
                herbs -= 1
                hp = min(1200.0, hp + random.uniform(200, 400))
            elif ink_ribbons > 0 and frame > 0 and frame % 80 == 0:
                action = "save_game"
                reasoning = "saving progress at typewriter"
                ink_ribbons -= 1
            elif random.random() < 0.25:
                # Pick up items
                action = "pick_up_item"
                reasoning = "found item in room"
                pickup_type = random.random()
                if pickup_type < 0.3:
                    ammo_handgun += random.randint(5, 15)
                elif pickup_type < 0.5:
                    ammo_shotgun += random.randint(2, 5)
                elif pickup_type < 0.7:
                    herbs += 1
                elif pickup_type < 0.85:
                    ink_ribbons += 1
            else:
                action = "explore"
                reasoning = "searching current room"

        # Clamp values
        hp = max(1.0, min(1200.0, hp))
        ammo_handgun = max(0, ammo_handgun)
        ammo_shotgun = max(0, ammo_shotgun)
        herbs = max(0, herbs)
        ink_ribbons = max(0, ink_ribbons)

        observations = f"Room {room_id}, danger level {room_danger:.1f}"

        rows.append([
            ts.isoformat(), frame, action, reasoning, observations,
            round(hp, 1), ammo_handgun, ammo_shotgun, herbs,
            ink_ribbons, round(room_danger, 1),
        ])

    header = [
        "timestamp", "step", "action", "reasoning", "observations",
        "hp", "ammo_handgun", "ammo_shotgun", "herbs",
        "ink_ribbons", "room_danger",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"Generated {num_rows} survival horror rows -> {output_path}")
    return output_path

if __name__ == "__main__":
    generate()
