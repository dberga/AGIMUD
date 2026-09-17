#!/usr/bin/env python3
"""
SWM Plots Module - Timeline visualization and chart generation for the Simulated World.

Two roles:
  1. Standalone CLI: generates CSV + PNG timeline charts for ONE world folder.
  2. Reusable plotting library: exposes helper functions used by swm_analyze.py
     for cross-world comparisons.

Outputs (per-world CLI mode):
    CSV: actions_timeline.csv, emotions_timeline.csv, ai_states_timeline.csv,
         goals_timeline.csv, status_timeline.csv, *_matrix.csv, *_per_tick.csv
    JSON: timelines_snapshot.json
    PNG:  *_by_character.png, *_over_time.png, *_lineplot.png, *_heatmap.png
"""

import json
import os
import csv
import sys
import glob
import math
import atexit
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter, defaultdict

# Optional matplotlib imports
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    plt = None
    np = None
    mpatches = None


# ============================================================
# SHARED CONSTANTS (also used by swm_analyze.py)
# ============================================================

TIMELINE_MAP = {
    'action_counts':     ('action_timeline',     'action'),
    'emotion_counts':    ('emotion_timeline',    'emotion'),
    'goal_counts':       ('goal_timeline',       'goal'),
    'ai_state_counts':   ('ai_state_timeline',   'ai_state'),
}

_TIMELINE_MAP = TIMELINE_MAP

MATRIX_SPECS = [
    ('emotion_action_matrix',  'emotion',   'action',    'Emotion',   'Action',    'emotion_action'),
    ('action_emotion_matrix',  'action',    'emotion',   'Action',    'Emotion',   'action_emotion'),
    ('emotion_aistate_matrix', 'emotion',   'ai_state',  'Emotion',   'AI State',  'emotion_aistate'),
    ('action_aistate_matrix',  'action',    'ai_state',  'Action',    'AI State',  'action_aistate'),
    ('goal_emotion_matrix',    'goal',      'emotion',   'Goal',      'Emotion',   'goal_emotion'),
    ('goal_aistate_matrix',    'goal',      'ai_state',  'Goal',      'AI State',  'goal_aistate'),
]

_MATRIX_SPECS = MATRIX_SPECS

STATUS_VARS = ['Mean_Health', 'Mean_Stamina', 'Mean_Morale']
ACTIVITY_VARS = ['Actions_Total', 'Emotions_Total', 'Goals_Total', 'AI_States_Total',
                 'Distinct_Emotions', 'Distinct_Goals', 'Distinct_AI_States',
                 'Emotion_Transitions', 'Emotion_Entropy', 'Goal_Entropy',
                 'AI_State_Entropy']


OUTPUT_PNGS = [
    "actions_by_character.png",
    "aistates_by_character.png",
    "emotions_by_character.png",
    "goals_by_character.png",
    "actions_over_time.png",
    "aistates_over_time.png",
    "emotions_over_time.png",
    "goals_over_time.png",
    "actions_lineplot.png",
    "aistates_lineplot.png",
    "emotions_lineplot.png",
    "goals_lineplot.png",
    "emotion_action_heatmap.png",
    "emotion_aistate_heatmap.png",
    "action_aistate_heatmap.png",
    "goal_emotion_heatmap.png",
    "goal_aistate_heatmap.png",
]


# ============================================================
# SAFE STYLE HELPER (public)
# ============================================================

def safe_set_style(plt_module=None):
    """Try a few nice seaborn/ggplot styles, silently fall back."""
    plt_ = plt_module if plt_module is not None else plt
    if plt_ is None:
        return
    for style in ('seaborn-v0_8-darkgrid', 'seaborn-darkgrid', 'ggplot'):
        try:
            plt_.style.use(style)
            return
        except Exception:
            continue


def _safe_set_style(plt_module=None):
    return safe_set_style(plt_module)


# ============================================================
# REUSABLE PLOT HELPERS (used by swm_analyze.py)
# ============================================================

