#!/usr/bin/env python3
"""
SWM Plots Module - Timeline visualization and chart generation for the Simulated World.
Handles CSV export and PNG chart generation for actions, emotions and goals over time.
Can be used standalone to regenerate charts from existing CSV data.

Outputs:
    CSV:
        - actions_timeline.csv
        - emotions_timeline.csv
        - ai_states_timeline.csv
        - goals_timeline.csv
        - emotion_action_matrix.csv
        - action_emotion_matrix.csv
        - emotion_aistate_matrix.csv
        - emotions_per_tick.csv
        - actions_per_tick.csv
        - goals_per_tick.csv

    JSON:
        - timelines_snapshot.json       (full, untruncated timelines)

    PNG:
        - actions_by_character.png
        - aistates_by_character.png
        - emotions_by_character.png
        - goals_by_character.png
        - actions_over_time.png         (stacked bar)
        - emotions_over_time.png        (stacked bar)
        - goals_over_time.png           (stacked bar)
        - actions_lineplot.png          (line plot, all characters summed)
        - emotions_lineplot.png         (line plot, all characters summed)
        - goals_lineplot.png            (line plot, all characters summed)
        - emotion_action_heatmap.png
        - emotion_aistate_heatmap.png
"""

import json
import os
import csv
import sys
import atexit
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter, defaultdict

# Optional matplotlib imports (done lazily in generate_all_charts)
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


