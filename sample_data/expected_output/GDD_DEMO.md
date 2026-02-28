# Game Design Document: DEMO

Generated: 2026-02-28T10:05:15.677170
Data samples: 720
Causal chains: 5
Mode: Local analysis (no LLM)

---

## Overview

This GDD was auto-generated from gameplay data analysis of a PS1 game.
The analysis tracked 6 parameters: money, visitors, satisfaction, nausea, hunger, ride_intensity.

## Parameter Definitions

| Parameter | Role |
|-----------|------|
| money | Primary resource / economy indicator |
| visitors | Population / demand metric |
| satisfaction | Quality of experience indicator |
| nausea | Negative status effect |
| hunger | Time-dependent need |
| ride_intensity | Intensity / risk factor |

## Descriptive Statistics

| Parameter | Min | Max | Mean | Std | Range |
|-----------|-----|-----|------|-----|-------|
| money | 5003.0 | 6432.0 | 6194.4 | 276.3 | 1429.0 |
| visitors | 10.0 | 100.0 | 18.8 | 23.4 | 90.0 |
| satisfaction | 5.0 | 74.7 | 16.2 | 17.6 | 69.7 |
| nausea | 3.9 | 49.2 | 27.8 | 12.5 | 45.3 |
| hunger | 8.6 | 75.0 | 41.8 | 18.5 | 66.4 |
| ride_intensity | 11.5 | 87.3 | 50.6 | 22.1 | 75.8 |

### Parameter Behavior Classification

- **money**: Equilibrium metric (stable)
- **visitors**: Volatile parameter (high std/mean ratio)
- **satisfaction**: Volatile parameter (high std/mean ratio)
- **nausea**: Cyclical status effect (oscillating)
- **hunger**: Cyclical status effect (oscillating)
- **ride_intensity**: Cyclical status effect (oscillating)

## Correlation Matrix

| Pair | r | Strength | Direction |
|------|---|----------|-----------|
| money ↔ visitors | -0.731 | Strong | Negative |
| money ↔ satisfaction | -0.887 | Strong | Negative |
| money ↔ nausea | -0.234 | Negligible | Negative |
| money ↔ hunger | 0.247 | Negligible | Positive |
| money ↔ ride_intensity | -0.277 | Negligible | Negative |
| visitors ↔ satisfaction | 0.885 | Strong | Positive |
| visitors ↔ nausea | 0.365 | Weak | Positive |
| visitors ↔ hunger | -0.129 | Negligible | Negative |
| visitors ↔ ride_intensity | 0.393 | Weak | Positive |
| satisfaction ↔ nausea | 0.183 | Negligible | Positive |
| satisfaction ↔ hunger | -0.204 | Negligible | Negative |
| satisfaction ↔ ride_intensity | 0.255 | Negligible | Positive |
| nausea ↔ hunger | 0.240 | Negligible | Positive |
| nausea ↔ ride_intensity | 0.935 | Very strong | Positive |
| hunger ↔ ride_intensity | 0.194 | Negligible | Positive |

## Data Quality Report

- **Total samples:** 720
- **Time range:** 2025-01-01 12:00:00 → 2025-01-01 12:59:55
- **Duration:** 0 days 00:59:55

### Missing Values

No missing values detected.


### Outliers (IQR Method)

- **money**: 67 outliers
- **visitors**: 107 outliers
- **satisfaction**: 87 outliers

## Event / Action Analysis

Total recorded actions: **720**

### Top Actions

| Rank | Action | Count | Frequency |
|------|--------|-------|-----------|
| 1 | add_bench | 174 | 24.2% |
| 2 | lower_price | 165 | 22.9% |
| 3 | clean_park | 152 | 21.1% |
| 4 | adjust_intensity | 79 | 11.0% |
| 5 | upgrade_ride | 67 | 9.3% |
| 6 | build_ride | 56 | 7.8% |
| 7 | observe | 14 | 1.9% |
| 8 | buy_food | 4 | 0.6% |
| 9 | set_price | 3 | 0.4% |
| 10 | check_finances | 2 | 0.3% |

## Core Mechanics

The following mechanics were extracted from gameplay data analysis:

### Mechanic 1: money change
**Confidence:** 59%

**Effects:**

- **visitors**: -0.59/step (delay: 10 frames)
- **satisfaction**: -0.90/step (delay: 10 frames)
- **nausea**: -0.13/step (delay: 10 frames)
- **ride_intensity**: -0.38/step (delay: 10 frames)