def plot_comparative_grouped_bars(aggregates, field, title, out_path,
                                  cmap_name='tab10', top_k=12):
    """Grouped bars per world for a given aggregate field (e.g. 'action_counts')."""
    if not aggregates or plt is None or np is None:
        return
    totals = defaultdict(int)
    for agg in aggregates:
        for cat, cnt in getattr(agg, field).items():
            totals[cat] += cnt
    if not totals:
        return
    top_categories = sorted(totals.items(), key=lambda x: -x[1])[:top_k]
    categories = [c for c, _ in top_categories]
    n_worlds = len(aggregates)
    n_cats = len(categories)
    bar_width = 0.8 / max(1, n_worlds)

    fig, ax = plt.subplots(figsize=(max(10, n_cats * 0.9), 6))
    x = np.arange(n_cats)
    cmap = plt.cm.get_cmap(cmap_name, max(10, n_worlds))      
    world_colors = {agg.world_name: cmap(i % 10) for i, agg in enumerate(aggregates)} 

    for i, agg in enumerate(aggregates):
        counts = getattr(agg, field)
        values = [counts.get(c, 0) for c in categories]
        ax.bar(x + i * bar_width, values, bar_width,
               label=agg.world_name, color=world_colors[agg.world_name])

    ax.set_xticks(x + bar_width * (n_worlds - 1) / 2)
    ax.set_xticklabels(categories, rotation=45, ha='right', fontsize=9)
    ax.set_ylabel('Total occurrences')
    ax.set_title(title)
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_comparative_lineplot_over_time(aggregates, field, title, out_path,
                                        cmap_name='tab20'):
    """One line per world: total observations per tick for the given field.

    NOTE: for emotions / AI states, this is often constant (= number of active
    characters). Prefer plot_comparative_entropy_over_time or
    plot_comparative_dominant_share_over_time for more informative views.
    """
    if not aggregates or plt is None or np is None:
        return
    if field not in TIMELINE_MAP:
        print(f"[WARN] plot_comparative_lineplot_over_time: unknown field '{field}'")
        return
    timeline_attr, _key = TIMELINE_MAP[field]

    fig, ax = plt.subplots(figsize=(14, 6))
    cmap = plt.cm.get_cmap(cmap_name, max(20, len(aggregates)))
    plotted = False
    for i, agg in enumerate(aggregates):
        if not getattr(agg, 'plotter', None):
            continue
        timeline = getattr(agg.plotter, timeline_attr, []) or []
        tick_totals = defaultdict(int)
        for entry in timeline:
            tick_totals[entry.get('tick', 0)] += 1
        if not tick_totals:
            continue
        ticks = sorted(tick_totals.keys())
        y = [tick_totals[t] for t in ticks]
        ax.plot(ticks, y, marker='o', markersize=3, linewidth=1.8,
                color=cmap(i % 20), label=agg.world_name, alpha=0.85)
        plotted = True
    if not plotted:
        plt.close()
        return
    ax.set_xlabel('Tick')
    ax.set_ylabel('Total observations')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_comparative_entropy_over_time(aggregates, field, title, out_path,
                                       cmap_name='tab10'):
    """
    Line plot per world: Shannon entropy (bits) of the category distribution
    computed at each tick, across the given timeline.

    Low entropy  -> one category dominates
    High entropy -> categories are spread out evenly
    """
    if not aggregates or plt is None or np is None:
        return
    if field not in TIMELINE_MAP:
        print(f"[WARN] plot_comparative_entropy_over_time: unknown field '{field}'")
        return
    timeline_attr, key_field = TIMELINE_MAP[field]

    fig, ax = plt.subplots(figsize=(14, 6))
    cmap = plt.cm.get_cmap(cmap_name, max(10, len(aggregates)))
    plotted = False
    for i, agg in enumerate(aggregates):
        if not getattr(agg, 'plotter', None):
            continue
        timeline = getattr(agg.plotter, timeline_attr, []) or []
        tick_cat = defaultdict(lambda: defaultdict(int))
        for entry in timeline:
            tick_cat[entry.get('tick', 0)][entry.get(key_field, 'Unknown')] += 1
        if not tick_cat:
            continue
        ticks = sorted(tick_cat.keys())
        ys = []
        for t in ticks:
            counts = list(tick_cat[t].values())
            total = sum(counts)
            if total == 0:
                ys.append(0.0)
                continue
            probs = [c / total for c in counts if c > 0]
            H = -sum(p * math.log2(p) for p in probs)
            ys.append(H)
        ax.plot(ticks, ys, linewidth=1.8, color=cmap(i % 10),
                label=agg.world_name, alpha=0.85)
        plotted = True
    if not plotted:
        plt.close()
        return
    ax.set_xlabel('Tick')
    ax.set_ylabel('Shannon entropy (bits)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_comparative_dominant_share_over_time(aggregates, field, title, out_path,
                                              cmap_name='tab10'):
    """
    Line plot per world: share (0..1) of the most frequent category at each tick.
    """
    if not aggregates or plt is None or np is None:
        return
    if field not in TIMELINE_MAP:
        print(f"[WARN] plot_comparative_dominant_share_over_time: unknown field '{field}'")
        return
    timeline_attr, key_field = TIMELINE_MAP[field]

    fig, ax = plt.subplots(figsize=(14, 6))
    cmap = plt.cm.get_cmap(cmap_name, max(10, len(aggregates)))
    plotted = False
    for i, agg in enumerate(aggregates):
        if not getattr(agg, 'plotter', None):
            continue
        timeline = getattr(agg.plotter, timeline_attr, []) or []
        tick_cat = defaultdict(lambda: defaultdict(int))
        for entry in timeline:
            tick_cat[entry.get('tick', 0)][entry.get(key_field, 'Unknown')] += 1
        if not tick_cat:
            continue
        ticks = sorted(tick_cat.keys())
        ys = []
        for t in ticks:
            counts = list(tick_cat[t].values())
            total = sum(counts)
            ys.append((max(counts) / total) if total > 0 else 0.0)
        ax.plot(ticks, ys, linewidth=1.8, color=cmap(i % 10),
                label=agg.world_name, alpha=0.85)
        plotted = True
    if not plotted:
        plt.close()
        return
    ax.set_xlabel('Tick')
    ax.set_ylabel('Dominant category share')
    ax.set_ylim(0, 1.05)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_comparative_lineplot_stacked_categories(aggregates, field, title, out_path,
                                                 cmap_name='tab20', top_k=10):
    """One subplot per world; top-K categories shown as separate lines."""
    if not aggregates or plt is None or np is None:
        return
    if field not in TIMELINE_MAP:
        return
    timeline_attr, key_field = TIMELINE_MAP[field]

    n_worlds = len(aggregates)
    fig, axes = plt.subplots(n_worlds, 1,
                             figsize=(14, max(4, 3 * n_worlds)),
                             sharex=False)
    if n_worlds == 1:
        axes = [axes]

    totals = defaultdict(int)
    for agg in aggregates:
        for cat, cnt in getattr(agg, field).items():
            totals[cat] += cnt
    top_cats = [c for c, _ in sorted(totals.items(), key=lambda x: -x[1])[:top_k]]
    cmap = plt.cm.get_cmap(cmap_name, max(20, len(top_cats)))
    colors = {c: cmap(i % 20) for i, c in enumerate(top_cats)}

    for ax, agg in zip(axes, aggregates):
        if not getattr(agg, 'plotter', None):
            ax.set_visible(False)
            continue
        timeline = getattr(agg.plotter, timeline_attr, []) or []
        tick_cat = defaultdict(lambda: defaultdict(int))
        for entry in timeline:
            tick_cat[entry.get('tick', 0)][entry.get(key_field, 'Unknown')] += 1
        if not tick_cat:
            ax.set_title(f"{agg.world_name} (no data)")
            continue
        ticks = sorted(tick_cat.keys())
        for c in top_cats:
            y = [tick_cat[t].get(c, 0) for t in ticks]
            if any(y):
                ax.plot(ticks, y, linewidth=1.6, color=colors[c], label=c, alpha=0.85)
        ax.set_title(f"{agg.world_name} - {title}")
        ax.set_ylabel('Per tick')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=7, ncol=1)

    axes[-1].set_xlabel('Tick')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_boxplot_metric(aggregates, per_char_dict_name, ylabel, title, out_path):
    """Boxplot of a per-character dict across worlds."""
    if not aggregates or plt is None or np is None:
        return
    data = []
    labels = []
    for agg in aggregates:
        d = getattr(agg, per_char_dict_name, None)
        if d:
            data.append(list(d.values()))
            labels.append(agg.world_name)
    if not data:
        return
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.2), 5))
    bp = ax.boxplot(data, labels=labels, patch_artist=True, widths=0.6)
    cmap = plt.cm.get_cmap('tab10', max(10, len(labels)))
    for i, box in enumerate(bp['boxes']):
        box.set_facecolor(cmap(i % 10))
        box.set_alpha(0.7)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_variable_over_time(aggregates, variable, out_path, agg_mode='mean'):
    """Line plot per world of a status variable over ticks."""
    if not aggregates or plt is None or np is None:
        return
    fig, ax = plt.subplots(figsize=(14, 6))
    cmap = plt.cm.get_cmap('tab10', max(10, len(aggregates)))
    plotted = False
    ylabel = f"{variable}"
    for i, agg in enumerate(aggregates):
        if not agg.status_timeline:
            continue
        tick_values = defaultdict(list)
        for entry in agg.status_timeline:
            v = entry.get(variable)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tick_values[entry.get('tick', 0)].append(v)
        if not tick_values:
            continue
        ticks = sorted(tick_values.keys())
        if agg_mode == 'mean':
            y = [sum(tick_values[t]) / len(tick_values[t]) for t in ticks]
            ylabel = f"Mean {variable} (across characters)"
        else:
            y = [sum(tick_values[t]) for t in ticks]
            ylabel = f"Sum {variable}"
        ax.plot(ticks, y, linewidth=1.8, color=cmap(i % 10),
                label=agg.world_name, alpha=0.85)
        plotted = True
    if not plotted:
        plt.close()
        return
    ax.set_xlabel('Tick')
    ax.set_ylabel(ylabel)
    ax.set_title(f'{variable.capitalize()} over Time (per world)')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_boxplot_status_variable(aggregates, variable, out_path):
    """Boxplot of a status variable across worlds."""
    if not aggregates or plt is None or np is None:
        return
    data = []
    labels = []
    for agg in aggregates:
        vals = [e.get(variable) for e in agg.status_timeline
                if isinstance(e.get(variable), (int, float))
                and not isinstance(e.get(variable), bool)]
        if vals:
            data.append(vals)
            labels.append(agg.world_name)
    if not data:
        return
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.2), 5))
    bp = ax.boxplot(data, labels=labels, patch_artist=True, widths=0.6)
    cmap = plt.cm.get_cmap('tab10', max(10, len(labels)))
    for i, box in enumerate(bp['boxes']):
        box.set_facecolor(cmap(i % 10))
        box.set_alpha(0.7)
    ax.set_ylabel(variable)
    ax.set_title(f'{variable.capitalize()} distribution across Worlds')
    ax.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


def plot_aggregated_heatmap(matrix, row_label, col_label, title, out_path,
                            normalize='none'):
    """Single heatmap of an aggregated co-occurrence matrix."""
    if plt is None or np is None:
        return False
    rows = sorted(matrix.keys())
    cols = set()
    for inner in matrix.values():
        cols.update(inner.keys())
    cols = sorted(cols)
    if not rows or not cols:
        return False

    raw = np.zeros((len(rows), len(cols)), dtype=float)
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            raw[i, j] = matrix[r].get(c, 0)

    if normalize == 'row':
        denom = raw.sum(axis=1, keepdims=True)
        data = np.divide(raw, denom, out=np.zeros_like(raw), where=denom > 0)
        fmt = '{:.2f}'
    elif normalize == 'col':
        denom = raw.sum(axis=0, keepdims=True)
        data = np.divide(raw, denom, out=np.zeros_like(raw), where=denom > 0)
        fmt = '{:.2f}'
    else:
        data = raw
        fmt = '{:.0f}'

    n_rows, n_cols = data.shape
    fig, ax = plt.subplots(figsize=(max(10, n_cols * 0.7), max(5, n_rows * 0.6)))
    im = ax.imshow(data, cmap='YlOrRd', aspect='auto', origin='upper')
    plt.colorbar(im, ax=ax,
                 label=('Probability' if normalize != 'none' else 'Frequency'))
    ax.set_xticks(np.arange(n_cols))
    ax.set_yticks(np.arange(n_rows))
    ax.set_xticklabels(cols, rotation=45, ha='right', fontsize=8)
    ax.set_yticklabels(rows, fontsize=9)
    ax.set_xlabel(col_label)
    ax.set_ylabel(row_label)
    ax.set_title(title)
    max_val = data.max() if data.size else 1
    for i in range(n_rows):
        for j in range(n_cols):
            if data[i, j] > 0:
                ax.text(j, i, fmt.format(data[i, j]), ha='center', va='center',
                        fontsize=7,
                        color='black' if data[i, j] < max_val / 2 else 'white')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")
    return True


