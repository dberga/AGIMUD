#!/usr/bin/env python3
"""
SWM Analyze Module - Cross-world comparative analysis with full statistical pipeline.

Reads a set of world folders, aggregates timelines, and produces:
    - Per-world plots (same as swm_plots.py, but organized under per_world/<name>/)
      -> generated at the END as an annex
    - Comparative bar charts (actions, emotions, goals, AI states)
    - Comparative line plots over time (one line per world)
    - Comparative entropy / dominant-share line plots (replaces flat line plots)
    - Comparative line plots per category (subplots per world)
    - Box plots of per-character metrics across worlds
    - Dynamics of status variables over time (line plots + box plots)
    - Pearson + Spearman correlation matrix (per-character metrics)
    - Status x Activity correlation matrix (Pearson + Spearman, per world too)
    - Scatter plots status vs activity
    - Cross-world occurrence / co-occurrence matrices:
        * aggregated (raw counts, row-normalized, col-normalized)
        * per-world long-format CSV
        * aggregated heatmaps + small-multiple per-world heatmaps
    - Cohen's d effect sizes between worlds
    - Statistical pipeline per variable:
        1. Normality (Shapiro-Wilk, or D'Agostino-Pearson fallback)
        2. Homogeneity of variance (Levene)
        3. Omnibus: ANOVA / Welch / Kruskal-Wallis
        4. Post-hoc: Tukey HSD / Games-Howell / Dunn + Holm-Bonferroni
        5. Effect sizes: eta^2 (parametric), epsilon^2 (non-parametric)
    - All tables in CSV and LaTeX.
    - Full console output mirrored to analysis.txt

Plotting is delegated to swm_plots.py (shared library), so the same helpers
are reused both by the per-world CLI and by this cross-world analyzer.

Usage:
    python swm_analyze.py --worlds world1 world2 world3
    python swm_analyze.py --worlds world1,world2,world3
    python swm_analyze.py --worlds "world_*"
    python swm_analyze.py --worlds world_*
    python swm_analyze.py --worlds world1 world2 --csv-only
    python swm_analyze.py --worlds world1 world2 --no-latex
    python swm_analyze.py --worlds world1 world2 --no-charts
    python swm_analyze.py --worlds world1 world2 --skip-per-world-plots
    python swm_analyze.py --worlds world1 world2 --skip-matrices
    python swm_analyze.py --worlds world1 world2 --no-log

Optional:
    pip install scipy   # enables full parametric + post-hoc pipeline
"""

import argparse
import csv
import glob
import json
import math
import os
import statistics as stat
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# --- Optional scipy ---
try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except ImportError:
    scipy_stats = None
    HAS_SCIPY = False

# --- Reuse loader + plotting helpers from swm_plots ---
try:
    from swm_plots import (
        TimelinePlotter, HAS_MATPLOTLIB,
        TIMELINE_MAP, MATRIX_SPECS,
        STATUS_VARS, ACTIVITY_VARS,
        safe_set_style,
        plot_comparative_grouped_bars,
        plot_comparative_lineplot_over_time,
        plot_comparative_entropy_over_time,
        plot_comparative_dominant_share_over_time,
        plot_comparative_lineplot_stacked_categories,
        plot_boxplot_metric,
        plot_variable_over_time,
        plot_boxplot_status_variable,
        plot_aggregated_heatmap,
        plot_per_world_heatmaps_grid,
        plot_status_vs_activity_scatter,
    )
except ImportError:
    print("[ERROR] swm_plots.py must be in the same directory as swm_analyze.py")
    sys.exit(1)

if HAS_MATPLOTLIB:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
else:
    print("[ERROR] matplotlib is required for swm_analyze.py")
    sys.exit(1)


# ============================================================
# STDOUT TEE -> analysis.txt
# ============================================================

