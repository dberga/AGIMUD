#!/usr/bin/env python3
"""
SWM Run Module - Main runner with full visualization loop, emotion tracking,
social reasoning, and rule-bound character actions.
All display, behavior, emotions, and reasoning loaded dynamically from JSON files.

Plotting and timeline visualization delegated to swm_plots.TimelinePlotter.

Modes:
    --auto       : continuous simulation (Ctrl+C to stop)
    --interact   : step-by-step, with 'continue' option
    --dynamic    : continuous + live command input; on --max-epoch, switches to interactive
"""

import json
import os
import time
import random
import sys
import signal
import threading
import select
from datetime import datetime
from typing import Dict, List, Any, Optional
import csv

from swm import SimulatedWorldModule
from swm_corpus_loader import DynamicEntity
from swm_plots import TimelinePlotter


class WorldRunner:
    """Main runner for the simulated world with emotion, reasoning, and rule-bound actions"""

    def __init__(self, fps: float = 1.0, load_existing: bool = True, world_folder: str = None,
                 interact: bool = False, dynamic: bool = False, max_epoch: int = 10000):
        self.fps = fps
        self.tick_interval = 1.0 / fps
        self.running = False
        self.tick_count = 0
        self._current_tick = 0
        self.world = None
        self.event_history = []
        self.max_history = 100
        self.world_folder = world_folder
        self.interact = interact
        self.dynamic = dynamic
        self.max_epoch = max_epoch
        self.max_epoch_reached = False
        self.shutdown_requested = False
        self.continuous_mode = False
        self.continuous_thread = None
        self.auto_render = True
        self.input_buffer = ""
        self.mode = "auto"
        self.last_render_time = 0
        self.min_render_interval = 0.5

        # Track last action/goal per character (for emotion timeline context)
        self.last_action_per_char: Dict[str, str] = {}
        self.last_goal_per_char: Dict[str, str] = {}

        # Statistics tracking
        self.statistics = {
            'characters': {},
            'global': {
                'total_ticks': 0,
                'total_actions': 0,
                'total_emotion_transitions': 0,
                'total_movements': 0,
                'total_social_actions': 0,
                'emotion_transition_matrix': {}
            }
        }
        self.emotion_history = {}

        # Load all configurations from JSON
        self.vocab = self._load_json("world_vocabulary.json")
        self.dynamics = self._load_json("world_dynamics.json")
        self.generation_config = self._load_json("generation_config.json")

        # Find world folder if not specified
        if self.world_folder is None:
            self.world_folder = self._find_latest_world()

        # Check if world folder exists and has required files
        if not self._validate_world_folder():
            print("[ERROR] No valid world folder found. Please run swm_generate.py first.")
            sys.exit(1)

        # Load action catalog
        self.action_catalog = self._load_action_catalog()

        # Load variable catalog
        self.variable_catalog = self._load_variable_catalog()

        # Initialize Simulated World Module with full reasoning corpora
        self._initialize_world(load_existing)

        # Initialize plotter (delegated module)
        self.plotter = TimelinePlotter(self.world_folder)

        # Create log file in world folder
        run_timestamp = datetime.now().strftime("%d_%m_%Y-%H_%M_%S")
        self.run_id = f"run_{run_timestamp}"
        self.log_file = os.path.join(self.world_folder, f"{self.run_id}.log")
        self.log_lines = []

        # Set up signal handlers
        self._setup_signal_handlers()

        print(f"[INIT] World Runner initialized at {fps} FPS with Emotion & Social Reasoning Engine")
        print(f"[WORLD] Using world folder: {self.world_folder}")
        print(f"[LOG] Writing to {self.log_file}")
        if self.max_epoch and self.max_epoch > 0:
            print(f"[LIMIT] Max epochs: {self.max_epoch}")
        else:
            print(f"[LIMIT] Max epochs: unlimited")
        sys.stdout.flush()

    # ==================== SETUP ====================

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, 'SIGTSTP'):
            signal.signal(signal.SIGTSTP, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print(f"\n[STOP] Signal received. Saving state and shutting down...")
        self.shutdown_requested = True
        self.running = False
        self.continuous_mode = False

        if self.world:
            self._save_runtime_state()
            self._export_statistics()
            self.plotter.export_all_csv()
            self.plotter.generate_all_charts()
            self._flush_log()

        if signum == signal.SIGTSTP:
            sys.exit(0)

    def _validate_world_folder(self) -> bool:
        if self.world_folder is None or self.world_folder == ".":
            return False
        if not os.path.exists(self.world_folder):
            print(f"[ERROR] World folder does not exist: {self.world_folder}")
            return False
        if not os.path.isdir(self.world_folder):
            print(f"[ERROR] Path is not a directory: {self.world_folder}")
            return False

        required_files = ["characters.json", "objects.json", "scenes.json",
                          "rules.json", "world_states.json"]
        missing_files = []
        for filename in required_files:
            filepath = os.path.join(self.world_folder, filename)
            if not os.path.exists(filepath):
                missing_files.append(filename)

        if missing_files:
            print(f"[ERROR] Missing required files in {self.world_folder}:")
            for f in missing_files:
                print(f"  - {f}")
            print("[INFO] Please run swm_generate.py to create a new world.")
            return False
        return True

    def _find_latest_world(self) -> str:
        world_folders = [d for d in os.listdir('.') if os.path.isdir(d) and d.startswith('world_')]
        if world_folders:
            world_folders.sort(reverse=True)
            print(f"[INFO] Found world folder: {world_folders[0]}")
            return world_folders[0]
        else:
            print("[WARNING] No world folder found. Please run swm_generate.py first.")
            return None

    def _load_json(self, filename: str) -> Dict[str, Any]:
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load {filename}: {e}")
                return {}

        world_path = os.path.join(self.world_folder, filename) if self.world_folder else filename
        if os.path.exists(world_path):
            try:
                with open(world_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load {world_path}: {e}")
                return {}
        return {}

    def _get_vocab(self, key: str, default: list = None) -> list:
        return self.vocab.get(key, default or [])

    def _get_field_value(self, obj: Any, path: str, default: Any = None) -> Any:
        if not obj:
            return default
        parts = path.split('.')
        current = obj
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return default
            else:
                return default
        return current if current is not None else default

    def _get_display_field(self, field_config: Dict[str, Any], ws: Dict[str, Any],
                           global_states: Dict, timers: Dict) -> str:
        key = field_config.get('key', '')
        label = field_config.get('label', key)
        default = field_config.get('default', 'Unknown')
        format_str = field_config.get('format', '{label}: {value}')
        transform = field_config.get('transform', '')

        if '.' in key:
            parts = key.split('.')
            if parts[0] == 'global_states':
                value = global_states.get(parts[1], default)
            elif parts[0] == 'global_timers':
                value = timers.get(parts[1], default)
            else:
                value = ws.get(parts[0], default)
        else:
            value = ws.get(key, default)

        if value is None or value == default:
            value = ws.get(key, default)

        if transform == 'day_cycle':
            if isinstance(value, (int, float)):
                hours = int(value // 60)
                minutes = int(value % 60)
                formatted = f"{hours:02d}:{minutes:02d}"
            else:
                formatted = str(value) if value else '00:00'
        else:
            formatted = str(value) if value is not None and value != default else '?'

        try:
            return format_str.format(label=label, value=formatted)
        except Exception:
            return f"{label}: {formatted}"

    def _flush_log(self):
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(self.log_lines))
        except Exception as e:
            print(f"[ERROR] Failed to write log: {e}")

    def _load_action_catalog(self) -> List[str]:
        catalog_path = os.path.join(self.world_folder, "action_catalog.json")
        if os.path.exists(catalog_path):
            try:
                with open(catalog_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('action_catalog', [])
            except Exception as e:
                print(f"[ERROR] Failed to load {catalog_path}: {e}")

        if os.path.exists("action_catalog.json"):
            try:
                with open("action_catalog.json", 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('action_catalog', [])
            except Exception as e:
                print(f"[ERROR] Failed to load action_catalog.json: {e}")

        return [
            "GATHER_ALL_RESOURCES_GREEDY",
            "HARVEST_SUSTAINABLE_SHARED",
            "NEGOTIATE_COOPERATIVE_PACT",
            "IDLE_WAIT",
            "ATTACK_ENEMY_GREEDY",
            "SHARE_RESOURCES_WITH_ALLIES",
            "HOARD_RESOURCES_SELFISHLY",
            "PROPOSE_PEACE_TREATY",
            "DECLARE_WAR_AGGRESSIVE"
        ]

    def _load_variable_catalog(self) -> Dict[str, List[str]]:
        var_path = os.path.join(self.world_folder, "variable_catalog.json")
        if os.path.exists(var_path):
            try:
                with open(var_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('variable_catalog', {})
            except Exception as e:
                print(f"[ERROR] Failed to load {var_path}: {e}")

        if os.path.exists("variable_catalog.json"):
            try:
                with open("variable_catalog.json", 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('variable_catalog', {})
            except Exception as e:
                print(f"[ERROR] Failed to load variable_catalog.json: {e}")

        return {
            'character_variables': [
                'health', 'stamina', 'hunger', 'thirst', 'energy', 'morale', 'loyalty', 'trust'
            ],
            'object_variables': [
                'durability', 'quality', 'quantity', 'charge'
            ],
            'world_states': [
                'time_of_day', 'weather', 'season', 'resource_abundance'
            ]
        }

    # ==================== WORLD INIT ====================

    def _initialize_world(self, load_existing: bool):
        runtime_path = os.path.join(self.world_folder, "world_state_runtime.json")

        kwargs = {
            'characters_file': os.path.join(self.world_folder, "characters.json"),
            'objects_file': os.path.join(self.world_folder, "objects.json"),
            'scenes_file': os.path.join(self.world_folder, "scenes.json"),
            'rules_file': os.path.join(self.world_folder, "rules.json"),
            'world_states_file': os.path.join(self.world_folder, "world_states.json")
        }

        for opt_key, opt_filename in [
            ('knowledge_file', 'knowledge_base.json'),
            ('action_catalog_file', 'action_catalog.json'),
            ('character_graph_file', 'character_graph.json'),
            ('condition_registry_file', 'condition_registry.json')
        ]:
            path = os.path.join(self.world_folder, opt_filename)
            if os.path.exists(path):
                kwargs[opt_key] = path

        if load_existing and os.path.exists(runtime_path):
            print("[INFO] Loading existing world state from world_state_runtime.json")
            self.world = SimulatedWorldModule(**kwargs)
            self._load_runtime_state()
        else:
            print("[INFO] Creating new world state from JSON files")
            self.world = SimulatedWorldModule(**kwargs)
            self._record_initial_state()
            self._save_runtime_state()

        self._init_statistics()

    def _load_runtime_state(self):
        runtime_path = os.path.join(self.world_folder, "world_state_runtime.json")
        try:
            with open(runtime_path, 'r', encoding='utf-8') as f:
                runtime_data = json.load(f)

            self.world.characters.clear_all()
            self.world.objects.clear_all()

            if 'world_states' in runtime_data:
                for key, value in runtime_data['world_states'].items():
                    self.world.world_states.set(key, value)

            if 'characters' in runtime_data:
                for char_data in runtime_data['characters']:
                    self.world.characters.add_entity(char_data)
                print(f"[OK] Loaded {len(runtime_data['characters'])} characters from runtime state")

            if 'objects' in runtime_data:
                for obj_data in runtime_data['objects']:
                    self.world.objects.add_entity(obj_data)
                print(f"[OK] Loaded {len(runtime_data['objects'])} objects from runtime state")

            if 'event_history' in runtime_data:
                self.event_history = runtime_data['event_history'][-self.max_history:]
                print(f"[OK] Loaded {len(self.event_history)} events from runtime state")
            else:
                self._record_initial_state()

            if 'tick_count' in runtime_data:
                self.tick_count = runtime_data['tick_count']

            self.plotter = TimelinePlotter(self.world_folder)
            self.plotter.load_from_runtime(runtime_data)
            if (self.plotter.action_timeline or self.plotter.emotion_timeline
                    or self.plotter.ai_state_timeline or self.plotter.goal_timeline):
                print(f"[OK] Loaded {len(self.plotter.action_timeline)} action, "
                      f"{len(self.plotter.emotion_timeline)} emotion, "
                      f"{len(self.plotter.ai_state_timeline)} AI state, "
                      f"{len(self.plotter.goal_timeline)} goal entries")

            print("[OK] Runtime state loaded successfully")

        except Exception as e:
            print(f"[ERROR] Failed to load runtime state: {e}")
            self._record_initial_state()
            self._save_runtime_state()

    def _save_runtime_state(self):
        runtime_path = os.path.join(self.world_folder, "world_state_runtime.json")
        try:
            runtime_data = {
                "world_states": self.world.world_states.to_dict(),
                "characters": [c.to_dict() for c in self.world.characters.get_all()],
                "objects": [o.to_dict() for o in self.world.objects.get_all()],
                "event_history": self.event_history[-self.max_history:],
                "tick_count": self.tick_count,
                "action_timeline": self.plotter.action_timeline[-1000:],
                "emotion_timeline": self.plotter.emotion_timeline[-1000:],
                "ai_state_timeline": self.plotter.ai_state_timeline[-1000:],
                "goal_timeline": self.plotter.goal_timeline[-1000:],
                "last_saved": datetime.now().isoformat()
            }

            with open(runtime_path, 'w', encoding='utf-8') as f:
                json.dump(runtime_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save runtime state: {e}")
            return False

    def _record_initial_state(self):
        templates = self.dynamics.get('message_templates', {})
        locations = self._get_vocab('locations', ['Unknown'])

        for char in self.world.characters.get_all():
            name = char.get('name', 'Unknown')
            faction = char.get('social_attributes', {}).get('faction', 'Unknown')
            location = char.get('navigation', {}).get('current_location', 'Unknown')

            template = templates.get('character_entry', '[ENTRY] {character_name} enters the world')
            try:
                event = template.format(character_name=name, faction=faction, location=location)
            except KeyError:
                event = f"[ENTRY] {name} enters the world"
            self._add_event(event, 'entry', 'character', name)

        for obj in self.world.objects.get_all():
            name = obj.get('name', 'Unknown')
            obj_type = obj.get('properties', {}).get('type', 'item')
            quality = obj.get('object_variables', {}).get('quality', 'standard')
            location = random.choice(locations) if locations else 'Unknown'

            template = templates.get('object_entry', '[ENTRY] An object appears')
            try:
                event = template.format(quality=quality, object_type=obj_type,
                                        object_name=name, location=location)
            except KeyError:
                event = f"[ENTRY] {name} appears"
            self._add_event(event, 'entry', 'object', name)

    def _init_statistics(self):
        for char in self.world.characters.get_all():
            name = char.get('name', 'Unknown')
            self.statistics['characters'][name] = {
                'health_values': [],
                'stamina_values': [],
                'morale_values': [],
                'emotion_transitions': [],
                'actions_taken': [],
                'behavior_states': [],
                'emotions_observed': [],
                'goals_observed': [],
                'movement_count': 0,
                'social_action_count': 0,
                'tick_count': 0
            }
            self.emotion_history[name] = None

    # ==================== STATISTICS EXPORT ====================

    def _export_statistics(self):
        if self.tick_count < 1:
            return
        self._update_statistics()

        csv_path = os.path.join(self.world_folder, "statistics.csv")
        self._export_csv(csv_path)

        tex_path = os.path.join(self.world_folder, "statistics.tex")
        self._export_latex(tex_path)

        props_path = os.path.join(self.world_folder, "character_properties.tex")
        self._export_character_properties(props_path)

    def _update_statistics(self):
        self.statistics['global']['total_ticks'] = self.tick_count

        for char in self.world.characters.get_all():
            name = char.get('name', 'Unknown')
            if name not in self.statistics['characters']:
                continue

            status = char.get('status_variables', {})
            stats = self.statistics['characters'][name]

            if status:
                stats['health_values'].append(status.get('health', 50))
                stats['stamina_values'].append(status.get('stamina', 50))
                stats['morale_values'].append(status.get('morale', 50))

            stats['behavior_states'].append(char.get('ai_state', 'IDLE'))

            emotion = self.world.get_character_emotion(char) if hasattr(self.world, 'get_character_emotion') else 'neutral'
            stats['emotions_observed'].append(emotion)

            goal = self.world.get_current_goal(char) if hasattr(self.world, 'get_current_goal') else 'unknown'
            stats['goals_observed'].append(goal)

            stats['tick_count'] += 1

    def _export_csv(self, filepath: str):
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Character',
                    'Mean_Health', 'Std_Health',
                    'Mean_Stamina', 'Std_Stamina',
                    'Mean_Morale', 'Std_Morale',
                    'Emotion_Transitions',
                    'Actions_Taken',
                    'Movement_Count',
                    'Social_Actions',
                    'Unique_Behavior_States',
                    'Most_Common_State',
                    'Most_Common_Emotion',
                    'Most_Common_Goal'
                ])

                for name, stats in self.statistics['characters'].items():
                    import statistics as stat

                    health = stats['health_values']
                    stamina = stats['stamina_values']
                    morale = stats['morale_values']
                    emotions = stats['emotions_observed']
                    goals = stats['goals_observed']

                    most_common_emotion = max(set(emotions), key=emotions.count) if emotions else 'N/A'
                    most_common_goal = max(set(goals), key=goals.count) if goals else 'N/A'

                    writer.writerow([
                        name,
                        round(stat.mean(health), 2) if health else 'N/A',
                        round(stat.stdev(health), 2) if len(health) > 1 else 'N/A',
                        round(stat.mean(stamina), 2) if stamina else 'N/A',
                        round(stat.stdev(stamina), 2) if len(stamina) > 1 else 'N/A',
                        round(stat.mean(morale), 2) if morale else 'N/A',
                        round(stat.stdev(morale), 2) if len(morale) > 1 else 'N/A',
                        len(stats['emotion_transitions']),
                        len(stats['actions_taken']),
                        stats['movement_count'],
                        stats['social_action_count'],
                        len(set(stats['behavior_states'])),
                        max(set(stats['behavior_states']), key=stats['behavior_states'].count) if stats['behavior_states'] else 'N/A',
                        most_common_emotion,
                        most_common_goal
                    ])
        except Exception as e:
            print(f"[ERROR] Failed to export CSV: {e}")

    def _export_latex(self, filepath: str):
        try:
            lines = []
            lines.append("\\begin{table}[htbp]")
            lines.append("\\centering")
            lines.append("\\caption{Character Statistics Summary}")
            lines.append("\\label{tab:character_stats}")
            lines.append("\\begin{adjustbox}{width=\\columnwidth}")
            lines.append("\\begin{tabular}{|l|c|c|c|c|c|}")
            lines.append("\\hline")
            lines.append("\\textbf{Character} & \\textbf{Health} & \\textbf{Stamina} & \\textbf{Most Common State} & \\textbf{Most Common Emotion} & \\textbf{Most Common Goal} \\\\")
            lines.append("\\hline")

            for name, stats in self.statistics['characters'].items():
                import statistics as stat

                health = stats['health_values']
                stamina = stats['stamina_values']
                emotions = stats['emotions_observed']
                goals = stats['goals_observed']

                health_str = f"{stat.mean(health):.1f}" if health else "N/A"
                stamina_str = f"{stat.mean(stamina):.1f}" if stamina else "N/A"

                most_common_state = max(set(stats['behavior_states']), key=stats['behavior_states'].count) if stats['behavior_states'] else 'N/A'
                most_common_emotion = max(set(emotions), key=emotions.count) if emotions else 'N/A'
                most_common_goal = max(set(goals), key=goals.count) if goals else 'N/A'

                lines.append(f"{name} & {health_str} & {stamina_str} & {most_common_state} & {most_common_emotion} & {most_common_goal} \\\\")

            lines.append("\\hline")
            lines.append("\\end{tabular}")
            lines.append("\\end{adjustbox}")
            lines.append("\\end{table}")

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
        except Exception as e:
            print(f"[ERROR] Failed to export LaTeX: {e}")

    def _export_character_properties(self, filepath: str):
        try:
            lines = []
            lines.append("\\begin{table}[htbp]")
            lines.append("\\centering")
            lines.append("\\caption{Character Properties}")
            lines.append("\\label{tab:character_properties}")
            lines.append("\\begin{adjustbox}{width=\\columnwidth}")
            lines.append("\\begin{tabular}{|l|c|c|c|c|}")
            lines.append("\\hline")
            lines.append("\\textbf{Character} & \\textbf{Faction} & \\textbf{Alignment} & \\textbf{Primary Value} & \\textbf{Current Goal} \\\\")
            lines.append("\\hline")

            for char in self.world.characters.get_all():
                name = char.get('name', 'Unknown')

                social = char.get('social_attributes', {})
                faction = social.get('faction', 'N/A')
                alignment = social.get('alignment', 'N/A')

                schwartz = social.get('schwartz_values', {})
                if schwartz:
                    primary_value = max(schwartz, key=schwartz.get)
                    primary_value = f"{primary_value} ({schwartz[primary_value]:.1f})"
                else:
                    primary_value = 'N/A'

                reasoning = char.get('memory_perception', {}).get('reasoning_stack', {})
                current_goal = reasoning.get('current_goal', 'N/A')

                lines.append(f"{name} & {faction} & {alignment} & {primary_value} & {current_goal} \\\\")

            lines.append("\\hline")
            lines.append("\\end{tabular}")
            lines.append("\\end{adjustbox}")
            lines.append("\\end{table}")

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
        except Exception as e:
            print(f"[ERROR] Failed to export character properties: {e}")

    # ==================== MAX EPOCH HANDLING ====================

    def _check_max_epoch(self) -> bool:
        if self.max_epoch is None or self.max_epoch <= 0:
            return False
        if self.tick_count < self.max_epoch:
            return False

        if self.max_epoch_reached:
            return True

        self.max_epoch_reached = True
        print(f"\n[MAX_EPOCH] Reached epoch limit ({self.max_epoch}). "
              f"Saving state exactly like 'quit'...")
        self._save_runtime_state()
        self._export_statistics()
        self.plotter.export_all_csv()
        self.plotter.generate_all_charts()
        self._flush_log()
        print(f"[MAX_EPOCH] State, statistics, CSVs and charts saved at Epoch {self.tick_count}.")
        return True

    # ==================== MAIN UPDATE LOOP ====================

    def _update_world(self, render: bool = True):
        self.tick_count += 1
        self.world._current_tick = self.tick_count
        
        timers = self.world.world_states.get('global_timers', {})
        timers['world_time'] = timers.get('world_time', 0) + 1
        timers['day_cycle'] = (timers.get('day_cycle', 0) + 1) % 1440
        self.world.world_states.set('global_timers', timers)

        self._update_time_of_day()
        self._process_global_events()

        chars = self.world.characters.get_all()
        for char in chars:
            if hasattr(self.world, 'update_goal_based_on_status'):
                self.world.update_goal_based_on_status(char)

            if hasattr(self.world, 'select_next_behavior_state'):
                next_state = self.world.select_next_behavior_state(char)
                if next_state:
                    self.world.set_behavior_state(char, next_state)
            
            self._update_character(char)
            self._process_character_social_actions(char, chars)
            # Detect real events and update emotion
            appraisal_events = self._detect_appraisal_events(char)
            if appraisal_events:
                # Pick highest-intensity event
                event = appraisal_events[0]
                emotion, intensity = self.world.compute_emotion_from_appraisal(char, event)
                # Duration: 1 to 60 ticks depending on intensity
                duration = max(1, int(intensity * 60))
                self.world.emotion_manager.set_character_emotion(
                    char, emotion, intensity, duration_ticks=duration
                )
            # Always decay emotion each tick
            self.world.emotion_manager.tick_emotion_decay(char, self.tick_count)
            #current_emotion = self.world.get_character_emotion(char)
            
            # Track emotion / ai_state / goal timelines
            name = char.get('name', 'Unknown')
            current_emotion = self.world.get_character_emotion(char) if hasattr(self.world, 'get_character_emotion') else 'neutral'
            current_ai_state = char.get('ai_state', 'IDLE')
            current_goal = self.world.get_current_goal(char) if hasattr(self.world, 'get_current_goal') else 'unknown'
            last_action = self.last_action_per_char.get(name)
            last_goal = self.last_goal_per_char.get(name)

            # AI state entry
            self.plotter.add_ai_state_entry(
                self.tick_count, name, current_ai_state, current_emotion
            )

            # Emotion entry (with context)
            self.plotter.add_emotion_entry(
                self.tick_count, name, current_emotion,
                action=last_action or '',
                ai_state=current_ai_state,
                goal=current_goal
            )

            # Goal entry (only record when it changes to avoid huge files)
            if last_goal != current_goal:
                self.plotter.add_goal_entry(
                    self.tick_count, name, current_goal,
                    emotion=current_emotion,
                    ai_state=current_ai_state
                )
                self.last_goal_per_char[name] = current_goal

            # Emotion transition tracking
            if name in self.emotion_history:
                if self.emotion_history[name] is not None and self.emotion_history[name] != current_emotion:
                    if name in self.statistics['characters']:
                        # Detect emotion change
                        prev = self.emotion_history.get(name)
                        if prev and prev != current_emotion:
                            self.statistics['characters'][name]['emotion_transitions'].append(
                                f"{prev}->{current_emotion}"
                            )
                        self.statistics['global']['total_emotion_transitions'] += 1
                self.emotion_history[name] = current_emotion

        for obj in self.world.objects.get_all():
            self._update_object(obj)

        self._update_statistics()

        if self.tick_count % 10 == 0:
            self._save_runtime_state()
            self._export_statistics()
            self.plotter.export_all_csv(verbose=False)

        if render:
            self._render()

        if self._check_max_epoch():
            self.running = False
            self.continuous_mode = False

    # ==================== CHARACTER LOGIC ====================

    def _process_character_social_actions(self, char: DynamicEntity, all_chars: List[DynamicEntity]):
        if not self.action_catalog:
            return

        if random.random() < 0.12:
            action = random.choice(self.action_catalog)
            char_name = char.get('name', 'Unknown')
            location = char.get('navigation', {}).get('current_location', 'Unknown')
            current_emotion = self.world.get_character_emotion(char) if hasattr(self.world, 'get_character_emotion') else 'neutral'
            current_ai_state = char.get('ai_state', 'IDLE')

            if char_name in self.statistics['characters']:
                self.statistics['characters'][char_name]['actions_taken'].append(action)
                self.statistics['global']['total_actions'] += 1

            self.plotter.add_action_entry(
                self.tick_count, char_name, action, current_emotion,
                ai_state=current_ai_state
            )
            self.last_action_per_char[char_name] = action

            target_char = None
            social_actions = ["DECLARE_WAR_AGGRESSIVE", "PROPOSE_PEACE_TREATY",
                              "NEGOTIATE_COOPERATIVE_PACT", "SHARE_RESOURCES_WITH_ALLIES",
                              "ATTACK_ENEMY_GREEDY"]

            if action in social_actions and len(all_chars) > 1:
                potential_targets = [c for c in all_chars if c.get('name') != char_name]
                if potential_targets:
                    target_char = random.choice(potential_targets)
                    if char_name in self.statistics['characters']:
                        self.statistics['characters'][char_name]['social_action_count'] += 1
                        self.statistics['global']['total_social_actions'] += 1

            validated_action = action
            if hasattr(self.world, 'reasoning_engine') and self.world.reasoning_engine:
                try:
                    if hasattr(self.world.reasoning_engine, 'system_rules') and self.world.reasoning_engine.system_rules:
                        result = self.world.reasoning_engine.system_rules.validate_and_filter_action(action)
                        if isinstance(result, dict):
                            validated_action = result.get('action', action)
                        else:
                            validated_action = result
                except Exception:
                    pass

            if target_char:
                target_name = target_char.get('name', 'Unknown')
                msg = f"[SOCIAL ACTION] {char_name} targets {target_name} with '{validated_action}' at {location}"
                self._add_event(msg, 'social_action', 'character', char_name)
            else:
                msg = f"[ACTION] {char_name} executes '{validated_action}' at {location}"
                self._add_event(msg, 'action', 'character', char_name)

    def _update_time_of_day(self):
        time_config = self.dynamics.get('world_state_management', {}).get('time_of_day', {})
        if not time_config.get('enabled', False):
            return

        day_cycle = self.world.world_states.get('global_timers', {}).get('day_cycle', 0)
        current_time = self.world.world_states.get('global_states', {}).get('time_of_day', 'morning')

        transitions = time_config.get('transitions', [])
        for transition in transitions:
            if transition.get('from') == current_time:
                after_ticks = transition.get('after_ticks', 120)
                if day_cycle % after_ticks == 0:
                    new_state = transition.get('to')
                    if new_state:
                        self.world.world_states.set('global_states.time_of_day', new_state)
                        template = time_config.get('message_template', '[TIME] Time changes to {new_state}')
                        self._add_event(template.format(new_state=new_state), 'time', 'world')
                        break

    def _process_global_events(self):
        events_config = self.dynamics.get('global_events', {})
        if not events_config.get('enabled', False):
            return

        event_types = events_config.get('event_types', [])
        for event_type in event_types:
            probability = event_type.get('probability', 0.05)
            if random.random() < probability:
                triggers = event_type.get('triggers', [])
                trigger_met = True
                for trigger in triggers:
                    if not self._check_event_trigger(trigger):
                        trigger_met = False
                        break

                if trigger_met:
                    self._process_event(event_type)

    def _check_event_trigger(self, trigger: Dict[str, Any]) -> bool:
        trigger_type = trigger.get('type', 'random')
        condition = trigger.get('condition', '')
        probability = trigger.get('probability', 0.5)

        if trigger_type == 'random':
            if condition:
                if 'characters.count' in condition:
                    count = self.world.characters.count()
                    if '> 0' in condition and count == 0:
                        return False
                    if '>= 2' in condition and count < 2:
                        return False
                if 'tick_count %' in condition:
                    parts = condition.split('==')
                    if len(parts) == 2:
                        try:
                            mod = int(parts[0].split('%')[1].strip())
                            if self.tick_count % mod != 0:
                                return False
                        except Exception:
                            pass
            return random.random() < probability
        return True

    def _process_event(self, event_config: Dict[str, Any]):
        event_id = event_config.get('id', 'event')

        if event_id == 'character_action':
            action = random.choice(self.action_catalog) if self.action_catalog else "IDLE_WAIT"
            chars = self.world.characters.get_all()
            if chars:
                char = random.choice(chars)
                name = char.get('name', 'Unknown')
                location = char.get('navigation', {}).get('current_location', 'Unknown')
                message = f"[ACTION] {name} performs '{action}' at {location}"
                self._add_event(message, event_id, 'world')
                return

        message = self._build_event_message(event_config)
        self._add_event(message, event_id, 'world')

        effects = event_config.get('effects', [])
        for effect in effects:
            self._apply_effect(effect)

    def _build_event_message(self, event_config: Dict[str, Any]) -> str:
        template = event_config.get('message_template', '[EVENT] An event occurred')
        placeholders = event_config.get('placeholders', {})

        resolved = {}
        for key, config in placeholders.items():
            source = config.get('source')
            if source == 'list':
                values = config.get('list', [])
                resolved[key] = random.choice(values) if values else 'unknown'
            elif source == 'character':
                chars = self.world.characters.get_all()
                names = [c.get('name', 'Unknown') for c in chars]
                index = config.get('index', -1)
                if 0 <= index < len(names):
                    resolved[key] = names[index]
                else:
                    resolved[key] = random.choice(names) if names else 'Someone'
            elif source == 'location':
                locations = self._get_vocab('locations', ['Unknown'])
                resolved[key] = random.choice(locations) if locations else 'Unknown'
            elif source == 'random_int':
                min_val = config.get('min', 1)
                max_val = config.get('max', 20)
                resolved[key] = str(random.randint(min_val, max_val))
            else:
                resolved[key] = config.get('value', 'unknown')

        message = template
        for key, value in resolved.items():
            message = message.replace('{' + key + '}', str(value))
        return message

    def _apply_effect(self, effect: Dict[str, Any]):
        effect_type = effect.get('type')
        target = effect.get('target')
        operation = effect.get('operation')
        value = effect.get('value')

        if effect_type == 'set_state':
            if target:
                parts = target.split('.')
                if len(parts) == 2 and parts[0] == 'global_states':
                    current = self.world.world_states.get('global_states', {})
                    current[parts[1]] = value
                    self.world.world_states.set('global_states', current)

        elif effect_type == 'modify_character':
            for char in self.world.characters.get_all():
                status = char.get('status_variables', {})
                if target in status and isinstance(status[target], (int, float)):
                    if operation == 'add':
                        status[target] = max(0, min(100, status[target] + (value or 0)))
                        char.set('status_variables', status)

        elif effect_type == 'set_flag':
            if target:
                self.world.set_global_flag(target, bool(value))

    def _update_character(self, char: DynamicEntity):
        self._update_character_status(char)
        self._update_character_movement(char)
        self._update_ai_state(char)

    def _update_character_status(self, char: DynamicEntity):
        char_status_config = self.dynamics.get('status_changes', {}).get('character_status', {})
        status = char.get('status_variables', {})
        if not status:
            return

        ai_state = char.get('ai_state', 'idle').lower()

        for stat_name, stat_config in char_status_config.items():
            if stat_name in status:
                change_rate = stat_config.get('change_rate', {})
                rate_config = change_rate.get(ai_state, {'rate': 0.0})
                rate = rate_config.get('rate', 0.0)

                new_value = status[stat_name] + rate
                min_val = stat_config.get('min', 0)
                max_val = stat_config.get('max', 100)
                status[stat_name] = max(min_val, min(max_val, new_value))

                random_events = stat_config.get('random_events', {})
                for event_name, event_config in random_events.items():
                    if random.random() < event_config.get('probability', 0):
                        change = event_config.get('change', 0)
                        new_value = status[stat_name] + change
                        status[stat_name] = max(min_val, min(max_val, new_value))

                        if abs(change) > 10:
                            name = char.get('name', 'Unknown')
                            message = event_config.get('message', 'changes')
                            self._add_event(f"[STATUS] {name} {message}", 'status', 'character', name)

        char.set('status_variables', status)

    def _update_character_movement(self, char: DynamicEntity):
        movement_config = self.dynamics.get('character_movement', {})
        if not movement_config.get('enabled', False):
            return

        if random.random() < movement_config.get('movement_probability', 0.15):
            locations = self._get_vocab('locations', ['Unknown'])
            if locations:
                nav = char.get('navigation', {})
                if isinstance(nav, dict):
                    old_loc = nav.get('current_location', 'Unknown')
                    new_loc = random.choice(locations)
                    if new_loc != old_loc:
                        nav['current_location'] = new_loc
                        char.set('navigation', nav)
                        name = char.get('name', 'Unknown')

                        if name in self.statistics['characters']:
                            self.statistics['characters'][name]['movement_count'] += 1
                            self.statistics['global']['total_movements'] += 1

                        template = movement_config.get('message_template',
                            "[MOVEMENT] {character_name} moves from {old_location} to {new_location}")
                        try:
                            event = template.format(character_name=name, old_location=old_loc, new_location=new_loc)
                        except KeyError:
                            event = f"[MOVEMENT] {name} moves from {old_loc} to {new_loc}"
                        self._add_event(event, 'movement', 'character', name)

    def _update_ai_state(self, char: DynamicEntity):
        ai_config = self.dynamics.get('ai_state_changes', {})
        transitions = ai_config.get('transitions', [])

        current_state = char.get('ai_state', 'IDLE')
        status = char.get('status_variables', {})
        name = char.get('name', 'Unknown')

        for transition in transitions:
            if transition.get('from') != current_state:
                continue

            condition = transition.get('condition', {})
            if self._evaluate_ai_condition(condition, char, status):
                if random.random() < transition.get('probability', 0.5):
                    new_state = transition.get('to')
                    char.set('ai_state', new_state)
                    message = transition.get('message', f"changes state: {current_state} -> {new_state}")
                    self._add_event(f"[AI] {name} {message}", 'ai', 'character', name)
                    break

    def _evaluate_ai_condition(self, condition: Dict[str, Any], char: DynamicEntity, status: Dict) -> bool:
        if not condition:
            return True

        cond_type = condition.get('type')

        if cond_type == 'tick_mod':
            mod = condition.get('mod', 10)
            return self.tick_count % mod == 0
        elif cond_type == 'status_less_than':
            target = condition.get('target')
            threshold = condition.get('threshold', 50)
            return status.get(target, 0) < threshold
        elif cond_type == 'status_greater_than':
            target = condition.get('target')
            threshold = condition.get('threshold', 50)
            return status.get(target, 0) > threshold
        elif cond_type == 'random_chance':
            threshold = condition.get('threshold', 0.5)
            return random.random() < threshold
        elif cond_type == 'and':
            for cond in condition.get('conditions', []):
                if not self._evaluate_ai_condition(cond, char, status):
                    return False
            return True
        elif cond_type == 'or':
            for cond in condition.get('conditions', []):
                if self._evaluate_ai_condition(cond, char, status):
                    return True
            return False
        return True

    def _update_object(self, obj: DynamicEntity):
        object_status_config = self.dynamics.get('status_changes', {}).get('object_status', {})
        variables = obj.get('object_variables', {})

        if not variables:
            return

        for stat_name, stat_config in object_status_config.items():
            if stat_name in variables:
                change_rate = stat_config.get('change_rate', {})
                rate_config = change_rate.get('idle', {'rate': 0.0})
                rate = rate_config.get('rate', 0.0)

                new_value = variables[stat_name] + rate
                min_val = stat_config.get('min', 0)
                max_val = stat_config.get('max', 100)
                variables[stat_name] = max(min_val, min(max_val, new_value))

                random_events = stat_config.get('random_events', {})
                for event_name, event_config in random_events.items():
                    if random.random() < event_config.get('probability', 0):
                        change = event_config.get('change', 0)
                        new_value = variables[stat_name] + change
                        variables[stat_name] = max(min_val, min(max_val, new_value))

                        if abs(change) > 10:
                            name = obj.get('name', 'Unknown')
                            message = event_config.get('message', 'changes')
                            self._add_event(f"[DURABILITY] {name} {message}", 'durability', 'object', name)

        obj.set('object_variables', variables)

    def _add_event(self, text: str, event_type: str, entity_type: str, entity_name: str = None):
        self.event_history.append({
            'tick': self.tick_count,
            'type': event_type,
            'entity_type': entity_type,
            'entity_name': entity_name or 'world',
            'text': text,
            'timestamp': datetime.now().isoformat()
        })

        if len(self.event_history) > self.max_history:
            self.event_history = self.event_history[-self.max_history:]

    def _format_value(self, value: Any) -> str:
        if value is None:
            return '?'
        if isinstance(value, float):
            return str(int(round(value)))
        if isinstance(value, bool):
            return str(value)
        return str(value)

    # ==================== RENDER ====================

    def _render(self):
        display = self.dynamics.get('display', {})
        header_width = display.get('header_width', 80)
        separator = display.get('header_separator', '=')
        title = display.get('title', 'SIMULATED WORLD')

        output_lines = []
        output_lines.append(separator * header_width)
        output_lines.append(f"{title} - EPOCH {self.tick_count}"
                            + (f" / {self.max_epoch}" if self.max_epoch and self.max_epoch > 0 else ""))
        output_lines.append(f"FPS: {self.fps} | Time: {datetime.now().strftime(display.get('date_format', '%Y-%m-%d %H:%M:%S'))}")
        output_lines.append(f"World: {self.world_folder}")
        output_lines.append(separator * header_width)

        ws = self.world.world_states.to_dict()
        global_states = ws.get('global_states', {})
        timers = ws.get('global_timers', {})

        world_state_display = display.get('world_state_display', {})
        output_lines.append(f"\n[{world_state_display.get('label', 'WORLD STATE')}]")

        for field in world_state_display.get('fields', []):
            formatted = self._get_display_field(field, ws, global_states, timers)
            output_lines.append(f"  {formatted}")

        char_display = display.get('character_display', {})
        chars = self.world.characters.get_all()
        output_lines.append(f"\n[{char_display.get('label', 'CHARACTERS')}] ({len(chars)})")

        for char in chars:
            name = char.get('name', 'Unknown')
            ai_state = char.get('ai_state', 'IDLE')

            goal = self.world.get_current_goal(char) if hasattr(self.world, 'get_current_goal') else 'unknown'
            emotion = self.world.get_character_emotion(char) if hasattr(self.world, 'get_character_emotion') else 'neutral'

            status = char.get('status_variables', {})
            health = self._format_value(status.get('health', '?')) if status else '?'
            stamina = self._format_value(status.get('stamina', '?')) if status else '?'
            location = char.get('navigation', {}).get('current_location', '?')

            output_lines.append(f"  * {name} [{ai_state}] | Goal: {goal} | Emotion: {emotion} | HP:{health} | ST:{stamina} @ {location}")

        events_display = display.get('events_display', {})
        max_events = events_display.get('max_display', 10)
        output_lines.append(f"\n[{events_display.get('label', 'RECENT EVENTS')}]")

        for event in self.event_history[-max_events:]:
            tick = event.get('tick', '?')
            text = event.get('text', '')
            output_lines.append(f"  [{tick}] {text}")

        output_lines.append(separator * header_width)

        for line in output_lines:
            print(line)

        self.log_lines.extend(output_lines)
        self._flush_log()
        sys.stdout.flush()

    # ==================== COMMANDS ====================

    def _process_command(self, cmd: str) -> bool:
        cmd = cmd.strip().lower()
        if not cmd:
            return False

        parts = cmd.split()
        command = parts[0].lower()

        if command in ['q', 'quit', 'exit']:
            print("\n[STOP] Saving state and shutting down...")
            self.shutdown_requested = True
            self.running = False
            self._save_runtime_state()
            self._export_statistics()
            self.plotter.export_all_csv()
            self.plotter.generate_all_charts()
            self._flush_log()
            return True

        elif command == 'help':
            print("\n" + "="*60)
            print("AVAILABLE COMMANDS")
            print("="*60)
            print("  [Enter]              - Force an immediate tick update")
            print("  help                 - Show this help menu")
            print("  summary              - Print full world and character status summary")
            print("  catalog              - List all available actions in catalog")
            print("  var                  - List all available variables")
            print("  list                 - List all characters, states, and HP")
            print("  action <Name> <ACTION> - Force character action intent")
            print("  set char <Name> <var> <val> - Modify character status variable")
            print("  set world <key> <val> - Modify global world state")
            print("  save                 - Save current world state")
            print("  stats                - Export statistics to CSV and LaTeX")
            print("  charts               - Generate timeline charts")
            print("  timelines            - Export timeline CSVs")
            print("  mode                 - Show current mode")
            print("  q / quit / exit      - Save and exit")
            print("="*60)

        elif command == 'mode':
            print(f"\n[CURRENT MODE] {self.mode.upper()}")
            if self.mode == "dynamic":
                print(f"  - Running continuously at {self.fps} FPS")
                print("  - Commands can be typed at any time")
            elif self.mode == "interactive":
                print("  - Step-by-step mode")
                print("  - Press Enter or type 'n' to advance one epoch")
            else:
                print("  - Automatic mode")
                print("  - Running continuously without command input")
            if self.max_epoch and self.max_epoch > 0:
                print(f"  - Max epochs: {self.max_epoch} (reached: {self.max_epoch_reached})")

        elif command == 'summary':
            self._render()

        elif command == 'stats':
            self._export_statistics()
            print("[OK] Statistics exported")

        elif command == 'charts':
            self.plotter.generate_all_charts()
            print("[OK] Charts generated")

        elif command == 'timelines':
            self.plotter.export_all_csv()
            print("[OK] Timeline data exported")

        elif command == 'catalog':
            print("\n[ACTION CATALOG]")
            for idx, act in enumerate(self.action_catalog, 1):
                print(f"  {idx}. {act}")

        elif command == 'var':
            print("\n[VARIABLE CATALOG]")
            char_vars = self.variable_catalog.get('character_variables', [])
            if char_vars:
                print("\n  CHARACTER VARIABLES:")
                for var in char_vars:
                    print(f"    - {var}")
            obj_vars = self.variable_catalog.get('object_variables', [])
            if obj_vars:
                print("\n  OBJECT VARIABLES:")
                for var in obj_vars:
                    print(f"    - {var}")
            world_vars = self.variable_catalog.get('world_states', [])
            if world_vars:
                print("\n  WORLD STATES:")
                for var in world_vars:
                    print(f"    - {var}")
            print()

        elif command == 'list':
            print("\n[CHARACTERS]")
            for c in self.world.characters.get_all():
                status = c.get('status_variables', {})
                status_str = ", ".join([f"{k}:{v}" for k, v in status.items()]) if status else "No status"
                print(f"  - {c.get('name')} | State: {c.get('ai_state')} | {status_str} | Location: {c.get('navigation', {}).get('current_location')}")

            print("\n[OBJECTS]")
            for obj in self.world.objects.get_all():
                vars_str = ", ".join([f"{k}:{v}" for k, v in obj.get('object_variables', {}).items()]) if obj.get('object_variables') else "No variables"
                print(f"  - {obj.get('name')} | Type: {obj.get('properties', {}).get('type', 'unknown')} | {vars_str}")

            print("\n[WORLD STATES]")
            ws = self.world.world_states.to_dict()
            for key, value in ws.items():
                if key not in ['global_timers', 'global_states']:
                    print(f"  - {key}: {value}")
            if 'global_states' in ws:
                for key, value in ws['global_states'].items():
                    print(f"  - global_states.{key}: {value}")
            if 'global_timers' in ws:
                for key, value in ws['global_timers'].items():
                    print(f"  - global_timers.{key}: {value}")

        elif command == 'action':
            if len(parts) < 3:
                print("[ERROR] Usage: action <CharacterName> <ACTION_NAME>")
                return False
            char_name = parts[1]
            action_intent = parts[2].upper()

            if self.action_catalog and action_intent not in self.action_catalog:
                print(f"[ERROR] '{action_intent}' is invalid. Type 'catalog' to check valid actions.")
                return False

            target_char = next((c for c in self.world.characters.get_all() if c.get('name', '').lower() == char_name.lower()), None)
            if target_char:
                loc = target_char.get('navigation', {}).get('current_location', 'Unknown')
                msg = f"[ACTION] {target_char.get('name')} performs '{action_intent}' at {loc}"
                self._add_event(msg, 'user_action', 'character', target_char.get('name'))
                print(f"[OK] {msg}")
            else:
                print(f"[ERROR] Character '{char_name}' not found.")

        elif command == 'set':
            if len(parts) < 4:
                print("[ERROR] Usage: set char <Name> <var> <val> OR set world <key> <val>")
                return False
            sub_target = parts[1].lower()

            if sub_target == 'char':
                if len(parts) < 5:
                    print("[ERROR] Usage: set char <CharacterName> <variable> <value>")
                    return False
                char_name = parts[2]
                var_name = parts[3]
                val_str = parts[4]

                target_char = next((c for c in self.world.characters.get_all() if c.get('name', '').lower() == char_name.lower()), None)
                if target_char:
                    status = target_char.get('status_variables', {})
                    if var_name in status:
                        try:
                            orig_val = status[var_name]
                            if isinstance(orig_val, bool):
                                new_val = val_str.lower() in ['true', '1', 'yes']
                            elif isinstance(orig_val, int):
                                new_val = int(val_str)
                            elif isinstance(orig_val, float):
                                new_val = float(val_str)
                            else:
                                new_val = val_str

                            status[var_name] = new_val
                            target_char.set('status_variables', status)
                            print(f"[OK] Set {target_char.get('name')}'s {var_name} to {new_val}")
                            self._add_event(f"[ADMIN] Set {target_char.get('name')}'s {var_name} to {new_val}", 'admin', 'character', target_char.get('name'))
                        except ValueError:
                            print(f"[ERROR] Invalid number format for value '{val_str}'.")
                    else:
                        print(f"[ERROR] Status variable '{var_name}' not found. Type 'var' to see available variables.")
                else:
                    print(f"[ERROR] Character '{char_name}' not found.")

            elif sub_target == 'world':
                key = parts[2]
                val_str = parts[3]
                try:
                    if val_str.lower() in ['true', 'false']:
                        new_val = val_str.lower() == 'true'
                    else:
                        try:
                            new_val = float(val_str) if '.' in val_str else int(val_str)
                        except ValueError:
                            new_val = val_str

                    self.world.world_states.set(key, new_val)
                    print(f"[OK] Set world state '{key}' to {new_val}")
                    self._add_event(f"[ADMIN] Set world state '{key}' to {new_val}", 'admin', 'world')
                except Exception as e:
                    print(f"[ERROR] Failed to set world state: {e}")
            else:
                print("[ERROR] Unknown set target. Use 'set char' or 'set world'.")

        elif command == 'save':
            self._save_runtime_state()
            self._export_statistics()
            print(f"[OK] World state saved at Epoch {self.tick_count}")

        else:
            print(f"[ERROR] Unknown command '{command}'. Type 'help' for options.")

        return False
        
    def _detect_appraisal_events(self, char):
        """Detect real events that trigger emotion appraisals."""
        events = []
        status = char.get('status_variables', {})
        ai_state = char.get('ai_state', 'IDLE').upper()
        prev_ai_state = char.get('_prev_ai_state', ai_state)
        
        # 1. State transitions
        if prev_ai_state != ai_state:
            if ai_state in ('FLEEING', 'FLEE'):
                events.append('threat_detected')
            elif ai_state == 'COMBAT' and status.get('health', 100) < 40:
                events.append('goal_blocked')  # can't win
            elif ai_state == 'REST':
                events.append('loss_experienced')  # losing time
            elif ai_state in ('SOCIALIZE', 'SHARE'):
                events.append('goal_achieved')  # social goal met
            elif ai_state in ('EXPLORE', 'SEARCHING'):
                events.append('novelty_detected')
            elif ai_state == 'GATHER':
                events.append('goal_achieved')
        
        # 2. Resource / status events
        if status.get('health', 100) < 30:
            events.append('threat_detected')
        if status.get('stamina', 100) < 20:
            events.append('loss_experienced')
        if status.get('hunger', 0) > 80 or status.get('thirst', 0) > 80:
            events.append('goal_blocked')  # survival blocked
        
        # 3. Random events during tick (10% chance)
        if random.random() < 0.10:
            events.append(random.choice([
                'novelty_detected', 'goal_achieved', 'goal_blocked',
                'threat_detected', 'loss_experienced', 'contamination_detected'
            ]))
        
        char.set('_prev_ai_state', ai_state)
        return events
    
    # ==================== RUN MODES ====================

    def _run_dynamic_mode(self):
        self.mode = "dynamic"
        print("\n" + "="*70)
        print("DYNAMIC MODE ACTIVE")
        print(f"Running at {self.fps} FPS. Type commands anytime (press Enter to execute).")
        if self.max_epoch and self.max_epoch > 0:
            print(f"Will switch to interactive mode at epoch {self.max_epoch}.")
        print("Type 'help' for available commands, 'q' to quit.")
        print("="*70)

        self._render()

        cmd_buffer = ""
        last_tick_time = time.time()
        prompt_shown = True

        print("[DYNAMIC] ", end="", flush=True)

        while self.running and not self.shutdown_requested:
            try:
                current_time = time.time()

                if sys.platform == 'win32':
                    import msvcrt
                    if msvcrt.kbhit():
                        char = msvcrt.getch()
                        if char == b'\r':
                            print()
                            if cmd_buffer.strip():
                                should_exit = self._process_command(cmd_buffer.strip())
                                cmd_buffer = ""
                                if should_exit:
                                    return
                            else:
                                self._update_world(render=True)
                            if self.max_epoch_reached:
                                return
                            print("[DYNAMIC] ", end="", flush=True)
                            prompt_shown = True
                            last_tick_time = current_time
                        elif char == b'\x08':
                            if cmd_buffer:
                                cmd_buffer = cmd_buffer[:-1]
                                print("\b \b", end="", flush=True)
                        else:
                            try:
                                decoded = char.decode('utf-8')
                                if decoded.isprintable():
                                    cmd_buffer += decoded
                                    print(decoded, end="", flush=True)
                                    prompt_shown = False
                            except UnicodeDecodeError:
                                pass
                else:
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        char = sys.stdin.read(1)
                        if char == '\n' or char == '\r':
                            print()
                            if cmd_buffer.strip():
                                should_exit = self._process_command(cmd_buffer.strip())
                                cmd_buffer = ""
                                if should_exit:
                                    return
                            else:
                                self._update_world(render=True)
                            if self.max_epoch_reached:
                                return
                            print("[DYNAMIC] ", end="", flush=True)
                            prompt_shown = True
                            last_tick_time = current_time
                        elif char == '\x7f' or char == '\x08':
                            if cmd_buffer:
                                cmd_buffer = cmd_buffer[:-1]
                                print("\b \b", end="", flush=True)
                        elif char.isprintable():
                            cmd_buffer += char
                            print(char, end="", flush=True)
                            prompt_shown = False

                elapsed_since_tick = current_time - last_tick_time
                if elapsed_since_tick >= self.tick_interval:
                    self._update_world(render=True)
                    last_tick_time = current_time

                    if self.max_epoch_reached:
                        print("\n[MAX_EPOCH] Exiting dynamic mode -> switching to interactive mode.")
                        return

                    if not prompt_shown:
                        print("[DYNAMIC] ", end="", flush=True)
                        prompt_shown = True
                else:
                    time.sleep(0.01)

            except KeyboardInterrupt:
                print("\n[STOP] Dynamic mode interrupted. Saving state...")
                self.shutdown_requested = True
                self.running = False
                self._save_runtime_state()
                self._export_statistics()
                self.plotter.export_all_csv()
                self.plotter.generate_all_charts()
                self._flush_log()
                break
            except Exception as e:
                print(f"\n[ERROR] {e}")
                print("[DYNAMIC] ", end="", flush=True)
                continue

    def _run_interactive_mode(self):
        self.mode = "interactive"
        print("\n" + "="*70)
        print("INTERACTIVE MODE ACTIVE")
        print("Commands: [Enter] / n / next - Step forward one epoch")
        print("          c / continue       - Run continuously (Ctrl+C to stop)")
        print("          Type 'help' for all commands")
        if self.max_epoch_reached:
            print(f"[NOTE] Max epoch ({self.max_epoch}) already reached. Advancing is disabled.")
        print("="*70)

        self._render()

        while self.running and not self.shutdown_requested:
            try:
                sys.stdout.write("\nswm-interactive> ")
                sys.stdout.flush()

                cmd = sys.stdin.readline()

                if not cmd:
                    print("\n[STOP] EOF detected. Saving state and shutting down...")
                    self.shutdown_requested = True
                    self.running = False
                    self._save_runtime_state()
                    self._export_statistics()
                    self.plotter.export_all_csv()
                    self.plotter.generate_all_charts()
                    self._flush_log()
                    break

                cmd = cmd.strip().lower()

                if not cmd or cmd in ['n', 'next']:
                    if self.max_epoch_reached:
                        print(f"[MAX_EPOCH] Cannot advance beyond {self.max_epoch}. "
                              f"Use 'q' to exit or other commands.")
                        continue
                    self._update_world(render=True)
                    continue

                if cmd in ['c', 'continue']:
                    if self.max_epoch_reached:
                        print(f"[MAX_EPOCH] Cannot continue beyond {self.max_epoch}.")
                        continue
                    print(f"[START] Continuous mode activated at {self.fps} FPS. Press Ctrl+C to stop.")
                    self.continuous_mode = True
                    self._run_continuous_loop()
                    print(f"[STOP] Continuous mode stopped at Epoch {self.tick_count}")
                    self._render()
                    continue

                if cmd in ['s', 'save']:
                    self._save_runtime_state()
                    self._export_statistics()
                    print(f"[OK] World state saved at Epoch {self.tick_count}")
                    continue

                if self._process_command(cmd):
                    return

            except KeyboardInterrupt:
                if self.continuous_mode:
                    print("\n[STOP] Continuous mode interrupted.")
                    self.continuous_mode = False
                    self._render()
                    continue
                else:
                    print("\n[STOP] Keyboard interrupt detected. Saving state and shutting down...")
                    self.shutdown_requested = True
                    self.running = False
                    self._save_runtime_state()
                    self._export_statistics()
                    self.plotter.export_all_csv()
                    self.plotter.generate_all_charts()
                    self._flush_log()
                    break
            except EOFError:
                print("\n[STOP] EOF detected. Saving state and shutting down...")
                self.shutdown_requested = True
                self.running = False
                self._save_runtime_state()
                self._export_statistics()
                self.plotter.export_all_csv()
                self.plotter.generate_all_charts()
                self._flush_log()
                break
            except Exception as e:
                print(f"\n[ERROR] Unexpected error: {e}")
                continue

    def _run_continuous_loop(self):
        while self.continuous_mode and self.running and not self.shutdown_requested:
            start_time = time.time()
            self._update_world(render=True)

            if self.max_epoch_reached:
                print(f"\n[MAX_EPOCH] Continuous mode stopped at Epoch {self.tick_count}.")
                self.continuous_mode = False
                break

            elapsed = time.time() - start_time
            sleep_time = max(0, self.tick_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _run_auto_mode(self):
        self.mode = "auto"
        print(f"[START] World running automatically at {self.fps} FPS")
        if self.max_epoch and self.max_epoch > 0:
            print(f"[LIMIT] Will stop automatically at epoch {self.max_epoch}")
        print("Press Ctrl+C to save and quit")
        time.sleep(1)

        try:
            while self.running and not self.shutdown_requested:
                start_time = time.time()
                self._update_world(render=True)

                if self.max_epoch_reached:
                    print(f"\n[MAX_EPOCH] Auto mode stopped at Epoch {self.tick_count}.")
                    break

                elapsed = time.time() - start_time
                sleep_time = max(0, self.tick_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n[STOP] Saving state before exit...")
            self._save_runtime_state()
            self._export_statistics()
            self.plotter.export_all_csv()
            self.plotter.generate_all_charts()
            self._flush_log()
            print(f"[OK] World state saved. Ran for {self.tick_count} epochs")
            print(f"[OK] Log saved to {self.log_file}")
        except Exception as e:
            print(f"\n[ERROR] Unexpected error: {e}")
            self._save_runtime_state()
            self._export_statistics()
            self.plotter.export_all_csv()
            self.plotter.generate_all_charts()
            self._flush_log()

    def run(self):
        self.running = True

        if self.dynamic:
            self._run_dynamic_mode()

            if self.max_epoch_reached and not self.shutdown_requested:
                print("\n[SWITCH] Continuing in interactive mode...")
                self.running = True
                self._run_interactive_mode()
            return

        if self.interact:
            self._run_interactive_mode()
            return

        self._run_auto_mode()


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Run the simulated world with visualization and interactivity',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python swm_run.py --world world_2024_01_15
  python swm_run.py --world world_2024_01_15 --fps 2 --max-epoch 500
  python swm_run.py --world world_2024_01_15 --dynamic --max-epoch 1000
  python swm_run.py --world world_2024_01_15 --interact
  python swm_run.py --world world_2024_01_15 --new
        """
    )
    parser.add_argument('--fps', type=float, default=1.0,
                        help='Frames per second (default: 1.0)')
    parser.add_argument('--new', action='store_true',
                        help='Create a new world state (ignore existing)')
    parser.add_argument('--world', type=str,
                        help='Specify a world folder to load')
    parser.add_argument('--interact', action='store_true',
                        help='Interactive step-by-step mode')
    parser.add_argument('--dynamic', action='store_true',
                        help='Dynamic mode: continuous simulation with command input')
    parser.add_argument('--max-epoch', type=int, default=10000,
                        help='Maximum number of epochs before stopping/saving (default: 10000, 0=unlimited)')
    args = parser.parse_args()

    runner = WorldRunner(
        fps=args.fps,
        load_existing=not args.new,
        world_folder=args.world,
        interact=args.interact,
        dynamic=args.dynamic,
        max_epoch=args.max_epoch,
    )
    runner.run()


if __name__ == "__main__":
    main()