def plot_per_world_heatmaps_grid(aggregates, attr_name, row_label, col_label,
                                 title, out_path):
    """Small multiples: one heatmap per world, shared axes + shared colorbar."""
    if plt is None or np is None:
        return False
    rows_seen = set()
    cols_seen = set()
    per_world = {}
    for agg in aggregates:
        if not getattr(agg, 'plotter', None):
            continue
        m = getattr(agg.plotter, attr_name, None) or {}
        per_world[agg.world_name] = m
        rows_seen.update(m.keys())
        for inner in m.values():
            cols_seen.update(inner.keys())
    rows_seen = sorted(rows_seen)
    cols_seen = sorted(cols_seen)
    if not rows_seen or not cols_seen:
        return False

    n_worlds = len(per_world)
    if n_worlds == 0:
        return False

    matrices = []
    vmax = 0
    for w, m in per_world.items():
        arr = np.zeros((len(rows_seen), len(cols_seen)), dtype=float)
        for i, r in enumerate(rows_seen):
            for j, c in enumerate(cols_seen):
                arr[i, j] = m.get(r, {}).get(c, 0)
        matrices.append((w, arr))
        vmax = max(vmax, arr.max() if arr.size else 0)

    n_cols_grid = min(3, n_worlds)
    n_rows_grid = math.ceil(n_worlds / n_cols_grid)

    cell_w = max(5.0, 0.55 * len(cols_seen))
    cell_h = max(4.0, 0.45 * len(rows_seen))
    fig_w = cell_w * n_cols_grid
    fig_h = cell_h * n_rows_grid + 1.2

    fig, axes = plt.subplots(
        n_rows_grid, n_cols_grid,
        figsize=(fig_w, fig_h),
        squeeze=False,
        sharex=True, sharey=True,
    )

    im = None
    for idx, (w, arr) in enumerate(matrices):
        r_i = idx // n_cols_grid
        c_i = idx % n_cols_grid
        ax = axes[r_i][c_i]
        im = ax.imshow(arr, cmap='YlOrRd', aspect='auto', origin='upper',
                       vmin=0, vmax=vmax)
        ax.set_title(w, fontsize=11, pad=10)

        ax.set_xticks(np.arange(len(cols_seen)))
        ax.set_yticks(np.arange(len(rows_seen)))

        if c_i == 0:
            ax.set_yticklabels(rows_seen, fontsize=8)
        else:
            ax.tick_params(labelleft=False)

        if r_i == n_rows_grid - 1:
            ax.set_xticklabels(cols_seen, rotation=45, ha='right',
                               rotation_mode='anchor', fontsize=8)
        else:
            ax.tick_params(labelbottom=False)

    for k in range(n_worlds, n_rows_grid * n_cols_grid):
        axes[k // n_cols_grid][k % n_cols_grid].set_visible(False)

    try:
        fig.supxlabel(col_label, fontsize=11, y=0.015)
        fig.supylabel(row_label, fontsize=11, x=0.01)
    except AttributeError:
        fig.text(0.5, 0.01, col_label, ha='center', fontsize=11)
        fig.text(0.01, 0.5, row_label, va='center', rotation='vertical', fontsize=11)

    fig.suptitle(title, fontsize=13, y=0.985)

    fig.subplots_adjust(
        left=0.08, right=0.90, top=0.93, bottom=0.10,
        wspace=0.08, hspace=0.18,
    )

    if im is not None:
        cbar_ax = fig.add_axes([0.92, 0.15, 0.015, 0.70])
        fig.colorbar(im, cax=cbar_ax, label='Frequency')

    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[CHART] {out_path}")
    return True


def plot_status_vs_activity_scatter(rows, status_var, activity_var, out_path):
    """Scatter of status_var vs activity_var, colored by world, with r/rho."""
    if plt is None or np is None:
        return
    filtered = [r for r in rows
                if r.get(status_var) is not None and r.get(activity_var) is not None]
    if len(filtered) < 3:
        return
    xs = [float(r[status_var]) for r in filtered]
    ys = [float(r[activity_var]) for r in filtered]
    worlds = [r['World'] for r in filtered]
    unique_worlds = sorted(set(worlds))

    def _pearson(xs, ys):
        n = len(xs)
        if n < 2:
            return 0.0
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        dy = math.sqrt(sum((y - my) ** 2 for y in ys))
        if dx == 0 or dy == 0:
            return 0.0
        return num / (dx * dy)

    def _rank(vals):
        n = len(vals)
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg
            i = j + 1
        return ranks

    r_p = _pearson(xs, ys)
    r_s = _pearson(_rank(xs), _rank(ys))

    fig, ax = plt.subplots(figsize=(8, 6))
    cmap = plt.cm.get_cmap('tab10', max(10, len(unique_worlds)))
    for i, w in enumerate(unique_worlds):
        wx = [x for x, ww in zip(xs, worlds) if ww == w]
        wy = [y for y, ww in zip(ys, worlds) if ww == w]
        ax.scatter(wx, wy, label=w, color=cmap(i % 10), alpha=0.75, s=45,
                   edgecolors='black', linewidths=0.4)

    ax.set_xlabel(status_var)
    ax.set_ylabel(activity_var)
    ax.set_title(f'{status_var} vs {activity_var}\n'
                 f'Pearson r={r_p:+.3f}   Spearman rho={r_s:+.3f}   n={len(xs)}')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=8)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"[CHART] {out_path}")


# ============================================================
# TimelinePlotter
# ============================================================