### Mechanic 2: visitors change
**Confidence:** 61%

**Effects:**

- **money**: +1.99/step (delay: 1 frames)
- **satisfaction**: -0.08/step (delay: 1 frames)
- **nausea**: -0.13/step (delay: 10 frames)
- **ride_intensity**: -0.38/step (delay: 10 frames)

### Mechanic 3: satisfaction change
**Confidence:** 72%

**Effects:**

- **money**: +1.99/step (delay: 1 frames)
- **visitors**: -0.59/step (delay: 10 frames)
- **ride_intensity**: -0.38/step (delay: 10 frames)

### Mechanic 4: nausea change
**Confidence:** 65%

**Effects:**

- **visitors**: -0.06/step (delay: 1 frames)
- **ride_intensity**: -0.03/step (delay: 1 frames)

### Mechanic 5: ride_intensity change
**Confidence:** 68%

**Effects:**

- **visitors**: -0.06/step (delay: 1 frames)
- **nausea**: -0.04/step (delay: 5 frames)

## Balance Design

### Parameter Interactions

| Source | Target | Lag | Correlation |
|--------|--------|-----|-------------|
| money | visitors | 10 | -0.829 |
| visitors | money | 1 | -0.723 |
| money | satisfaction | 10 | -0.909 |
| satisfaction | money | 1 | -0.883 |
| money | nausea | 10 | -0.313 |
| money | ride_intensity | 10 | -0.322 |
| visitors | satisfaction | 1 | 0.879 |
| satisfaction | visitors | 10 | 0.929 |
| visitors | nausea | 10 | 0.409 |
| nausea | visitors | 1 | 0.361 |
| visitors | ride_intensity | 10 | 0.416 |
| ride_intensity | visitors | 1 | 0.390 |
| satisfaction | ride_intensity | 10 | 0.338 |
| nausea | ride_intensity | 1 | 0.930 |
| ride_intensity | nausea | 5 | 0.965 |

### Tuning Guidelines

Parameters should be balanced to create meaningful trade-offs. Key relationships identified:

- **money change** (confidence: 59%)
- **visitors change** (confidence: 61%)
- **satisfaction change** (confidence: 72%)
- **nausea change** (confidence: 65%)
- **ride_intensity change** (confidence: 68%)

## Feedback Loops

### Positive (Reinforcing) Loops

These loops amplify changes — can lead to runaway growth or collapse:

- **money → ride_intensity → nausea → visitors → money**: money→ride_intensity (r=-0.322), ride_intensity→nausea (r=0.965), nausea→visitors (r=0.361), visitors→money (r=-0.723) — positive feedback
- **money → ride_intensity → nausea → visitors → satisfaction → money**: money→ride_intensity (r=-0.322), ride_intensity→nausea (r=0.965), nausea→visitors (r=0.361), visitors→satisfaction (r=0.879), satisfaction→money (r=-0.883) — positive feedback
- **money → ride_intensity → visitors → money**: money→ride_intensity (r=-0.322), ride_intensity→visitors (r=0.390), visitors→money (r=-0.723) — positive feedback
- **money → ride_intensity → visitors → satisfaction → money**: money→ride_intensity (r=-0.322), ride_intensity→visitors (r=0.390), visitors→satisfaction (r=0.879), satisfaction→money (r=-0.883) — positive feedback
- **money → nausea → ride_intensity → visitors → money**: money→nausea (r=-0.313), nausea→ride_intensity (r=0.930), ride_intensity→visitors (r=0.390), visitors→money (r=-0.723) — positive feedback
- **money → nausea → ride_intensity → visitors → satisfaction → money**: money→nausea (r=-0.313), nausea→ride_intensity (r=0.930), ride_intensity→visitors (r=0.390), visitors→satisfaction (r=0.879), satisfaction→money (r=-0.883) — positive feedback
- **money → nausea → visitors → money**: money→nausea (r=-0.313), nausea→visitors (r=0.361), visitors→money (r=-0.723) — positive feedback
- **money → nausea → visitors → satisfaction → money**: money→nausea (r=-0.313), nausea→visitors (r=0.361), visitors→satisfaction (r=0.879), satisfaction→money (r=-0.883) — positive feedback
- **money ↔ satisfaction**: money→satisfaction (r=-0.909), satisfaction→money (r=-0.883) — positive feedback
- **money → satisfaction → ride_intensity → nausea → visitors → money**: money→satisfaction (r=-0.909), satisfaction→ride_intensity (r=0.338), ride_intensity→nausea (r=0.965), nausea→visitors (r=0.361), visitors→money (r=-0.723) — positive feedback
- **money → satisfaction → ride_intensity → visitors → money**: money→satisfaction (r=-0.909), satisfaction→ride_intensity (r=0.338), ride_intensity→visitors (r=0.390), visitors→money (r=-0.723) — positive feedback
- **money → satisfaction → visitors → money**: money→satisfaction (r=-0.909), satisfaction→visitors (r=0.929), visitors→money (r=-0.723) — positive feedback
- **money ↔ visitors**: money→visitors (r=-0.829), visitors→money (r=-0.723) — positive feedback
- **money → visitors → satisfaction → money**: money→visitors (r=-0.829), visitors→satisfaction (r=0.879), satisfaction→money (r=-0.883) — positive feedback
- **nausea ↔ ride_intensity**: nausea→ride_intensity (r=0.930), ride_intensity→nausea (r=0.965) — positive feedback
- **nausea → ride_intensity → visitors → nausea**: nausea→ride_intensity (r=0.930), ride_intensity→visitors (r=0.390), visitors→nausea (r=0.409) — positive feedback
- **nausea ↔ visitors**: nausea→visitors (r=0.361), visitors→nausea (r=0.409) — positive feedback
- **nausea → visitors → ride_intensity → nausea**: nausea→visitors (r=0.361), visitors→ride_intensity (r=0.416), ride_intensity→nausea (r=0.965) — positive feedback
- **nausea → visitors → satisfaction → ride_intensity → nausea**: nausea→visitors (r=0.361), visitors→satisfaction (r=0.879), satisfaction→ride_intensity (r=0.338), ride_intensity→nausea (r=0.965) — positive feedback
- **ride_intensity ↔ visitors**: ride_intensity→visitors (r=0.390), visitors→ride_intensity (r=0.416) — positive feedback
- **ride_intensity → visitors → satisfaction → ride_intensity**: ride_intensity→visitors (r=0.390), visitors→satisfaction (r=0.879), satisfaction→ride_intensity (r=0.338) — positive feedback
- **satisfaction ↔ visitors**: satisfaction→visitors (r=0.929), visitors→satisfaction (r=0.879) — positive feedback

## Game State Analysis

### Expected Game States

The AI agent should recognize and handle these game states:

| State | Description | Recommended Action |
|-------|-------------|--------------------|
| Menu | Title/option selection screens | Navigate with D-pad, confirm with Circle |
| Gameplay | Active game simulation | Execute strategy-based actions |
| Dialog | NPC/event text boxes | Advance with Circle, read content |
| Loading | Screen transitions | Wait, no input needed |
| Pause | Game paused | Resume with Start or navigate pause menu |

### State Transition Patterns

Common transitions observed in PS1 management/simulation games:

- Menu → Loading → Gameplay (game start)
- Gameplay → Dialog → Gameplay (event trigger)
- Gameplay → Pause → Gameplay (player pause)
- Gameplay → Menu (game over / exit)

## Adaptive Strategy Configuration

### Strategy Modes

| Strategy | Trigger Condition | Focus |
|----------|-------------------|-------|
| expansion | money > 8000, visitors < 15 | Build new attractions, grow park |
| satisfaction | satisfaction < 30, nausea > 70 | Improve visitor comfort |
| cost_reduction | money < 1000 | Reduce expenses, optimize revenue |
| exploration | No specific trigger | Discover new areas and actions |
| balanced | Default / no threshold active | Adaptive switching |

### Threshold Customization

Strategy thresholds can be customized per game via JSON config:

```json
{
  "thresholds": [
    {
      "parameter": "money",
      "operator": "lt",
      "value": 1000,
      "target_strategy": "cost_reduction",
      "priority": 10
    },
    {
      "parameter": "satisfaction",
      "operator": "lt",
      "value": 30,
      "target_strategy": "satisfaction",
      "priority": 9
    }
  ]
}
```

## Implementation Priority

Based on causal chain confidence scores:

1. **satisfaction change** — confidence 72%, 3 downstream effects
2. **ride_intensity change** — confidence 68%, 2 downstream effects
3. **nausea change** — confidence 65%, 2 downstream effects
4. **visitors change** — confidence 61%, 4 downstream effects
5. **money change** — confidence 59%, 4 downstream effects

