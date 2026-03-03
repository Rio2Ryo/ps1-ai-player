#!/usr/bin/env python3
"""FastAPI-based web dashboard for PS1 AI Player monitoring.

Provides a read-only monitoring UI for browsing past sessions, viewing
parameter charts, causal graphs, and GDD documents in a browser.

Usage:
    python dashboard.py [--host 0.0.0.0] [--port 8080] [--log-dir logs/] [--reports-dir reports/]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json as _json_mod
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.responses import StreamingResponse

from log_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="PS1 AI Player Dashboard", version="0.1.0")

# Configurable directories (set via CLI or overridden in tests)
LOG_DIR = Path("logs")
REPORTS_DIR = Path("reports")

# ---------------------------------------------------------------------------
# HTML layout helpers
# ---------------------------------------------------------------------------

_CSS = """\
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 0; padding: 0; background: #f5f5f5; color: #333; }
nav { background: #1565c0; padding: 12px 24px; display: flex; gap: 20px; align-items: center; }
nav a { color: #fff; text-decoration: none; font-weight: 500; }
nav a:hover { text-decoration: underline; }
nav .brand { font-size: 1.2em; font-weight: 700; margin-right: 20px; }
.container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
table { border-collapse: collapse; width: 100%; background: #fff; margin: 16px 0; }
th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
th { background: #e3f2fd; }
tr:nth-child(even) { background: #fafafa; }
a { color: #1565c0; }
.card { background: #fff; border-radius: 6px; padding: 20px; margin: 16px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12); }
h1, h2, h3 { color: #1565c0; }
pre { background: #263238; color: #eeffff; padding: 16px; border-radius: 4px;
      overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; }
img.chart { max-width: 100%; border: 1px solid #ddd; margin: 8px 0; }
.btn { display: inline-block; background: #1565c0; color: #fff; padding: 8px 16px;
       border-radius: 4px; text-decoration: none; border: none; cursor: pointer;
       font-size: 14px; }
.btn:hover { background: #0d47a1; }
"""

_NAV = """\
<nav>
  <span class="brand">PS1 AI Dashboard</span>
  <a href="/">Sessions</a>
  <a href="/monitor">Monitor</a>
  <a href="/watcher">Watcher</a>
  <a href="/compare">Compare</a>
  <a href="/session/diff">Diff</a>
  <a href="/cross-analysis">Cross-Analysis</a>
  <a href="/parameters">Parameters</a>
  <a href="/reports">Reports</a>
  <a href="/optimize">Optimize</a>
  <a href="/gdd">GDD Docs</a>
  <a href="/sample/themepark">Sample: ThemePark</a>
  <a href="/sample/rpg">Sample: RPG</a>
  <a href="/sample/action">Sample: Action</a>
</nav>
"""


def _render(title: str, body: str) -> HTMLResponse:
    """Wrap *body* HTML in a full page with nav and CSS."""
    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — PS1 AI Dashboard</title>
<style>{_CSS}</style></head>
<body>{_NAV}<div class="container">{body}</div></body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Chart generation helpers (wrappers around visualizer.py)
# ---------------------------------------------------------------------------

def _chart_to_png(chart_func, *args, **kwargs) -> bytes:
    """Call a visualizer plot function with a temp file and return PNG bytes."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        chart_func(*args, output_path=tmp_path, **kwargs)
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def _chart_to_base64(chart_func, *args, **kwargs) -> str:
    """Generate a chart and return as a base64 data URI."""
    png_bytes = _chart_to_png(chart_func, *args, **kwargs)
    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _comparison_chart_to_base64(sessions, param: str) -> str:
    """Generate an overlay chart comparing *param* across *sessions*.

    Each session is plotted as a separate color-coded line on the same axis.
    Returns a base64 data URI for an inline ``<img>`` tag.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
              "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

    fig, ax = plt.subplots(figsize=(10, 3.5))
    for idx, s in enumerate(sessions):
        if param not in s.df.columns:
            continue
        color = colors[idx % len(colors)]
        steps = range(len(s.df))
        ax.plot(steps, s.df[param], linewidth=1.2, alpha=0.85,
                color=color, label=s.timestamp)
    ax.set_xlabel("Step")
    ax.set_ylabel(param)
    ax.set_title(f"{param} — Session Overlay")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        fig.savefig(tmp_path, dpi=120)
        plt.close(fig)
        png_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _action_heatmap_to_base64(heatmap_df) -> str:
    """Render an action heatmap DataFrame as a base64 PNG data URI.

    *heatmap_df* has step-interval labels as the index and action names
    as columns, with integer counts as values.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    data = heatmap_df.values.T  # actions × intervals
    actions = list(heatmap_df.columns)
    intervals = list(heatmap_df.index)

    fig_height = max(2.5, 0.5 * len(actions))
    fig, ax = plt.subplots(figsize=(max(8, 0.6 * len(intervals)), fig_height))
    im = ax.imshow(data, aspect="auto", cmap="YlOrRd", interpolation="nearest")
    ax.set_xticks(range(len(intervals)))
    ax.set_xticklabels(intervals, fontsize=7, rotation=45, ha="right")
    ax.set_yticks(range(len(actions)))
    ax.set_yticklabels(actions, fontsize=8)
    ax.set_xlabel("Step Interval")
    ax.set_ylabel("Action")
    ax.set_title("Action Heatmap (count per interval)")
    fig.colorbar(im, ax=ax, shrink=0.8)

    # Annotate cells with counts
    for i in range(len(actions)):
        for j in range(len(intervals)):
            val = int(data[i, j])
            if val > 0:
                ax.text(j, i, str(val), ha="center", va="center",
                        fontsize=7, color="black" if val < data.max() * 0.7 else "white")

    fig.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        fig.savefig(tmp_path, dpi=120)
        plt.close(fig)
        png_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _correlation_heatmap_to_base64(corr_matrix) -> str:
    """Render a Pearson correlation matrix as a heatmap base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    labels = list(corr_matrix.columns)
    data = corr_matrix.values

    size = max(4, 0.7 * len(labels))
    fig, ax = plt.subplots(figsize=(size, size))
    im = ax.imshow(data, cmap="RdBu_r", vmin=-1, vmax=1, interpolation="nearest")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_title("Parameter Correlation Matrix")
    fig.colorbar(im, ax=ax, shrink=0.8)

    for i in range(len(labels)):
        for j in range(len(labels)):
            val = data[i, j]
            color = "white" if abs(val) > 0.6 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=7, color=color)

    fig.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        fig.savefig(tmp_path, dpi=120)
        plt.close(fig)
        png_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _histogram_to_base64(all_values: dict[str, list[float]]) -> str:
    """Render per-parameter distribution histograms as a base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    params = list(all_values.keys())
    n = len(params)
    if n == 0:
        raise ValueError("No parameters")

    cols = min(3, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 3 * rows), squeeze=False)

    for idx, param in enumerate(params):
        r, c = divmod(idx, cols)
        ax = axes[r][c]
        vals = all_values[param]
        ax.hist(vals, bins=20, color="#1565c0", alpha=0.7, edgecolor="white")
        ax.set_title(param, fontsize=10)
        ax.set_xlabel("Value", fontsize=8)
        ax.set_ylabel("Frequency", fontsize=8)
        ax.tick_params(labelsize=7)

    # Hide unused axes
    for idx in range(n, rows * cols):
        r, c = divmod(idx, cols)
        axes[r][c].set_visible(False)

    fig.suptitle("Parameter Distributions (All Sessions)", fontsize=12)
    fig.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        fig.savefig(tmp_path, dpi=120)
        plt.close(fig)
        png_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _param_trend_to_base64(sessions, param: str) -> str:
    """Render per-session mean values as a trend line for *param*."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels: list[str] = []
    means: list[float] = []
    for s in sessions:
        if param in s.df.columns:
            labels.append(s.timestamp)
            means.append(float(s.df[param].mean()))

    if not means:
        raise ValueError(f"No data for {param}")

    fig, ax = plt.subplots(figsize=(max(6, 0.8 * len(labels)), 3.5))
    ax.plot(range(len(means)), means, marker="o", linewidth=2,
            color="#1565c0", markersize=6)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=7, rotation=45, ha="right")
    ax.set_ylabel(param)
    ax.set_title(f"{param} — Mean per Session")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        fig.savefig(tmp_path, dpi=120)
        plt.close(fig)
        png_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _timeline_chart_to_base64(session) -> str:
    """Generate an integrated timeline chart for a session.

    Shows action colour bars on a secondary axis and parameter lines on
    the primary axis, with event markers (strategy switches, threshold
    crossings) as vertical dashed lines.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    df = session.df
    steps = df["step"].values if "step" in df.columns else np.arange(len(df))
    params = session.parameters

    if not params:
        raise ValueError("No numeric parameters")

    # Colour palette for parameters
    param_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

    fig, ax1 = plt.subplots(figsize=(max(10, len(df) * 0.04), 4.5))

    # Plot parameter lines
    for idx, param in enumerate(params):
        if param not in df.columns:
            continue
        color = param_colors[idx % len(param_colors)]
        ax1.plot(steps, df[param].values, linewidth=1.2, alpha=0.8,
                 color=color, label=param)

    ax1.set_xlabel("Step")
    ax1.set_ylabel("Parameter Value")
    ax1.legend(fontsize=7, loc="upper left", ncol=min(len(params), 4))
    ax1.grid(True, alpha=0.2)

    # Action colour bars on secondary axis
    if "action" in df.columns:
        actions = df["action"].astype(str).values
        unique_actions = sorted(set(actions))
        action_cmap = {a: i for i, a in enumerate(unique_actions)}
        action_colors_map = plt.cm.Set3(np.linspace(0, 1, max(len(unique_actions), 1)))

        ax2 = ax1.twinx()
        for i, (step_val, action) in enumerate(zip(steps, actions)):
            cidx = action_cmap[action]
            ax2.barh(cidx, 1, left=step_val, height=0.8,
                     color=action_colors_map[cidx], alpha=0.5)
        ax2.set_yticks(range(len(unique_actions)))
        ax2.set_yticklabels(unique_actions, fontsize=7)
        ax2.set_ylabel("Action", fontsize=8)

    # Strategy switch markers from session_info
    info = session.session_info or {}
    switches = info.get("strategy_switches", [])
    if isinstance(switches, list):
        for sw in switches:
            if isinstance(sw, dict) and "step" in sw:
                ax1.axvline(x=sw["step"], color="purple", linestyle="--",
                            alpha=0.6, linewidth=1)

    ax1.set_title(f"Session Timeline: {session.timestamp}")
    fig.tight_layout()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        fig.savefig(tmp_path, dpi=120)
        plt.close(fig)
        png_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _load_session(csv_filename: str):
    """Load a SessionData from LOG_DIR by CSV filename."""
    from session_replay import SessionData

    csv_path = LOG_DIR / csv_filename
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"Session CSV not found: {csv_filename}")
    try:
        return SessionData.from_log_path(csv_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes: HTML pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page — list all sessions and links to sample data."""
    from session_replay import SessionData
    from session_scorer import SessionScorer
    from session_tagger import SessionTagger

    sessions = SessionData.discover_sessions(LOG_DIR)
    tagger = SessionTagger(log_dir=LOG_DIR)
    scorer = SessionScorer()

    # Tag filter
    tag_filter = request.query_params.get("tag")
    if tag_filter:
        filtered_names = set(tagger.sessions_with_tag(tag_filter))
        sessions = [s for s in sessions if s.csv_path.name in filtered_names]

    all_tags = tagger.all_known_tags()

    body = "<h1>Sessions</h1>"

    # Tag filter dropdown
    if all_tags:
        body += '<form method="get"><label>Filter by tag: <select name="tag">'
        body += '<option value="">All</option>'
        for t in all_tags:
            sel = ' selected' if t == tag_filter else ''
            body += f'<option value="{t}"{sel}>{t}</option>'
        body += '</select></label> <button class="btn" type="submit">Filter</button></form>'

    # Session search form
    body += (
        '<div class="card"><h3>Search Sessions</h3>'
        '<form method="get" id="search-form">'
        '<label>Parameter condition: '
        '<input type="text" name="param" placeholder="e.g. hp last > 50" '
        'style="width:220px;"></label> '
        '<label>Steps: '
        '<input type="text" name="steps" placeholder="e.g. 10-100" '
        'style="width:100px;"></label> '
        '<label>Date range: '
        '<input type="text" name="date" placeholder="e.g. 20250101-20250201" '
        'style="width:180px;"></label><br><br>'
        '<label>Tag: '
        '<input type="text" name="search_tag" placeholder="tag name" '
        'style="width:120px;"></label> '
        '<label>Note contains: '
        '<input type="text" name="note" placeholder="search text" '
        'style="width:150px;"></label> '
        '<button class="btn" type="submit">Search</button>'
        '</form></div>'
    )

    # Apply search filters if any search params are present
    search_param = request.query_params.get("param", "").strip()
    search_steps = request.query_params.get("steps", "").strip()
    search_date = request.query_params.get("date", "").strip()
    search_tag = request.query_params.get("search_tag", "").strip()
    search_note = request.query_params.get("note", "").strip()

    has_search = any([search_param, search_steps, search_date, search_tag, search_note])
    if has_search:
        from session_search import ParamCondition, SessionSearch

        conditions = []
        if search_param:
            try:
                conditions.append(ParamCondition.parse(search_param))
            except ValueError:
                pass  # ignore invalid condition

        min_steps = max_steps = None
        if search_steps and "-" in search_steps:
            parts = search_steps.split("-", 1)
            min_steps = int(parts[0]) if parts[0].strip() else None
            max_steps = int(parts[1]) if parts[1].strip() else None

        date_from = date_to = None
        if search_date and "-" in search_date:
            parts = search_date.split("-", 1)
            date_from = parts[0].strip() if parts[0].strip() else None
            date_to = parts[1].strip() if parts[1].strip() else None

        searcher = SessionSearch(
            log_dir=LOG_DIR,
            param_conditions=conditions,
            min_steps=min_steps,
            max_steps=max_steps,
            date_from=date_from,
            date_to=date_to,
            tag=search_tag or None,
            note_query=search_note or None,
        )
        matched = searcher.search()
        matched_names = {s.csv_path.name for s in matched}
        sessions = [s for s in sessions if s.csv_path.name in matched_names]

    rows = ""
    for s in sessions:
        link = f"/session/{s.csv_path.name}"
        tags = tagger.get_tags(s.csv_path.name)
        tags_str = ", ".join(tags) if tags else ""
        score_val = scorer.score(s).total
        rows += (
            f"<tr>"
            f"<td><a href=\"{link}\">{s.timestamp}</a></td>"
            f"<td>{s.game_id}</td>"
            f"<td>{s.total_steps}</td>"
            f"<td>${s.cost_usd:.4f}</td>"
            f"<td>{s.duration_seconds:.1f}s</td>"
            f"<td>{score_val:.1f}</td>"
            f"<td>{tags_str}</td>"
            f"</tr>"
        )

    if rows:
        body += (
            "<table><tr><th>Timestamp</th><th>Game ID</th>"
            "<th>Steps</th><th>Cost</th><th>Duration</th><th>Score</th><th>Tags</th></tr>"
            f"{rows}</table>"
        )
    else:
        body += "<p>No sessions found in <code>{}</code>.</p>".format(LOG_DIR)

    body += (
        '<div class="card"><h3>Sample Data</h3>'
        '<a class="btn" href="/sample/themepark">ThemePark</a> '
        '<a class="btn" href="/sample/rpg">RPG</a> '
        '<a class="btn" href="/sample/action">Action</a></div>'
    )

    return _render("Home", body)


# ---------------------------------------------------------------------------
# Routes: Session Diff (must be before /session/{csv_filename} to avoid capture)
# ---------------------------------------------------------------------------

@app.get("/session/diff", response_class=HTMLResponse)
async def session_diff_page(request: Request):
    """Step-level diff page — select two sessions or view diff results."""
    from session_replay import SessionData

    sessions = SessionData.discover_sessions(LOG_DIR)

    csv_a = request.query_params.get("a")
    csv_b = request.query_params.get("b")

    body = "<h1>Session Diff</h1>"

    if not csv_a or not csv_b:
        # Show session selector form
        if len(sessions) < 2:
            body += "<p>Need at least 2 sessions. Currently found: {}</p>".format(
                len(sessions)
            )
            return _render("Diff", body)

        body += '<form method="get">'
        body += '<label>Session A: <select name="a">'
        for s in sessions:
            body += f'<option value="{s.csv_path.name}">{s.timestamp} — {s.game_id} ({s.total_steps} steps)</option>'
        body += '</select></label><br><br>'
        body += '<label>Session B: <select name="b">'
        for s in sessions:
            body += f'<option value="{s.csv_path.name}">{s.timestamp} — {s.game_id} ({s.total_steps} steps)</option>'
        body += '</select></label><br><br>'
        body += '<button class="btn" type="submit">Diff</button></form>'
        return _render("Diff", body)

    # Load sessions and compute diff
    from replay_diff import ReplayDiff

    path_a = LOG_DIR / csv_a
    path_b = LOG_DIR / csv_b
    if not path_a.exists():
        raise HTTPException(status_code=404, detail=f"Session CSV not found: {csv_a}")
    if not path_b.exists():
        raise HTTPException(status_code=404, detail=f"Session CSV not found: {csv_b}")

    try:
        session_a = SessionData.from_log_path(path_a)
        session_b = SessionData.from_log_path(path_b)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    differ = ReplayDiff(session_a, session_b)
    summary = differ.summary()

    # Summary card
    body += '<div class="card"><h2>Summary</h2>'
    body += f"<p><strong>Session A:</strong> {summary['session_a']}</p>"
    body += f"<p><strong>Session B:</strong> {summary['session_b']}</p>"
    body += f"<p><strong>Steps A:</strong> {summary['total_steps_a']}</p>"
    body += f"<p><strong>Steps B:</strong> {summary['total_steps_b']}</p>"
    body += f"<p><strong>Common steps:</strong> {summary['common_steps']}</p>"
    body += f"<p><strong>Divergence count:</strong> {summary['divergence_count']}</p>"
    body += f"<p><strong>Divergence rate:</strong> {summary['divergence_rate']:.2%}</p>"
    if summary["param_diffs"]:
        body += "<p><strong>Mean |param diffs|:</strong> "
        parts = [f"{k}: {v:.4f}" for k, v in summary["param_diffs"].items()]
        body += ", ".join(parts) + "</p>"
    body += "</div>"

    # Divergence points table
    div_points = differ.divergence_points()
    all_params = sorted(
        set(session_a.parameters) | set(session_b.parameters)
    )
    if div_points:
        body += '<div class="card"><h2>Divergence Points</h2>'
        body += "<table><tr><th>Step</th><th>Action A</th><th>Action B</th>"
        for p in all_params:
            body += f"<th>{p} diff</th>"
        body += "</tr>"
        for sd in div_points:
            body += f'<tr style="background:#fff3e0"><td>{sd.step}</td>'
            body += f"<td>{sd.action_a or ''}</td><td>{sd.action_b or ''}</td>"
            for p in all_params:
                pd_delta = sd.param_deltas.get(p)
                diff_val = ""
                if pd_delta and pd_delta.diff is not None:
                    diff_val = f"{pd_delta.diff:+.2f}"
                body += f"<td>{diff_val}</td>"
            body += "</tr>"
        body += "</table></div>"
    else:
        body += '<div class="card"><p>No divergence points — sessions have identical actions.</p></div>'

    # Per-parameter side-by-side comparison
    if all_params:
        body += '<div class="card"><h2>Parameter Comparison</h2>'
        for param in all_params:
            pc = differ.param_comparison(param)
            if pc.empty:
                continue
            valid_diffs = pc["diff"].dropna()
            if len(valid_diffs) == 0:
                continue
            mean_diff = valid_diffs.abs().mean()
            max_diff = valid_diffs.abs().max()
            body += f"<h3>{param}</h3>"
            body += f"<p>Mean |diff|: {mean_diff:.4f} / Max |diff|: {max_diff:.4f}</p>"
        body += "</div>"

    return _render("Diff", body)


@app.get("/api/session/diff")
async def api_session_diff(request: Request):
    """JSON API: step-level diff between two sessions."""
    from session_replay import SessionData

    csv_a = request.query_params.get("a")
    csv_b = request.query_params.get("b")

    if not csv_a or not csv_b:
        raise HTTPException(status_code=400, detail="Both 'a' and 'b' query params required")

    from replay_diff import ReplayDiff

    path_a = LOG_DIR / csv_a
    path_b = LOG_DIR / csv_b
    if not path_a.exists():
        raise HTTPException(status_code=404, detail=f"Session CSV not found: {csv_a}")
    if not path_b.exists():
        raise HTTPException(status_code=404, detail=f"Session CSV not found: {csv_b}")

    try:
        session_a = SessionData.from_log_path(path_a)
        session_b = SessionData.from_log_path(path_b)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    differ = ReplayDiff(session_a, session_b)
    return JSONResponse(content=differ.to_dict())


@app.get("/session/{csv_filename}", response_class=HTMLResponse)
async def session_detail(csv_filename: str):
    """Single session detail page with summary and charts."""
    from session_tagger import SessionTagger

    session = _load_session(csv_filename)
    tagger = SessionTagger(log_dir=LOG_DIR)
    tags = tagger.get_tags(csv_filename)

    # Summary card
    body = f"<h1>Session: {session.timestamp}</h1>"
    body += '<div class="card">'
    body += f"<p><strong>Game ID:</strong> {session.game_id}</p>"
    body += f"<p><strong>Steps:</strong> {session.total_steps}</p>"
    body += f"<p><strong>Duration:</strong> {session.duration_seconds:.1f}s</p>"
    body += f"<p><strong>Cost:</strong> ${session.cost_usd:.4f}</p>"
    body += f"<p><strong>Parameters:</strong> {', '.join(session.parameters)}</p>"
    tags_str = ", ".join(tags) if tags else "<em>none</em>"
    body += f"<p><strong>Tags:</strong> {tags_str}</p>"
    body += "</div>"

    # Quick-tag form
    body += '<div class="card"><h3>Manage Tags</h3>'
    body += f'<form method="post" action="/api/session/{csv_filename}/tags">'
    body += '<input type="hidden" name="action" value="tag">'
    body += '<input type="text" name="tags" placeholder="tag1, tag2, ..." style="padding:6px;width:300px;">'
    body += ' <button class="btn" type="submit">Add Tags</button></form>'
    if tags:
        body += f'<form method="post" action="/api/session/{csv_filename}/tags" style="margin-top:8px;">'
        body += '<input type="hidden" name="action" value="untag">'
        body += '<input type="text" name="tags" placeholder="tag to remove" style="padding:6px;width:300px;">'
        body += ' <button class="btn" type="submit" style="background:#e53935;">Remove Tags</button></form>'
    body += "</div>"

    # Session note
    note = tagger.get_note(csv_filename)
    body += '<div class="card"><h3>Session Note</h3>'
    if note:
        body += f"<p>{note}</p>"
    else:
        body += "<p><em>No note set.</em></p>"
    body += f'<form method="post" action="/api/session/{csv_filename}/notes">'
    body += '<textarea name="note" rows="3" style="padding:6px;width:100%;box-sizing:border-box;" '
    body += f'placeholder="Add a note about this session...">{note}</textarea>'
    body += ' <button class="btn" type="submit" style="margin-top:6px;">Save Note</button></form>'
    if note:
        body += f'<form method="post" action="/api/session/{csv_filename}/notes" style="margin-top:6px;">'
        body += '<input type="hidden" name="note" value="">'
        body += '<button class="btn" type="submit" style="background:#e53935;">Delete Note</button></form>'
    body += "</div>"

    # Time-series chart (inline base64)
    if session.parameters:
        try:
            from visualizer import plot_time_series

            src = _chart_to_base64(plot_time_series, session.df, session.parameters)
            body += '<h2>Parameter Time Series</h2>'
            body += f'<img class="chart" src="{src}" alt="Time Series">'
        except Exception as exc:
            body += f"<p>Chart error: {exc}</p>"

    # Integrated timeline chart (actions + parameters + events)
    if session.parameters:
        try:
            src = _timeline_chart_to_base64(session)
            body += '<h2>Session Timeline</h2>'
            body += f'<img class="chart" src="{src}" alt="Session Timeline">'
        except Exception:
            pass  # timeline chart is optional enhancement

    # Chart links
    body += "<h2>Charts</h2><ul>"
    for chart_type in ("timeseries", "correlation", "causal_graph", "lag_correlations"):
        body += (
            f'<li><a href="/session/{csv_filename}/chart/{chart_type}">'
            f'{chart_type}</a> (PNG)</li>'
        )
    body += "</ul>"

    # Timeline table (first 50 rows)
    body += "<h2>Timeline (first 50 steps)</h2>"
    df_head = session.df.head(50)
    cols = list(df_head.columns)
    header = "".join(f"<th>{c}</th>" for c in cols)
    trows = ""
    for _, row in df_head.iterrows():
        trows += "<tr>" + "".join(f"<td>{row[c]}</td>" for c in cols) + "</tr>"
    body += f"<table><tr>{header}</tr>{trows}</table>"

    # Links to replay / actions / predict / export
    body += '<h2>Actions &amp; Export</h2>'
    body += (
        f'<a class="btn" href="/session/{csv_filename}/replay">Step Replay</a> '
        f'<a class="btn" href="/session/{csv_filename}/actions">Action Analysis</a> '
        f'<a class="btn" href="/session/{csv_filename}/predict">Predict</a> '
        f'<a class="btn" href="/session/{csv_filename}/recommend">Recommend</a> '
        f'<a class="btn" href="/session/{csv_filename}/export">Download ZIP</a>'
    )

    return _render(f"Session {session.timestamp}", body)


@app.get("/session/{csv_filename}/replay", response_class=HTMLResponse)
async def session_replay_view(csv_filename: str, request: Request):
    """Interactive step-through replay page."""
    from session_replay import ActionAnalyzer, SessionTimeline

    session = _load_session(csv_filename)
    tl = SessionTimeline(session)

    # Determine current step from query param
    step_param = request.query_params.get("step")
    steps = sorted(session.df["step"].unique())
    if not steps:
        return _render("Replay", "<h1>No steps in session</h1>")

    if step_param is not None:
        current_step = int(step_param)
    else:
        current_step = int(steps[0])

    # Navigation
    step_idx = steps.index(current_step) if current_step in steps else 0
    current_step = int(steps[step_idx])
    prev_step = int(steps[step_idx - 1]) if step_idx > 0 else None
    next_step = int(steps[step_idx + 1]) if step_idx < len(steps) - 1 else None

    info = tl.get_step_enriched(current_step)

    body = f"<h1>Replay: {session.timestamp} — Step {current_step}</h1>"

    # Navigation buttons
    body += '<div style="margin: 12px 0;">'
    if prev_step is not None:
        body += f'<a class="btn" href="/session/{csv_filename}/replay?step={prev_step}">&laquo; Prev</a> '
    body += f'<span style="margin: 0 12px;">Step {step_idx + 1} / {len(steps)}</span>'
    if next_step is not None:
        body += f' <a class="btn" href="/session/{csv_filename}/replay?step={next_step}">Next &raquo;</a>'
    body += '</div>'

    # Step detail card
    body += '<div class="card">'
    if "actions" in info:
        body += f"<p><strong>Actions:</strong> {', '.join(str(a) for a in info['actions'])}</p>"
    else:
        body += f"<p><strong>Action:</strong> {info.get('action', '')}</p>"
    body += f"<p><strong>Reasoning:</strong> {info.get('reasoning', '')}</p>"
    body += f"<p><strong>Observations:</strong> {info.get('observations', '')}</p>"

    # Parameters with deltas
    body += "<h3>Parameters</h3><table><tr><th>Parameter</th><th>Value</th><th>Delta</th></tr>"
    for param in session.parameters:
        val = info.get(param, "")
        delta_str = ""
        if prev_step is not None:
            try:
                prev_val = tl.parameter_at_step(param, prev_step)
                cur_val = float(val)
                delta = cur_val - prev_val
                delta_str = f"{delta:+.2f}"
            except (KeyError, ValueError, TypeError):
                pass
        body += f"<tr><td>{param}</td><td>{val}</td><td>{delta_str}</td></tr>"
    body += "</table>"

    # Streak indicator
    analyzer = ActionAnalyzer(session)
    streaks = analyzer.action_streaks()
    for s in streaks:
        if s["start_step"] <= current_step <= s["end_step"]:
            body += (
                f'<p><strong>Streak:</strong> {s["action"]} x{s["length"]} '
                f'(steps {s["start_step"]}-{s["end_step"]})</p>'
            )
            break

    if "history_parameters" in info:
        body += f"<p><strong>History snapshot:</strong> {info['history_parameters']}</p>"
    body += "</div>"

    return _render(f"Replay Step {current_step}", body)


@app.get("/session/{csv_filename}/actions", response_class=HTMLResponse)
async def session_actions_view(csv_filename: str):
    """Action analysis page — frequency, transitions, parameter impact, streaks."""
    from session_replay import ActionAnalyzer

    session = _load_session(csv_filename)
    analyzer = ActionAnalyzer(session)

    body = f"<h1>Action Analysis: {session.timestamp}</h1>"

    # Frequency table
    freq = analyzer.action_frequency()
    if freq:
        total = sum(freq.values())
        body += '<div class="card"><h2>Action Frequency</h2><table>'
        body += "<tr><th>Action</th><th>Count</th><th>Pct</th></tr>"
        for act, cnt in sorted(freq.items(), key=lambda x: -x[1]):
            pct = cnt / total * 100 if total else 0
            body += f"<tr><td>{act}</td><td>{cnt}</td><td>{pct:.1f}%</td></tr>"
        body += "</table></div>"
    else:
        body += "<p>No actions found in session data.</p>"

    # Transition matrix
    trans = analyzer.action_transitions()
    if trans:
        all_actions = sorted(set(trans.keys()) | {a for d in trans.values() for a in d})
        body += '<div class="card"><h2>Action Transitions</h2><table>'
        body += "<tr><th>From \\ To</th>" + "".join(f"<th>{a}</th>" for a in all_actions) + "</tr>"
        for src in all_actions:
            body += f"<tr><td><strong>{src}</strong></td>"
            for dst in all_actions:
                cnt = trans.get(src, {}).get(dst, 0)
                body += f"<td>{cnt if cnt else ''}</td>"
            body += "</tr>"
        body += "</table></div>"

    # Parameter impact
    params = session.parameters
    if params and freq:
        body += '<div class="card"><h2>Action-Parameter Impact</h2>'
        for param in params:
            impact = analyzer.action_parameter_impact(param)
            if impact:
                body += f"<h3>{param}</h3><table>"
                body += "<tr><th>Action</th><th>Mean Delta</th><th>Median Delta</th><th>Count</th></tr>"
                for act, stats in sorted(impact.items()):
                    body += (
                        f"<tr><td>{act}</td>"
                        f"<td>{stats['mean_delta']:.4f}</td>"
                        f"<td>{stats['median_delta']:.4f}</td>"
                        f"<td>{stats['count']}</td></tr>"
                    )
                body += "</table>"
        body += "</div>"

    # Streaks
    streaks = analyzer.action_streaks()
    if streaks:
        body += '<div class="card"><h2>Top Action Streaks</h2><table>'
        body += "<tr><th>Action</th><th>Length</th><th>Start</th><th>End</th></tr>"
        for s in streaks[:10]:
            body += (
                f"<tr><td>{s['action']}</td><td>{s['length']}</td>"
                f"<td>{s['start_step']}</td><td>{s['end_step']}</td></tr>"
            )
        body += "</table></div>"

    # Action heatmap (step-interval x action type)
    heatmap_df = analyzer.action_heatmap()
    if not heatmap_df.empty:
        try:
            src = _action_heatmap_to_base64(heatmap_df)
            body += (
                '<div class="card"><h2>Action Heatmap</h2>'
                f'<img src="{src}" alt="Action heatmap" '
                'style="max-width:100%;">'
                '</div>'
            )
        except Exception:
            pass

    return _render(f"Actions: {session.timestamp}", body)


@app.get("/session/{csv_filename}/chart/{chart_type}")
async def session_chart(csv_filename: str, chart_type: str):
    """Return a PNG chart for a session."""
    session = _load_session(csv_filename)

    if not session.parameters:
        raise HTTPException(status_code=400, detail="No numeric parameters in session")

    try:
        if chart_type == "timeseries":
            from visualizer import plot_time_series
            png = _chart_to_png(plot_time_series, session.df, session.parameters)

        elif chart_type == "correlation":
            from visualizer import plot_correlation_heatmap
            png = _chart_to_png(plot_correlation_heatmap, session.df, session.parameters)

        elif chart_type == "causal_graph":
            from data_analyzer import CausalChainExtractor
            from visualizer import plot_causal_graph

            extractor = CausalChainExtractor()
            extractor.load_logs([session.csv_path])
            extractor.compute_correlations()
            extractor.detect_lag_correlations()
            extractor.build_causal_graph()
            png = _chart_to_png(plot_causal_graph, extractor.causal_chains)

        elif chart_type == "lag_correlations":
            from data_analyzer import CausalChainExtractor
            from visualizer import plot_lag_correlations

            extractor = CausalChainExtractor()
            extractor.load_logs([session.csv_path])
            extractor.compute_correlations()
            extractor.detect_lag_correlations()
            png = _chart_to_png(plot_lag_correlations, extractor.lag_correlations)

        else:
            raise HTTPException(status_code=404, detail=f"Unknown chart type: {chart_type}")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chart generation failed: {exc}")

    return Response(content=png, media_type="image/png")


@app.get("/session/{csv_filename}/export")
async def session_export(csv_filename: str):
    """Download a session as a ZIP bundle."""
    from session_exporter import SessionExporter

    session = _load_session(csv_filename)
    exporter = SessionExporter(session)
    zip_bytes = exporter.export_bytes()
    zip_name = session.csv_path.stem + ".zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@app.get("/cross-analysis", response_class=HTMLResponse)
async def cross_analysis(request: Request):
    """Cross-session analysis page — parameter evolution, strategy effectiveness,
    action effectiveness, and recommendations across all sessions."""
    from cross_session_analyzer import CrossSessionAnalyzer
    from session_replay import SessionData

    game_filter = request.query_params.get("game")
    sessions = SessionData.discover_sessions(LOG_DIR, game_id=game_filter)

    body = "<h1>Cross-Session Analysis</h1>"

    # Game filter form
    all_sessions = SessionData.discover_sessions(LOG_DIR)
    game_ids = sorted({s.game_id for s in all_sessions})
    if game_ids:
        body += '<form method="get"><label>Game: <select name="game">'
        body += '<option value="">All</option>'
        for gid in game_ids:
            sel = ' selected' if gid == game_filter else ''
            body += f'<option value="{gid}"{sel}>{gid}</option>'
        body += '</select></label> <button class="btn" type="submit">Filter</button></form>'

    if not sessions:
        body += f"<p>No sessions found in <code>{LOG_DIR}</code>.</p>"
        return _render("Cross-Analysis", body)

    analyzer = CrossSessionAnalyzer(sessions)

    # Session progression
    prog = analyzer.session_progression()
    body += '<div class="card"><h2>Session Progression</h2><table>'
    cols = list(prog.columns)
    body += "<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
    for _, row in prog.iterrows():
        body += "<tr>" + "".join(f"<td>{row[c]}</td>" for c in cols) + "</tr>"
    body += "</table></div>"

    # Parameter evolution
    evol = analyzer.parameter_evolution()
    if evol:
        body += '<div class="card"><h2>Parameter Evolution</h2>'
        for param, entries in evol.items():
            body += f"<h3>{param}</h3><table>"
            body += "<tr><th>Session</th><th>Mean</th><th>Min</th><th>Max</th>"
            body += "<th>First</th><th>Last</th><th>Trend</th></tr>"
            for e in entries:
                trend = e["trend"]
                trend_style = ""
                if trend == "rising":
                    trend_style = ' style="color:green"'
                elif trend == "falling":
                    trend_style = ' style="color:red"'
                body += (
                    f"<tr><td>{e['session']}</td><td>{e['mean']}</td>"
                    f"<td>{e['min']}</td><td>{e['max']}</td>"
                    f"<td>{e['first']}</td><td>{e['last']}</td>"
                    f"<td{trend_style}>{trend}</td></tr>"
                )
            body += "</table>"
        body += "</div>"

    # Strategy effectiveness
    strat_df = analyzer.strategy_effectiveness()
    if not strat_df.empty:
        body += '<div class="card"><h2>Strategy Effectiveness</h2><table>'
        cols = list(strat_df.columns)
        body += "<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
        for _, row in strat_df.iterrows():
            body += "<tr>" + "".join(f"<td>{row[c]}</td>" for c in cols) + "</tr>"
        body += "</table></div>"

    # Action effectiveness
    all_params: set[str] = set()
    for s in sessions:
        all_params.update(s.parameters)
    if all_params:
        body += '<div class="card"><h2>Action Effectiveness</h2>'
        for param in sorted(all_params):
            try:
                act_df = analyzer.action_effectiveness(param)
            except KeyError:
                continue
            if act_df.empty:
                continue
            body += f"<h3>{param}</h3><table>"
            body += "<tr><th>Action</th><th>Mean Delta</th><th>Median Delta</th><th>Count</th></tr>"
            for _, row in act_df.iterrows():
                body += (
                    f"<tr><td>{row['action']}</td>"
                    f"<td>{row['mean_delta']:.4f}</td>"
                    f"<td>{row['median_delta']:.4f}</td>"
                    f"<td>{int(row['count'])}</td></tr>"
                )
            body += "</table>"
        body += "</div>"

    # Recommendations
    recs = analyzer.recommendations()
    if recs:
        body += '<div class="card"><h2>Recommendations</h2><ul>'
        for r in recs:
            body += f"<li>{r}</li>"
        body += "</ul></div>"

    # Anomaly alerts
    try:
        from anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(sessions)
        anomalies = detector.detect_all()
        if anomalies:
            body += '<div class="card" style="border-left: 4px solid #e53935;">'
            body += f"<h2>Anomaly Alerts ({len(anomalies)})</h2>"
            severity_colors = {"high": "#e53935", "medium": "#fb8c00", "low": "#fdd835"}
            for a in anomalies:
                color = severity_colors.get(a.severity, "#999")
                label = a.severity.upper()
                body += (
                    f'<p><span style="color:{color};font-weight:bold;">'
                    f"[{label}]</span> {a.description}</p>"
                )
            body += "</div>"
    except Exception as exc:
        logger.debug("Anomaly detection skipped: %s", exc)

    return _render("Cross-Analysis", body)


@app.get("/optimize", response_class=HTMLResponse)
async def optimize_page(request: Request):
    """Strategy optimisation page — select a strategy JSON and view tuning results."""
    from session_replay import SessionData
    from strategy_optimizer import StrategyOptimizer

    body = "<h1>Strategy Optimizer</h1>"

    # Discover strategy files
    strat_dir = Path("config/strategies")
    strat_files: list[Path] = []
    if strat_dir.is_dir():
        strat_files = sorted(strat_dir.glob("*.json"))

    if not strat_files:
        body += "<p>No strategy files found in <code>config/strategies/</code>.</p>"
        return _render("Optimize", body)

    selected = request.query_params.get("strategy")

    # Strategy selector
    body += '<form method="get"><label>Strategy: <select name="strategy">'
    for sf in strat_files:
        sel = ' selected' if sf.name == selected else ''
        body += f'<option value="{sf.name}"{sel}>{sf.name}</option>'
    body += '</select></label> <button class="btn" type="submit">Optimize</button></form>'

    if not selected:
        body += "<p>Select a strategy and click Optimize.</p>"
        return _render("Optimize", body)

    strat_path = strat_dir / selected
    if not strat_path.exists():
        body += f"<p>Strategy file not found: <code>{selected}</code></p>"
        return _render("Optimize", body)

    sessions = SessionData.discover_sessions(LOG_DIR)
    if not sessions:
        body += f"<p>No sessions found in <code>{LOG_DIR}</code>.</p>"
        return _render("Optimize", body)

    import json as _json
    strategy_config = _json.loads(strat_path.read_text())
    optimizer = StrategyOptimizer(strategy_config, sessions)

    # Diff
    diff_lines = optimizer.diff()
    if diff_lines:
        body += '<div class="card"><h2>Proposed Changes</h2><ul>'
        for d in diff_lines:
            body += f"<li><code>{d}</code></li>"
        body += "</ul></div>"
    else:
        body += '<div class="card"><p>No changes recommended for current data.</p></div>'

    # Optimised config preview
    optimized = optimizer.optimize()
    clean = {k: v for k, v in optimized.items() if not k.startswith("_")}
    body += '<div class="card"><h2>Optimised Config</h2>'
    body += f"<pre>{_json.dumps(clean, indent=2)}</pre></div>"

    # Notes
    notes = optimized.get("_optimization_notes", [])
    if notes:
        body += '<div class="card"><h2>Optimisation Notes</h2><ul>'
        for n in notes:
            body += f"<li>{n}</li>"
        body += "</ul></div>"

    return _render("Optimize", body)


# ---------------------------------------------------------------------------
# Routes: Memory Watcher
# ---------------------------------------------------------------------------

def _load_watcher_rules() -> list[dict]:
    """Load watcher rules from all strategy configs in config/strategies/.

    Each strategy threshold is converted to a watcher rule with severity
    derived from priority (>=8 → high, >=5 → medium, else → low).
    """
    strat_dir = Path("config/strategies")
    if not strat_dir.is_dir():
        return []

    rules: list[dict] = []
    seen: set[tuple] = set()
    for sf in sorted(strat_dir.glob("*.json")):
        try:
            config = _json_mod.loads(sf.read_text())
        except Exception:
            continue
        for t in config.get("thresholds", []):
            key = (t["parameter"], t["operator"], t["value"])
            if key in seen:
                continue
            seen.add(key)
            priority = t.get("priority", 5)
            severity = "high" if priority >= 8 else "medium" if priority >= 5 else "low"
            rules.append({
                "parameter": t["parameter"],
                "operator": t["operator"],
                "value": t["value"],
                "severity": severity,
                "message": f'{t["parameter"]} {t["operator"]} {t["value"]} '
                           f'({sf.stem}: {t.get("target_strategy", "alert")})',
            })
    return rules


@app.get("/watcher", response_class=HTMLResponse)
async def watcher_page(request: Request):
    """Real-time watcher page — threshold alerts + spike detection.

    Auto-refreshes via <meta refresh> and also connects to SSE for instant alerts.
    """
    import pandas as pd

    from memory_watcher import MemoryWatcher

    body = '<meta http-equiv="refresh" content="5">'
    body += "<h1>Memory Watcher</h1>"

    # Load rules from strategy configs
    rules = _load_watcher_rules()

    # Strategy selector (optional override)
    strat_dir = Path("config/strategies")
    strat_files = sorted(strat_dir.glob("*.json")) if strat_dir.is_dir() else []
    strat_filter = request.query_params.get("strategy")
    if strat_files:
        body += '<form method="get"><label>Strategy filter: <select name="strategy">'
        body += '<option value="">All strategies</option>'
        for sf in strat_files:
            sel = ' selected' if sf.name == strat_filter else ''
            body += f'<option value="{sf.name}"{sel}>{sf.name}</option>'
        body += '</select></label> <button class="btn" type="submit">Apply</button></form>'

    # If a specific strategy is selected, use only its rules
    if strat_filter:
        strat_path = strat_dir / strat_filter
        if strat_path.exists():
            try:
                config = _json_mod.loads(strat_path.read_text())
                watcher = MemoryWatcher.from_strategy_config(config)
                rules_for_display = [r.to_dict() for r in watcher.rules]
            except Exception:
                rules_for_display = rules
        else:
            rules_for_display = rules
    else:
        rules_for_display = rules

    # Show configured rules
    if rules_for_display:
        body += '<div class="card"><h2>Active Rules</h2><table>'
        body += "<tr><th>Parameter</th><th>Operator</th><th>Value</th>"
        body += "<th>Severity</th><th>Message</th></tr>"
        for r in rules_for_display:
            sev_color = {"high": "#e53935", "medium": "#fb8c00", "low": "#fdd835"}.get(
                r.get("severity", ""), "#999"
            )
            body += (
                f"<tr><td>{r['parameter']}</td><td>{r['operator']}</td>"
                f"<td>{r['value']}</td>"
                f'<td><span style="color:{sev_color};font-weight:bold;">'
                f"{r.get('severity', '').upper()}</span></td>"
                f"<td>{r.get('message', '')}</td></tr>"
            )
        body += "</table></div>"
    else:
        body += '<div class="card"><p>No watcher rules configured. Add strategy files to <code>config/strategies/</code>.</p></div>'

    # Check active session against rules
    csv_path, df = _find_active_session()
    if csv_path is None or df is None or df.empty:
        body += '<div class="card"><p>No active session found. Watching for *_agent.csv files...</p></div>'
    else:
        # Run watcher on the active session
        _FIXED = {"timestamp", "step", "action", "reasoning", "observations"}
        parameters = [
            c for c in df.columns
            if c not in _FIXED and pd.api.types.is_numeric_dtype(df[c])
        ]

        watcher = MemoryWatcher(rules_for_display) if rules_for_display else MemoryWatcher([])
        for _, row in df.iterrows():
            values = {}
            for param in parameters:
                try:
                    values[param] = float(row[param])
                except (ValueError, TypeError):
                    pass
            ts = str(row.get("timestamp", ""))
            watcher.check_values(values, ts)

        alerts = watcher.alerts
        summary = watcher.alert_summary()

        # Summary card
        body += '<div class="card"><h2>Session Status</h2>'
        body += f"<p><strong>Session:</strong> {csv_path.name}</p>"
        body += f"<p><strong>Steps analyzed:</strong> {len(df)}</p>"
        body += f"<p><strong>Total alerts:</strong> {summary['total']}</p>"
        if summary["by_kind"]:
            parts = [f"{k}: {v}" for k, v in summary["by_kind"].items()]
            body += f"<p><strong>By type:</strong> {', '.join(parts)}</p>"
        if summary["by_severity"]:
            parts = [f"{k}: {v}" for k, v in summary["by_severity"].items()]
            body += f"<p><strong>By severity:</strong> {', '.join(parts)}</p>"
        body += "</div>"

        # Alert list
        if alerts:
            severity_colors = {"high": "#e53935", "medium": "#fb8c00", "low": "#fdd835"}
            body += '<div class="card" style="border-left: 4px solid #e53935;">'
            body += f"<h2>Alerts ({len(alerts)})</h2>"
            # Show most recent alerts first (last 50)
            for a in reversed(alerts[-50:]):
                color = severity_colors.get(a.severity, "#999")
                label = a.severity.upper()
                kind_badge = f"[{a.kind.upper()}]"
                body += (
                    f'<p><span style="color:{color};font-weight:bold;">'
                    f"[{label}]</span> {kind_badge} {a.description} "
                    f'<small style="color:#999">@ {a.timestamp}</small></p>'
                )
            body += "</div>"
        else:
            body += '<div class="card"><p>No alerts triggered for active session.</p></div>'

    # SSE connection script for live alerts
    body += """
<div class="card" id="sse-alerts" style="display:none; border-left: 4px solid #1565c0;">
  <h2>Live Alerts (SSE)</h2>
  <div id="sse-list"></div>
</div>
<script>
if (typeof(EventSource) !== "undefined") {
  var source = new EventSource("/api/watcher/events");
  var panel = document.getElementById("sse-alerts");
  var list = document.getElementById("sse-list");
  source.onmessage = function(event) {
    panel.style.display = "block";
    var a = JSON.parse(event.data);
    var colors = {"high": "#e53935", "medium": "#fb8c00", "low": "#fdd835"};
    var color = colors[a.severity] || "#999";
    var p = document.createElement("p");
    p.innerHTML = '<span style="color:' + color + ';font-weight:bold;">[' +
      a.severity.toUpperCase() + ']</span> [' + a.kind.toUpperCase() + '] ' +
      a.description;
    list.insertBefore(p, list.firstChild);
  };
}
</script>
"""

    return _render("Watcher", body)


@app.get("/api/watcher/alerts")
async def api_watcher_alerts(request: Request):
    """JSON API: run watcher on active session and return alerts."""
    import pandas as pd

    from memory_watcher import MemoryWatcher

    csv_path, df = _find_active_session()
    if csv_path is None or df is None or df.empty:
        return JSONResponse(content={"active": False, "alerts": [], "summary": {"total": 0}})

    # Load rules
    strat_name = request.query_params.get("strategy")
    if strat_name:
        strat_path = Path("config/strategies") / strat_name
        if strat_path.exists():
            config = _json_mod.loads(strat_path.read_text())
            watcher = MemoryWatcher.from_strategy_config(config)
        else:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strat_name}")
    else:
        rules = _load_watcher_rules()
        watcher = MemoryWatcher(rules)

    _FIXED = {"timestamp", "step", "action", "reasoning", "observations"}
    parameters = [
        c for c in df.columns
        if c not in _FIXED and pd.api.types.is_numeric_dtype(df[c])
    ]

    for _, row in df.iterrows():
        values = {}
        for param in parameters:
            try:
                values[param] = float(row[param])
            except (ValueError, TypeError):
                pass
        ts = str(row.get("timestamp", ""))
        watcher.check_values(values, ts)

    return JSONResponse(content={
        "active": True,
        "csv_filename": csv_path.name,
        "total_steps": len(df),
        "summary": watcher.alert_summary(),
        "alerts": [a.to_dict() for a in watcher.alerts],
    })


@app.get("/api/watcher/events")
async def api_watcher_events(request: Request):
    """SSE endpoint: stream watcher alerts as the active session grows.

    Each SSE event contains a JSON-encoded WatcherAlert.  A keepalive
    comment is sent every 2 seconds.
    """
    import pandas as pd

    from memory_watcher import MemoryWatcher

    rules = _load_watcher_rules()

    async def generate():
        watcher = MemoryWatcher(rules)
        last_row_count = 0

        while True:
            if await request.is_disconnected():
                break

            csv_path, df = _find_active_session()
            if df is not None and len(df) > last_row_count:
                _FIXED = {"timestamp", "step", "action", "reasoning", "observations"}
                parameters = [
                    c for c in df.columns
                    if c not in _FIXED and pd.api.types.is_numeric_dtype(df[c])
                ]
                new_rows = df.iloc[last_row_count:]
                for _, row in new_rows.iterrows():
                    values = {}
                    for param in parameters:
                        try:
                            values[param] = float(row[param])
                        except (ValueError, TypeError):
                            pass
                    ts = str(row.get("timestamp", ""))
                    new_alerts = watcher.check_values(values, ts)
                    for alert in new_alerts:
                        yield f"data: {_json_mod.dumps(alert.to_dict())}\n\n"
                last_row_count = len(df)

            yield ": keepalive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/compare", response_class=HTMLResponse)
async def compare_form():
    """Multi-session comparison form."""
    from session_replay import SessionData

    sessions = SessionData.discover_sessions(LOG_DIR)

    body = "<h1>Compare Sessions</h1>"
    if len(sessions) < 2:
        body += "<p>Need at least 2 sessions to compare. Currently found: {}</p>".format(
            len(sessions)
        )
        return _render("Compare", body)

    body += '<form method="post" action="/compare/result">'
    body += "<p>Select 2 or more sessions:</p>"
    for s in sessions:
        body += (
            f'<label><input type="checkbox" name="sessions" '
            f'value="{s.csv_path.name}"> '
            f'{s.timestamp} — {s.game_id} ({s.total_steps} steps)</label><br>'
        )
    body += '<br><button class="btn" type="submit">Compare</button></form>'

    return _render("Compare", body)


@app.post("/compare/result", response_class=HTMLResponse)
async def compare_result(request: Request):
    """Comparison result page."""
    from session_replay import SessionComparator, SessionData

    form = await request.form()
    selected = form.getlist("sessions")
    if len(selected) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 sessions")

    sessions = []
    for name in selected:
        csv_path = LOG_DIR / name
        if csv_path.exists():
            sessions.append(SessionData.from_log_path(csv_path))

    if len(sessions) < 2:
        raise HTTPException(status_code=400, detail="Could not load enough sessions")

    comp = SessionComparator(sessions)
    summary = comp.compare_summary()

    body = "<h1>Comparison Result</h1>"

    # Summary table
    body += "<h2>Summary</h2><table>"
    cols = list(summary.columns)
    body += "<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
    for _, row in summary.iterrows():
        body += "<tr>" + "".join(f"<td>{row[c]}</td>" for c in cols) + "</tr>"
    body += "</table>"

    # --- Parameter overlay charts + stats tables ---
    # Collect the union of numeric parameters across all sessions
    all_params: list[str] = []
    seen: set[str] = set()
    for s in sessions:
        for p in s.parameters:
            if p not in seen:
                all_params.append(p)
                seen.add(p)

    if all_params:
        body += "<h2>Parameter Comparison Charts</h2>"
        for param in all_params:
            # Overlay chart
            try:
                src = _comparison_chart_to_base64(sessions, param)
                body += f'<img src="{src}" alt="{param} overlay chart" '
                body += 'style="max-width:100%;margin-bottom:8px;">'
            except Exception:
                body += f"<p><em>Could not generate chart for {param}</em></p>"

            # Per-session stats table from compare_parameters()
            stats = comp.compare_parameters(param)
            if stats:
                body += "<table><tr><th>Session</th>"
                stat_keys = ["mean", "min", "max", "std", "first", "last"]
                for k in stat_keys:
                    body += f"<th>{k}</th>"
                body += "</tr>"
                for ts, vals in stats.items():
                    body += f"<tr><td>{ts}</td>"
                    for k in stat_keys:
                        body += f"<td>{vals.get(k, '')}</td>"
                    body += "</tr>"
                body += "</table><br>"

    # Strategy diffs
    diffs = comp.diff_strategies()
    body += "<h2>Strategy Differences</h2><ul>"
    for d in diffs:
        body += f"<li><strong>{d['timestamp']}</strong> ({d['game_id']}): {d['strategy']}</li>"
    body += "</ul>"

    return _render("Comparison", body)


@app.get("/gdd", response_class=HTMLResponse)
async def gdd_list():
    """List available GDD files."""
    body = "<h1>GDD Documents</h1>"

    if not REPORTS_DIR.is_dir():
        body += f"<p>Reports directory not found: <code>{REPORTS_DIR}</code></p>"
        return _render("GDD", body)

    md_files = sorted(REPORTS_DIR.glob("*.md"))
    if not md_files:
        body += "<p>No GDD markdown files found.</p>"
    else:
        body += "<ul>"
        for f in md_files:
            body += f'<li><a href="/gdd/{f.name}">{f.name}</a></li>'
        body += "</ul>"

    return _render("GDD", body)


@app.get("/gdd/{filename}", response_class=HTMLResponse)
async def gdd_view(filename: str):
    """Render a GDD markdown file as HTML (simple pre-formatted)."""
    filepath = REPORTS_DIR / filename
    if not filepath.exists() or not filepath.suffix == ".md":
        raise HTTPException(status_code=404, detail=f"GDD file not found: {filename}")

    content = filepath.read_text()

    # Simple markdown to HTML conversion: headers, bold, lists
    lines = []
    for line in content.split("\n"):
        if line.startswith("### "):
            lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            lines.append(f"<li>{line[2:]}</li>")
        elif line.startswith("---"):
            lines.append("<hr>")
        elif line.strip() == "":
            lines.append("<br>")
        else:
            lines.append(f"<p>{line}</p>")

    body = f'<div class="card">{"".join(lines)}</div>'

    return _render(f"GDD: {filename}", body)


@app.get("/sample/{genre}", response_class=HTMLResponse)
async def sample_analysis(genre: str):
    """Run analysis on sample data and show results."""
    sample_map = {
        "themepark": "sample_data/sample_log.csv",
        "rpg": "sample_data/rpg_sample_log.csv",
        "action": "sample_data/action_sample_log.csv",
    }

    if genre not in sample_map:
        raise HTTPException(status_code=404, detail=f"Unknown genre: {genre}. Use: themepark, rpg, action")

    csv_path = Path(sample_map[genre])
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"Sample data not found: {csv_path}")

    import pandas as pd

    df = pd.read_csv(csv_path)
    numeric_cols = [
        c for c in df.columns
        if c not in ("timestamp", "frame", "source_file", "action", "reasoning", "observations")
        and pd.api.types.is_numeric_dtype(df[c])
    ]

    body = f"<h1>Sample Analysis: {genre.title()}</h1>"
    body += f"<p>Data: <code>{csv_path}</code> ({len(df)} rows)</p>"

    # Stats card
    if numeric_cols:
        body += '<div class="card"><h2>Parameter Statistics</h2><table>'
        body += "<tr><th>Parameter</th><th>Mean</th><th>Min</th><th>Max</th><th>Std</th></tr>"
        for col in numeric_cols:
            s = df[col]
            body += (
                f"<tr><td>{col}</td><td>{s.mean():.2f}</td>"
                f"<td>{s.min():.2f}</td><td>{s.max():.2f}</td>"
                f"<td>{s.std():.2f}</td></tr>"
            )
        body += "</table></div>"

    # Time series chart
    if numeric_cols:
        try:
            from visualizer import plot_time_series

            src = _chart_to_base64(plot_time_series, df, numeric_cols)
            body += '<h2>Time Series</h2>'
            body += f'<img class="chart" src="{src}" alt="Time Series">'
        except Exception as exc:
            body += f"<p>Chart error: {exc}</p>"

    # Causal analysis
    try:
        from data_analyzer import CausalChainExtractor

        extractor = CausalChainExtractor()
        extractor.load_logs([csv_path])
        extractor.compute_correlations()
        extractor.detect_lag_correlations()
        extractor.build_causal_graph()

        if extractor.causal_chains:
            body += '<div class="card"><h2>Causal Chains</h2><ul>'
            for chain in extractor.causal_chains:
                trigger = chain.get("trigger", "Unknown")
                confidence = chain.get("confidence", 0)
                effects = chain.get("effects", [])
                eff_str = ", ".join(
                    f"{e.get('parameter', '?')} (lag={e.get('lag_frames', 0)})"
                    for e in effects
                )
                body += f"<li><strong>{trigger}</strong> (conf={confidence:.2f}): {eff_str}</li>"
            body += "</ul></div>"

        # Causal graph chart
        if extractor.causal_chains:
            from visualizer import plot_causal_graph

            src = _chart_to_base64(plot_causal_graph, extractor.causal_chains)
            body += '<h2>Causal Graph</h2>'
            body += f'<img class="chart" src="{src}" alt="Causal Graph">'

    except Exception as exc:
        body += f"<p>Analysis error: {exc}</p>"

    return _render(f"Sample: {genre.title()}", body)


# ---------------------------------------------------------------------------
# Live monitoring helpers
# ---------------------------------------------------------------------------

CAPTURES_DIR = Path("captures")


def _find_active_session() -> tuple[Path | None, "pd.DataFrame | None"]:
    """Find the most recently modified ``*_agent.csv`` in *LOG_DIR*.

    Returns ``(csv_path, dataframe)`` or ``(None, None)`` when no matching
    file is found.
    """
    import pandas as pd

    candidates = sorted(LOG_DIR.glob("*_agent.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None, None
    csv_path = candidates[0]
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None, None
    return csv_path, df


def _compute_param_stats(df: "pd.DataFrame", parameters: list[str]) -> dict[str, dict]:
    """Compute per-parameter stats for the monitor view.

    Returns a dict mapping parameter name → {value, delta, min, max, mean, trend}.
    """
    stats: dict[str, dict] = {}
    for param in parameters:
        col = df[param]
        current = col.iloc[-1]
        previous = col.iloc[-2] if len(col) >= 2 else current
        delta = float(current - previous)

        # Trend from last 20 rows
        trend = "~"
        tail = col.tail(20)
        if len(tail) >= 3:
            diffs = tail.diff().dropna()
            pos = int((diffs > 0).sum())
            neg = int((diffs < 0).sum())
            total = pos + neg
            if total > 0:
                if pos / total >= 0.65:
                    trend = "\u2191"  # ↑
                elif neg / total >= 0.65:
                    trend = "\u2193"  # ↓
                elif pos / total >= 0.35 and neg / total >= 0.35:
                    trend = "\u2195"  # ↕ (volatile)
                else:
                    trend = "\u2192"  # → (stable)

        stats[param] = {
            "value": float(current),
            "delta": delta,
            "min": float(col.min()),
            "max": float(col.max()),
            "mean": float(col.mean()),
            "trend": trend,
        }
    return stats


def _extract_monitor_data(csv_path: Path, df: "pd.DataFrame") -> dict:
    """Build the monitor data dict used by both HTML and JSON endpoints."""
    import re
    import pandas as pd

    _FIXED = {"timestamp", "step", "action", "reasoning", "observations"}
    parameters = [
        c for c in df.columns
        if c not in _FIXED and pd.api.types.is_numeric_dtype(df[c])
    ]

    # Parse game_id from filename
    m = re.match(r"^(\d{8}_\d{6})_(.+)_agent\.csv$", csv_path.name)
    game_id = m.group(2) if m else "unknown"
    timestamp_str = m.group(1) if m else ""

    # Duration
    duration = 0.0
    if len(df) >= 2 and "timestamp" in df.columns:
        try:
            ts = pd.to_datetime(df["timestamp"])
            duration = (ts.iloc[-1] - ts.iloc[0]).total_seconds()
        except Exception:
            pass

    # Latest step
    latest_row = df.iloc[-1].to_dict() if len(df) > 0 else {}

    # Parameter stats
    param_stats = _compute_param_stats(df, parameters) if parameters else {}

    # Recent actions (last 20 rows)
    recent = df.tail(20).to_dict(orient="records")

    return {
        "active": True,
        "csv_filename": csv_path.name,
        "game_id": game_id,
        "timestamp": timestamp_str,
        "total_steps": len(df),
        "duration_seconds": duration,
        "parameters": parameters,
        "latest_step": latest_row,
        "param_stats": param_stats,
        "recent_actions": recent,
    }


# ---------------------------------------------------------------------------
# Routes: Live monitoring
# ---------------------------------------------------------------------------

@app.get("/monitor", response_class=HTMLResponse)
async def monitor():
    """Live monitoring page — auto-refreshes every 5 seconds."""
    csv_path, df = _find_active_session()
    if csv_path is None or df is None or df.empty:
        body = (
            '<meta http-equiv="refresh" content="5">'
            "<h1>Live Monitor</h1>"
            '<div class="card"><p>No active session found. '
            f"Watching <code>{LOG_DIR}</code> for *_agent.csv files&hellip;</p></div>"
        )
        return _render("Monitor", body)

    data = _extract_monitor_data(csv_path, df)

    body = '<meta http-equiv="refresh" content="5">'
    body += "<h1>Live Monitor</h1>"

    # Session info bar
    body += '<div class="card">'
    body += f"<p><strong>Session:</strong> {data['csv_filename']}</p>"
    body += f"<p><strong>Game ID:</strong> {data['game_id']}</p>"
    body += f"<p><strong>Steps:</strong> {data['total_steps']}</p>"
    body += f"<p><strong>Duration:</strong> {data['duration_seconds']:.1f}s</p>"
    body += (
        f'<a class="btn" href="/session/{data["csv_filename"]}">Full Session Detail</a> '
        f'<a class="btn" href="/session/{data["csv_filename"]}/actions">Action Analysis</a>'
    )
    body += "</div>"

    # Latest step card
    latest = data["latest_step"]
    body += '<div class="card"><h2>Latest Step</h2>'
    body += f"<p><strong>Step:</strong> {latest.get('step', '')}</p>"
    body += f"<p><strong>Action:</strong> {latest.get('action', '')}</p>"
    body += f"<p><strong>Reasoning:</strong> {latest.get('reasoning', '')}</p>"
    body += f"<p><strong>Observations:</strong> {latest.get('observations', '')}</p>"
    body += "</div>"

    # Parameter dashboard
    if data["param_stats"]:
        body += '<div class="card"><h2>Parameters</h2>'
        body += "<table><tr><th>Parameter</th><th>Value</th><th>Delta</th>"
        body += "<th>Min</th><th>Max</th><th>Mean</th><th>Trend</th></tr>"
        for param, st in data["param_stats"].items():
            delta_color = ""
            if st["delta"] > 0:
                delta_color = ' style="color:green"'
            elif st["delta"] < 0:
                delta_color = ' style="color:red"'
            body += (
                f"<tr><td>{param}</td>"
                f"<td>{st['value']:.2f}</td>"
                f"<td{delta_color}>{st['delta']:+.2f}</td>"
                f"<td>{st['min']:.2f}</td>"
                f"<td>{st['max']:.2f}</td>"
                f"<td>{st['mean']:.2f}</td>"
                f"<td>{st['trend']}</td></tr>"
            )
        body += "</table></div>"

    # Screenshot
    body += '<div class="card"><h2>Screenshot</h2>'
    body += '<img class="chart" src="/api/monitor/screenshot" alt="Live screenshot" '
    body += 'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\'">'
    body += '<p style="display:none">No live screenshot available.</p>'
    body += "</div>"

    # Recent actions table
    if data["recent_actions"]:
        body += '<div class="card"><h2>Recent Actions (last 20)</h2>'
        cols = list(data["recent_actions"][0].keys())
        body += "<table><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
        for row in data["recent_actions"]:
            body += "<tr>" + "".join(f"<td>{row.get(c, '')}</td>" for c in cols) + "</tr>"
        body += "</table></div>"

    return _render("Monitor", body)


@app.get("/api/monitor")
async def api_monitor():
    """JSON API: live session data for programmatic access."""
    csv_path, df = _find_active_session()
    if csv_path is None or df is None or df.empty:
        return JSONResponse(content={"active": False})

    data = _extract_monitor_data(csv_path, df)
    # Sanitise NaN values for JSON serialisation
    import math
    def _sanitise(obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: _sanitise(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitise(v) for v in obj]
        return obj
    return JSONResponse(content=_sanitise(data))


@app.get("/api/monitor/screenshot")
async def api_monitor_screenshot():
    """Return the latest screenshot from the captures directory."""
    captures = CAPTURES_DIR
    candidates = []
    if captures.is_dir():
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            candidates.extend(captures.glob(ext))
    if not candidates:
        raise HTTPException(status_code=404, detail="No screenshot available")

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    media = "image/jpeg" if latest.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return Response(content=latest.read_bytes(), media_type=media)


# ---------------------------------------------------------------------------
# Routes: Session Tags API
# ---------------------------------------------------------------------------

@app.get("/api/session/{csv_filename}/tags")
async def api_get_tags(csv_filename: str):
    """JSON API: get tags for a session."""
    from session_tagger import SessionTagger

    tagger = SessionTagger(log_dir=LOG_DIR)
    tags = tagger.get_tags(csv_filename)
    return JSONResponse(content={"csv_filename": csv_filename, "tags": tags})


@app.post("/api/session/{csv_filename}/tags")
async def api_post_tags(csv_filename: str, request: Request):
    """Add or remove tags for a session.

    Accepts form data or JSON with ``action`` (tag/untag) and ``tags``
    (comma-separated string or list).  Returns updated tags and redirects
    to the session detail page when submitted from a browser form.
    """
    from session_tagger import SessionTagger

    tagger = SessionTagger(log_dir=LOG_DIR)

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        action = body.get("action", "tag")
        raw_tags = body.get("tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        form = await request.form()
        action = form.get("action", "tag")
        raw_tags_str = form.get("tags", "")
        raw_tags = [t.strip() for t in raw_tags_str.split(",") if t.strip()]

    if action == "untag":
        result = tagger.untag(csv_filename, *raw_tags)
    else:
        result = tagger.tag(csv_filename, *raw_tags)

    # If request came from a form, redirect back to session detail
    if "application/json" not in content_type:
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=f"/session/{csv_filename}", status_code=303)

    return JSONResponse(content={"csv_filename": csv_filename, "tags": result})


# ---------------------------------------------------------------------------
# Routes: Session Notes API
# ---------------------------------------------------------------------------

@app.get("/api/session/{csv_filename}/notes")
async def api_get_notes(csv_filename: str):
    """JSON API: get note for a session."""
    from session_tagger import SessionTagger

    tagger = SessionTagger(log_dir=LOG_DIR)
    note = tagger.get_note(csv_filename)
    return JSONResponse(content={"csv_filename": csv_filename, "note": note})


@app.post("/api/session/{csv_filename}/notes")
async def api_post_notes(csv_filename: str, request: Request):
    """Set or delete note for a session.

    Accepts form data or JSON with ``note`` field.  Empty note deletes it.
    Redirects to session detail when submitted from a browser form.
    """
    from session_tagger import SessionTagger

    tagger = SessionTagger(log_dir=LOG_DIR)

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        note_text = body.get("note", "")
    else:
        form = await request.form()
        note_text = form.get("note", "")

    result = tagger.set_note(csv_filename, note_text)

    if "application/json" not in content_type:
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=f"/session/{csv_filename}", status_code=303)

    return JSONResponse(content={"csv_filename": csv_filename, "note": result})


# ---------------------------------------------------------------------------
# Routes: JSON API
# ---------------------------------------------------------------------------

@app.get("/api/sessions")
async def api_sessions():
    """JSON API: list all sessions."""
    from session_replay import SessionData

    sessions = SessionData.discover_sessions(LOG_DIR)
    return JSONResponse(content=[
        {
            "csv_filename": s.csv_path.name,
            "timestamp": s.timestamp,
            "game_id": s.game_id,
            "total_steps": s.total_steps,
            "cost_usd": s.cost_usd,
            "duration_seconds": s.duration_seconds,
            "parameters": s.parameters,
        }
        for s in sessions
    ])


@app.get("/api/sessions/search")
async def api_sessions_search(request: Request):
    """JSON API: search/filter sessions."""
    from session_search import ParamCondition, SessionSearch

    param_strs = request.query_params.getlist("param")
    conditions = []
    for p in param_strs:
        try:
            conditions.append(ParamCondition.parse(p))
        except ValueError:
            pass

    steps = request.query_params.get("steps", "").strip()
    min_steps = max_steps = None
    if steps and "-" in steps:
        parts = steps.split("-", 1)
        min_steps = int(parts[0]) if parts[0].strip() else None
        max_steps = int(parts[1]) if parts[1].strip() else None

    date = request.query_params.get("date", "").strip()
    date_from = date_to = None
    if date and "-" in date:
        parts = date.split("-", 1)
        date_from = parts[0].strip() if parts[0].strip() else None
        date_to = parts[1].strip() if parts[1].strip() else None

    tag = request.query_params.get("tag", "").strip() or None
    note = request.query_params.get("note", "").strip() or None

    searcher = SessionSearch(
        log_dir=LOG_DIR,
        param_conditions=conditions,
        min_steps=min_steps,
        max_steps=max_steps,
        date_from=date_from,
        date_to=date_to,
        tag=tag,
        note_query=note,
    )
    results = searcher.search()

    return JSONResponse(content={
        "criteria": searcher.to_dict(),
        "count": len(results),
        "sessions": [
            {
                "csv_filename": s.csv_path.name,
                "timestamp": s.timestamp,
                "game_id": s.game_id,
                "total_steps": s.total_steps,
                "cost_usd": s.cost_usd,
            }
            for s in results
        ],
    })


@app.get("/api/sessions/ranking")
async def api_sessions_ranking():
    """JSON API: score and rank all sessions."""
    from session_replay import SessionData
    from session_scorer import SessionScorer

    sessions = SessionData.discover_sessions(LOG_DIR)
    scorer = SessionScorer()
    ranking = scorer.rank_sessions(sessions)
    return JSONResponse(content=ranking)


@app.get("/api/session/{csv_filename}")
async def api_session_detail(csv_filename: str):
    """JSON API: single session detail."""
    session = _load_session(csv_filename)
    return JSONResponse(content={
        "csv_filename": session.csv_path.name,
        "timestamp": session.timestamp,
        "game_id": session.game_id,
        "total_steps": session.total_steps,
        "cost_usd": session.cost_usd,
        "duration_seconds": session.duration_seconds,
        "parameters": session.parameters,
        "session_info": session.session_info,
    })


@app.get("/api/session/{csv_filename}/data")
async def api_session_data(csv_filename: str):
    """JSON API: full CSV data as JSON."""
    session = _load_session(csv_filename)
    records = session.df.to_dict(orient="records")
    return JSONResponse(content={
        "csv_filename": session.csv_path.name,
        "total_rows": len(records),
        "columns": list(session.df.columns),
        "data": records,
    })


@app.get("/api/cross-analysis")
async def api_cross_analysis(request: Request):
    """JSON API: cross-session analysis results."""
    from cross_session_analyzer import CrossSessionAnalyzer
    from session_replay import SessionData

    game_filter = request.query_params.get("game")
    sessions = SessionData.discover_sessions(LOG_DIR, game_id=game_filter)
    if not sessions:
        return JSONResponse(content={"session_count": 0, "error": "No sessions found"})

    analyzer = CrossSessionAnalyzer(sessions)
    return JSONResponse(content=analyzer.to_dict())


@app.get("/api/optimize")
async def api_optimize(request: Request):
    """JSON API: strategy optimisation results."""
    from session_replay import SessionData
    from strategy_optimizer import StrategyOptimizer

    strategy_name = request.query_params.get("strategy")
    if not strategy_name:
        # List available strategies
        strat_dir = Path("config/strategies")
        files = sorted(strat_dir.glob("*.json")) if strat_dir.is_dir() else []
        return JSONResponse(content={"strategies": [f.name for f in files]})

    strat_path = Path("config/strategies") / strategy_name
    if not strat_path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_name}")

    sessions = SessionData.discover_sessions(LOG_DIR)
    if not sessions:
        return JSONResponse(content={"error": "No sessions found"})

    import json as _json
    config = _json.loads(strat_path.read_text())
    optimizer = StrategyOptimizer(config, sessions)
    optimized = optimizer.optimize()
    clean = {k: v for k, v in optimized.items() if not k.startswith("_")}
    return JSONResponse(content={
        "original": config,
        "optimized": clean,
        "diff": optimizer.diff(),
        "notes": optimized.get("_optimization_notes", []),
    })


# ---------------------------------------------------------------------------
# Routes: Action Recommendations
# ---------------------------------------------------------------------------

@app.get("/session/{csv_filename}/recommend", response_class=HTMLResponse)
async def session_recommend(csv_filename: str):
    """Action recommendation page — top actions based on historical data."""
    from action_recommender import ActionRecommender
    from session_replay import SessionData

    session = _load_session(csv_filename)
    training = SessionData.discover_sessions(LOG_DIR)

    body = f"<h1>Action Recommendations: {session.timestamp}</h1>"

    if not training:
        body += "<p>No training sessions available.</p>"
        body += f'<p><a class="btn" href="/session/{csv_filename}">Back to Session</a></p>'
        return _render(f"Recommend: {session.timestamp}", body)

    recommender = ActionRecommender(training, top_n=5)
    data = recommender.to_dict(session)

    # Parameter weights
    body += '<div class="card"><h2>Parameter Urgency</h2>'
    body += "<table><tr><th>Parameter</th><th>Weight</th><th>Priority</th></tr>"
    for param, w in data["param_weights"].items():
        if w >= 2.0:
            priority = "HIGH"
            color = "red"
        elif w >= 1.5:
            priority = "MEDIUM"
            color = "#fb8c00"
        else:
            priority = "normal"
            color = "gray"
        body += (
            f"<tr><td>{param}</td><td>{w}</td>"
            f'<td style="color:{color};font-weight:bold">{priority}</td></tr>'
        )
    body += "</table></div>"

    # Recommendations
    body += '<div class="card"><h2>Top Recommendations</h2>'
    for rec in data["recommendations"]:
        score_color = "green" if rec["score"] > 0 else ("red" if rec["score"] < 0 else "gray")
        body += f'<div style="border-left:4px solid {score_color};padding:8px 16px;margin:8px 0;">'
        body += f'<h3>#{rec["rank"]}: {rec["action"]} '
        body += f'<span style="color:{score_color}">(score: {rec["score"]})</span></h3>'
        body += f'<p><strong>Reason:</strong> {rec["reason"]}</p>'
        if rec["param_impacts"]:
            body += "<table><tr><th>Parameter</th><th>Expected Delta</th></tr>"
            for p, d in rec["param_impacts"].items():
                d_color = "green" if d > 0 else ("red" if d < 0 else "gray")
                body += f'<tr><td>{p}</td><td style="color:{d_color}">{d:+.4f}</td></tr>'
            body += "</table>"
        body += "</div>"
    body += "</div>"

    body += (
        f'<p><a class="btn" href="/session/{csv_filename}">Back to Session</a></p>'
    )

    return _render(f"Recommend: {session.timestamp}", body)


@app.get("/api/session/{csv_filename}/recommend")
async def api_session_recommend(csv_filename: str):
    """JSON API: action recommendations for a session."""
    from action_recommender import ActionRecommender
    from session_replay import SessionData

    session = _load_session(csv_filename)
    training = SessionData.discover_sessions(LOG_DIR)

    if not training:
        return JSONResponse(content={
            "session": session.timestamp,
            "recommendations": [],
            "error": "No training sessions available",
        })

    recommender = ActionRecommender(training, top_n=5)
    return JSONResponse(content=recommender.to_dict(session))


# ---------------------------------------------------------------------------
# Routes: Parameter Prediction
# ---------------------------------------------------------------------------

@app.get("/session/{csv_filename}/predict", response_class=HTMLResponse)
async def session_predict(csv_filename: str):
    """Prediction page — per-parameter charts, regression summary, threshold table."""
    from parameter_predictor import ParameterPredictor, plot_prediction

    session = _load_session(csv_filename)
    predictor = ParameterPredictor(session)

    body = f"<h1>Parameter Predictions: {session.timestamp}</h1>"

    # Regression summary
    body += '<div class="card"><h2>Regression Summary</h2>'
    body += "<table><tr><th>Parameter</th><th>Slope</th><th>Intercept</th>"
    body += "<th>R&sup2;</th><th>Trend</th></tr>"
    for param in session.parameters:
        reg = predictor.linear_regression(param)
        trend = "rising" if reg["slope"] > 0 else ("falling" if reg["slope"] < 0 else "flat")
        color = "green" if trend == "rising" else ("red" if trend == "falling" else "gray")
        body += (
            f"<tr><td>{param}</td><td>{reg['slope']:.4f}</td>"
            f"<td>{reg['intercept']:.4f}</td><td>{reg['r_squared']:.4f}</td>"
            f'<td style="color:{color}">{trend}</td></tr>'
        )
    body += "</table></div>"

    # Threshold predictions
    thresholds = predictor.predict_all_thresholds()
    body += '<div class="card"><h2>Threshold Predictions</h2>'
    body += "<table><tr><th>Parameter</th><th>Threshold</th><th>Direction</th>"
    body += "<th>Est. Step</th><th>Current</th><th>Slope</th></tr>"
    for t in thresholds:
        est = str(t["estimated_step"]) if t["estimated_step"] is not None else "N/A"
        body += (
            f"<tr><td>{t['parameter']}</td><td>{t['threshold']:.2f}</td>"
            f"<td>{t['direction']}</td><td>{est}</td>"
            f"<td>{t['current_value']:.2f}</td><td>{t['slope']:.4f}</td></tr>"
        )
    body += "</table></div>"

    # Per-parameter prediction charts
    if session.parameters:
        body += '<div class="card"><h2>Prediction Charts</h2>'
        for param in session.parameters:
            try:
                src = _chart_to_base64(
                    plot_prediction, predictor, param, 20,
                )
                body += f'<h3>{param}</h3>'
                body += f'<img class="chart" src="{src}" alt="Prediction: {param}">'
            except Exception as exc:
                body += f"<p>Chart error for {param}: {exc}</p>"
        body += "</div>"

    body += (
        f'<p><a class="btn" href="/session/{csv_filename}">Back to Session</a></p>'
    )

    return _render(f"Predictions: {session.timestamp}", body)


@app.get("/api/session/{csv_filename}/predict")
async def api_session_predict(csv_filename: str):
    """JSON API: parameter predictions for a session."""
    from parameter_predictor import ParameterPredictor

    session = _load_session(csv_filename)
    predictor = ParameterPredictor(session)
    return JSONResponse(content=predictor.to_dict())


@app.get("/api/session/{csv_filename}/timeline")
async def api_session_timeline(csv_filename: str):
    """JSON API: session timeline data (actions + parameters per step)."""
    import pandas as pd

    from session_replay import SessionData, _FIXED_COLUMNS

    session = _load_session(csv_filename)
    df = session.df
    params = session.parameters

    steps: list[dict] = []
    for _, row in df.iterrows():
        entry: dict = {
            "step": int(row.get("step", 0)),
            "action": str(row.get("action", "")),
        }
        for p in params:
            if p in row:
                entry[p] = float(row[p]) if pd.notna(row[p]) else None
        steps.append(entry)

    # Strategy switches from session_info
    info = session.session_info or {}
    switches = info.get("strategy_switches", [])

    # Action summary
    action_counts: dict[str, int] = {}
    if "action" in df.columns:
        for a, cnt in df["action"].value_counts().items():
            action_counts[str(a)] = int(cnt)

    return JSONResponse(content={
        "csv_filename": csv_filename,
        "session": session.timestamp,
        "total_steps": session.total_steps,
        "parameters": params,
        "actions": sorted(action_counts.keys()),
        "action_counts": action_counts,
        "strategy_switches": switches if isinstance(switches, list) else [],
        "steps": steps,
    })


# ---------------------------------------------------------------------------
# Routes: Alert Notifier
# ---------------------------------------------------------------------------

def _notifier_config_path() -> Path:
    """Default path for the notifier config file."""
    return LOG_DIR / "alert_notifier.json"


@app.get("/notifier", response_class=HTMLResponse)
async def notifier_page():
    """Alert notifier configuration and status page."""
    from alert_notifier import AlertNotifier

    body = "<h1>Alert Notifier</h1>"

    config_path = _notifier_config_path()
    if config_path.exists():
        notifier = AlertNotifier.from_config_file(config_path)
        body += '<div class="card"><h2>Webhook Configuration</h2>'
        if notifier.webhooks:
            body += "<table><tr><th>Name</th><th>Backend</th><th>Enabled</th>"
            body += "<th>Min Severity</th><th>URL</th></tr>"
            for w in notifier.webhooks:
                name = w.name or "(unnamed)"
                enabled_style = "color:green" if w.enabled else "color:red"
                body += (
                    f"<tr><td>{name}</td><td>{w.backend}</td>"
                    f'<td style="{enabled_style}">{w.enabled}</td>'
                    f"<td>{w.min_severity}</td>"
                    f"<td><code>{w.url[:40]}...</code></td></tr>"
                )
            body += "</table>"
        else:
            body += "<p>No webhooks configured.</p>"
        body += "</div>"
    else:
        body += '<div class="card"><p>No notifier config found at '
        body += f"<code>{config_path}</code>.</p>"
        body += "<p>Create a config file with webhook definitions. Example:</p>"
        body += '<pre>{"webhooks": [{"backend": "slack", "url": "https://hooks.slack.com/...", '
        body += '"enabled": true, "min_severity": "medium", "name": "my-slack"}]}</pre>'
        body += "</div>"

    # Test send form
    body += '<div class="card"><h2>Test Notification</h2>'
    body += '<form method="post" action="/api/notifier/test">'
    body += '<button class="btn" type="submit">Send Test Alert</button>'
    body += "</form></div>"

    return _render("Alert Notifier", body)


@app.get("/api/notifier/config")
async def api_notifier_config_get():
    """GET notifier webhook configuration."""
    from alert_notifier import AlertNotifier

    config_path = _notifier_config_path()
    if not config_path.exists():
        return JSONResponse(content={"webhooks": [], "configured": False})
    notifier = AlertNotifier.from_config_file(config_path)
    return JSONResponse(content={
        "webhooks": [w.to_dict() for w in notifier.webhooks],
        "configured": True,
    })


@app.post("/api/notifier/config")
async def api_notifier_config_post(request: Request):
    """POST to update notifier webhook configuration."""
    from alert_notifier import AlertNotifier, WebhookConfig

    body = await request.json()
    webhooks_data = body.get("webhooks", [])
    webhooks = [WebhookConfig.from_dict(w) for w in webhooks_data]
    notifier = AlertNotifier(webhooks)
    notifier.save_config(_notifier_config_path())
    return JSONResponse(content={
        "webhooks": [w.to_dict() for w in notifier.webhooks],
        "saved": True,
    })


@app.post("/api/notifier/test")
async def api_notifier_test():
    """Send a test alert to all configured webhooks."""
    from alert_notifier import AlertMessage, AlertNotifier
    from datetime import datetime

    config_path = _notifier_config_path()
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="No notifier config found")

    notifier = AlertNotifier.from_config_file(config_path)
    test_alert = AlertMessage(
        severity="low",
        title="Test Alert",
        description="Test notification from PS1 AI Player dashboard.",
        source="test",
        timestamp=datetime.now().isoformat(),
    )
    result = notifier.send_all([test_alert])
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Routes: Parameter Dashboard
# ---------------------------------------------------------------------------

@app.get("/parameters", response_class=HTMLResponse)
async def parameters_page(request: Request):
    """Cross-session parameter correlation dashboard.

    Shows correlation heatmap, distribution histograms, and per-parameter
    mean-trend lines across all sessions.
    """
    import pandas as pd

    from data_analyzer import CausalChainExtractor
    from session_replay import SessionData

    game_filter = request.query_params.get("game")
    sessions = SessionData.discover_sessions(LOG_DIR, game_id=game_filter)

    body = "<h1>Parameter Dashboard</h1>"

    # Game filter form
    all_sessions = SessionData.discover_sessions(LOG_DIR)
    game_ids = sorted({s.game_id for s in all_sessions})
    if game_ids:
        body += '<form method="get"><label>Game: <select name="game">'
        body += '<option value="">All</option>'
        for gid in game_ids:
            sel = ' selected' if gid == game_filter else ''
            body += f'<option value="{gid}"{sel}>{gid}</option>'
        body += '</select></label> <button class="btn" type="submit">Filter</button></form>'

    if not sessions:
        body += f"<p>No sessions found in <code>{LOG_DIR}</code>.</p>"
        return _render("Parameters", body)

    body += f"<p>Analyzing {len(sessions)} session(s).</p>"

    # Collect all numeric parameters and their pooled values
    all_params: list[str] = []
    seen: set[str] = set()
    for s in sessions:
        for p in s.parameters:
            if p not in seen:
                all_params.append(p)
                seen.add(p)

    if not all_params:
        body += "<p>No numeric parameters found in sessions.</p>"
        return _render("Parameters", body)

    # --- 1. Correlation heatmap via CausalChainExtractor ---
    csv_paths = [s.csv_path for s in sessions]
    extractor = CausalChainExtractor()
    extractor.load_logs(csv_paths)
    corr_matrix = extractor.compute_correlations()

    if not corr_matrix.empty:
        body += '<div class="card"><h2>Correlation Heatmap</h2>'
        try:
            src = _correlation_heatmap_to_base64(corr_matrix)
            body += f'<img src="{src}" alt="Correlation heatmap" style="max-width:100%;">'
        except Exception:
            body += "<p>Could not generate correlation heatmap.</p>"
        body += "</div>"

    # --- 2. Parameter distribution histograms ---
    all_values: dict[str, list[float]] = {}
    for param in all_params:
        vals: list[float] = []
        for s in sessions:
            if param in s.df.columns:
                vals.extend(s.df[param].dropna().astype(float).tolist())
        if vals:
            all_values[param] = vals

    if all_values:
        body += '<div class="card"><h2>Parameter Distributions</h2>'
        try:
            src = _histogram_to_base64(all_values)
            body += f'<img src="{src}" alt="Parameter distributions" style="max-width:100%;">'
        except Exception:
            body += "<p>Could not generate histograms.</p>"
        body += "</div>"

    # --- 3. Per-parameter trend lines across sessions ---
    if len(sessions) >= 2:
        body += '<div class="card"><h2>Parameter Trends Across Sessions</h2>'
        for param in all_params:
            try:
                src = _param_trend_to_base64(sessions, param)
                body += f'<h3>{param}</h3>'
                body += f'<img src="{src}" alt="{param} trend" style="max-width:100%;margin-bottom:12px;">'
            except Exception:
                pass
        body += "</div>"

    # --- 4. Lag correlations summary ---
    if not corr_matrix.empty:
        extractor.detect_lag_correlations()
        lag_corrs = extractor.lag_correlations
        if lag_corrs:
            body += '<div class="card"><h2>Lag Correlations</h2>'
            body += "<table><tr><th>Source</th><th>Target</th><th>Lag</th>"
            body += "<th>Correlation</th><th>p-value</th></tr>"
            for _key, lc in lag_corrs.items():
                corr_val = lc["correlation"]
                color = "green" if corr_val > 0 else "red"
                body += (
                    f"<tr><td>{lc['source']}</td><td>{lc['target']}</td>"
                    f"<td>{lc['lag']}</td>"
                    f'<td style="color:{color}">{corr_val:.4f}</td>'
                    f"<td>{lc['p_value']:.6f}</td></tr>"
                )
            body += "</table></div>"

    return _render("Parameters", body)


@app.get("/api/parameters/correlations")
async def api_parameters_correlations(request: Request):
    """JSON API: cross-session parameter correlation matrix and lag correlations."""
    import pandas as pd

    from data_analyzer import CausalChainExtractor
    from session_replay import SessionData

    game_filter = request.query_params.get("game")
    sessions = SessionData.discover_sessions(LOG_DIR, game_id=game_filter)

    if not sessions:
        return JSONResponse(content={
            "session_count": 0, "correlation_matrix": {}, "lag_correlations": {},
        })

    csv_paths = [s.csv_path for s in sessions]
    extractor = CausalChainExtractor()
    extractor.load_logs(csv_paths)
    corr_matrix = extractor.compute_correlations()
    extractor.detect_lag_correlations()

    # Per-param stats across sessions
    param_stats: dict[str, dict] = {}
    all_params: list[str] = []
    seen: set[str] = set()
    for s in sessions:
        for p in s.parameters:
            if p not in seen:
                all_params.append(p)
                seen.add(p)

    for param in all_params:
        vals: list[float] = []
        per_session: list[dict] = []
        for s in sessions:
            if param in s.df.columns:
                col = s.df[param].dropna().astype(float)
                vals.extend(col.tolist())
                per_session.append({
                    "session": s.timestamp,
                    "mean": round(float(col.mean()), 4),
                    "min": round(float(col.min()), 4),
                    "max": round(float(col.max()), 4),
                    "std": round(float(col.std()), 4),
                })
        if vals:
            param_stats[param] = {
                "global_mean": round(float(pd.Series(vals).mean()), 4),
                "global_std": round(float(pd.Series(vals).std()), 4),
                "sessions": per_session,
            }

    return JSONResponse(content={
        "session_count": len(sessions),
        "parameters": all_params,
        "correlation_matrix": corr_matrix.round(4).to_dict() if not corr_matrix.empty else {},
        "lag_correlations": extractor.lag_correlations,
        "param_stats": param_stats,
    })


# ---------------------------------------------------------------------------
# Routes: Batch Reports
# ---------------------------------------------------------------------------

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Batch report page — generate or view comprehensive analysis reports."""
    from session_replay import SessionData

    sessions = SessionData.discover_sessions(LOG_DIR)

    body = "<h1>Batch Reports</h1>"

    # Report generation form
    body += '<div class="card"><h2>Generate Report</h2>'
    body += '<form method="post" action="/api/reports/generate">'
    body += '<label>Format: <select name="format">'
    body += '<option value="markdown">Markdown</option>'
    body += '<option value="json">JSON</option>'
    body += '<option value="html">HTML</option>'
    body += '</select></label> '

    # Game filter
    game_ids = sorted({s.game_id for s in sessions})
    if game_ids:
        body += '<label>Game: <select name="game">'
        body += '<option value="">All</option>'
        for gid in game_ids:
            body += f'<option value="{gid}">{gid}</option>'
        body += '</select></label> '

    body += '<button class="btn" type="submit">Generate</button>'
    body += '</form></div>'

    body += f"<p>Available sessions: {len(sessions)}</p>"

    # Show last generated report if it exists
    report_path = REPORTS_DIR / "batch_report.md"
    if report_path.exists():
        content = report_path.read_text()
        # Simple markdown rendering
        rendered_lines: list[str] = []
        for line in content.split("\n"):
            if line.startswith("### "):
                rendered_lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("## "):
                rendered_lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("# "):
                rendered_lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("- "):
                rendered_lines.append(f"<li>{line[2:]}</li>")
            elif line.startswith("|"):
                rendered_lines.append(f"<p><code>{line}</code></p>")
            elif line.strip() == "":
                rendered_lines.append("<br>")
            else:
                rendered_lines.append(f"<p>{line}</p>")
        body += '<div class="card"><h2>Last Report</h2>'
        body += "".join(rendered_lines)
        body += "</div>"

    return _render("Reports", body)


@app.post("/api/reports/generate")
async def api_reports_generate(request: Request):
    """Generate a batch report and return it.

    Accepts form data or JSON with ``format`` (markdown/json/html) and
    optional ``game`` filter.  Saves a copy to REPORTS_DIR.
    """
    from batch_report import BatchReportGenerator
    from session_replay import SessionData

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        fmt = body.get("format", "markdown")
        game_filter = body.get("game") or None
    else:
        form = await request.form()
        fmt = form.get("format", "markdown")
        game_filter = form.get("game") or None

    sessions = SessionData.discover_sessions(LOG_DIR, game_id=game_filter)
    if not sessions:
        return JSONResponse(content={"error": "No sessions found"}, status_code=404)

    # Auto-detect strategy config
    strategy_config = None
    strat_dir = Path("config/strategies")
    if strat_dir.is_dir():
        files = sorted(strat_dir.glob("*.json"))
        if files:
            try:
                strategy_config = _json_mod.loads(files[0].read_text())
            except Exception:
                pass

    generator = BatchReportGenerator(sessions, strategy_config=strategy_config)

    if fmt == "json":
        output = generator.to_json()
        ext = ".json"
    elif fmt == "html":
        output = generator.to_html()
        ext = ".html"
    else:
        output = generator.to_markdown()
        ext = ".md"

    # Save to reports dir
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"batch_report{ext}"
    report_path.write_text(output)

    if fmt == "json":
        return JSONResponse(content=_json_mod.loads(output))
    elif fmt == "html":
        return HTMLResponse(content=output)
    else:
        # Redirect to /reports page for form submissions
        if "application/json" not in content_type:
            from starlette.responses import RedirectResponse
            return RedirectResponse(url="/reports", status_code=303)
        return JSONResponse(content={"report": output, "saved_to": str(report_path)})


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the dashboard server."""
    parser = argparse.ArgumentParser(description="PS1 AI Player Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--log-dir", default="logs", help="Session log directory (default: logs)")
    parser.add_argument("--reports-dir", default="reports", help="Reports directory (default: reports)")
    parser.add_argument("--captures-dir", default="captures", help="Screenshot captures directory (default: captures)")
    args = parser.parse_args()

    global LOG_DIR, REPORTS_DIR, CAPTURES_DIR
    LOG_DIR = Path(args.log_dir)
    REPORTS_DIR = Path(args.reports_dir)
    CAPTURES_DIR = Path(args.captures_dir)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