class _Tee:
    """Duplicates stdout to multiple streams (console + file)."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def start_logging(out_dir: str):
    """Redirect sys.stdout to a tee that also writes analysis.txt.
    Returns the open file handle (must be closed at the end)."""
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "analysis.txt")
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, log_file)
    print(f"[LOG] Console output is being mirrored to: {log_path}")
    return log_file


def stop_logging(log_file):
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        sys.stdout = sys.__stdout__
    except Exception:
        pass
    try:
        log_file.flush()
        log_file.close()
    except Exception:
        pass


# ============================================================
# WORLD COLLECTION
# ============================================================

def parse_worlds_argument(worlds_input: List[str]) -> List[str]:
    worlds: List[str] = []
    for token in worlds_input:
        for sub in str(token).split(','):
            sub = sub.strip()
            if not sub:
                continue
            matches = glob.glob(sub)
            if matches:
                worlds.extend(sorted(matches))
            else:
                worlds.append(sub)
    seen = set()
    unique = []
    for w in worlds:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


def validate_worlds(worlds: List[str]) -> List[str]:
    expected = ["actions_timeline.csv", "emotions_timeline.csv",
                "ai_states_timeline.csv", "goals_timeline.csv"]
    valid = []
    for w in worlds:
        if not os.path.isdir(w):
            print(f"[WARN] Skipping non-existent folder: {w}")
            continue
        found = [f for f in expected if os.path.exists(os.path.join(w, f))]
        if not found:
            print(f"[WARN] Skipping {w} (no timeline CSVs found)")
            continue
        valid.append(w)
    return valid


# ============================================================
# AGGREGATION
# ============================================================

class WorldAggregate:
    def __init__(self, world_path: str):
        self.world_path = world_path
        self.world_name = os.path.basename(os.path.normpath(world_path))

        self.action_counts: Dict[str, int] = defaultdict(int)
        self.emotion_counts: Dict[str, int] = defaultdict(int)
        self.goal_counts: Dict[str, int] = defaultdict(int)
        self.ai_state_counts: Dict[str, int] = defaultdict(int)

        self.per_char_actions: Dict[str, int] = {}
        self.per_char_emotions: Dict[str, int] = {}
        self.per_char_goals: Dict[str, int] = {}
        self.per_char_ai_states: Dict[str, int] = {}
        self.per_char_health: Dict[str, float] = {}
        self.per_char_stamina: Dict[str, float] = {}
        self.per_char_morale: Dict[str, float] = {}
        self.per_char_emotion_transitions: Dict[str, int] = {}

        # Totals per character (not distinct)
        self.per_char_emotions_total: Dict[str, int] = {}
        self.per_char_goals_total: Dict[str, int] = {}
        self.per_char_ai_states_total: Dict[str, int] = {}

        # NEW: entropy per character (replaces Distinct_* when zero-variance)
        self.per_char_emotion_entropy: Dict[str, float] = {}
        self.per_char_goal_entropy: Dict[str, float] = {}
        self.per_char_ai_state_entropy: Dict[str, float] = {}

        self.status_timeline: List[Dict[str, Any]] = []
        self.plotter: Optional[TimelinePlotter] = None
        self.character_stats: Dict[str, Dict[str, Any]] = {}

    def load(self) -> bool:
        self.plotter = TimelinePlotter(self.world_path)
        self.plotter.load_from_csv()

        # Actions
        for entry in self.plotter.action_timeline:
            char = entry.get('character', 'Unknown')
            act = entry.get('action', 'Unknown')
            self.action_counts[act] += 1
            self.per_char_actions[char] = self.per_char_actions.get(char, 0) + 1

        # Emotions: distinct + total + per-character counts for entropy
        char_emotions_distinct: Dict[str, set] = defaultdict(set)
        char_emotions_total: Dict[str, int] = defaultdict(int)
        char_emotion_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for entry in self.plotter.emotion_timeline:
            char = entry.get('character', 'Unknown')
            emo = entry.get('emotion', 'neutral')
            self.emotion_counts[emo] += 1
            char_emotions_distinct[char].add(emo)
            char_emotions_total[char] += 1
            char_emotion_counts[char][emo] += 1
        for char, emo_set in char_emotions_distinct.items():
            self.per_char_emotions[char] = len(emo_set)
        for char, tot in char_emotions_total.items():
            self.per_char_emotions_total[char] = tot
        for char, counts in char_emotion_counts.items():
            self.per_char_emotion_entropy[char] = _entropy_from_counts(dict(counts))

        # Goals: distinct + total + entropy
        char_goals_distinct: Dict[str, set] = defaultdict(set)
        char_goals_total: Dict[str, int] = defaultdict(int)
        char_goal_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for entry in self.plotter.goal_timeline:
            char = entry.get('character', 'Unknown')
            goal = entry.get('goal', 'Unknown')
            self.goal_counts[goal] += 1
            char_goals_distinct[char].add(goal)
            char_goals_total[char] += 1
            char_goal_counts[char][goal] += 1
        for char, goal_set in char_goals_distinct.items():
            self.per_char_goals[char] = len(goal_set)
        for char, tot in char_goals_total.items():
            self.per_char_goals_total[char] = tot
        for char, counts in char_goal_counts.items():
            self.per_char_goal_entropy[char] = _entropy_from_counts(dict(counts))

        # AI states: distinct + total + entropy
        char_ai_states_distinct: Dict[str, set] = defaultdict(set)
        char_ai_states_total: Dict[str, int] = defaultdict(int)
        char_ai_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for entry in self.plotter.ai_state_timeline:
            state = entry.get('ai_state', 'Unknown')
            char = entry.get('character', 'Unknown')
            self.ai_state_counts[state] += 1
            char_ai_states_distinct[char].add(state)
            char_ai_states_total[char] += 1
            char_ai_counts[char][state] += 1
        for char, state_set in char_ai_states_distinct.items():
            self.per_char_ai_states[char] = len(state_set)
        for char, tot in char_ai_states_total.items():
            self.per_char_ai_states_total[char] = tot
        for char, counts in char_ai_counts.items():
            self.per_char_ai_state_entropy[char] = _entropy_from_counts(dict(counts))

        if hasattr(self.plotter, 'status_timeline'):
            self.status_timeline = self.plotter.status_timeline

        stats_path = os.path.join(self.world_path, "statistics.csv")
        if os.path.exists(stats_path):
            self._load_statistics_csv(stats_path)

        return True

    def _load_statistics_csv(self, stats_path: str):
        try:
            with open(stats_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Character') or row.get('character') or 'Unknown'
                    try:
                        health = float(row.get('Mean_Health') or 0)
                        stamina = float(row.get('Mean_Stamina') or 0)
                        morale = float(row.get('Mean_Morale') or 0)
                        transitions = int(float(row.get('Emotion_Transitions') or 0))
                    except (ValueError, TypeError):
                        continue
                    if health:
                        self.per_char_health[name] = health
                    if stamina:
                        self.per_char_stamina[name] = stamina
                    if morale:
                        self.per_char_morale[name] = morale
                    self.per_char_emotion_transitions[name] = transitions
                    self.character_stats[name] = dict(row)
        except Exception as e:
            print(f"[WARN] Could not load statistics.csv from {self.world_path}: {e}")


def _entropy_from_counts(counts: Dict[str, int]) -> float:
    """Shannon entropy in bits from a dict of counts."""
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    ent = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            ent -= p * math.log2(p)
    return ent


# ============================================================
# SHARED HELPERS
# ============================================================

def _latex_escape(s: str) -> str:
    return (str(s).replace('\\', '\\textbackslash{}')
                   .replace('_', '\\_')
                   .replace('%', '\\%')
                   .replace('&', '\\&')
                   .replace('#', '\\#')
                   .replace('{', '\\{')
                   .replace('}', '\\}'))


# ============================================================
# STATISTICAL PRIMITIVES (no-scipy fallbacks)
# ============================================================

def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: List[float], ddof: int = 1) -> float:
    n = len(values)
    if n <= ddof:
        return 0.0
    m = _mean(values)
    return sum((v - m) ** 2 for v in values) / (n - ddof)


def _std(values: List[float], ddof: int = 1) -> float:
    return math.sqrt(_variance(values, ddof))


def _skewness(values: List[float]) -> float:
    n = len(values)
    if n < 3:
        return 0.0
    m = _mean(values)
    s = _std(values, ddof=0)
    if s == 0:
        return 0.0
    m3 = sum((v - m) ** 3 for v in values) / n
    g1 = m3 / (s ** 3)
    return math.sqrt(n * (n - 1)) / (n - 2) * g1 if n > 2 else g1


def _kurtosis_excess(values: List[float]) -> float:
    n = len(values)
    if n < 4:
        return 0.0
    m = _mean(values)
    s = _std(values, ddof=0)
    if s == 0:
        return 0.0
    m4 = sum((v - m) ** 4 for v in values) / n
    g2 = m4 / (s ** 4) - 3.0
    return ((n + 1) * g2 + 6) * (n - 1) / ((n - 2) * (n - 3)) if n > 3 else g2


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _chi2_sf(x: float, df: int) -> float:
    if x <= 0:
        return 1.0
    a = df / 2.0
    z = x / 2.0
    if z < a + 1:
        term = 1.0 / a
        total = term
        n = 1
        while n < 200:
            term *= z / (a + n)
            total += term
            if abs(term) < abs(total) * 1e-12:
                break
            n += 1
        p = total * math.exp(-z + a * math.log(z) - math.lgamma(a))
        return max(0.0, min(1.0, 1.0 - p))
    else:
        tiny = 1e-30
        b = z + 1 - a
        c = 1 / tiny
        d = 1 / b
        h = d
        for i in range(1, 200):
            an = -i * (i - a)
            b += 2
            d = an * d + b
            if abs(d) < tiny:
                d = tiny
            c = b + an / c
            if abs(c) < tiny:
                c = tiny
            d = 1 / d
            delta = d * c
            h *= delta
            if abs(delta - 1) < 1e-12:
                break
        q = math.exp(-z + a * math.log(z) - math.lgamma(a)) * h
        return max(0.0, min(1.0, q))


def _f_sf(f: float, df1: int, df2: int) -> float:
    if f <= 0:
        return 1.0
    x = df2 / (df2 + df1 * f)
    a = df2 / 2.0
    b = df1 / 2.0

    def betai_series(a, b, x):
        tiny = 1e-30
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                      + a * math.log(x) + b * math.log(1 - x))
        if x < (a + 1) / (a + b + 2):
            qab = a + b; qap = a + 1; qam = a - 1
            c = 1.0
            d = 1.0 - qab * x / qap
            if abs(d) < tiny:
                d = tiny
            d = 1.0 / d
            h = d
            for m in range(1, 200):
                m2 = 2 * m
                aa = m * (b - m) * x / ((qam + m2) * (a + m2))
                d = 1.0 + aa * d
                if abs(d) < tiny:
                    d = tiny
                c = 1.0 + aa / c
                if abs(c) < tiny:
                    c = tiny
                d = 1.0 / d
                h *= d * c
                aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
                d = 1.0 + aa * d
                if abs(d) < tiny:
                    d = tiny
                c = 1.0 + aa / c
                if abs(c) < tiny:
                    c = tiny
                d = 1.0 / d
                delta = d * c
                h *= delta
                if abs(delta - 1) < 1e-12:
                    break
            return bt * h / a
        else:
            return 1.0 - betai_series(b, a, 1 - x)

    return betai_series(a, b, x)


# ============================================================
# NORMALITY / VARIANCE
# ============================================================

def dagostino_pearson(values: List[float]) -> Tuple[float, float]:
    n = len(values)
    if n < 8:
        return (0.0, 1.0)
    skew = _skewness(values)
    kurt = _kurtosis_excess(values)
    Y = skew * math.sqrt(((n + 1) * (n + 3)) / (6 * (n - 2)))
    beta2 = (3 * (n * n + 27 * n - 70) * (n + 1) * (n + 3)) / \
            ((n - 2) * (n + 5) * (n + 7) * (n + 9))
    W2 = -1 + math.sqrt(2 * (beta2 - 1))
    delta = 1.0 / math.sqrt(0.5 * math.log(W2))
    alpha = math.sqrt(2.0 / (W2 - 1))
    Z1 = delta * math.asinh(Y / alpha) if skew != 0 else 0.0

    E = 3 * (n - 1) / (n + 1)
    varb2 = (24 * n * (n - 2) * (n - 3)) / ((n + 1) ** 2 * (n + 3) * (n + 5))
    x = (kurt + 3 - E) / math.sqrt(varb2) if varb2 > 0 else 0.0
    Z2 = x if varb2 > 0 else 0.0

    K2 = Z1 * Z1 + Z2 * Z2
    p = _chi2_sf(K2, 2)
    return (K2, p)


def normality_test(values: List[float]) -> Tuple[float, float, str]:
    if HAS_SCIPY:
        if len(values) < 3:
            return (0.0, 1.0, "shapiro")
        try:
            s, p = scipy_stats.shapiro(values)
            return (s, p, "shapiro")
        except Exception:
            return (0.0, 1.0, "shapiro-failed")
    else:
        k2, p = dagostino_pearson(values)
        return (k2, p, "dagostino")


def levene_manual(groups: List[List[float]]) -> Tuple[float, float]:
    k = len(groups)
    if k < 2:
        return (0.0, 1.0)
    medians = [stat.median(g) for g in groups]
    z = [[abs(x - med) for x in g] for g, med in zip(groups, medians)]
    ns = [len(zi) for zi in z]
    if any(n < 2 for n in ns):
        return (0.0, 1.0)
    zi_means = [_mean(zi) for zi in z]
    z_grand = sum(n * m for n, m in zip(ns, zi_means)) / sum(ns)
    num = sum(n * (m - z_grand) ** 2 for n, m in zip(ns, zi_means))
    den = sum(sum((v - m) ** 2 for v in zi) for zi, m in zip(z, zi_means))
    df1 = k - 1
    df2 = sum(ns) - k
    if df2 <= 0 or den == 0:
        return (0.0, 1.0)
    W = (df2 / df1) * (num / den)
    p = _f_sf(W, df1, df2)
    return (W, p)


def variance_homogeneity_test(groups: List[List[float]]) -> Tuple[float, float, str]:
    if HAS_SCIPY:
        try:
            w, p = scipy_stats.levene(*groups, center='median')
            return (w, p, "levene")
        except Exception:
            pass
    w, p = levene_manual(groups)
    return (w, p, "levene-manual")


# ============================================================
# OMNIBUS TESTS
# ============================================================

def anova_manual(groups: List[List[float]]) -> Dict[str, Any]:
    k = len(groups)
    ns = [len(g) for g in groups]
    N = sum(ns)
    if k < 2 or N <= k:
        return {'test': 'ANOVA', 'stat': 0.0, 'p': 1.0, 'df1': 0, 'df2': 0}
    grand_mean = sum(sum(g) for g in groups) / N
    ss_between = sum(n * (_mean(g) - grand_mean) ** 2 for n, g in zip(ns, groups))
    ss_within = sum(sum((x - _mean(g)) ** 2 for x in g) for g in groups)
    df1 = k - 1
    df2 = N - k
    if df2 <= 0 or ss_within == 0:
        return {'test': 'ANOVA', 'stat': 0.0, 'p': 1.0, 'df1': df1, 'df2': df2}
    F = (ss_between / df1) / (ss_within / df2)
    p = _f_sf(F, df1, df2)
    return {'test': 'ANOVA', 'stat': F, 'p': p, 'df1': df1, 'df2': df2}


def welch_anova_manual(groups: List[List[float]]) -> Dict[str, Any]:
    k = len(groups)
    ns = [len(g) for g in groups]
    if k < 2 or any(n < 2 for n in ns):
        return {'test': 'Welch-ANOVA', 'stat': 0.0, 'p': 1.0, 'df1': 0, 'df2': 0}
    means = [_mean(g) for g in groups]
    variances = [_variance(g) for g in groups]
    weights = [n / v if v > 0 else 0.0 for n, v in zip(ns, variances)]
    W = sum(weights)
    if W == 0:
        return {'test': 'Welch-ANOVA', 'stat': 0.0, 'p': 1.0, 'df1': 0, 'df2': 0}
    weighted_mean = sum(w * m for w, m in zip(weights, means)) / W
    num = sum(w * (m - weighted_mean) ** 2 for w, m in zip(weights, means)) / (k - 1)
    den = 1 + (2 * (k - 2) / (k * k - 1)) * sum((1 - w / W) ** 2 / (n - 1)
                                                for w, n in zip(weights, ns) if n > 1)
    F = num / den if den > 0 else 0.0
    df1 = k - 1
    df2_den = sum((1 - w / W) ** 2 / (n - 1) for w, n in zip(weights, ns) if n > 1)
    df2 = (k * k - 1) / (3 * df2_den) if df2_den > 0 else 1
    p = _f_sf(F, df1, int(df2)) if df2 > 0 else 1.0
    return {'test': 'Welch-ANOVA', 'stat': F, 'p': p, 'df1': df1, 'df2': df2}


def kruskal_wallis_manual(groups: List[List[float]]) -> Dict[str, Any]:
    k = len(groups)
    ns = [len(g) for g in groups]
    N = sum(ns)
    if k < 2 or N < 3:
        return {'test': 'Kruskal-Wallis', 'stat': 0.0, 'p': 1.0, 'df': k - 1}
    combined = []
    for i, g in enumerate(groups):
        for v in g:
            combined.append((v, i))
    combined.sort(key=lambda t: t[0])

    ranks = [0.0] * N
    i = 0
    while i < N:
        j = i
        while j + 1 < N and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for kk in range(i, j + 1):
            ranks[kk] = avg_rank
        i = j + 1

    rank_sums = [0.0] * k
    for idx, (_, gi) in enumerate(combined):
        rank_sums[gi] += ranks[idx]

    H = 12.0 / (N * (N + 1)) * sum(rs * rs / n for rs, n in zip(rank_sums, ns) if n > 0) - 3 * (N + 1)
    tie_counts = Counter(v for v, _ in combined)
    tie_correction = sum(t ** 3 - t for t in tie_counts.values() if t > 1)
    if tie_correction > 0:
        H /= (1 - tie_correction / (N ** 3 - N))
    df = k - 1
    p = _chi2_sf(H, df)
    return {'test': 'Kruskal-Wallis', 'stat': H, 'p': p, 'df': df}


def omnibus_test(groups: List[List[float]],
                 all_normal: bool,
                 equal_var: bool) -> Dict[str, Any]:
    if HAS_SCIPY:
        try:
            if all_normal and equal_var:
                f, p = scipy_stats.f_oneway(*groups)
                return {'test': 'ANOVA', 'stat': f, 'p': p}
            elif all_normal and not equal_var:
                return welch_anova_manual(groups)
            else:
                h, p = scipy_stats.kruskal(*groups)
                return {'test': 'Kruskal-Wallis', 'stat': h, 'p': p}
        except Exception:
            pass
    if all_normal and equal_var:
        return anova_manual(groups)
    elif all_normal and not equal_var:
        return welch_anova_manual(groups)
    else:
        return kruskal_wallis_manual(groups)


# ============================================================
# POST-HOC TESTS
# ============================================================

def holm_bonferroni(p_values: List[float]) -> List[float]:
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda t: t[1])
    adjusted = [0.0] * m
    running_max = 0.0
    for rank, (idx, p) in enumerate(indexed):
        adj = p * (m - rank)
        running_max = max(running_max, adj)
        adjusted[idx] = min(1.0, running_max)
    return adjusted


def dunn_test(groups: List[List[float]], labels: List[str]) -> List[Dict[str, Any]]:
    k = len(groups)
    ns = [len(g) for g in groups]
    N = sum(ns)
    if N < 3 or k < 2:
        return []
    combined = []
    for i, g in enumerate(groups):
        for v in g:
            combined.append((v, i))
    combined.sort(key=lambda t: t[0])

    ranks = [0.0] * N
    i = 0
    while i < N:
        j = i
        while j + 1 < N and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for kk in range(i, j + 1):
            ranks[kk] = avg_rank
        i = j + 1

    rank_sums = [0.0] * k
    for idx, (_, gi) in enumerate(combined):
        rank_sums[gi] += ranks[idx]
    mean_ranks = [rs / n if n > 0 else 0.0 for rs, n in zip(rank_sums, ns)]

    tie_counts = Counter(v for v, _ in combined)
    tie_correction = sum(t ** 3 - t for t in tie_counts.values() if t > 1)
    sigma2 = N * (N + 1) / 12.0
    if tie_correction > 0:
        sigma2 -= tie_correction / (12.0 * (N - 1))

    raw = []
    pairs = []
    for i in range(k):
        for j in range(i + 1, k):
            if ns[i] == 0 or ns[j] == 0:
                continue
            denom = math.sqrt(sigma2 * (1.0 / ns[i] + 1.0 / ns[j])) if sigma2 > 0 else 0
            if denom == 0:
                z = 0.0
                p = 1.0
            else:
                z = (mean_ranks[i] - mean_ranks[j]) / denom
                p = 2 * (1 - _norm_cdf(abs(z)))
            raw.append(p)
            pairs.append((labels[i], labels[j], z, p))

    adjusted = holm_bonferroni(raw)
    results = []
    for (a, b, z, p_raw), p_adj in zip(pairs, adjusted):
        results.append({
            'a': a, 'b': b, 'stat': z,
            'p_raw': p_raw, 'p_adj': p_adj,
            'method': 'Dunn-Holm',
        })
    return results


def tukey_hsd_scipy(groups: List[List[float]], labels: List[str]) -> List[Dict[str, Any]]:
    if not HAS_SCIPY:
        return []
    try:
        result = scipy_stats.tukey_hsd(*groups)
    except Exception:
        return dunn_test(groups, labels)
    k = len(labels)
    out = []
    for i in range(k):
        for j in range(i + 1, k):
            out.append({
                'a': labels[i], 'b': labels[j],
                'stat': float(result.statistic[i, j]),
                'p_raw': float(result.pvalue[i, j]),
                'p_adj': float(result.pvalue[i, j]),
                'method': 'Tukey-HSD',
            })
    return out


def pairwise_welch_holm(groups: List[List[float]],
                        labels: List[str]) -> List[Dict[str, Any]]:
    k = len(groups)
    raw = []
    pairs = []
    for i in range(k):
        for j in range(i + 1, k):
            g1, g2 = groups[i], groups[j]
            if len(g1) < 2 or len(g2) < 2:
                continue
            m1, m2 = _mean(g1), _mean(g2)
            v1, v2 = _variance(g1), _variance(g2)
            n1, n2 = len(g1), len(g2)
            se = math.sqrt(v1 / n1 + v2 / n2)
            if se == 0:
                t = 0.0
                p = 1.0
            else:
                t = (m1 - m2) / se
                num = (v1 / n1 + v2 / n2) ** 2
                den = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
                df = num / den if den > 0 else 1
                if HAS_SCIPY:
                    p = 2 * (1 - scipy_stats.t.cdf(abs(t), df))
                else:
                    p = 2 * (1 - _norm_cdf(abs(t)))
            raw.append(p)
            pairs.append((labels[i], labels[j], t, p))

    adjusted = holm_bonferroni(raw)
    results = []
    for (a, b, t, p_raw), p_adj in zip(pairs, adjusted):
        results.append({
            'a': a, 'b': b, 'stat': t,
            'p_raw': p_raw, 'p_adj': p_adj,
            'method': 'Welch-Holm',
        })
    return results


def post_hoc_test(groups: List[List[float]],
                  labels: List[str],
                  omnibus: Dict[str, Any]) -> List[Dict[str, Any]]:
    method = omnibus.get('test', '')
    if HAS_SCIPY and method == 'ANOVA':
        return tukey_hsd_scipy(groups, labels)
    elif method == 'Kruskal-Wallis':
        return dunn_test(groups, labels)
    elif method == 'Welch-ANOVA':
        return pairwise_welch_holm(groups, labels)
    else:
        return dunn_test(groups, labels)


# ============================================================
# EFFECT SIZES
# ============================================================

def cohens_d(xs: List[float], ys: List[float]) -> float:
    n1, n2 = len(xs), len(ys)
    if n1 < 2 or n2 < 2:
        return 0.0
    m1, m2 = _mean(xs), _mean(ys)
    v1, v2 = _variance(xs), _variance(ys)
    pooled = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)) if (n1 + n2 - 2) > 0 else 0
    if pooled == 0:
        return 0.0
    return (m1 - m2) / pooled


def interpret_cohens_d(d: float) -> str:
    ad = abs(d)
    if ad < 0.2:
        return "negligible"
    elif ad < 0.5:
        return "small"
    elif ad < 0.8:
        return "medium"
    else:
        return "large"


def eta_squared_anova(F: float, df1: int, df2: int) -> float:
    if df1 <= 0 or df2 <= 0 or F <= 0:
        return 0.0
    return (F * df1) / (F * df1 + df2)


def epsilon_squared_kruskal(H: float, N: int) -> float:
    if N <= 1 or H <= 0:
        return 0.0
    return H / ((N ** 2 - 1) / (N + 1))


# ============================================================
# PER-CHARACTER VARIABLE COLLECTION
# ============================================================

def _collect_world_variable_values(aggregates: List[WorldAggregate]):
    variables = ['Mean_Health', 'Mean_Stamina', 'Mean_Morale',
                 'Actions_Total', 'Distinct_Emotions', 'Distinct_Goals',
                 'Distinct_AI_States', 'Emotion_Transitions',
                 'Emotion_Entropy', 'Goal_Entropy', 'AI_State_Entropy']

    per_world: Dict[str, Dict[str, List[float]]] = {}
    for agg in aggregates:
        d: Dict[str, List[float]] = {v: [] for v in variables}
        names = set()
        names.update(agg.per_char_actions.keys())
        names.update(agg.per_char_emotions.keys())
        names.update(agg.per_char_goals.keys())
        names.update(agg.per_char_ai_states.keys())
        names.update(agg.per_char_health.keys())
        names.update(agg.per_char_stamina.keys())
        names.update(agg.per_char_morale.keys())
        names.update(agg.per_char_emotion_transitions.keys())
        names.update(agg.per_char_emotion_entropy.keys())
        names.update(agg.per_char_goal_entropy.keys())
        names.update(agg.per_char_ai_state_entropy.keys())
        for name in names:
            row = {
                'Mean_Health': agg.per_char_health.get(name),
                'Mean_Stamina': agg.per_char_stamina.get(name),
                'Mean_Morale': agg.per_char_morale.get(name),
                'Actions_Total': agg.per_char_actions.get(name, 0),
                'Distinct_Emotions': agg.per_char_emotions.get(name, 0),
                'Distinct_Goals': agg.per_char_goals.get(name, 0),
                'Distinct_AI_States': agg.per_char_ai_states.get(name, 0),
                'Emotion_Transitions': agg.per_char_emotion_transitions.get(name, 0),
                'Emotion_Entropy': agg.per_char_emotion_entropy.get(name),
                'Goal_Entropy': agg.per_char_goal_entropy.get(name),
                'AI_State_Entropy': agg.per_char_ai_state_entropy.get(name),
            }
            for v in variables:
                if row[v] is not None:
                    d[v].append(float(row[v]))
        per_world[agg.world_name] = d
    return variables, per_world


# ============================================================
# STATISTICAL PIPELINE
# ============================================================

def run_statistical_pipeline(aggregates: List[WorldAggregate]) -> List[Dict[str, Any]]:
    variables, per_world = _collect_world_variable_values(aggregates)
    world_names = list(per_world.keys())

    results = []
    for v in variables:
        groups = [per_world[w][v] for w in world_names]
        used_worlds = [w for w, g in zip(world_names, groups) if len(g) >= 2]
        groups = [g for g in groups if len(g) >= 2]

        if len(groups) < 2:
            results.append({'variable': v, 'skipped': True,
                            'reason': 'not enough groups with n>=2'})
            continue

        # NEW: skip variables with essentially zero variance across all data
        all_vals = [x for g in groups for x in g]
        if all_vals:
            mu = sum(all_vals) / len(all_vals)
            sd = (sum((x - mu) ** 2 for x in all_vals) / max(1, len(all_vals) - 1)) ** 0.5
            if sd < 1e-6:
                results.append({'variable': v, 'skipped': True,
                                'reason': 'zero variance (constant across all groups)'})
                continue

        normality = []
        for g in groups:
            s, p, name = normality_test(g)
            normality.append({'stat': s, 'p': p, 'test': name, 'n': len(g)})
        all_normal = all(n['p'] > 0.05 for n in normality)

        lev_stat, lev_p, lev_name = variance_homogeneity_test(groups)
        equal_var = lev_p > 0.05

        omnibus = omnibus_test(groups, all_normal, equal_var)

        if omnibus['test'] in ('ANOVA', 'Welch-ANOVA'):
            df1 = omnibus.get('df1', len(groups) - 1)
            df2 = omnibus.get('df2', sum(len(g) for g in groups) - len(groups))
            effect_size = eta_squared_anova(omnibus['stat'], df1, int(df2) if df2 > 0 else 1)
            effect_name = 'eta^2'
        else:
            N = sum(len(g) for g in groups)
            effect_size = epsilon_squared_kruskal(omnibus['stat'], N)
            effect_name = 'epsilon^2'

        posthoc = []
        if omnibus['p'] < 0.05:
            posthoc = post_hoc_test(groups, used_worlds, omnibus)

        results.append({
            'variable': v,
            'skipped': False,
            'worlds': used_worlds,
            'group_sizes': [len(g) for g in groups],
            'group_means': [_mean(g) for g in groups],
            'group_std': [_std(g) for g in groups],
            'normality': normality,
            'all_normal': all_normal,
            'levene_stat': lev_stat,
            'levene_p': lev_p,
            'levene_test': lev_name,
            'equal_var': equal_var,
            'omnibus': omnibus,
            'effect_size': effect_size,
            'effect_size_name': effect_name,
            'posthoc': posthoc,
        })
    return results


# ============================================================
# PRINTING: STATISTICAL PIPELINE
# ============================================================

def print_statistical_pipeline(results: List[Dict[str, Any]]):
    print("\n" + "=" * 100)
    print("STATISTICAL PIPELINE (per variable)")
    print("=" * 100)
    print("[INFO] scipy detected: full parametric tests available."
          if HAS_SCIPY else
          "[INFO] scipy NOT detected: using fallbacks.")
    for r in results:
        print("\n" + "-" * 100)
        print(f"VARIABLE: {r['variable']}")
        print("-" * 100)
        if r.get('skipped'):
            print(f"  [SKIPPED] {r.get('reason', '')}")
            continue
        print("  Group summary:")
        for w, n, m, s in zip(r['worlds'], r['group_sizes'],
                              r['group_means'], r['group_std']):
            print(f"    {w:30}  n={n:3d}  mean={m:8.2f}  std={s:7.2f}")
        print("  Normality per group:")
        for w, norm in zip(r['worlds'], r['normality']):
            status = "normal" if norm['p'] > 0.05 else "NOT normal"
            print(f"    {w:30}  {norm['test']:10}  stat={norm['stat']:7.3f}  "
                  f"p={norm['p']:.4f}  -> {status}")
        print(f"  => all groups normal? {'YES' if r['all_normal'] else 'NO'}")
        print(f"  Levene: stat={r['levene_stat']:.4f}  p={r['levene_p']:.4f}  "
              f"-> {'equal variances' if r['equal_var'] else 'UNEQUAL variances'}")
        om = r['omnibus']
        sig = "***" if om['p'] < 0.001 else "**" if om['p'] < 0.01 else "*" if om['p'] < 0.05 else "n.s."
        print(f"  Omnibus: {om['test']:18}  stat={om['stat']:8.4f}  p={om['p']:.4f}  {sig}")
        print(f"  Effect size ({r['effect_size_name']}): {r['effect_size']:.4f}")
        if r['posthoc']:
            sig_pairs = [p for p in r['posthoc'] if p['p_adj'] < 0.05]
            print("  Post-hoc significant pairs:")
            if not sig_pairs:
                print("    (none after correction)")
            else:
                for p in sig_pairs:
                    mark = "***" if p['p_adj'] < 0.001 else "**" if p['p_adj'] < 0.01 else "*"
                    print(f"    {p['a']:20} vs {p['b']:20}  "
                          f"stat={p['stat']:+.3f}  p_raw={p['p_raw']:.4f}  "
                          f"p_adj={p['p_adj']:.4f} {mark}  [{p['method']}]")
    print("=" * 100)


# ============================================================
# CSV EXPORTS: STATISTICAL PIPELINE
# ============================================================

def write_statistical_pipeline_csv(results, out_path):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Variable', 'Worlds_Used', 'All_Normal', 'Normality_Test',
            'Levene_Stat', 'Levene_p', 'Equal_Var',
            'Omnibus_Test', 'Omnibus_Stat', 'Omnibus_p',
            'Effect_Size_Name', 'Effect_Size',
            'PostHoc_Method', 'Sig_Pairs_Count'])
        for r in results:
            if r.get('skipped'):
                writer.writerow([r['variable'], '', '--', '--', '--', '--', '--',
                                 '--', '--', '--', '--', '--', '--', 'SKIPPED'])
                continue
            norm_test = r['normality'][0]['test'] if r['normality'] else '--'
            om = r['omnibus']
            posthoc_method = r['posthoc'][0]['method'] if r['posthoc'] else '--'
            sig_count = sum(1 for p in r['posthoc'] if p['p_adj'] < 0.05)
            writer.writerow([
                r['variable'], ';'.join(r['worlds']),
                r['all_normal'], norm_test,
                round(r['levene_stat'], 4), round(r['levene_p'], 6), r['equal_var'],
                om['test'], round(om['stat'], 4), round(om['p'], 6),
                r['effect_size_name'], round(r['effect_size'], 4),
                posthoc_method, sig_count])
    print(f"[CSV]   {out_path}")


def write_statistical_pipeline_posthoc_csv(results, out_path):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Variable', 'World_A', 'World_B', 'Method', 'Stat',
                         'p_raw', 'p_adj', 'Significant'])
        for r in results:
            if r.get('skipped'):
                continue
            for p in r['posthoc']:
                writer.writerow([r['variable'], p['a'], p['b'], p['method'],
                                 round(p['stat'], 4), round(p['p_raw'], 6),
                                 round(p['p_adj'], 6), p['p_adj'] < 0.05])
    print(f"[CSV]   {out_path}")


# ============================================================
# LaTeX: STATISTICAL PIPELINE
# ============================================================

def write_statistical_pipeline_latex(results, out_path):
    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\caption{Statistical pipeline per variable: normality, homogeneity, omnibus test, effect size.}")
    lines.append("\\label{tab:statistical_pipeline}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append("\\begin{tabular}{|l|c|c|c|c|c|c|}")
    lines.append("\\hline")
    lines.append("\\textbf{Variable} & \\textbf{All Normal?} & \\textbf{Levene $p$} & "
                 "\\textbf{Equal Var?} & \\textbf{Omnibus} & \\textbf{$p$-value} & "
                 "\\textbf{Effect size} \\\\")
    lines.append("\\hline")
    for r in results:
        if r.get('skipped'):
            lines.append(f"\\texttt{{{_latex_escape(r['variable'])}}} & -- & -- & -- & -- & -- & -- \\\\")
            continue
        om = r['omnibus']
        p_str = f"{om['p']:.4f}"
        if om['p'] < 0.001:
            p_str = f"\\cellcolor{{red!25}}{p_str}"
        elif om['p'] < 0.01:
            p_str = f"\\cellcolor{{orange!25}}{p_str}"
        elif om['p'] < 0.05:
            p_str = f"\\cellcolor{{yellow!25}}{p_str}"
        lines.append(
            f"\\texttt{{{_latex_escape(r['variable'])}}} & "
            f"{'Yes' if r['all_normal'] else 'No'} & "
            f"{r['levene_p']:.3f} & "
            f"{'Yes' if r['equal_var'] else 'No'} & "
            f"{om['test']} & {p_str} & "
            f"{r['effect_size_name']}={r['effect_size']:.3f} \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


def write_statistical_pipeline_posthoc_latex(results, out_path):
    sig_pairs = []
    for r in results:
        if r.get('skipped'):
            continue
        for p in r['posthoc']:
            if p['p_adj'] < 0.05:
                sig_pairs.append((r['variable'], p))

    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\caption{Statistically significant post-hoc pairwise differences ($p_{\\text{adj}} < 0.05$).}")
    lines.append("\\label{tab:statistical_posthoc}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append("\\begin{tabular}{|l|l|l|l|c|c|c|}")
    lines.append("\\hline")
    lines.append("\\textbf{Variable} & \\textbf{World A} & \\textbf{World B} & \\textbf{Method} & "
                 "\\textbf{Stat} & \\textbf{$p_{\\text{raw}}$} & \\textbf{$p_{\\text{adj}}$} \\\\")
    lines.append("\\hline")
    if not sig_pairs:
        lines.append("\\multicolumn{7}{|c|}{No significant post-hoc differences at $\\alpha=0.05$} \\\\")
    else:
        for v, p in sig_pairs:
            p_adj_str = f"{p['p_adj']:.4f}"
            if p['p_adj'] < 0.001:
                p_adj_str = f"\\cellcolor{{red!25}}{p_adj_str}"
            elif p['p_adj'] < 0.01:
                p_adj_str = f"\\cellcolor{{orange!25}}{p_adj_str}"
            else:
                p_adj_str = f"\\cellcolor{{yellow!25}}{p_adj_str}"
            lines.append(
                f"\\texttt{{{_latex_escape(v)}}} & "
                f"{_latex_escape(p['a'])} & {_latex_escape(p['b'])} & "
                f"{p['method']} & {p['stat']:+.3f} & "
                f"{p['p_raw']:.4f} & {p_adj_str} \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


# ============================================================
# PER-WORLD PLOTS (reuse swm_plots.TimelinePlotter)
# ============================================================

def generate_per_world_plots(aggregates: List[WorldAggregate], out_root: str):
    """
    For each world, generate all the individual timeline charts that
    swm_plots.py produces, but saved into <out>/per_world/<world_name>/.
    """
    for agg in aggregates:
        if not agg.plotter:
            continue
        world_dir = os.path.join(out_root, "per_world", agg.world_name)
        os.makedirs(world_dir, exist_ok=True)
        original_folder = agg.plotter.world_folder
        agg.plotter.world_folder = world_dir
        try:
            print(f"\n[PER-WORLD PLOTS] {agg.world_name} -> {world_dir}")
            agg.plotter.generate_all_charts()
        except Exception as e:
            print(f"[ERROR] Failed to generate per-world plots for {agg.world_name}: {e}")
        finally:
            agg.plotter.world_folder = original_folder


# ============================================================
# COMPARATIVE CSVs
# ============================================================

def write_comparative_counts_csv(aggregates, field, out_path):
    if not aggregates:
        return
    all_cats = set()
    for agg in aggregates:
        all_cats.update(getattr(agg, field).keys())
    all_cats = sorted(all_cats)
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Category'] + [agg.world_name for agg in aggregates] + ['Total'])
        for cat in all_cats:
            row = [cat]
            total = 0
            for agg in aggregates:
                v = getattr(agg, field).get(cat, 0)
                row.append(v); total += v
            row.append(total)
            writer.writerow(row)
    print(f"[CSV]   {out_path}")


def write_per_character_metrics_csv(aggregates, out_path):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['World', 'Character',
                         'Actions_Total', 'Distinct_Emotions', 'Distinct_Goals',
                         'Distinct_AI_States',
                         'Emotions_Total', 'Goals_Total', 'AI_States_Total',
                         'Emotion_Entropy', 'Goal_Entropy', 'AI_State_Entropy',
                         'Mean_Health', 'Mean_Stamina', 'Mean_Morale',
                         'Emotion_Transitions'])
        for agg in aggregates:
            names = set()
            names.update(agg.per_char_actions.keys())
            names.update(agg.per_char_emotions.keys())
            names.update(agg.per_char_goals.keys())
            names.update(agg.per_char_ai_states.keys())
            names.update(agg.per_char_health.keys())
            names.update(agg.per_char_stamina.keys())
            names.update(agg.per_char_morale.keys())
            names.update(agg.per_char_emotion_transitions.keys())
            names.update(agg.per_char_emotions_total.keys())
            names.update(agg.per_char_goals_total.keys())
            names.update(agg.per_char_ai_states_total.keys())
            names.update(agg.per_char_emotion_entropy.keys())
            names.update(agg.per_char_goal_entropy.keys())
            names.update(agg.per_char_ai_state_entropy.keys())
            for name in sorted(names):
                writer.writerow([
                    agg.world_name, name,
                    agg.per_char_actions.get(name, 0),
                    agg.per_char_emotions.get(name, 0),
                    agg.per_char_goals.get(name, 0),
                    agg.per_char_ai_states.get(name, 0),
                    agg.per_char_emotions_total.get(name, 0),
                    agg.per_char_goals_total.get(name, 0),
                    agg.per_char_ai_states_total.get(name, 0),
                    round(agg.per_char_emotion_entropy.get(name, 0.0), 4),
                    round(agg.per_char_goal_entropy.get(name, 0.0), 4),
                    round(agg.per_char_ai_state_entropy.get(name, 0.0), 4),
                    round(agg.per_char_health.get(name, 0.0), 2),
                    round(agg.per_char_stamina.get(name, 0.0), 2),
                    round(agg.per_char_morale.get(name, 0.0), 2),
                    agg.per_char_emotion_transitions.get(name, 0)])
    print(f"[CSV]   {out_path}")


def write_comparative_summary_csv(aggregates, out_path):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['World', 'Total_Actions', 'Total_Emotions', 'Total_Goals',
                         'Total_AI_States',
                         'Distinct_Actions', 'Distinct_Emotions', 'Distinct_Goals',
                         'Distinct_AI_States',
                         'Mean_Health', 'Mean_Stamina', 'Mean_Morale',
                         'Mean_Emotion_Transitions', 'Mean_Emotion_Entropy',
                         'Mean_Goal_Entropy', 'Mean_AI_State_Entropy'])
        for agg in aggregates:
            def _m(d):
                vals = list(d.values())
                return round(sum(vals) / len(vals), 2) if vals else 0.0
            writer.writerow([
                agg.world_name,
                sum(agg.action_counts.values()),
                sum(agg.emotion_counts.values()),
                sum(agg.goal_counts.values()),
                sum(agg.ai_state_counts.values()),
                len(agg.action_counts), len(agg.emotion_counts),
                len(agg.goal_counts), len(agg.ai_state_counts),
                _m(agg.per_char_health), _m(agg.per_char_stamina),
                _m(agg.per_char_morale), _m(agg.per_char_emotion_transitions),
                _m(agg.per_char_emotion_entropy), _m(agg.per_char_goal_entropy),
                _m(agg.per_char_ai_state_entropy)])
    print(f"[CSV]   {out_path}")


def write_dynamics_summary_csv(aggregates, out_path):
    variables = detect_status_variables(aggregates)
    if not variables:
        print(f"[WARN] No status variables found to summarize in {out_path}")
        return
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        header = ['World']
        for v in variables:
            header += [f'{v}_mean', f'{v}_std', f'{v}_min', f'{v}_max']
        writer.writerow(header)
        for agg in aggregates:
            row = [agg.world_name]
            for v in variables:
                vals = [e.get(v) for e in agg.status_timeline
                        if isinstance(e.get(v), (int, float))
                        and not isinstance(e.get(v), bool)]
                if vals:
                    row += [round(stat.mean(vals), 2),
                            round(stat.stdev(vals), 2) if len(vals) > 1 else 0.0,
                            round(min(vals), 2), round(max(vals), 2)]
                else:
                    row += ['--', '--', '--', '--']
            writer.writerow(row)
    print(f"[CSV]   {out_path}")


# ============================================================
# BASIC LaTeX TABLES
# ============================================================

def write_latex_summary(aggregates, out_path):
    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\caption{Cross-world aggregate statistics.}")
    lines.append("\\label{tab:cross_world_summary}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append("\\begin{tabular}{|l|c|c|c|c|c|c|c|}")
    lines.append("\\hline")
    lines.append("\\textbf{World} & \\textbf{Actions} & \\textbf{Emotions} & "
                 "\\textbf{Goals} & \\textbf{AI States} & \\textbf{Mean HP} & "
                 "\\textbf{Mean ST} & \\textbf{Mean MO} \\\\")
    lines.append("\\hline")
    for agg in aggregates:
        def _m(d):
            vals = list(d.values())
            return f"{sum(vals)/len(vals):.1f}" if vals else "--"
        lines.append(
            f"{_latex_escape(agg.world_name)} & "
            f"{sum(agg.action_counts.values())} & "
            f"{sum(agg.emotion_counts.values())} & "
            f"{sum(agg.goal_counts.values())} & "
            f"{sum(agg.ai_state_counts.values())} & "
            f"{_m(agg.per_char_health)} & {_m(agg.per_char_stamina)} & "
            f"{_m(agg.per_char_morale)} \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


def write_latex_counts_table(aggregates, field, caption, label, out_path, top_k=12):
    if not aggregates:
        return
    totals = defaultdict(int)
    for agg in aggregates:
        for cat, cnt in getattr(agg, field).items():
            totals[cat] += cnt
    top_categories = [c for c, _ in sorted(totals.items(), key=lambda x: -x[1])[:top_k]]
    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append(f"\\caption{{{caption}}}")
    lines.append(f"\\label{{{label}}}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append(f"\\begin{{tabular}}{{|l|{'c|' * len(aggregates)}}}")
    lines.append("\\hline")
    lines.append("\\textbf{Category} & " + " & ".join(
        f"\\textbf{{{_latex_escape(a.world_name)}}}" for a in aggregates) + " \\\\")
    lines.append("\\hline")
    for cat in top_categories:
        row = [f"\\texttt{{{_latex_escape(cat)}}}"]
        for agg in aggregates:
            row.append(str(getattr(agg, field).get(cat, 0)))
        lines.append(" & ".join(row) + " \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


def write_latex_dynamics_table(aggregates, out_path):
    variables = detect_status_variables(aggregates)
    if not variables:
        return
    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\caption{Cross-world dynamics of status variables (mean value).}")
    lines.append("\\label{tab:cross_world_dynamics}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append(f"\\begin{{tabular}}{{|l|{'c|' * len(variables)}}}")
    lines.append("\\hline")
    lines.append("\\textbf{World} & " +
                 " & ".join(f"\\textbf{{{_latex_escape(v)}}}" for v in variables) + " \\\\")
    lines.append("\\hline")
    for agg in aggregates:
        row = [_latex_escape(agg.world_name)]
        for v in variables:
            vals = [e.get(v) for e in agg.status_timeline
                    if isinstance(e.get(v), (int, float))
                    and not isinstance(e.get(v), bool)]
            row.append(f"{stat.mean(vals):.1f}" if vals else "--")
        lines.append(" & ".join(row) + " \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


# ============================================================
# DYNAMICS: STATUS VARIABLE DETECTION
# ============================================================

def detect_status_variables(aggregates):
    numeric = {}
    for agg in aggregates:
        for entry in agg.status_timeline:
            for k, v in entry.items():
                if k in ('tick', 'character', 'ai_state', 'emotion'):
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    numeric[k] = numeric.get(k, 0) + 1
    return sorted(numeric.keys())


# ============================================================
# CORRELATION
# ============================================================

def pearson_correlation(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _rank(values: List[float]) -> List[float]:
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda t: t[1])
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


def spearman_correlation(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    rx = _rank(xs)
    ry = _rank(ys)
    return pearson_correlation(rx, ry)


def build_per_character_matrix(aggregates):
    variables = ['Mean_Health', 'Mean_Stamina', 'Mean_Morale',
                 'Actions_Total', 'Distinct_Emotions', 'Distinct_Goals',
                 'Distinct_AI_States', 'Emotion_Transitions',
                 'Emotion_Entropy', 'Goal_Entropy', 'AI_State_Entropy']
    rows = []
    for agg in aggregates:
        names = set()
        names.update(agg.per_char_actions.keys())
        names.update(agg.per_char_emotions.keys())
        names.update(agg.per_char_goals.keys())
        names.update(agg.per_char_ai_states.keys())
        names.update(agg.per_char_health.keys())
        names.update(agg.per_char_stamina.keys())
        names.update(agg.per_char_morale.keys())
        names.update(agg.per_char_emotion_transitions.keys())
        names.update(agg.per_char_emotion_entropy.keys())
        names.update(agg.per_char_goal_entropy.keys())
        names.update(agg.per_char_ai_state_entropy.keys())
        for name in names:
            row = {
                'World': agg.world_name, 'Character': name,
                'Mean_Health': agg.per_char_health.get(name),
                'Mean_Stamina': agg.per_char_stamina.get(name),
                'Mean_Morale': agg.per_char_morale.get(name),
                'Actions_Total': agg.per_char_actions.get(name, 0),
                'Distinct_Emotions': agg.per_char_emotions.get(name, 0),
                'Distinct_Goals': agg.per_char_goals.get(name, 0),
                'Distinct_AI_States': agg.per_char_ai_states.get(name, 0),
                'Emotion_Transitions': agg.per_char_emotion_transitions.get(name, 0),
                'Emotion_Entropy': agg.per_char_emotion_entropy.get(name),
                'Goal_Entropy': agg.per_char_goal_entropy.get(name),
                'AI_State_Entropy': agg.per_char_ai_state_entropy.get(name),
            }
            if all(row.get(v) is not None for v in variables):
                rows.append(row)
    columns = {v: [] for v in variables}
    for r in rows:
        for v in variables:
            columns[v].append(float(r[v]))
    return variables, columns


def compute_correlation_matrix(variables, columns):
    return {(v1, v2): pearson_correlation(columns[v1], columns[v2])
            for v1 in variables for v2 in variables}


def print_correlation_matrix(variables, matrix):
    print("\n" + "=" * 90)
    print("PEARSON CORRELATION MATRIX (per-character metrics)")
    print("=" * 90)
    header = "Variable".ljust(24) + "".join(f"{v[:9].rjust(11)}" for v in variables)
    print(header)
    print("-" * len(header))
    for v1 in variables:
        row = v1[:22].ljust(24)
        for v2 in variables:
            row += f"{matrix[(v1, v2)]:>11.2f}"
        print(row)
    print("=" * 90)


def write_correlation_csv(variables, matrix, out_path):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Variable'] + variables)
        for v1 in variables:
            writer.writerow([v1] + [round(matrix[(v1, v2)], 3) for v2 in variables])
    print(f"[CSV]   {out_path}")


def write_correlation_latex(variables, matrix, out_path):
    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append("\\caption{Pearson correlation matrix between per-character metrics.}")
    lines.append("\\label{tab:correlation_matrix}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append(f"\\begin{{tabular}}{{|l|{'c|' * len(variables)}}}")
    lines.append("\\hline")
    lines.append("\\textbf{Variable} & " +
                 " & ".join(f"\\textbf{{{_latex_escape(v)}}}" for v in variables) + " \\\\")
    lines.append("\\hline")
    for v1 in variables:
        row = [f"\\texttt{{{_latex_escape(v1)}}}"]
        for v2 in variables:
            c = matrix[(v1, v2)]
            if v1 == v2:
                row.append("\\cellcolor{gray!20}1.00")
            elif c > 0.5:
                row.append(f"\\cellcolor{{blue!20}}{c:.2f}")
            elif c > 0.2:
                row.append(f"\\cellcolor{{blue!10}}{c:.2f}")
            elif c < -0.5:
                row.append(f"\\cellcolor{{red!20}}{c:.2f}")
            elif c < -0.2:
                row.append(f"\\cellcolor{{red!10}}{c:.2f}")
            else:
                row.append(f"{c:.2f}")
        lines.append(" & ".join(row) + " \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


# ============================================================
# STATUS x ACTIVITY CORRELATION
# ============================================================

def build_status_activity_rows(aggregates) -> List[Dict[str, Any]]:
    """Per-character rows containing status + activity metrics."""
    rows = []
    for agg in aggregates:
        names = set()
        names.update(agg.per_char_health.keys())
        names.update(agg.per_char_stamina.keys())
        names.update(agg.per_char_morale.keys())
        names.update(agg.per_char_actions.keys())
        names.update(agg.per_char_emotions_total.keys())
        names.update(agg.per_char_goals_total.keys())
        names.update(agg.per_char_ai_states_total.keys())
        names.update(agg.per_char_emotion_entropy.keys())
        names.update(agg.per_char_goal_entropy.keys())
        names.update(agg.per_char_ai_state_entropy.keys())

        for name in names:
            if (name not in agg.per_char_health
                    and name not in agg.per_char_stamina
                    and name not in agg.per_char_morale):
                continue
            rows.append({
                'World': agg.world_name,
                'Character': name,
                'Mean_Health': agg.per_char_health.get(name),
                'Mean_Stamina': agg.per_char_stamina.get(name),
                'Mean_Morale': agg.per_char_morale.get(name),
                'Actions_Total': agg.per_char_actions.get(name, 0),
                'Emotions_Total': agg.per_char_emotions_total.get(name, 0),
                'Goals_Total': agg.per_char_goals_total.get(name, 0),
                'AI_States_Total': agg.per_char_ai_states_total.get(name, 0),
                'Distinct_Emotions': agg.per_char_emotions.get(name, 0),
                'Distinct_Goals': agg.per_char_goals.get(name, 0),
                'Distinct_AI_States': agg.per_char_ai_states.get(name, 0),
                'Emotion_Transitions': agg.per_char_emotion_transitions.get(name, 0),
                'Emotion_Entropy': agg.per_char_emotion_entropy.get(name, 0.0),
                'Goal_Entropy': agg.per_char_goal_entropy.get(name, 0.0),
                'AI_State_Entropy': agg.per_char_ai_state_entropy.get(name, 0.0),
            })
    return rows


def compute_status_activity_correlations(rows: List[Dict[str, Any]]):
    all_vars = STATUS_VARS + ACTIVITY_VARS
    filtered = [r for r in rows if all(r.get(v) is not None for v in all_vars)]
    columns = {v: [float(r[v]) for r in filtered] for v in all_vars}
    return all_vars, columns, filtered


def print_status_activity_correlations(rows: List[Dict[str, Any]]):
    all_vars, columns, filtered = compute_status_activity_correlations(rows)
    n = len(filtered)
    print("\n" + "=" * 100)
    print(f"STATUS x ACTIVITY CORRELATIONS (n = {n} character-world rows)")
    print("=" * 100)
    if n < 3:
        print("[WARN] Not enough rows for meaningful correlation.")
        return
    print(f"{'Status \\ Activity':<18}", end="")
    for a in ACTIVITY_VARS:
        print(f"{a[:14]:>16}", end="")
    print()
    print("-" * (18 + 16 * len(ACTIVITY_VARS)))
    for s in STATUS_VARS:
        print(f"{s:<18}", end="")
        for a in ACTIVITY_VARS:
            r_p = pearson_correlation(columns[s], columns[a])
            r_s = spearman_correlation(columns[s], columns[a])
            print(f"{r_p:>+7.2f}/{r_s:>+6.2f}", end="")
        print()
    print("\n  Format: Pearson / Spearman")
    print("=" * 100)

    worlds = sorted(set(r['World'] for r in filtered))
    if len(worlds) > 1:
        print("\nPER-WORLD STATUS x ACTIVITY CORRELATIONS (Pearson only)")
        print("=" * 100)
        for w in worlds:
            sub = [r for r in filtered if r['World'] == w]
            if len(sub) < 3:
                print(f"  [{w}] n={len(sub)} -> too few for correlation")
                continue
            print(f"\n  --- {w} (n={len(sub)}) ---")
            sub_cols = {v: [float(r[v]) for r in sub] for v in all_vars}
            print(f"  {'Status \\ Activity':<18}", end="")
            for a in ACTIVITY_VARS:
                print(f"{a[:14]:>16}", end="")
            print()
            for s in STATUS_VARS:
                print(f"  {s:<18}", end="")
                for a in ACTIVITY_VARS:
                    r_p = pearson_correlation(sub_cols[s], sub_cols[a])
                    print(f"{r_p:>+16.2f}", end="")
                print()
        print("=" * 100)


def write_status_activity_correlations_csv(rows: List[Dict[str, Any]], out_path: str):
    all_vars, columns, filtered = compute_status_activity_correlations(rows)
    n = len(filtered)
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Status_Variable', 'Activity_Variable',
                         'Pearson_r', 'Spearman_r', 'N'])
        for s in STATUS_VARS:
            for a in ACTIVITY_VARS:
                r_p = pearson_correlation(columns[s], columns[a])
                r_s = spearman_correlation(columns[s], columns[a])
                writer.writerow([s, a, round(r_p, 4), round(r_s, 4), n])
    print(f"[CSV]   {out_path}")

    per_world_path = out_path.replace('.csv', '_per_world.csv')
    worlds = sorted(set(r['World'] for r in filtered))
    with open(per_world_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['World', 'Status_Variable', 'Activity_Variable',
                         'Pearson_r', 'Spearman_r', 'N'])
        for w in worlds:
            sub = [r for r in filtered if r['World'] == w]
            if len(sub) < 2:
                continue
            sub_cols = {v: [float(r[v]) for r in sub] for v in all_vars}
            for s in STATUS_VARS:
                for a in ACTIVITY_VARS:
                    r_p = pearson_correlation(sub_cols[s], sub_cols[a])
                    r_s = spearman_correlation(sub_cols[s], sub_cols[a])
                    writer.writerow([w, s, a, round(r_p, 4), round(r_s, 4), len(sub)])
    print(f"[CSV]   {per_world_path}")


def write_status_activity_correlations_latex(rows: List[Dict[str, Any]], out_path: str):
    all_vars, columns, filtered = compute_status_activity_correlations(rows)
    n = len(filtered)
    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append(f"\\caption{{Status $\\times$ activity correlations (n={n}). "
                 "Each cell shows Pearson $r$ / Spearman $\\rho$.}")
    lines.append("\\label{tab:status_activity_corr}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append(f"\\begin{{tabular}}{{|l|{'c|' * len(ACTIVITY_VARS)}}}")
    lines.append("\\hline")
    lines.append("\\textbf{Status} & " +
                 " & ".join(f"\\textbf{{{_latex_escape(a)}}}" for a in ACTIVITY_VARS) + " \\\\")
    lines.append("\\hline")
    for s in STATUS_VARS:
        row = [f"\\texttt{{{_latex_escape(s)}}}"]
        for a in ACTIVITY_VARS:
            r_p = pearson_correlation(columns[s], columns[a])
            r_s = spearman_correlation(columns[s], columns[a])
            cell = f"{r_p:+.2f}/{r_s:+.2f}"
            if abs(r_p) >= 0.5:
                cell = f"\\cellcolor{{red!20}}{cell}"
            elif abs(r_p) >= 0.3:
                cell = f"\\cellcolor{{orange!20}}{cell}"
            elif abs(r_p) >= 0.1:
                cell = f"\\cellcolor{{yellow!20}}{cell}"
            row.append(cell)
        lines.append(" & ".join(row) + " \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


# ============================================================
# OCCURRENCE / CO-OCCURRENCE MATRICES (cross-world)
# ============================================================

def _sum_matrices(aggregates, attr_name):
    total = defaultdict(lambda: defaultdict(int))
    for agg in aggregates:
        if not agg.plotter:
            continue
        m = getattr(agg.plotter, attr_name, None)
        if not m:
            continue
        for r, inner in m.items():
            for c, v in inner.items():
                total[r][c] += v
    return total


def write_aggregated_matrix_csv(matrix, row_label, col_label, out_path,
                                normalize='none'):
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
        norm = np.divide(raw, denom, out=np.zeros_like(raw), where=denom > 0)
    elif normalize == 'col':
        denom = raw.sum(axis=0, keepdims=True)
        norm = np.divide(raw, denom, out=np.zeros_like(raw), where=denom > 0)
    elif normalize == 'all':
        s = raw.sum()
        norm = raw / s if s > 0 else raw
    else:
        norm = raw

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([f'{row_label} \\ {col_label}'] + cols)
        for i, r in enumerate(rows):
            writer.writerow([r] + [round(float(v), 4) for v in norm[i]])
    print(f"[CSV]   {out_path}")
    return True


def write_per_world_matrices_csv(aggregates, attr_name, row_label, col_label, out_path):
    rows_seen = set()
    cols_seen = set()
    for agg in aggregates:
        if not agg.plotter:
            continue
        m = getattr(agg.plotter, attr_name, None) or {}
        rows_seen.update(m.keys())
        for inner in m.values():
            cols_seen.update(inner.keys())
    rows_seen = sorted(rows_seen)
    cols_seen = sorted(cols_seen)

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['World', row_label, col_label, 'Count'])
        for agg in aggregates:
            if not agg.plotter:
                continue
            m = getattr(agg.plotter, attr_name, None) or {}
            for r in rows_seen:
                for c in cols_seen:
                    v = m.get(r, {}).get(c, 0)
                    if v:
                        writer.writerow([agg.world_name, r, c, v])
    print(f"[CSV]   {out_path}")


def run_occurrence_matrices(aggregates, out_dir, csv_only=False, no_charts=False):
    """Generate aggregated + per-world occurrence matrices and heatmaps.

    Plotting delegates to swm_plots.plot_aggregated_heatmap and
    swm_plots.plot_per_world_heatmaps_grid (shared library).
    """
    print("\n" + "=" * 70)
    print("OCCURRENCE / CO-OCCURRENCE MATRICES")
    print("=" * 70)

    mat_dir = os.path.join(out_dir, 'matrices')
    os.makedirs(mat_dir, exist_ok=True)

    for attr, row_field, col_field, row_label, col_label, slug in MATRIX_SPECS:
        print(f"\n[MATRIX] {slug}")

        agg_matrix = _sum_matrices(aggregates, attr)

        write_aggregated_matrix_csv(
            agg_matrix, row_label, col_label,
            os.path.join(mat_dir, f'{slug}_aggregated.csv'),
            normalize='none')
        write_aggregated_matrix_csv(
            agg_matrix, row_label, col_label,
            os.path.join(mat_dir, f'{slug}_aggregated_rowNorm.csv'),
            normalize='row')
        write_aggregated_matrix_csv(
            agg_matrix, row_label, col_label,
            os.path.join(mat_dir, f'{slug}_aggregated_colNorm.csv'),
            normalize='col')

        write_per_world_matrices_csv(
            aggregates, attr, row_label, col_label,
            os.path.join(mat_dir, f'{slug}_per_world.csv'))

        if not csv_only and not no_charts:
            plot_aggregated_heatmap(
                agg_matrix, row_label, col_label,
                f'{row_label}-{col_label} Co-occurrence (aggregated across worlds)',
                os.path.join(mat_dir, f'{slug}_aggregated_heatmap.png'),
                normalize='none')
            plot_aggregated_heatmap(
                agg_matrix, row_label, col_label,
                f'{row_label}-{col_label} Co-occurrence (row-normalized)',
                os.path.join(mat_dir, f'{slug}_aggregated_rowNorm_heatmap.png'),
                normalize='row')
            plot_per_world_heatmaps_grid(
                aggregates, attr, row_label, col_label,
                f'{row_label}-{col_label} Co-occurrence - per world',
                os.path.join(mat_dir, f'{slug}_per_world_heatmaps.png'))

    print("=" * 70)


# ============================================================
# EFFECT SIZES (Cohen's d)
# ============================================================

def compute_effect_sizes(aggregates):
    variables, per_world = _collect_world_variable_values(aggregates)
    world_means = {v: {} for v in variables}
    for v in variables:
        for world, d in per_world.items():
            vals = d[v]
            world_means[v][world] = _mean(vals) if vals else 0.0
    pairwise = {v: [] for v in variables}
    names = list(per_world.keys())
    for v in variables:
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                d = cohens_d(per_world[a][v], per_world[b][v])
                pairwise[v].append((a, b, d, interpret_cohens_d(d)))
    return {'variables': variables, 'world_means': world_means, 'pairwise': pairwise}


def print_effect_sizes(effect_data):
    print("\n" + "=" * 90)
    print("EFFECT SIZES (Cohen's d) between worlds, per variable")
    print("=" * 90)
    for v in effect_data['variables']:
        print(f"\n--- {v} ---")
        for world, mean in effect_data['world_means'][v].items():
            print(f"  {world:30} mean = {mean:8.2f}")
        for a, b, d, interp in effect_data['pairwise'][v]:
            print(f"    {a:20} vs {b:20}  d = {d:+.2f}  ({interp})")
    print("=" * 90)


def write_effect_sizes_csv(effect_data, out_path):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Variable', 'World_A', 'World_B', 'Cohens_d', 'Interpretation',
                         'Mean_A', 'Mean_B', 'Diff', 'Pct_Change'])
        for v in effect_data['variables']:
            means = effect_data['world_means'][v]
            for a, b, d, interp in effect_data['pairwise'][v]:
                ma, mb = means[a], means[b]
                diff = ma - mb
                pct = (diff / mb * 100) if mb != 0 else 0.0
                writer.writerow([v, a, b, round(d, 3), interp,
                                 round(ma, 2), round(mb, 2),
                                 round(diff, 2), round(pct, 2)])
    print(f"[CSV]   {out_path}")


def write_effect_sizes_latex(effect_data, out_path, top_n=20):
    flat = []
    for v in effect_data['variables']:
        means = effect_data['world_means'][v]
        for a, b, d, interp in effect_data['pairwise'][v]:
            flat.append((v, a, b, d, interp, means[a], means[b]))
    flat.sort(key=lambda x: -abs(x[3]))
    flat = flat[:top_n]

    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append(f"\\caption{{Top {top_n} pairwise effect sizes (Cohen's $d$). Sorted by magnitude.}}")
    lines.append("\\label{tab:effect_sizes}")
    lines.append("\\begin{adjustbox}{width=\\textwidth}")
    lines.append("\\begin{tabular}{|l|l|l|c|c|c|c|c|}")
    lines.append("\\hline")
    lines.append("\\textbf{Variable} & \\textbf{World A} & \\textbf{World B} & "
                 "\\textbf{Mean A} & \\textbf{Mean B} & \\textbf{$d$} & \\textbf{Eff.} & "
                 "\\textbf{$\\Delta$ \\%} \\\\")
    lines.append("\\hline")
    for v, a, b, d, interp, ma, mb in flat:
        pct = ((ma - mb) / mb * 100) if mb != 0 else 0.0
        if abs(d) >= 0.8:
            d_str = f"\\cellcolor{{red!25}}{d:+.2f}"
        elif abs(d) >= 0.5:
            d_str = f"\\cellcolor{{orange!25}}{d:+.2f}"
        elif abs(d) >= 0.2:
            d_str = f"\\cellcolor{{yellow!25}}{d:+.2f}"
        else:
            d_str = f"{d:+.2f}"
        lines.append(f"\\texttt{{{_latex_escape(v)}}} & "
                     f"{_latex_escape(a)} & {_latex_escape(b)} & "
                     f"{ma:.2f} & {mb:.2f} & {d_str} & {interp} & {pct:+.1f} \\\\")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append("\\end{adjustbox}")
    lines.append("\\end{table}")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[TEX]   {out_path}")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Cross-world comparative analysis for SWM worlds.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python swm_analyze.py --worlds world1 world2 world3
  python swm_analyze.py --worlds world1,world2,world3
  python swm_analyze.py --worlds "world_*"
  python swm_analyze.py --worlds world_*
  python swm_analyze.py --worlds world1 world2 --csv-only
  python swm_analyze.py --worlds world1 world2 --no-latex
  python swm_analyze.py --worlds world1 world2 --no-charts
  python swm_analyze.py --worlds world1 world2 --skip-per-world-plots
  python swm_analyze.py --worlds world1 world2 --skip-matrices
  python swm_analyze.py --worlds world1 world2 --no-log
        """
    )
    parser.add_argument('--worlds', type=str, nargs='+', required=True,
                        help='World folders. Glob, comma list, or multiple tokens.')
    parser.add_argument('--out', type=str, default='analysis_out',
                        help='Output folder (default: analysis_out)')
    parser.add_argument('--csv-only', action='store_true',
                        help='Only produce CSVs, no charts or LaTeX')
    parser.add_argument('--no-latex', action='store_true',
                        help='Skip LaTeX table generation')
    parser.add_argument('--no-charts', action='store_true',
                        help='Skip chart generation')
    parser.add_argument('--skip-per-world-plots', action='store_true',
                        help='Skip the per-world plots '
                             '(individual line plots, stacked bars, heatmaps)')
    parser.add_argument('--skip-matrices', action='store_true',
                        help='Skip the cross-world occurrence / co-occurrence matrices')
    parser.add_argument('--top-k', type=int, default=12,
                        help='Number of top categories in charts/tables (default: 12)')
    parser.add_argument('--no-log', action='store_true',
                        help='Do not mirror stdout to analysis.txt')

    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    log_file = None
    if not args.no_log:
        log_file = start_logging(args.out)

    try:
        raw_worlds = parse_worlds_argument(args.worlds)
        worlds = validate_worlds(raw_worlds)
        if not worlds:
            print("[ERROR] No valid worlds found. Aborting.")
            sys.exit(1)

        print("=" * 70)
        print("SWM CROSS-WORLD ANALYSIS")
        print(f"Worlds: {worlds}")
        print(f"Output: {args.out}")
        print(f"scipy available: {'YES' if HAS_SCIPY else 'NO (using fallbacks)'}")
        print("=" * 70)

        aggregates: List[WorldAggregate] = []
        for w in worlds:
            print(f"\n[LOAD] {w}")
            agg = WorldAggregate(w)
            try:
                agg.load()
                aggregates.append(agg)
                print(f"  actions={sum(agg.action_counts.values())} "
                      f"emotions={sum(agg.emotion_counts.values())} "
                      f"goals={sum(agg.goal_counts.values())} "
                      f"ai_states={sum(agg.ai_state_counts.values())} "
                      f"status_entries={len(agg.status_timeline)}")
            except Exception as e:
                print(f"[ERROR] Failed to load {w}: {e}")

        if not aggregates:
            print("[ERROR] No worlds successfully loaded. Aborting.")
            sys.exit(1)

        # ============ CSVs (basic) ============
        write_comparative_counts_csv(aggregates, 'action_counts',
            os.path.join(args.out, 'comparative_actions.csv'))
        write_comparative_counts_csv(aggregates, 'emotion_counts',
            os.path.join(args.out, 'comparative_emotions.csv'))
        write_comparative_counts_csv(aggregates, 'goal_counts',
            os.path.join(args.out, 'comparative_goals.csv'))
        write_comparative_counts_csv(aggregates, 'ai_state_counts',
            os.path.join(args.out, 'comparative_ai_states.csv'))
        write_comparative_summary_csv(aggregates,
            os.path.join(args.out, 'comparative_summary.csv'))
        write_per_character_metrics_csv(aggregates,
            os.path.join(args.out, 'per_character_metrics.csv'))
        write_dynamics_summary_csv(aggregates,
            os.path.join(args.out, 'dynamics_summary.csv'))

        # ============ Comparative charts ============
        if not args.csv_only and not args.no_charts:
            safe_set_style()

            plot_comparative_grouped_bars(aggregates, 'action_counts',
                'Comparative Actions Distribution',
                os.path.join(args.out, 'comparative_actions_bar.png'),
                cmap_name='tab10', top_k=args.top_k)
            plot_comparative_grouped_bars(aggregates, 'emotion_counts',
                'Comparative Emotions Distribution',
                os.path.join(args.out, 'comparative_emotions_bar.png'),
                cmap_name='tab10', top_k=args.top_k)
            plot_comparative_grouped_bars(aggregates, 'goal_counts',
                'Comparative Goals Distribution',
                os.path.join(args.out, 'comparative_goals_bar.png'),
                cmap_name='tab10', top_k=args.top_k)
            plot_comparative_grouped_bars(aggregates, 'ai_state_counts',
                'Comparative AI States Distribution',
                os.path.join(args.out, 'comparative_ai_states_bar.png'),
                cmap_name='tab10', top_k=args.top_k)

            # Raw total observations per tick (can be flat, kept for reference)
            plot_comparative_lineplot_over_time(aggregates, 'action_counts',
                'Actions over Time - comparative (one line per world)',
                os.path.join(args.out, 'comparative_actions_lineplot.png'))
            plot_comparative_lineplot_over_time(aggregates, 'goal_counts',
                'Goals over Time - comparative (one line per world)',
                os.path.join(args.out, 'comparative_goals_lineplot.png'))

            # Entropy / dominant-share views (informative when totals are flat)
            plot_comparative_entropy_over_time(aggregates, 'emotion_counts',
                'Emotion entropy over Time - comparative',
                os.path.join(args.out, 'comparative_emotions_entropy.png'))
            plot_comparative_entropy_over_time(aggregates, 'ai_state_counts',
                'AI State entropy over Time - comparative',
                os.path.join(args.out, 'comparative_ai_states_entropy.png'))
            plot_comparative_entropy_over_time(aggregates, 'goal_counts',
                'Goal entropy over Time - comparative',
                os.path.join(args.out, 'comparative_goals_entropy.png'))
            plot_comparative_entropy_over_time(aggregates, 'action_counts',
                'Action entropy over Time - comparative',
                os.path.join(args.out, 'comparative_actions_entropy.png'))

            plot_comparative_dominant_share_over_time(aggregates, 'emotion_counts',
                'Dominant emotion share over Time - comparative',
                os.path.join(args.out, 'comparative_emotions_dominant_share.png'))
            plot_comparative_dominant_share_over_time(aggregates, 'ai_state_counts',
                'Dominant AI state share over Time - comparative',
                os.path.join(args.out, 'comparative_ai_states_dominant_share.png'))

            # Per-category line plots (top-K categories per subplot)
            plot_comparative_lineplot_stacked_categories(aggregates, 'action_counts',
                'Actions per category',
                os.path.join(args.out, 'comparative_actions_by_category_lineplot.png'),
                cmap_name='tab20', top_k=10)
            plot_comparative_lineplot_stacked_categories(aggregates, 'emotion_counts',
                'Emotions per category',
                os.path.join(args.out, 'comparative_emotions_by_category_lineplot.png'),
                cmap_name='tab10', top_k=10)
            plot_comparative_lineplot_stacked_categories(aggregates, 'goal_counts',
                'Goals per category',
                os.path.join(args.out, 'comparative_goals_by_category_lineplot.png'),
                cmap_name='tab10', top_k=10)
            plot_comparative_lineplot_stacked_categories(aggregates, 'ai_state_counts',
                'AI States per category',
                os.path.join(args.out, 'comparative_ai_states_by_category_lineplot.png'),
                cmap_name='tab10', top_k=10)

            for dict_name, label, fname in [
                ('per_char_health', 'Mean Health', 'boxplot_health_by_world.png'),
                ('per_char_stamina', 'Mean Stamina', 'boxplot_stamina_by_world.png'),
                ('per_char_morale', 'Mean Morale', 'boxplot_morale_by_world.png'),
                ('per_char_actions', 'Total Actions', 'boxplot_actions_by_world.png'),
                ('per_char_goals', 'Distinct Goals', 'boxplot_goals_by_world.png'),
                ('per_char_emotions', 'Distinct Emotions', 'boxplot_emotions_by_world.png'),
                ('per_char_emotion_entropy', 'Emotion Entropy', 'boxplot_emotion_entropy_by_world.png'),
                ('per_char_goal_entropy', 'Goal Entropy', 'boxplot_goal_entropy_by_world.png'),
                ('per_char_ai_state_entropy', 'AI State Entropy', 'boxplot_ai_state_entropy_by_world.png'),
            ]:
                plot_boxplot_metric(aggregates, dict_name, label,
                    f'Per-character {label} across Worlds',
                    os.path.join(args.out, fname))

            # Dynamics (status variables over time)
            status_vars = detect_status_variables(aggregates)
            if status_vars:
                print(f"\n[DYNAMICS] Detected status variables: {status_vars}")
                for var in status_vars:
                    plot_variable_over_time(aggregates, var,
                        os.path.join(args.out, f'dynamics_{var}_over_time.png'))
                    plot_boxplot_status_variable(aggregates, var,
                        os.path.join(args.out, f'dynamics_boxplot_{var}.png'))
            else:
                print("[WARN] No status variables found (need status_timeline.csv)")

        # ============ Occurrence / co-occurrence matrices ============
        if not args.skip_matrices:
            run_occurrence_matrices(aggregates, args.out,
                                    csv_only=args.csv_only,
                                    no_charts=args.no_charts)
        else:
            print("\n[INFO] Occurrence matrices skipped (--skip-matrices)")

        # ============ Correlation (general per-character matrix) ============
        variables, columns = build_per_character_matrix(aggregates)
        if variables and all(len(columns[v]) >= 2 for v in variables):
            corr_matrix = compute_correlation_matrix(variables, columns)
            print_correlation_matrix(variables, corr_matrix)
            write_correlation_csv(variables, corr_matrix,
                os.path.join(args.out, 'correlation_matrix.csv'))
            if not args.csv_only and not args.no_latex:
                write_correlation_latex(variables, corr_matrix,
                    os.path.join(args.out, 'correlation_matrix.tex'))
        else:
            print("[WARN] Not enough per-character data for correlation matrix")

        # ============ Status x Activity correlations ============
        print("\n[STATUS x ACTIVITY] Computing correlations...")
        sa_rows = build_status_activity_rows(aggregates)
        if len(sa_rows) >= 3:
            print_status_activity_correlations(sa_rows)
            write_status_activity_correlations_csv(
                sa_rows, os.path.join(args.out, 'correlation_status_activity.csv'))
            if not args.csv_only and not args.no_latex:
                write_status_activity_correlations_latex(
                    sa_rows, os.path.join(args.out, 'correlation_status_activity.tex'))
            if not args.csv_only and not args.no_charts:
                scatter_dir = os.path.join(args.out, 'scatter_status_activity')
                os.makedirs(scatter_dir, exist_ok=True)
                for s in STATUS_VARS:
                    for a in ACTIVITY_VARS:
                        fname = f"scatter_{s}_vs_{a}.png"
                        plot_status_vs_activity_scatter(
                            sa_rows, s, a, os.path.join(scatter_dir, fname))
        else:
            print(f"[WARN] Only {len(sa_rows)} status/activity rows; need >=3 for correlation.")

        # ============ Effect sizes ============
        if len(aggregates) >= 2:
            effect_data = compute_effect_sizes(aggregates)
            print_effect_sizes(effect_data)
            write_effect_sizes_csv(effect_data,
                os.path.join(args.out, 'effect_sizes.csv'))
            if not args.csv_only and not args.no_latex:
                write_effect_sizes_latex(effect_data,
                    os.path.join(args.out, 'effect_sizes.tex'),
                    top_n=args.top_k * 2)
        else:
            print("[INFO] Only one world loaded; skipping effect-size comparison")

        # ============ Statistical pipeline ============
        if len(aggregates) >= 2:
            print("\n[STATS] Running statistical pipeline...")
            stat_results = run_statistical_pipeline(aggregates)
            print_statistical_pipeline(stat_results)
            write_statistical_pipeline_csv(stat_results,
                os.path.join(args.out, 'statistical_pipeline.csv'))
            write_statistical_pipeline_posthoc_csv(stat_results,
                os.path.join(args.out, 'statistical_pipeline_posthoc.csv'))
            if not args.csv_only and not args.no_latex:
                write_statistical_pipeline_latex(stat_results,
                    os.path.join(args.out, 'statistical_pipeline.tex'))
                write_statistical_pipeline_posthoc_latex(stat_results,
                    os.path.join(args.out, 'statistical_pipeline_posthoc.tex'))

        # ============ LaTeX: base tables ============
        if not args.csv_only and not args.no_latex:
            write_latex_summary(aggregates,
                os.path.join(args.out, 'comparative_summary.tex'))
            write_latex_counts_table(aggregates, 'action_counts',
                'Comparative Actions Distribution (top categories).',
                'tab:cross_world_actions',
                os.path.join(args.out, 'comparative_actions.tex'), top_k=args.top_k)
            write_latex_counts_table(aggregates, 'emotion_counts',
                'Comparative Emotions Distribution.',
                'tab:cross_world_emotions',
                os.path.join(args.out, 'comparative_emotions.tex'), top_k=args.top_k)
            write_latex_counts_table(aggregates, 'goal_counts',
                'Comparative Goals Distribution.',
                'tab:cross_world_goals',
                os.path.join(args.out, 'comparative_goals.tex'), top_k=args.top_k)
            write_latex_counts_table(aggregates, 'ai_state_counts',
                'Comparative AI States Distribution.',
                'tab:cross_world_ai_states',
                os.path.join(args.out, 'comparative_ai_states.tex'), top_k=args.top_k)
            write_latex_dynamics_table(aggregates,
                os.path.join(args.out, 'dynamics_summary.tex'))

        # ============ Per-world plots (ANNEX - moved to the END) ============
        if not args.csv_only and not args.no_charts and not args.skip_per_world_plots:
            print("\n" + "=" * 70)
            print("[PER-WORLD PLOTS] Generating per-world charts (annex)")
            print("=" * 70)
            generate_per_world_plots(aggregates, args.out)
        elif args.skip_per_world_plots:
            print("\n[INFO] Per-world plots skipped (--skip-per-world-plots)")

        print("\n" + "=" * 70)
        print(f"[DONE] Analysis complete. Output in: {args.out}")
        if not args.no_log:
            print(f"[DONE] Full console log: {os.path.join(args.out, 'analysis.txt')}")
        print("=" * 70)

    finally:
        if log_file is not None:
            stop_logging(log_file)


if __name__ == "__main__":
    main()