class TimelinePlotter:
    """Generates CSV files and charts for action/emotion/goal/AI-state/status timelines"""

    KNOWN_AI_STATES = {
        'IDLE', 'GUARDING', 'FLEEING', 'SHARE', 'EXPLORE', 'COMBAT',
        'PATROL', 'ATTACK', 'RETREAT', 'DEFEND', 'GATHER', 'TRADE',
        'REST', 'HUNT', 'SOCIALIZE', 'FLEE', 'HELP', 'SHARING'
    }

    def __init__(self, world_folder: str, max_timeline_entries: Optional[int] = None):
        self.world_folder = world_folder
        self.max_timeline_entries = max_timeline_entries
        self._csv_dirty = True
        self.verbose = False

        self.action_timeline: List[Dict] = []
        self.emotion_timeline: List[Dict] = []
        self.ai_state_timeline: List[Dict] = []
        self.goal_timeline: List[Dict] = []
        self.status_timeline: List[Dict] = []

        self.emotion_action_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.action_emotion_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.emotion_aistate_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.action_aistate_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.goal_emotion_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.goal_aistate_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        self.character_emotion_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.character_action_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.character_aistate_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.character_goal_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        self.emotion_color_palette = [
            '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
            '#1abc9c', '#e67e22', '#34495e', '#95a5a6', '#d35400',
            '#c0392b', '#16a085',
        ]
        self.goal_color_palette = [
            '#2980b9', '#8e44ad', '#27ae60', '#d35400', '#c0392b',
            '#16a085', '#f39c12', '#7f8c8d', '#2c3e50', '#e74c3c',
            '#3498db', '#9b59b6',
        ]

        atexit.register(self._safe_export)

    # ==================== SAFETY ====================

    def _safe_export(self):
        try:
            if self._csv_dirty and (self.action_timeline or self.emotion_timeline
                                    or self.ai_state_timeline or self.goal_timeline
                                    or self.status_timeline):
                self.export_all_csv(verbose=False)
        except Exception:
            pass

    def _append_limited(self, timeline: List[Dict], entry: Dict):
        timeline.append(entry)
        if self.max_timeline_entries is not None and len(timeline) > self.max_timeline_entries:
            del timeline[:len(timeline) - self.max_timeline_entries]

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _diagnose(self, label: str):
        print(f"[DIAGNOSE] {label}:")
        print(f"  action_timeline: {len(self.action_timeline)} entries, "
              f"{len(self.character_action_counts)} characters, "
              f"{len(self._get_categories_from_counts(self.character_action_counts))} action categories")
        print(f"  emotion_timeline: {len(self.emotion_timeline)} entries, "
              f"{len(self.character_emotion_counts)} characters, "
              f"{len(self._get_categories_from_counts(self.character_emotion_counts))} emotion categories")
        print(f"  ai_state_timeline: {len(self.ai_state_timeline)} entries, "
              f"{len(self.character_aistate_counts)} characters, "
              f"{len(self._get_categories_from_counts(self.character_aistate_counts))} AI state categories")
        print(f"  goal_timeline: {len(self.goal_timeline)} entries, "
              f"{len(self.character_goal_counts)} characters, "
              f"{len(self._get_categories_from_counts(self.character_goal_counts))} goal categories")
        print(f"  status_timeline: {len(self.status_timeline)} entries")

    # ==================== DATA MANAGEMENT ====================

    def add_action_entry(self, tick: int, character: str, action: str,
                         emotion: str, ai_state: str = None):
        entry = {
            'tick': tick, 'character': character, 'action': action,
            'emotion': emotion, 'ai_state': ai_state or ''
        }
        self._append_limited(self.action_timeline, entry)
        self.action_emotion_matrix[action][emotion] += 1
        self.character_action_counts[character][action] += 1
        if ai_state:
            self.action_aistate_matrix[action][ai_state] += 1
        self._csv_dirty = True

    def add_emotion_entry(self, tick: int, character: str, emotion: str,
                          action: str = None, ai_state: str = None, goal: str = None):
        entry = {
            'tick': tick, 'character': character, 'emotion': emotion,
            'action': action or '', 'ai_state': ai_state or '', 'goal': goal or ''
        }
        self._append_limited(self.emotion_timeline, entry)
        if action:
            self.emotion_action_matrix[emotion][action] += 1
        if ai_state:
            self.emotion_aistate_matrix[emotion][ai_state] += 1
        if goal:
            self.goal_emotion_matrix[goal][emotion] += 1
        self.character_emotion_counts[character][emotion] += 1
        self._csv_dirty = True

    def add_ai_state_entry(self, tick: int, character: str, ai_state: str,
                           emotion: str = None):
        entry = {
            'tick': tick, 'character': character, 'ai_state': ai_state,
            'emotion': emotion or 'neutral'
        }
        self._append_limited(self.ai_state_timeline, entry)
        self.character_aistate_counts[character][ai_state] += 1
        if emotion:
            self.emotion_aistate_matrix[emotion][ai_state] += 1
        self._csv_dirty = True

    def add_goal_entry(self, tick: int, character: str, goal: str,
                       emotion: str = None, ai_state: str = None):
        entry = {
            'tick': tick, 'character': character, 'goal': goal,
            'emotion': emotion or 'neutral', 'ai_state': ai_state or ''
        }
        self._append_limited(self.goal_timeline, entry)
        self.character_goal_counts[character][goal] += 1
        if emotion:
            self.goal_emotion_matrix[goal][emotion] += 1
        if ai_state:
            self.goal_aistate_matrix[goal][ai_state] += 1
        self._csv_dirty = True

    def add_status_entry(self, tick: int, character: str,
                         status_vars: Dict[str, Any],
                         ai_state: str = None, emotion: str = None):
        """Record a status snapshot for a character at a given tick.

        Only numeric status variables are kept. Non-numeric fields are ignored.
        """
        entry = {
            'tick': tick,
            'character': character,
            'ai_state': ai_state or '',
            'emotion': emotion or '',
        }
        for k, v in (status_vars or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                entry[k] = v
        self._append_limited(self.status_timeline, entry)
        self._csv_dirty = True

    def _rebuild_matrices_from_timelines(self):
        self.emotion_action_matrix = defaultdict(lambda: defaultdict(int))
        self.action_emotion_matrix = defaultdict(lambda: defaultdict(int))
        self.emotion_aistate_matrix = defaultdict(lambda: defaultdict(int))
        self.action_aistate_matrix = defaultdict(lambda: defaultdict(int))
        self.goal_emotion_matrix = defaultdict(lambda: defaultdict(int))
        self.goal_aistate_matrix = defaultdict(lambda: defaultdict(int))
        self.character_emotion_counts = defaultdict(lambda: defaultdict(int))
        self.character_action_counts = defaultdict(lambda: defaultdict(int))
        self.character_aistate_counts = defaultdict(lambda: defaultdict(int))
        self.character_goal_counts = defaultdict(lambda: defaultdict(int))

        for entry in self.action_timeline:
            action = entry.get('action', 'Unknown')
            emotion = entry.get('emotion', 'neutral')
            ai_state = entry.get('ai_state', '')
            char = entry.get('character', 'Unknown')
            self.action_emotion_matrix[action][emotion] += 1
            self.character_action_counts[char][action] += 1
            if ai_state:
                self.action_aistate_matrix[action][ai_state] += 1

        for entry in self.emotion_timeline:
            emotion = entry.get('emotion', 'neutral')
            action = entry.get('action', '')
            ai_state = entry.get('ai_state', '')
            goal = entry.get('goal', '')
            char = entry.get('character', 'Unknown')
            if action:
                self.emotion_action_matrix[emotion][action] += 1
            if ai_state:
                self.emotion_aistate_matrix[emotion][ai_state] += 1
            if goal:
                self.goal_emotion_matrix[goal][emotion] += 1
            self.character_emotion_counts[char][emotion] += 1

        for entry in self.ai_state_timeline:
            ai_state = entry.get('ai_state', 'Unknown')
            char = entry.get('character', 'Unknown')
            emotion = entry.get('emotion', 'neutral')
            self.character_aistate_counts[char][ai_state] += 1
            if emotion:
                self.emotion_aistate_matrix[emotion][ai_state] += 1

        for entry in self.goal_timeline:
            goal = entry.get('goal', 'Unknown')
            char = entry.get('character', 'Unknown')
            emotion = entry.get('emotion', 'neutral')
            ai_state = entry.get('ai_state', '')
            self.character_goal_counts[char][goal] += 1
            if emotion:
                self.goal_emotion_matrix[goal][emotion] += 1
            if ai_state:
                self.goal_aistate_matrix[goal][ai_state] += 1

    def load_from_runtime(self, runtime_data: Dict[str, Any]):
        rt_actions = runtime_data.get('action_timeline', [])
        rt_emotions = runtime_data.get('emotion_timeline', [])
        rt_aistates = runtime_data.get('ai_state_timeline', [])
        rt_goals = runtime_data.get('goal_timeline', [])
        rt_status = runtime_data.get('status_timeline', [])

        if rt_actions and (not self.action_timeline or len(rt_actions) > len(self.action_timeline)):
            self.action_timeline = list(rt_actions)
        if rt_emotions and (not self.emotion_timeline or len(rt_emotions) > len(self.emotion_timeline)):
            self.emotion_timeline = list(rt_emotions)
        if rt_aistates and (not self.ai_state_timeline or len(rt_aistates) > len(self.ai_state_timeline)):
            self.ai_state_timeline = list(rt_aistates)
        if rt_goals and (not self.goal_timeline or len(rt_goals) > len(self.goal_timeline)):
            self.goal_timeline = list(rt_goals)
        if rt_status and (not self.status_timeline or len(rt_status) > len(self.status_timeline)):
            self.status_timeline = list(rt_status)

        self._rebuild_matrices_from_timelines()
        self._diagnose("After load_from_runtime")

    def save_timelines_snapshot(self) -> bool:
        filepath = os.path.join(self.world_folder, "timelines_snapshot.json")
        try:
            snapshot = {
                "action_timeline": self.action_timeline,
                "emotion_timeline": self.emotion_timeline,
                "ai_state_timeline": self.ai_state_timeline,
                "goal_timeline": self.goal_timeline,
                "status_timeline": self.status_timeline,
                "saved_at": datetime.now().isoformat(),
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save timelines snapshot: {e}")
            return False

    def load_timelines_snapshot(self) -> bool:
        filepath = os.path.join(self.world_folder, "timelines_snapshot.json")
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                snapshot = json.load(f)
            self.action_timeline = snapshot.get('action_timeline', [])
            self.emotion_timeline = snapshot.get('emotion_timeline', [])
            self.ai_state_timeline = snapshot.get('ai_state_timeline', [])
            self.goal_timeline = snapshot.get('goal_timeline', [])
            self.status_timeline = snapshot.get('status_timeline', [])
            self._rebuild_matrices_from_timelines()
            print(f"[OK] Loaded timelines snapshot: "
                  f"{len(self.action_timeline)} actions, "
                  f"{len(self.emotion_timeline)} emotions, "
                  f"{len(self.ai_state_timeline)} AI states, "
                  f"{len(self.goal_timeline)} goals, "
                  f"{len(self.status_timeline)} status")
            self._diagnose("After load_timelines_snapshot")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load timelines snapshot: {e}")
            return False

    def load_from_csv(self):
        actions_csv = os.path.join(self.world_folder, "actions_timeline.csv")
        emotions_csv = os.path.join(self.world_folder, "emotions_timeline.csv")
        aistate_csv = os.path.join(self.world_folder, "ai_states_timeline.csv")
        goals_csv = os.path.join(self.world_folder, "goals_timeline.csv")
        status_csv = os.path.join(self.world_folder, "status_timeline.csv")

        loaded_any = False

        if os.path.exists(actions_csv):
            try:
                with open(actions_csv, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.action_timeline = []
                    for row in reader:
                        try:
                            tick = int(row.get('Tick', 0))
                        except (ValueError, TypeError):
                            tick = 0
                        self.action_timeline.append({
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'action': row.get('Action', 'Unknown'),
                            'emotion': row.get('Emotion_At_Time', 'neutral'),
                            'ai_state': row.get('AI_State', '')
                        })
                print(f"[OK] Loaded {len(self.action_timeline)} action entries from CSV")
                loaded_any = True
            except Exception as e:
                print(f"[ERROR] Failed to load actions CSV: {e}")

        if os.path.exists(emotions_csv):
            try:
                with open(emotions_csv, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.emotion_timeline = []
                    for row in reader:
                        try:
                            tick = int(row.get('Tick', 0))
                        except (ValueError, TypeError):
                            tick = 0
                        self.emotion_timeline.append({
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'emotion': row.get('Emotion', 'neutral'),
                            'action': row.get('Action_At_Time', ''),
                            'ai_state': row.get('AI_State_At_Time', ''),
                            'goal': row.get('Goal_At_Time', '')
                        })
                print(f"[OK] Loaded {len(self.emotion_timeline)} emotion entries from CSV")
                loaded_any = True
            except Exception as e:
                print(f"[ERROR] Failed to load emotions CSV: {e}")

        if os.path.exists(aistate_csv):
            try:
                with open(aistate_csv, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.ai_state_timeline = []
                    for row in reader:
                        try:
                            tick = int(row.get('Tick', 0))
                        except (ValueError, TypeError):
                            tick = 0
                        self.ai_state_timeline.append({
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'ai_state': row.get('AI_State', 'Unknown'),
                            'emotion': row.get('Emotion_At_Time', 'neutral')
                        })
                print(f"[OK] Loaded {len(self.ai_state_timeline)} AI state entries from CSV")
                loaded_any = True
            except Exception as e:
                print(f"[ERROR] Failed to load AI states CSV: {e}")

        if os.path.exists(goals_csv):
            try:
                with open(goals_csv, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.goal_timeline = []
                    for row in reader:
                        try:
                            tick = int(row.get('Tick', 0))
                        except (ValueError, TypeError):
                            tick = 0
                        self.goal_timeline.append({
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'goal': row.get('Goal', 'Unknown'),
                            'emotion': row.get('Emotion_At_Time', 'neutral'),
                            'ai_state': row.get('AI_State_At_Time', '')
                        })
                print(f"[OK] Loaded {len(self.goal_timeline)} goal entries from CSV")
                loaded_any = True
            except Exception as e:
                print(f"[ERROR] Failed to load goals CSV: {e}")

        if os.path.exists(status_csv):
            try:
                with open(status_csv, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.status_timeline = []
                    for row in reader:
                        entry = {}
                        for k, v in row.items():
                            kl = k.lower()
                            if kl == 'tick':
                                try:
                                    entry['tick'] = int(v)
                                except (ValueError, TypeError):
                                    entry['tick'] = 0
                            elif kl == 'character':
                                entry['character'] = v
                            elif kl in ('ai_state', 'emotion'):
                                entry[kl] = v
                            else:
                                try:
                                    entry[k] = float(v) if '.' in v else int(v)
                                except (ValueError, TypeError):
                                    entry[k] = v
                        self.status_timeline.append(entry)
                print(f"[OK] Loaded {len(self.status_timeline)} status entries from CSV")
                loaded_any = True
            except Exception as e:
                print(f"[ERROR] Failed to load status CSV: {e}")

        if loaded_any:
            self._rebuild_matrices_from_timelines()
            self._diagnose("After load_from_csv")

    # ==================== CSV EXPORTS ====================

    def export_all_csv(self, verbose: bool = True):
        self._export_actions_timeline_csv()
        self._export_emotions_timeline_csv()
        self._export_ai_states_timeline_csv()
        self._export_goals_timeline_csv()
        self._export_status_timeline_csv()
        self._export_emotion_action_matrix_csv()
        self._export_action_emotion_matrix_csv()
        self._export_emotion_aistate_matrix_csv()
        self._export_action_aistate_matrix_csv()
        self._export_goal_emotion_matrix_csv()
        self._export_goal_aistate_matrix_csv()
        self._export_emotions_per_tick_csv()
        self._export_actions_per_tick_csv()
        self._export_ai_states_per_tick_csv()
        self._export_goals_per_tick_csv()
        self._export_status_per_tick_csv()
        self._csv_dirty = False
        if verbose:
            print(f"[OK] CSV exports written to {self.world_folder}")

    def _export_actions_timeline_csv(self):
        filepath = os.path.join(self.world_folder, "actions_timeline.csv")
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick', 'Character', 'Action', 'Emotion_At_Time', 'AI_State'])
                for entry in self.action_timeline:
                    writer.writerow([
                        entry.get('tick', ''), entry.get('character', ''),
                        entry.get('action', ''), entry.get('emotion', ''),
                        entry.get('ai_state', '')
                    ])
        except Exception as e:
            print(f"[ERROR] Failed to export actions timeline CSV: {e}")

    def _export_emotions_timeline_csv(self):
        filepath = os.path.join(self.world_folder, "emotions_timeline.csv")
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick', 'Character', 'Emotion', 'Action_At_Time',
                                 'AI_State_At_Time', 'Goal_At_Time'])
                for entry in self.emotion_timeline:
                    writer.writerow([
                        entry.get('tick', ''), entry.get('character', ''),
                        entry.get('emotion', ''), entry.get('action', ''),
                        entry.get('ai_state', ''), entry.get('goal', '')
                    ])
        except Exception as e:
            print(f"[ERROR] Failed to export emotions timeline CSV: {e}")

    def _export_ai_states_timeline_csv(self):
        filepath = os.path.join(self.world_folder, "ai_states_timeline.csv")
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick', 'Character', 'AI_State', 'Emotion_At_Time'])
                for entry in self.ai_state_timeline:
                    writer.writerow([
                        entry.get('tick', ''), entry.get('character', ''),
                        entry.get('ai_state', ''), entry.get('emotion', '')
                    ])
        except Exception as e:
            print(f"[ERROR] Failed to export AI states timeline CSV: {e}")

    def _export_goals_timeline_csv(self):
        filepath = os.path.join(self.world_folder, "goals_timeline.csv")
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick', 'Character', 'Goal', 'Emotion_At_Time', 'AI_State_At_Time'])
                for entry in self.goal_timeline:
                    writer.writerow([
                        entry.get('tick', ''), entry.get('character', ''),
                        entry.get('goal', ''), entry.get('emotion', ''),
                        entry.get('ai_state', '')
                    ])
        except Exception as e:
            print(f"[ERROR] Failed to export goals timeline CSV: {e}")

    def _export_status_timeline_csv(self):
        filepath = os.path.join(self.world_folder, "status_timeline.csv")
        try:
            if not self.status_timeline:
                return
            # Column order: tick, character, ai_state, emotion, then the rest
            fixed = ['tick', 'character', 'ai_state', 'emotion']
            extra, seen = [], set(fixed)
            for e in self.status_timeline:
                for k in e.keys():
                    if k not in seen:
                        extra.append(k)
                        seen.add(k)
            cols = fixed + sorted(extra)

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([c.capitalize() if c in ('tick', 'character') else c
                                 for c in cols])
                for entry in self.status_timeline:
                    writer.writerow([entry.get(c, '') for c in cols])
        except Exception as e:
            print(f"[ERROR] Failed to export status timeline CSV: {e}")

    def _export_matrix_csv(self, matrix, row_label, filename):
        filepath = os.path.join(self.world_folder, filename)
        try:
            rows = sorted(matrix.keys())
            cols = set()
            for inner in matrix.values():
                cols.update(inner.keys())
            cols = sorted(cols)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([row_label] + cols)
                for row in rows:
                    line = [row]
                    for col in cols:
                        line.append(matrix[row].get(col, 0))
                    writer.writerow(line)
        except Exception as e:
            print(f"[ERROR] Failed to export {filename}: {e}")

    def _export_emotion_action_matrix_csv(self):
        self._export_matrix_csv(self.emotion_action_matrix, 'Emotion', 'emotion_action_matrix.csv')

    def _export_action_emotion_matrix_csv(self):
        self._export_matrix_csv(self.action_emotion_matrix, 'Action', 'action_emotion_matrix.csv')

    def _export_emotion_aistate_matrix_csv(self):
        self._export_matrix_csv(self.emotion_aistate_matrix, 'Emotion', 'emotion_aistate_matrix.csv')

    def _export_action_aistate_matrix_csv(self):
        self._export_matrix_csv(self.action_aistate_matrix, 'Action', 'action_aistate_matrix.csv')

    def _export_goal_emotion_matrix_csv(self):
        self._export_matrix_csv(self.goal_emotion_matrix, 'Goal', 'goal_emotion_matrix.csv')

    def _export_goal_aistate_matrix_csv(self):
        self._export_matrix_csv(self.goal_aistate_matrix, 'Goal', 'goal_aistate_matrix.csv')

    def _export_per_tick_csv(self, timeline, key_field, filename, header):
        filepath = os.path.join(self.world_folder, filename)
        try:
            tick_counts = defaultdict(lambda: defaultdict(int))
            for entry in timeline:
                tick = entry.get('tick', 0)
                key = entry.get(key_field, 'Unknown')
                tick_counts[tick][key] += 1
            if not tick_counts:
                return
            ticks = sorted(tick_counts.keys())
            all_keys = set()
            for counts in tick_counts.values():
                all_keys.update(counts.keys())
            all_keys = sorted(all_keys)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick'] + all_keys + ['Total'])
                for tick in ticks:
                    row = [tick]
                    total = 0
                    for k in all_keys:
                        count = tick_counts[tick].get(k, 0)
                        row.append(count)
                        total += count
                    row.append(total)
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export {filename}: {e}")

    def _export_emotions_per_tick_csv(self):
        self._export_per_tick_csv(self.emotion_timeline, 'emotion', 'emotions_per_tick.csv', 'Emotion')

    def _export_actions_per_tick_csv(self):
        self._export_per_tick_csv(self.action_timeline, 'action', 'actions_per_tick.csv', 'Action')

    def _export_ai_states_per_tick_csv(self):
        self._export_per_tick_csv(self.ai_state_timeline, 'ai_state', 'ai_states_per_tick.csv', 'AI_State')

    def _export_goals_per_tick_csv(self):
        self._export_per_tick_csv(self.goal_timeline, 'goal', 'goals_per_tick.csv', 'Goal')

    def _export_status_per_tick_csv(self):
        """Per-tick aggregated status: mean of every numeric status field."""
        filepath = os.path.join(self.world_folder, "status_per_tick.csv")
        try:
            if not self.status_timeline:
                return
            # Collect numeric fields (exclude tick/character/ai_state/emotion)
            fixed = {'tick', 'character', 'ai_state', 'emotion'}
            numeric_fields = set()
            for e in self.status_timeline:
                for k, v in e.items():
                    if k in fixed:
                        continue
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        numeric_fields.add(k)
            if not numeric_fields:
                return
            numeric_fields = sorted(numeric_fields)

            tick_values = defaultdict(lambda: defaultdict(list))
            for e in self.status_timeline:
                t = e.get('tick', 0)
                for k in numeric_fields:
                    v = e.get(k)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        tick_values[t][k].append(v)
            ticks = sorted(tick_values.keys())

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick'] + [f'Mean_{k}' for k in numeric_fields]
                                + [f'Std_{k}' for k in numeric_fields])
                for t in ticks:
                    row = [t]
                    for k in numeric_fields:
                        vals = tick_values[t].get(k, [])
                        row.append(round(sum(vals) / len(vals), 3) if vals else '')
                    for k in numeric_fields:
                        vals = tick_values[t].get(k, [])
                        if len(vals) > 1:
                            m = sum(vals) / len(vals)
                            sd = (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
                            row.append(round(sd, 3))
                        else:
                            row.append('')
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export status_per_tick CSV: {e}")

    # ==================== CHART GENERATION ====================

    def generate_all_charts(self):
        if not HAS_MATPLOTLIB:
            print("[WARNING] matplotlib not installed. Skipping chart generation.")
            return

        print("\n" + "="*70)
        print("GENERATING TIMELINE CHARTS")
        print("="*70)

        self._diagnose("Before chart generation")

        # Actions
        self._chart_actions_by_character(plt, np)
        self._chart_actions_over_time(plt, np)
        self._chart_actions_lineplot(plt, np)
        self._chart_emotion_action_heatmap(plt, np)
        self._chart_action_aistate_heatmap(plt, np)

        # AI States
        self._chart_aistates_by_character(plt, np)
        self._chart_aistates_over_time(plt, np)
        self._chart_aistates_lineplot(plt, np)
        self._chart_emotion_aistate_heatmap(plt, np)

        # Emotions
        self._chart_emotions_by_character(plt, np)
        self._chart_emotions_over_time(plt, np)
        self._chart_emotions_lineplot(plt, np)

        # Goals
        self._chart_goals_by_character(plt, np)
        self._chart_goals_over_time(plt, np)
        self._chart_goals_lineplot(plt, np)
        self._chart_goal_emotion_heatmap(plt, np)
        self._chart_goal_aistate_heatmap(plt, np)

        print("="*70)

    def _safe_set_style(self, plt_module):
        return safe_set_style(plt_module)
    
    def _get_categories_from_counts(self, counts_dict: Dict[str, Dict[str, int]]) -> List[str]:
        totals = defaultdict(int)
        for inner in counts_dict.values():
            for cat, cnt in inner.items():
                totals[cat] += cnt
        return sorted([c for c, t in totals.items() if t > 0])

    def _stacked_barh_with_full_legend(self, counts_dict, categories, colors,
                                       title, xlabel, filepath, fig_width=12):
        if not counts_dict or not categories:
            print(f"[WARN] Skipping {filepath} (empty counts or categories)")
            return
        if len(categories) == 1:
            print(f"[WARN] {filepath}: only 1 category detected ({categories[0]}). "
                  f"The source data only contains 1 value for this field.")
        safe_set_style(plt)
        characters = sorted(counts_dict.keys())
        fig, ax = plt.subplots(figsize=(fig_width, max(5, len(characters) * 0.7)))
        y_pos = np.arange(len(characters))
        for i, char in enumerate(characters):
            left = 0
            for cat in categories:
                count = counts_dict[char].get(cat, 0)
                if count > 0:
                    ax.barh(i, count, left=left, height=0.7,
                            color=colors[cat], edgecolor='none')
                    left += count
        ax.set_yticks(y_pos)
        ax.set_yticklabels(characters)
        ax.set_xlabel(xlabel)
        ax.set_title(title)
        legend_handles = [mpatches.Patch(color=colors[cat], label=cat) for cat in categories]
        ax.legend(handles=legend_handles, labels=categories,
                  loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8, frameon=True)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _stacked_over_time(self, timeline, key_field, palette, title, filepath, cmap_name='tab20'):
        if not timeline:
            return
        tick_counts = defaultdict(lambda: defaultdict(int))
        for entry in timeline:
            tick_counts[entry.get('tick', 0)][entry.get(key_field, 'Unknown')] += 1
        if not tick_counts:
            return
        safe_set_style(plt)
        ticks = sorted(tick_counts.keys())

        all_keys = set()                              # <-- must exist
        for c in tick_counts.values():
            all_keys.update(c.keys())
        all_keys = sorted(all_keys)                   # <-- must be assigned
        if not all_keys:
            return                                    # <-- early return if empty

        if cmap_name == 'custom' and palette:
            colors = {k: palette[i % len(palette)] for i, k in enumerate(all_keys)}
        else:
            natural = 20 if cmap_name == 'tab20' else 10
            cmap = plt.cm.get_cmap(cmap_name, max(natural, len(all_keys)))
            colors = {k: cmap(i % natural) for i, k in enumerate(all_keys)}

        fig, ax = plt.subplots(figsize=(14, 6))
        bottoms = np.zeros(len(ticks))
        for k in all_keys:
            values = np.array([tick_counts[t].get(k, 0) for t in ticks])
            if values.sum() > 0:
                ax.bar(ticks, values, bottom=bottoms, width=1.0, color=colors[k])
                bottoms += values
        ax.set_xlabel('Tick')
        ax.set_ylabel('Observations')
        ax.set_title(title)
        legend_handles = [mpatches.Patch(color=colors[k], label=k) for k in all_keys]
        ax.legend(handles=legend_handles, labels=all_keys,
                  loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _lineplot_over_time(self, timeline, key_field, palette, title, filepath, cmap_name='tab20'):
        
        if not timeline:
            return
        tick_counts = defaultdict(lambda: defaultdict(int))
        for entry in timeline:
            tick_counts[entry.get('tick', 0)][entry.get(key_field, 'Unknown')] += 1
        if not tick_counts:
            return
        safe_set_style(plt)
        ticks = sorted(tick_counts.keys())
        all_keys = set()
        for c in tick_counts.values():
            all_keys.update(c.keys())
        all_keys = sorted(all_keys)
        if not all_keys:
            return

        if cmap_name == 'custom' and palette:
            colors = {k: palette[i % len(palette)] for i, k in enumerate(all_keys)}
        else:
            cmap = plt.cm.get_cmap(cmap_name, max(10, len(all_keys)))  
            colors = {k: cmap(i % 10) for i, k in enumerate(all_keys)} 

        fig, ax = plt.subplots(figsize=(14, 6))
        for k in all_keys:
            y = [tick_counts[t].get(k, 0) for t in ticks]
            ax.plot(ticks, y, marker='o', markersize=3, linewidth=1.8,
                    color=colors[k], label=k, alpha=0.85)
        total = [sum(tick_counts[t].values()) for t in ticks]
        ax.plot(ticks, total, linestyle='--', linewidth=1.2,
                color='black', alpha=0.5, label='TOTAL')
        ax.set_xlabel('Tick')
        ax.set_ylabel('Frequency (all characters)')
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _heatmap_from_matrix(self, matrix, row_label, col_label, title, filepath):
        matrix_np, rows, cols = self._build_matrix(matrix)
        if matrix_np is None:
            return
        n_rows, n_cols = matrix_np.shape
        fig, ax = plt.subplots(figsize=(max(10, n_cols * 0.7), max(5, n_rows * 0.6)))
        im = ax.imshow(matrix_np, cmap='YlOrRd', aspect='auto', origin='upper',
                       extent=(-0.5, n_cols - 0.5, n_rows - 0.5, -0.5))
        plt.colorbar(im, ax=ax, label='Frequency')
        ax.set_xticks(np.arange(n_cols))
        ax.set_yticks(np.arange(n_rows))
        ax.set_xticklabels(cols, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(rows, fontsize=9)
        ax.set_xlim(-0.5, n_cols - 0.5)
        ax.set_ylim(n_rows - 0.5, -0.5)
        ax.set_xlabel(col_label)
        ax.set_ylabel(row_label)
        ax.set_title(title)
        max_val = matrix_np.max() if matrix_np.size else 1
        for i in range(n_rows):
            for j in range(n_cols):
                if matrix_np[i, j] > 0:
                    ax.text(j, i, int(matrix_np[i, j]), ha="center", va="center",
                            color="black" if matrix_np[i, j] < max_val / 2 else "white",
                            fontsize=7)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _build_matrix(self, matrix_dict):
        if not matrix_dict:
            return None, None, None
        rows = sorted(matrix_dict.keys())
        cols = set()
        for col_counts in matrix_dict.values():
            cols.update(col_counts.keys())
        cols = sorted(cols)
        if not rows or not cols:
            return None, None, None
        matrix = np.zeros((len(rows), len(cols)), dtype=int)
        for i, row in enumerate(rows):
            for j, col in enumerate(cols):
                matrix[i, j] = matrix_dict[row].get(col, 0)
        return matrix, rows, cols

    # ---- ACTIONS ----

    def _chart_actions_by_character(self, plt, np):
        if not self.character_action_counts:
            return
        categories = self._get_categories_from_counts(self.character_action_counts)
        if not categories:
            return
        cmap = plt.cm.get_cmap('tab20', max(20, len(categories)))
        colors = {cat: cmap(i % 20) for i, cat in enumerate(categories)}
        filepath = os.path.join(self.world_folder, "actions_by_character.png")
        self._stacked_barh_with_full_legend(
            counts_dict=self.character_action_counts,
            categories=categories, colors=colors,
            title='Actions Distribution by Character (colored by Action Type)',
            xlabel='Number of Actions', filepath=filepath)

    def _chart_actions_over_time(self, plt, np):
        self._stacked_over_time(
            self.action_timeline, 'action', None,
            'Actions Over Time (stacked by Action Type)',
            os.path.join(self.world_folder, "actions_over_time.png"),
            cmap_name='tab20')

    def _chart_actions_lineplot(self, plt, np):
        self._lineplot_over_time(
            self.action_timeline, 'action', None,
            'Actions Over Time - Line Plot (sum of all characters)',
            os.path.join(self.world_folder, "actions_lineplot.png"),
            cmap_name='tab20')

    def _chart_emotion_action_heatmap(self, plt, np):
        self._heatmap_from_matrix(
            self.emotion_action_matrix, 'Emotion', 'Action',
            'Emotion-Action Co-occurrence Matrix',
            os.path.join(self.world_folder, "emotion_action_heatmap.png"))

    def _chart_action_aistate_heatmap(self, plt, np):
        self._heatmap_from_matrix(
            self.action_aistate_matrix, 'Action', 'AI State',
            'Action-AI State Co-occurrence Matrix',
            os.path.join(self.world_folder, "action_aistate_heatmap.png"))

    # ---- AI STATES ----

    def _chart_aistates_by_character(self, plt, np):
        if not self.character_aistate_counts:
            return
        categories = self._get_categories_from_counts(self.character_aistate_counts)
        if not categories:
            return
        cmap = plt.cm.get_cmap('tab10', max(10, len(categories)))
        colors = {cat: cmap(i % 10) for i, cat in enumerate(categories)}
        filepath = os.path.join(self.world_folder, "aistates_by_character.png")
        self._stacked_barh_with_full_legend(
            counts_dict=self.character_aistate_counts,
            categories=categories, colors=colors,
            title='AI States Distribution by Character (colored by State)',
            xlabel='Frequency', filepath=filepath)

    def _chart_aistates_over_time(self, plt, np):
        self._stacked_over_time(
            self.ai_state_timeline, 'ai_state', None,
            'AI States Over Time (stacked by State)',
            os.path.join(self.world_folder, "aistates_over_time.png"),
            cmap_name='tab10')

    def _chart_aistates_lineplot(self, plt, np):
        self._lineplot_over_time(
            self.ai_state_timeline, 'ai_state', None,
            'AI States Over Time - Line Plot (sum of all characters)',
            os.path.join(self.world_folder, "aistates_lineplot.png"),
            cmap_name='tab10')

    def _chart_emotion_aistate_heatmap(self, plt, np):
        self._heatmap_from_matrix(
            self.emotion_aistate_matrix, 'Emotion', 'AI State',
            'Emotion-AI State Co-occurrence Matrix',
            os.path.join(self.world_folder, "emotion_aistate_heatmap.png"))

    # ---- EMOTIONS ----

    def _chart_emotions_by_character(self, plt, np):
        if not self.character_emotion_counts:
            return
        categories = self._get_categories_from_counts(self.character_emotion_counts)
        if not categories:
            return
        colors = {cat: self.emotion_color_palette[i % len(self.emotion_color_palette)]
                  for i, cat in enumerate(categories)}
        filepath = os.path.join(self.world_folder, "emotions_by_character.png")
        self._stacked_barh_with_full_legend(
            counts_dict=self.character_emotion_counts,
            categories=categories, colors=colors,
            title='Emotions Distribution by Character (colored by Emotion)',
            xlabel='Frequency', filepath=filepath)

    def _chart_emotions_over_time(self, plt, np):
        self._stacked_over_time(
            self.emotion_timeline, 'emotion', self.emotion_color_palette,
            'Emotions Over Time (stacked by Emotion)',
            os.path.join(self.world_folder, "emotions_over_time.png"),
            cmap_name='custom')

    def _chart_emotions_lineplot(self, plt, np):
        self._lineplot_over_time(
            self.emotion_timeline, 'emotion', self.emotion_color_palette,
            'Emotions Over Time - Line Plot (sum of all characters)',
            os.path.join(self.world_folder, "emotions_lineplot.png"),
            cmap_name='custom')

    # ---- GOALS ----

    def _chart_goals_by_character(self, plt, np):
        if not self.character_goal_counts:
            return
        categories = self._get_categories_from_counts(self.character_goal_counts)
        if not categories:
            return
        colors = {cat: self.goal_color_palette[i % len(self.goal_color_palette)]
                  for i, cat in enumerate(categories)}
        filepath = os.path.join(self.world_folder, "goals_by_character.png")
        self._stacked_barh_with_full_legend(
            counts_dict=self.character_goal_counts,
            categories=categories, colors=colors,
            title='Goals Distribution by Character (colored by Goal)',
            xlabel='Frequency', filepath=filepath)

    def _chart_goals_over_time(self, plt, np):
        self._stacked_over_time(
            self.goal_timeline, 'goal', self.goal_color_palette,
            'Goals Over Time (stacked by Goal)',
            os.path.join(self.world_folder, "goals_over_time.png"),
            cmap_name='custom')

    def _chart_goals_lineplot(self, plt, np):
        self._lineplot_over_time(
            self.goal_timeline, 'goal', self.goal_color_palette,
            'Goals Over Time - Line Plot (sum of all characters)',
            os.path.join(self.world_folder, "goals_lineplot.png"),
            cmap_name='custom')

    def _chart_goal_emotion_heatmap(self, plt, np):
        self._heatmap_from_matrix(
            self.goal_emotion_matrix, 'Goal', 'Emotion',
            'Goal-Emotion Co-occurrence Matrix',
            os.path.join(self.world_folder, "goal_emotion_heatmap.png"))

    def _chart_goal_aistate_heatmap(self, plt, np):
        self._heatmap_from_matrix(
            self.goal_aistate_matrix, 'Goal', 'AI State',
            'Goal-AI State Co-occurrence Matrix',
            os.path.join(self.world_folder, "goal_aistate_heatmap.png"))


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate timeline charts from SWM world data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python swm_plots.py --world world_2024_01_15
  python swm_plots.py --folder world_2024_01_15
  python swm_plots.py --folder world_2024_01_15 --csv-only
  python swm_plots.py --folder world_2024_01_15 --charts-only
  python swm_plots.py --folder world_2024_01_15 --prefer-csv
  python swm_plots.py --folder world_2024_01_15 --from-csv
        """
    )
    parser.add_argument('--world', '--folder', dest='world', type=str, required=True,
                        help='Path to world folder. --folder is an alias of --world.')
    parser.add_argument('--csv-only', action='store_true',
                        help='Only export CSV files, no charts')
    parser.add_argument('--charts-only', action='store_true',
                        help='Only generate charts (assumes CSVs exist)')
    parser.add_argument('--from-csv', action='store_true',
                        help='Force loading ONLY from CSV files (ignore snapshot/runtime)')
    parser.add_argument('--prefer-csv', action='store_true',
                        help='Try CSV first, then snapshot/runtime as fallback')

    args = parser.parse_args()

    if not os.path.isdir(args.world):
        print(f"[ERROR] World folder not found: {args.world}")
        sys.exit(1)

    runtime_path = os.path.join(args.world, "world_state_runtime.json")
    snapshot_path = os.path.join(args.world, "timelines_snapshot.json")
    expected_csvs = [
        "actions_timeline.csv", "emotions_timeline.csv",
        "ai_states_timeline.csv", "goals_timeline.csv",
    ]
    existing_csvs = [f for f in expected_csvs if os.path.exists(os.path.join(args.world, f))]
    has_runtime = os.path.exists(runtime_path)
    has_snapshot = os.path.exists(snapshot_path)

    if not (has_runtime or has_snapshot or existing_csvs):
        print(f"[ERROR] No usable data found in {args.world}.")
        sys.exit(1)

    plotter = TimelinePlotter(args.world)
    plotter.verbose = True

    if not args.charts_only:
        loaded = False

        if args.from_csv:
            if existing_csvs:
                print(f"[INFO] --from-csv: loading from CSVs {existing_csvs}")
                plotter.load_from_csv()
                loaded = True
            else:
                print(f"[WARN] --from-csv specified but no CSVs found")

        elif args.prefer_csv:
            if existing_csvs:
                print(f"[INFO] --prefer-csv: loading from CSVs first")
                plotter.load_from_csv()
                loaded = True

        if not loaded:
            if has_snapshot:
                if plotter.load_timelines_snapshot():
                    loaded = True

            if not loaded and has_runtime:
                try:
                    with open(runtime_path, 'r', encoding='utf-8') as f:
                        runtime_data = json.load(f)
                    plotter.load_from_runtime(runtime_data)
                    if (plotter.action_timeline or plotter.emotion_timeline
                            or plotter.ai_state_timeline or plotter.goal_timeline
                            or plotter.status_timeline):
                        print(f"[OK] Loaded timeline from runtime state: {runtime_path}")
                        loaded = True
                except Exception as e:
                    print(f"[WARN] Could not load runtime state ({e})")

            if not loaded and existing_csvs:
                print(f"[INFO] Fallback: loading from CSVs")
                plotter.load_from_csv()
                loaded = True

        plotter.export_all_csv()

    if not args.csv_only:
        if (not plotter.action_timeline and not plotter.emotion_timeline
                and not plotter.ai_state_timeline and not plotter.goal_timeline
                and not plotter.status_timeline):
            print(f"[INFO] No timeline data in memory, attempting CSV load...")
            plotter.load_from_csv()
        plotter.generate_all_charts()

    print("\n[DONE] Timeline exports and charts complete")


if __name__ == "__main__":
    main()