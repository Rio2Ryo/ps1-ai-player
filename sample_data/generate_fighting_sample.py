#!/usr/bin/env python3
"""Generate synthetic fighting game data for testing."""
from __future__ import annotations
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

def generate(output_path: Path | None = None, num_rows: int = 720, seed: int = 42) -> Path:
    if output_path is None:
        output_path = Path(__file__).parent / "fighting_sample_log.csv"
    random.seed(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2025, 1, 1, 12, 0, 0)
    p1_hp = 170.0
    p2_hp = 170.0
    current_round = 1
    timer = 60.0
    combo_hits = 0
    p1_wins = 0
    p2_wins = 0

    rows: list[list] = []

    for frame in range(num_rows):
        ts = base_time + timedelta(seconds=frame * 2)

        # Timer countdown
        timer -= random.uniform(0.5, 1.5)

        # Determine action
        action = "block"
        reasoning = "neutral stance"
        observations = f"Round {current_round}, Timer {timer:.0f}"

        # Round end conditions
        round_ended = False
        if p1_hp <= 0 or p2_hp <= 0 or timer <= 0:
            round_ended = True
            if p1_hp > p2_hp:
                p1_wins += 1
            elif p2_hp > p1_hp:
                p2_wins += 1

            # Match end check (best of 3)
            if p1_wins >= 2 or p2_wins >= 2:
                # New match
                p1_wins = 0
                p2_wins = 0

            # Reset round
            current_round += 1
            p1_hp = 170.0
            p2_hp = 170.0
            timer = 60.0
            combo_hits = 0
            action = "round_start"
            reasoning = "new round beginning"
        else:
            # Combo continuation
            if combo_hits > 0 and random.random() < 0.5:
                # Continue combo
                action = "combo"
                reasoning = f"continuing {combo_hits}-hit combo"
                combo_hits += 1
                damage = random.uniform(5, 15)
                p2_hp -= damage
                # Opponent may counter
                if random.random() < 0.15:
                    combo_hits = 0
                    p1_hp -= random.uniform(10, 20)
            elif p1_hp < 30:
                # Defensive when low HP
                if random.random() < 0.6:
                    action = "block"
                    reasoning = "blocking to survive"
                    # Chip damage
                    p1_hp -= random.uniform(0, 3)
                else:
                    action = "dodge"
                    reasoning = "evading at low HP"
            elif p2_hp < 30:
                # Aggressive when opponent is low
                attack_type = random.random()
                if attack_type < 0.4:
                    action = "special_move"
                    reasoning = "finishing opponent with special"
                    damage = random.uniform(15, 35)
                    p2_hp -= damage
                    if random.random() < 0.2:
                        p1_hp -= random.uniform(5, 15)
                else:
                    action = "kick"
                    reasoning = "pressuring low-HP opponent"
                    damage = random.uniform(8, 18)
                    p2_hp -= damage
            elif timer < 10:
                # Time pressure: aggressive
                action = random.choice(["punch", "kick", "special_move"])
                reasoning = "rushing before time expires"
                damage = random.uniform(8, 25)
                p2_hp -= damage
                if random.random() < 0.3:
                    p1_hp -= random.uniform(5, 15)
            else:
                # Normal combat
                move = random.random()
                if move < 0.25:
                    action = "punch"
                    reasoning = "quick jab"
                    damage = random.uniform(5, 12)
                    p2_hp -= damage
                    if random.random() < 0.3:
                        combo_hits = 1
                elif move < 0.45:
                    action = "kick"
                    reasoning = "mid kick"
                    damage = random.uniform(8, 18)
                    p2_hp -= damage
                    if random.random() < 0.2:
                        combo_hits = 1
                elif move < 0.55:
                    action = "special_move"
                    reasoning = "special attack"
                    damage = random.uniform(15, 35)
                    p2_hp -= damage
                    if random.random() < 0.3:
                        p1_hp -= random.uniform(10, 20)
                elif move < 0.65:
                    action = "throw"
                    reasoning = "throw attempt"
                    if random.random() < 0.5:
                        p2_hp -= random.uniform(15, 25)
                    else:
                        reasoning = "throw whiffed"
                elif move < 0.80:
                    action = "block"
                    reasoning = "reading opponent's attack"
                    p1_hp -= random.uniform(0, 3)  # chip damage
                else:
                    action = "dodge"
                    reasoning = "sidestepping"

                # Opponent attacks back
                if action not in ("block", "dodge") and random.random() < 0.35:
                    p1_hp -= random.uniform(5, 20)

        # Clamp values
        p1_hp = max(0.0, min(170.0, p1_hp))
        p2_hp = max(0.0, min(170.0, p2_hp))
        timer = max(0.0, timer)
        combo_hits = max(0, min(20, combo_hits))

        rows.append([
            ts.isoformat(), frame, action, reasoning, observations,
            round(p1_hp, 1), round(p2_hp, 1), current_round,
            round(timer, 1), combo_hits,
        ])

    header = [
        "timestamp", "step", "action", "reasoning", "observations",
        "p1_hp", "p2_hp", "round", "timer", "combo_hits",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"Generated {num_rows} fighting rows -> {output_path}")
    return output_path

if __name__ == "__main__":
    generate()