class TimelinePlotter:
    """Generates CSV files and charts for action/emotion/goal timelines"""

    # AI states that are NOT actions from the catalog (used to filter)
    KNOWN_AI_STATES = {
        'IDLE', 'GUARDING', 'FLEEING', 'SHARE', 'EXPLORE', 'COMBAT',
        'PATROL', 'ATTACK', 'RETREAT', 'DEFEND', 'GATHER', 'TRADE',
        'REST', 'HUNT', 'SOCIALIZE', 'FLEE', 'HELP', 'SHARING'
    }

    def __init__(self, world_folder: str, max_timeline_entries: Optional[int] = None):
        self.world_folder = world_folder
        self.max_timeline_entries = max_timeline_entries  # None = unlimited
        self._csv_dirty = True

        # Timeline data (populated by WorldRunner)
        self.action_timeline: List[Dict] = []
        self.emotion_timeline: List[Dict] = []
        self.ai_state_timeline: List[Dict] = []
        self.goal_timeline: List[Dict] = []

        # Co-occurrence matrices
        self.emotion_action_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.action_emotion_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.emotion_aistate_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.character_emotion_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.character_action_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.character_aistate_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.character_goal_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Color palettes
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

        # Register atexit handler to ensure CSVs are saved even on crash
        atexit.register(self._safe_export)

    # ==================== SAFETY ====================

    def _safe_export(self):
        """Called on interpreter exit - ensure CSVs are written"""
        try:
            if self._csv_dirty and (self.action_timeline or self.emotion_timeline
                                    or self.ai_state_timeline or self.goal_timeline):
                self.export_all_csv(verbose=False)
        except Exception:
            pass

    def _append_limited(self, timeline: List[Dict], entry: Dict):
        """Append an entry, honouring the optional max_timeline_entries."""
        timeline.append(entry)
        if self.max_timeline_entries is not None and len(timeline) > self.max_timeline_entries:
            del timeline[:len(timeline) - self.max_timeline_entries]

    # ==================== DATA MANAGEMENT ====================

    def add_action_entry(self, tick: int, character: str, action: str,
                         emotion: str, ai_state: str = None):
        """Record a single action event (action from catalog, not ai_state)"""
        entry = {
            'tick': tick,
            'character': character,
            'action': action,
            'emotion': emotion,
            'ai_state': ai_state or ''
        }
        self._append_limited(self.action_timeline, entry)
        self.action_emotion_matrix[action][emotion] += 1
        self.character_action_counts[character][action] += 1
        self._csv_dirty = True

    def add_emotion_entry(self, tick: int, character: str, emotion: str,
                          action: str = None, ai_state: str = None, goal: str = None):
        """Record a single emotion observation"""
        entry = {
            'tick': tick,
            'character': character,
            'emotion': emotion,
            'action': action or '',
            'ai_state': ai_state or '',
            'goal': goal or ''
        }
        self._append_limited(self.emotion_timeline, entry)
        if action:
            self.emotion_action_matrix[emotion][action] += 1
        if ai_state:
            self.emotion_aistate_matrix[emotion][ai_state] += 1
        self.character_emotion_counts[character][emotion] += 1
        self._csv_dirty = True

    def add_ai_state_entry(self, tick: int, character: str, ai_state: str,
                           emotion: str = None):
        """Record a single AI state observation"""
        entry = {
            'tick': tick,
            'character': character,
            'ai_state': ai_state,
            'emotion': emotion or 'neutral'
        }
        self._append_limited(self.ai_state_timeline, entry)
        self.character_aistate_counts[character][ai_state] += 1
        if emotion:
            self.emotion_aistate_matrix[emotion][ai_state] += 1
        self._csv_dirty = True

    def add_goal_entry(self, tick: int, character: str, goal: str,
                       emotion: str = None, ai_state: str = None):
        """Record a single goal observation"""
        entry = {
            'tick': tick,
            'character': character,
            'goal': goal,
            'emotion': emotion or 'neutral',
            'ai_state': ai_state or ''
        }
        self._append_limited(self.goal_timeline, entry)
        self.character_goal_counts[character][goal] += 1
        self._csv_dirty = True

    def _rebuild_matrices_from_timelines(self):
        """Rebuild all co-occurrence matrices from the current timelines."""
        self.emotion_action_matrix = defaultdict(lambda: defaultdict(int))
        self.action_emotion_matrix = defaultdict(lambda: defaultdict(int))
        self.emotion_aistate_matrix = defaultdict(lambda: defaultdict(int))
        self.character_emotion_counts = defaultdict(lambda: defaultdict(int))
        self.character_action_counts = defaultdict(lambda: defaultdict(int))
        self.character_aistate_counts = defaultdict(lambda: defaultdict(int))
        self.character_goal_counts = defaultdict(lambda: defaultdict(int))

        for entry in self.action_timeline:
            action = entry.get('action', 'Unknown')
            emotion = entry.get('emotion', 'neutral')
            char = entry.get('character', 'Unknown')
            self.action_emotion_matrix[action][emotion] += 1
            self.character_action_counts[char][action] += 1

        for entry in self.emotion_timeline:
            emotion = entry.get('emotion', 'neutral')
            action = entry.get('action', '')
            ai_state = entry.get('ai_state', '')
            char = entry.get('character', 'Unknown')
            if action:
                self.emotion_action_matrix[emotion][action] += 1
            if ai_state:
                self.emotion_aistate_matrix[emotion][ai_state] += 1
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
            self.character_goal_counts[char][goal] += 1

    def load_from_runtime(self, runtime_data: Dict[str, Any]):
        """
        Load timeline data from a runtime state dict.

        IMPORTANT: this does NOT overwrite timelines already in memory if the
        incoming data is shorter (the runtime JSON is windowed/truncated).
        Only replaces when the incoming list is strictly larger.
        """
        rt_actions = runtime_data.get('action_timeline', [])
        rt_emotions = runtime_data.get('emotion_timeline', [])
        rt_aistates = runtime_data.get('ai_state_timeline', [])
        rt_goals = runtime_data.get('goal_timeline', [])

        if rt_actions and (not self.action_timeline or len(rt_actions) > len(self.action_timeline)):
            self.action_timeline = list(rt_actions)
        if rt_emotions and (not self.emotion_timeline or len(rt_emotions) > len(self.emotion_timeline)):
            self.emotion_timeline = list(rt_emotions)
        if rt_aistates and (not self.ai_state_timeline or len(rt_aistates) > len(self.ai_state_timeline)):
            self.ai_state_timeline = list(rt_aistates)
        if rt_goals and (not self.goal_timeline or len(rt_goals) > len(self.goal_timeline)):
            self.goal_timeline = list(rt_goals)

        self._rebuild_matrices_from_timelines()

    def save_timelines_snapshot(self) -> bool:
        """Save full (untruncated) timelines to a dedicated JSON snapshot."""
        filepath = os.path.join(self.world_folder, "timelines_snapshot.json")
        try:
            snapshot = {
                "action_timeline": self.action_timeline,
                "emotion_timeline": self.emotion_timeline,
                "ai_state_timeline": self.ai_state_timeline,
                "goal_timeline": self.goal_timeline,
                "saved_at": datetime.now().isoformat(),
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save timelines snapshot: {e}")
            return False

    def load_timelines_snapshot(self) -> bool:
        """Load full timelines from the dedicated JSON snapshot, if present."""
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
            self._rebuild_matrices_from_timelines()
            print(f"[OK] Loaded timelines snapshot: "
                  f"{len(self.action_timeline)} actions, "
                  f"{len(self.emotion_timeline)} emotions, "
                  f"{len(self.ai_state_timeline)} AI states, "
                  f"{len(self.goal_timeline)} goals")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load timelines snapshot: {e}")
            return False

    def load_from_csv(self):
        """Load timeline data from existing CSV files in world folder"""
        actions_csv = os.path.join(self.world_folder, "actions_timeline.csv")
        emotions_csv = os.path.join(self.world_folder, "emotions_timeline.csv")
        aistate_csv = os.path.join(self.world_folder, "ai_states_timeline.csv")
        goals_csv = os.path.join(self.world_folder, "goals_timeline.csv")

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
                        entry = {
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'action': row.get('Action', 'Unknown'),
                            'emotion': row.get('Emotion_At_Time', 'neutral'),
                            'ai_state': row.get('AI_State', '')
                        }
                        self.action_timeline.append(entry)
                print(f"[OK] Loaded {len(self.action_timeline)} action entries from CSV")
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
                        entry = {
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'emotion': row.get('Emotion', 'neutral'),
                            'action': row.get('Action_At_Time', ''),
                            'ai_state': row.get('AI_State_At_Time', ''),
                            'goal': row.get('Goal_At_Time', '')
                        }
                        self.emotion_timeline.append(entry)
                print(f"[OK] Loaded {len(self.emotion_timeline)} emotion entries from CSV")
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
                        entry = {
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'ai_state': row.get('AI_State', 'Unknown'),
                            'emotion': row.get('Emotion_At_Time', 'neutral')
                        }
                        self.ai_state_timeline.append(entry)
                print(f"[OK] Loaded {len(self.ai_state_timeline)} AI state entries from CSV")
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
                        entry = {
                            'tick': tick,
                            'character': row.get('Character', 'Unknown'),
                            'goal': row.get('Goal', 'Unknown'),
                            'emotion': row.get('Emotion_At_Time', 'neutral'),
                            'ai_state': row.get('AI_State_At_Time', '')
                        }
                        self.goal_timeline.append(entry)
                print(f"[OK] Loaded {len(self.goal_timeline)} goal entries from CSV")
            except Exception as e:
                print(f"[ERROR] Failed to load goals CSV: {e}")

        self._rebuild_matrices_from_timelines()

    # ==================== CSV EXPORTS ====================

    def export_all_csv(self, verbose: bool = True):
        """Export all timeline data as CSV files"""
        self._export_actions_timeline_csv()
        self._export_emotions_timeline_csv()
        self._export_ai_states_timeline_csv()
        self._export_goals_timeline_csv()
        self._export_emotion_action_matrix_csv()
        self._export_action_emotion_matrix_csv()
        self._export_emotion_aistate_matrix_csv()
        self._export_emotions_per_tick_csv()
        self._export_actions_per_tick_csv()
        self._export_goals_per_tick_csv()
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
                        entry.get('tick', ''),
                        entry.get('character', ''),
                        entry.get('action', ''),
                        entry.get('emotion', ''),
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
                        entry.get('tick', ''),
                        entry.get('character', ''),
                        entry.get('emotion', ''),
                        entry.get('action', ''),
                        entry.get('ai_state', ''),
                        entry.get('goal', '')
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
                        entry.get('tick', ''),
                        entry.get('character', ''),
                        entry.get('ai_state', ''),
                        entry.get('emotion', '')
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
                        entry.get('tick', ''),
                        entry.get('character', ''),
                        entry.get('goal', ''),
                        entry.get('emotion', ''),
                        entry.get('ai_state', '')
                    ])
        except Exception as e:
            print(f"[ERROR] Failed to export goals timeline CSV: {e}")

    def _export_emotion_action_matrix_csv(self):
        filepath = os.path.join(self.world_folder, "emotion_action_matrix.csv")
        try:
            emotions = sorted(self.emotion_action_matrix.keys())
            actions = set()
            for action_counts in self.emotion_action_matrix.values():
                actions.update(action_counts.keys())
            actions = sorted(actions)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Emotion'] + actions)
                for emotion in emotions:
                    row = [emotion]
                    for action in actions:
                        row.append(self.emotion_action_matrix[emotion].get(action, 0))
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export emotion-action matrix CSV: {e}")

    def _export_action_emotion_matrix_csv(self):
        filepath = os.path.join(self.world_folder, "action_emotion_matrix.csv")
        try:
            actions = sorted(self.action_emotion_matrix.keys())
            emotions = set()
            for emotion_counts in self.action_emotion_matrix.values():
                emotions.update(emotion_counts.keys())
            emotions = sorted(emotions)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Action'] + emotions)
                for action in actions:
                    row = [action]
                    for emotion in emotions:
                        row.append(self.action_emotion_matrix[action].get(emotion, 0))
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export action-emotion matrix CSV: {e}")

    def _export_emotion_aistate_matrix_csv(self):
        filepath = os.path.join(self.world_folder, "emotion_aistate_matrix.csv")
        try:
            emotions = sorted(self.emotion_aistate_matrix.keys())
            states = set()
            for state_counts in self.emotion_aistate_matrix.values():
                states.update(state_counts.keys())
            states = sorted(states)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Emotion'] + states)
                for emotion in emotions:
                    row = [emotion]
                    for state in states:
                        row.append(self.emotion_aistate_matrix[emotion].get(state, 0))
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export emotion-AI state matrix CSV: {e}")

    def _export_emotions_per_tick_csv(self):
        filepath = os.path.join(self.world_folder, "emotions_per_tick.csv")
        try:
            tick_emotions = defaultdict(lambda: defaultdict(int))
            for entry in self.emotion_timeline:
                tick = entry.get('tick', 0)
                emotion = entry.get('emotion', 'neutral')
                tick_emotions[tick][emotion] += 1
            if not tick_emotions:
                return
            ticks = sorted(tick_emotions.keys())
            all_emotions = set()
            for counts in tick_emotions.values():
                all_emotions.update(counts.keys())
            all_emotions = sorted(all_emotions)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick'] + all_emotions + ['Total'])
                for tick in ticks:
                    row = [tick]
                    total = 0
                    for emotion in all_emotions:
                        count = tick_emotions[tick].get(emotion, 0)
                        row.append(count)
                        total += count
                    row.append(total)
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export emotions-per-tick CSV: {e}")

    def _export_actions_per_tick_csv(self):
        filepath = os.path.join(self.world_folder, "actions_per_tick.csv")
        try:
            tick_actions = defaultdict(lambda: defaultdict(int))
            for entry in self.action_timeline:
                tick = entry.get('tick', 0)
                action = entry.get('action', 'Unknown')
                tick_actions[tick][action] += 1
            if not tick_actions:
                return
            ticks = sorted(tick_actions.keys())
            all_actions = set()
            for counts in tick_actions.values():
                all_actions.update(counts.keys())
            all_actions = sorted(all_actions)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick'] + all_actions + ['Total'])
                for tick in ticks:
                    row = [tick]
                    total = 0
                    for action in all_actions:
                        count = tick_actions[tick].get(action, 0)
                        row.append(count)
                        total += count
                    row.append(total)
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export actions-per-tick CSV: {e}")

    def _export_goals_per_tick_csv(self):
        filepath = os.path.join(self.world_folder, "goals_per_tick.csv")
        try:
            tick_goals = defaultdict(lambda: defaultdict(int))
            for entry in self.goal_timeline:
                tick = entry.get('tick', 0)
                goal = entry.get('goal', 'Unknown')
                tick_goals[tick][goal] += 1
            if not tick_goals:
                return
            ticks = sorted(tick_goals.keys())
            all_goals = set()
            for counts in tick_goals.values():
                all_goals.update(counts.keys())
            all_goals = sorted(all_goals)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Tick'] + all_goals + ['Total'])
                for tick in ticks:
                    row = [tick]
                    total = 0
                    for goal in all_goals:
                        count = tick_goals[tick].get(goal, 0)
                        row.append(count)
                        total += count
                    row.append(total)
                    writer.writerow(row)
        except Exception as e:
            print(f"[ERROR] Failed to export goals-per-tick CSV: {e}")

    # ==================== CHART GENERATION ====================

    def generate_all_charts(self):
        if not HAS_MATPLOTLIB:
            print("[WARNING] matplotlib not installed. Skipping chart generation.")
            print("[INFO] Install with: pip install matplotlib")
            return

        print("\n" + "="*70)
        print("GENERATING TIMELINE CHARTS")
        print("="*70)

        # Actions (from catalog)
        self._chart_actions_by_character(plt, np)
        self._chart_actions_over_time(plt, np)
        self._chart_actions_lineplot(plt, np)
        self._chart_emotion_action_heatmap(plt, np)

        # AI States
        self._chart_aistates_by_character(plt, np)
        self._chart_emotion_aistate_heatmap(plt, np)

        # Emotions
        self._chart_emotions_by_character(plt, np)
        self._chart_emotions_over_time(plt, np)
        self._chart_emotions_lineplot(plt, np)

        # Goals
        self._chart_goals_by_character(plt, np)
        self._chart_goals_over_time(plt, np)
        self._chart_goals_lineplot(plt, np)

        print("="*70)

    def _safe_set_style(self, plt):
        for style in ('seaborn-v0_8-darkgrid', 'seaborn-darkgrid', 'ggplot'):
            try:
                plt.style.use(style)
                return
            except Exception:
                continue

    def _get_categories_from_counts(self, counts_dict: Dict[str, Dict[str, int]]) -> List[str]:
        """
        Return the sorted list of all categories (keys of the inner dicts),
        filtered to those with a total count > 0.
        """
        totals = defaultdict(int)
        for inner in counts_dict.values():
            for cat, cnt in inner.items():
                totals[cat] += cnt
        return sorted([c for c, t in totals.items() if t > 0])

    def _stacked_barh_with_full_legend(self, counts_dict, categories, colors,
                                       title, xlabel, filepath,
                                       fig_width=12):
        """
        Draw a horizontal stacked bar chart per character, with a COMPLETE
        legend built from `categories` (not from the labels of one row).
        """
        if not counts_dict or not categories:
            return

        self._safe_set_style(plt)

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

        # Build a COMPLETE legend using proxy handles (independent of plot order)
        legend_handles = [
            mpatches.Patch(color=colors[cat], label=cat)
            for cat in categories
        ]
        ax.legend(
            handles=legend_handles,
            labels=categories,
            loc='center left',
            bbox_to_anchor=(1, 0.5),
            fontsize=8,
            frameon=True,
        )

        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

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
            categories=categories,
            colors=colors,
            title='Actions Distribution by Character (colored by Action Type)',
            xlabel='Number of Actions',
            filepath=filepath,
        )

    def _chart_actions_over_time(self, plt, np):
        if not self.action_timeline:
            return
        tick_actions = defaultdict(lambda: defaultdict(int))
        for entry in self.action_timeline:
            tick = entry.get('tick', 0)
            action = entry.get('action', 'Unknown')
            tick_actions[tick][action] += 1
        if not tick_actions:
            return

        self._safe_set_style(plt)
        ticks = sorted(tick_actions.keys())
        all_actions = set()
        for action_counts in tick_actions.values():
            all_actions.update(action_counts.keys())
        all_actions = sorted(all_actions)

        fig, ax = plt.subplots(figsize=(14, 6))
        cmap = plt.cm.get_cmap('tab20', max(20, len(all_actions)))
        action_colors = {action: cmap(i % 20) for i, action in enumerate(all_actions)}

        bottoms = np.zeros(len(ticks))
        for action in all_actions:
            values = np.array([tick_actions[t].get(action, 0) for t in ticks])
            if values.sum() > 0:
                ax.bar(ticks, values, bottom=bottoms, width=1.0,
                       color=action_colors[action])
                bottoms += values

        ax.set_xlabel('Tick')
        ax.set_ylabel('Actions')
        ax.set_title('Actions Over Time (stacked by Action Type)')

        legend_handles = [mpatches.Patch(color=action_colors[a], label=a) for a in all_actions]
        ax.legend(handles=legend_handles, labels=all_actions,
                  loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "actions_over_time.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _chart_actions_lineplot(self, plt, np):
        if not self.action_timeline:
            return
        tick_actions = defaultdict(lambda: defaultdict(int))
        for entry in self.action_timeline:
            tick = entry.get('tick', 0)
            action = entry.get('action', 'Unknown')
            tick_actions[tick][action] += 1
        if not tick_actions:
            return

        self._safe_set_style(plt)
        ticks = sorted(tick_actions.keys())
        all_actions = set()
        for counts in tick_actions.values():
            all_actions.update(counts.keys())
        all_actions = sorted(all_actions)

        cmap = plt.cm.get_cmap('tab20', max(20, len(all_actions)))
        action_colors = {action: cmap(i % 20) for i, action in enumerate(all_actions)}

        fig, ax = plt.subplots(figsize=(14, 6))
        for action in all_actions:
            y = [tick_actions[t].get(action, 0) for t in ticks]
            ax.plot(ticks, y, marker='o', markersize=3, linewidth=1.8,
                    color=action_colors[action], label=action, alpha=0.85)

        total = [sum(tick_actions[t].values()) for t in ticks]
        ax.plot(ticks, total, linestyle='--', linewidth=1.2,
                color='black', alpha=0.5, label='TOTAL (all actions)')

        ax.set_xlabel('Tick')
        ax.set_ylabel('Frequency (all characters)')
        ax.set_title('Actions Over Time - Line Plot (sum of all characters)')
        ax.grid(True, alpha=0.3)

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "actions_lineplot.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _chart_emotion_action_heatmap(self, plt, np):
        matrix, emotions, actions = self._build_matrix(self.emotion_action_matrix)
        if matrix is None:
            return

        n_rows, n_cols = matrix.shape
        fig, ax = plt.subplots(figsize=(max(10, n_cols * 0.7), max(5, n_rows * 0.6)))

        im = ax.imshow(
            matrix, cmap='YlOrRd', aspect='auto', origin='upper',
            extent=(-0.5, n_cols - 0.5, n_rows - 0.5, -0.5)
        )
        plt.colorbar(im, ax=ax, label='Frequency')

        ax.set_xticks(np.arange(n_cols))
        ax.set_yticks(np.arange(n_rows))
        ax.set_xticklabels(actions, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(emotions, fontsize=9)

        ax.set_xlim(-0.5, n_cols - 0.5)
        ax.set_ylim(n_rows - 0.5, -0.5)

        ax.set_xlabel('Action')
        ax.set_ylabel('Emotion')
        ax.set_title('Emotion-Action Co-occurrence Matrix')

        max_val = matrix.max() if matrix.size else 1
        for i in range(n_rows):
            for j in range(n_cols):
                if matrix[i, j] > 0:
                    ax.text(j, i, int(matrix[i, j]),
                            ha="center", va="center",
                            color="black" if matrix[i, j] < max_val / 2 else "white",
                            fontsize=7)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "emotion_action_heatmap.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

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
            categories=categories,
            colors=colors,
            title='AI States Distribution by Character (colored by State)',
            xlabel='Frequency',
            filepath=filepath,
        )

    def _chart_emotion_aistate_heatmap(self, plt, np):
        matrix, emotions, states = self._build_matrix(self.emotion_aistate_matrix)
        if matrix is None:
            return

        n_rows, n_cols = matrix.shape
        fig, ax = plt.subplots(figsize=(max(10, n_cols * 0.7), max(5, n_rows * 0.6)))

        im = ax.imshow(
            matrix, cmap='YlOrRd', aspect='auto', origin='upper',
            extent=(-0.5, n_cols - 0.5, n_rows - 0.5, -0.5)
        )
        plt.colorbar(im, ax=ax, label='Frequency')

        ax.set_xticks(np.arange(n_cols))
        ax.set_yticks(np.arange(n_rows))
        ax.set_xticklabels(states, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(emotions, fontsize=9)

        ax.set_xlim(-0.5, n_cols - 0.5)
        ax.set_ylim(n_rows - 0.5, -0.5)

        ax.set_xlabel('AI State')
        ax.set_ylabel('Emotion')
        ax.set_title('Emotion-AI State Co-occurrence Matrix')

        max_val = matrix.max() if matrix.size else 1
        for i in range(n_rows):
            for j in range(n_cols):
                if matrix[i, j] > 0:
                    ax.text(j, i, int(matrix[i, j]),
                            ha="center", va="center",
                            color="black" if matrix[i, j] < max_val / 2 else "white",
                            fontsize=7)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "emotion_aistate_heatmap.png")
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

    # ---- EMOTIONS ----

    def _chart_emotions_by_character(self, plt, np):
        if not self.character_emotion_counts:
            return
        categories = self._get_categories_from_counts(self.character_emotion_counts)
        if not categories:
            return
        colors = {
            cat: self.emotion_color_palette[i % len(self.emotion_color_palette)]
            for i, cat in enumerate(categories)
        }
        filepath = os.path.join(self.world_folder, "emotions_by_character.png")
        self._stacked_barh_with_full_legend(
            counts_dict=self.character_emotion_counts,
            categories=categories,
            colors=colors,
            title='Emotions Distribution by Character (colored by Emotion)',
            xlabel='Frequency',
            filepath=filepath,
        )

    def _chart_emotions_over_time(self, plt, np):
        if not self.emotion_timeline:
            return
        tick_emotions = defaultdict(lambda: defaultdict(int))
        for entry in self.emotion_timeline:
            tick = entry.get('tick', 0)
            emotion = entry.get('emotion', 'neutral')
            tick_emotions[tick][emotion] += 1
        if not tick_emotions:
            return

        self._safe_set_style(plt)
        ticks = sorted(tick_emotions.keys())
        all_emotions = set()
        for emotion_counts in tick_emotions.values():
            all_emotions.update(emotion_counts.keys())
        all_emotions = sorted(all_emotions)

        fig, ax = plt.subplots(figsize=(14, 6))
        emotion_colors = {
            emotion: self.emotion_color_palette[i % len(self.emotion_color_palette)]
            for i, emotion in enumerate(all_emotions)
        }

        bottoms = np.zeros(len(ticks))
        for emotion in all_emotions:
            values = np.array([tick_emotions[t].get(emotion, 0) for t in ticks])
            if values.sum() > 0:
                ax.bar(ticks, values, bottom=bottoms, width=1.0,
                       color=emotion_colors[emotion])
                bottoms += values

        ax.set_xlabel('Tick')
        ax.set_ylabel('Emotion Observations')
        ax.set_title('Emotions Over Time (stacked by Emotion)')

        legend_handles = [mpatches.Patch(color=emotion_colors[e], label=e) for e in all_emotions]
        ax.legend(handles=legend_handles, labels=all_emotions,
                  loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "emotions_over_time.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _chart_emotions_lineplot(self, plt, np):
        if not self.emotion_timeline:
            return
        tick_emotions = defaultdict(lambda: defaultdict(int))
        for entry in self.emotion_timeline:
            tick = entry.get('tick', 0)
            emotion = entry.get('emotion', 'neutral')
            tick_emotions[tick][emotion] += 1
        if not tick_emotions:
            return

        self._safe_set_style(plt)
        ticks = sorted(tick_emotions.keys())
        all_emotions = set()
        for counts in tick_emotions.values():
            all_emotions.update(counts.keys())
        all_emotions = sorted(all_emotions)

        emotion_colors = {
            emotion: self.emotion_color_palette[i % len(self.emotion_color_palette)]
            for i, emotion in enumerate(all_emotions)
        }

        fig, ax = plt.subplots(figsize=(14, 6))
        for emotion in all_emotions:
            y = [tick_emotions[t].get(emotion, 0) for t in ticks]
            ax.plot(ticks, y, marker='o', markersize=3, linewidth=1.8,
                    color=emotion_colors[emotion], label=emotion, alpha=0.85)

        total = [sum(tick_emotions[t].values()) for t in ticks]
        ax.plot(ticks, total, linestyle='--', linewidth=1.2,
                color='black', alpha=0.5, label='TOTAL (all emotions)')

        ax.set_xlabel('Tick')
        ax.set_ylabel('Frequency (all characters)')
        ax.set_title('Emotions Over Time - Line Plot (sum of all characters)')
        ax.grid(True, alpha=0.3)

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "emotions_lineplot.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    # ---- GOALS ----

    def _chart_goals_by_character(self, plt, np):
        if not self.character_goal_counts:
            return
        categories = self._get_categories_from_counts(self.character_goal_counts)
        if not categories:
            return
        colors = {
            cat: self.goal_color_palette[i % len(self.goal_color_palette)]
            for i, cat in enumerate(categories)
        }
        filepath = os.path.join(self.world_folder, "goals_by_character.png")
        self._stacked_barh_with_full_legend(
            counts_dict=self.character_goal_counts,
            categories=categories,
            colors=colors,
            title='Goals Distribution by Character (colored by Goal)',
            xlabel='Frequency',
            filepath=filepath,
        )

    def _chart_goals_over_time(self, plt, np):
        if not self.goal_timeline:
            return
        tick_goals = defaultdict(lambda: defaultdict(int))
        for entry in self.goal_timeline:
            tick = entry.get('tick', 0)
            goal = entry.get('goal', 'Unknown')
            tick_goals[tick][goal] += 1
        if not tick_goals:
            return

        self._safe_set_style(plt)
        ticks = sorted(tick_goals.keys())
        all_goals = set()
        for goal_counts in tick_goals.values():
            all_goals.update(goal_counts.keys())
        all_goals = sorted(all_goals)

        fig, ax = plt.subplots(figsize=(14, 6))
        goal_colors = {
            goal: self.goal_color_palette[i % len(self.goal_color_palette)]
            for i, goal in enumerate(all_goals)
        }

        bottoms = np.zeros(len(ticks))
        for goal in all_goals:
            values = np.array([tick_goals[t].get(goal, 0) for t in ticks])
            if values.sum() > 0:
                ax.bar(ticks, values, bottom=bottoms, width=1.0,
                       color=goal_colors[goal])
                bottoms += values

        ax.set_xlabel('Tick')
        ax.set_ylabel('Goal Observations')
        ax.set_title('Goals Over Time (stacked by Goal)')

        legend_handles = [mpatches.Patch(color=goal_colors[g], label=g) for g in all_goals]
        ax.legend(handles=legend_handles, labels=all_goals,
                  loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "goals_over_time.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")

    def _chart_goals_lineplot(self, plt, np):
        if not self.goal_timeline:
            return
        tick_goals = defaultdict(lambda: defaultdict(int))
        for entry in self.goal_timeline:
            tick = entry.get('tick', 0)
            goal = entry.get('goal', 'Unknown')
            tick_goals[tick][goal] += 1
        if not tick_goals:
            return

        self._safe_set_style(plt)
        ticks = sorted(tick_goals.keys())
        all_goals = set()
        for counts in tick_goals.values():
            all_goals.update(counts.keys())
        all_goals = sorted(all_goals)

        goal_colors = {
            goal: self.goal_color_palette[i % len(self.goal_color_palette)]
            for i, goal in enumerate(all_goals)
        }

        fig, ax = plt.subplots(figsize=(14, 6))
        for goal in all_goals:
            y = [tick_goals[t].get(goal, 0) for t in ticks]
            ax.plot(ticks, y, marker='o', markersize=3, linewidth=1.8,
                    color=goal_colors[goal], label=goal, alpha=0.85)

        total = [sum(tick_goals[t].values()) for t in ticks]
        ax.plot(ticks, total, linestyle='--', linewidth=1.2,
                color='black', alpha=0.5, label='TOTAL (all goals)')

        ax.set_xlabel('Tick')
        ax.set_ylabel('Frequency (all characters)')
        ax.set_title('Goals Over Time - Line Plot (sum of all characters)')
        ax.grid(True, alpha=0.3)

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)

        plt.tight_layout()
        filepath = os.path.join(self.world_folder, "goals_lineplot.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[CHART] {filepath}")


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate timeline charts from SWM world data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Regenerate everything (CSVs + charts) from a world folder
  python swm_plots.py --world world_2024_01_15
  python swm_plots.py --folder world_2024_01_15

  # Only CSVs (from runtime state or existing CSVs)
  python swm_plots.py --folder world_2024_01_15 --csv-only

  # Only charts (assumes CSVs already exist in the folder)
  python swm_plots.py --folder world_2024_01_15 --charts-only

  # Force loading ONLY from CSV, ignore runtime JSON
  python swm_plots.py --folder world_2024_01_15 --from-csv
        """
    )
    # --world and --folder are aliases (same dest)
    parser.add_argument('--world', '--folder', dest='world', type=str, required=True,
                        help='Path to world folder (contains CSVs / runtime JSON). '
                             '--folder is an alias of --world.')
    parser.add_argument('--csv-only', action='store_true',
                        help='Only export CSV files, no charts')
    parser.add_argument('--charts-only', action='store_true',
                        help='Only generate charts (assumes CSVs exist)')
    parser.add_argument('--from-csv', action='store_true',
                        help='Force loading timeline data from CSV files, '
                             'ignoring world_state_runtime.json and timelines_snapshot.json')

    args = parser.parse_args()

    if not os.path.isdir(args.world):
        print(f"[ERROR] World folder not found: {args.world}")
        sys.exit(1)

    # Verify that at least one input source exists
    runtime_path = os.path.join(args.world, "world_state_runtime.json")
    snapshot_path = os.path.join(args.world, "timelines_snapshot.json")
    expected_csvs = [
        "actions_timeline.csv",
        "emotions_timeline.csv",
        "ai_states_timeline.csv",
        "goals_timeline.csv",
    ]
    existing_csvs = [f for f in expected_csvs if os.path.exists(os.path.join(args.world, f))]
    has_runtime = os.path.exists(runtime_path)
    has_snapshot = os.path.exists(snapshot_path)

    if not (has_runtime or has_snapshot or existing_csvs):
        print(f"[ERROR] No usable data found in {args.world}.")
        print(f"        Looked for: world_state_runtime.json, timelines_snapshot.json "
              f"and/or {expected_csvs}")
        sys.exit(1)

    plotter = TimelinePlotter(args.world)

    if not args.charts_only:
        loaded = False

        if args.from_csv:
            # Explicitly force CSV loading
            if existing_csvs:
                print(f"[INFO] --from-csv: loading from CSVs {existing_csvs}")
                plotter.load_from_csv()
                loaded = True
            else:
                print(f"[WARN] --from-csv specified but no CSVs found in {args.world}")
        else:
            # Prefer full snapshot, then runtime (windowed), then CSV
            if has_snapshot:
                if plotter.load_timelines_snapshot():
                    loaded = True
                else:
                    print(f"[WARN] timelines_snapshot.json present but could not be loaded")

            if not loaded and has_runtime:
                try:
                    with open(runtime_path, 'r', encoding='utf-8') as f:
                        runtime_data = json.load(f)
                    plotter.load_from_runtime(runtime_data)
                    if (plotter.action_timeline or plotter.emotion_timeline
                            or plotter.ai_state_timeline or plotter.goal_timeline):
                        print(f"[OK] Loaded timeline from runtime state: {runtime_path}")
                        loaded = True
                    else:
                        print(f"[WARN] Runtime state was empty, falling back to CSV")
                except Exception as e:
                    print(f"[WARN] Could not load runtime state ({e}), falling back to CSV")

            if not loaded and existing_csvs:
                print(f"[INFO] Loading timeline data from CSVs: {existing_csvs}")
                plotter.load_from_csv()
                loaded = True

        plotter.export_all_csv()

    if not args.csv_only:
        if (not plotter.action_timeline and not plotter.emotion_timeline
                and not plotter.ai_state_timeline and not plotter.goal_timeline):
            print(f"[INFO] No timeline data in memory, attempting CSV load before charts...")
            plotter.load_from_csv()
        plotter.generate_all_charts()

    print("\n[DONE] Timeline exports and charts complete")


if __name__ == "__main__":
    main()