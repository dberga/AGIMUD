#!/usr/bin/env python3
"""
Simulated World Module - Main class with JSON loading and reasoning
All configuration from JSON files, no hardcoding.
Integrates swm_reason.py, swm_emotion.py, and swm_behavior.py.
"""

import os
import sys
import json
import time
import re
import random
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# Corpus & Dynamic Entity Imports
from swm_corpus_loader import SWMCorpusLoader, DynamicEntity, DynamicEntityCollection

# Encapsulated Logic Imports
from swm_reason import (
    SocialReasoningEngine,
    SchwartzValueMotor,
    OstromGovernanceMotor,
    MontesSierraBeliefMotor
)
from swm_emotion import EmotionManager
from swm_behavior import BehaviorManager


class TeeOutput:
    """Class to tee output to both console and a file"""
    def __init__(self, filename: str, mode: str = 'w'):
        self.terminal = sys.stdout
        self.log_file = open(filename, mode, encoding='utf-8')
        self.filename = filename
        self.buffer = []

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
        self.buffer.append(message)

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        self.log_file.close()

    def get_buffer(self):
        return ''.join(self.buffer)


class SimulatedWorldModule:
    """Main Simulated World Module with JSON loading and reasoning"""

    def __init__(self,
                 characters_file: str = "characters.json",
                 objects_file: str = "objects.json",
                 scenes_file: str = "scenes.json",
                 rules_file: str = "rules.json",
                 world_states_file: str = "world_states.json",
                 knowledge_file: str = None,
                 action_catalog_file: str = None,
                 character_graph_file: str = None,
                 condition_registry_file: str = None,
                 vocab_file: str = "world_vocabulary.json",
                 reasoning_config: str = None,
                 log_to_file: bool = True,
                 log_filename: str = "world_summary.log"):
        """Initialize the Simulated World Module by loading JSON files"""

        # Setup logging
        self.log_to_file = log_to_file
        self.log_filename = log_filename
        self.tee = None

        # Internal simulation clock (updated externally by the runner)
        self._current_tick = 0

        # Load vocabulary
        self.vocab = self._load_json(vocab_file) if os.path.exists(vocab_file) else {}

        # Store raw data collections
        self.corpus_loader = SWMCorpusLoader()

        # Game Entities
        self.characters: DynamicEntityCollection = self.corpus_loader.characters
        self.objects: DynamicEntityCollection = self.corpus_loader.objects
        self.scenes: DynamicEntityCollection = self.corpus_loader.scenes
        self.rules: DynamicEntityCollection = self.corpus_loader.rules
        self.other_users: DynamicEntityCollection = DynamicEntityCollection("user")

        # Global Elements
        self.world_states = self.corpus_loader.world_states
        self.knowledge_base = DynamicEntity()
        self.sound_graphics = DynamicEntity()
        self.system_rules = DynamicEntity()

        # Determine world folder from file paths
        self.world_folder = self._extract_world_folder(characters_file)

        # Setup log file path
        if self.log_to_file and self.world_folder:
            self.log_filepath = os.path.join(self.world_folder, self.log_filename)
        else:
            self.log_filepath = self.log_filename

        # Start logging
        self._start_logging()

        # Load corpora from JSON files
        self.load_corpora(
            characters_file, objects_file, scenes_file, rules_file, world_states_file,
            knowledge_file, action_catalog_file, character_graph_file, condition_registry_file
        )

        # Load condition registry from vocab or file
        self.condition_registry = self.knowledge_base.get('condition_registry', {})
        if not self.condition_registry:
            self.condition_registry = self.vocab.get('condition_registry', {})

        # Initialize Encapsulated Sub-Managers
        self.emotion_manager = EmotionManager(self.vocab, self.rules)
        self.behavior_manager = BehaviorManager(self.vocab, self.rules, self.world_states, self.condition_registry)

        # Initialize Social Reasoning Engine
        self.reasoning_engine = SocialReasoningEngine(test_file=reasoning_config or "reasoning_tests.json")

        # Load reasoning configs from rules into knowledge base
        self._load_reasoning_from_rules()
        self._load_reasoning_model()

        print("[INIT] Simulated World Module initialized")
        print(f"[INIT] Emotion model loaded with {len(self.emotion_manager.ekman_emotions)} emotions")
        print(f"[INIT] Condition registry loaded with {len(self.condition_registry)} conditions")
        print(f"[INIT] Social Reasoning Engine loaded with {len(self.reasoning_engine.test_loader.configurations)} configs")
        print(f"[INIT] Knowledge base loaded: {len(self.knowledge_base.to_dict())} items")
        print(f"[INIT] Logging to: {self.log_filepath}")

    # ==================== SETUP / LOGGING ====================

    def _extract_world_folder(self, filepath: str) -> Optional[str]:
        if not filepath:
            return None
        dirname = os.path.dirname(filepath)
        if dirname and os.path.isdir(dirname):
            return dirname
        return None

    def _start_logging(self):
        if self.log_to_file:
            log_dir = os.path.dirname(self.log_filepath)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            self.tee = TeeOutput(self.log_filepath, 'w')
            self.tee.write("=" * 70 + "\n")
            self.tee.write(f"WORLD SUMMARY - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.tee.write("=" * 70 + "\n\n")
            sys.stdout = self.tee

    def _stop_logging(self):
        if self.tee:
            sys.stdout = self.tee.terminal
            self.tee.close()
            self.tee = None

    def _load_json(self, filepath: str) -> Dict[str, Any]:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARNING] Failed to load {filepath}: {e}")
            return {}

    def _load_reasoning_from_rules(self):
        reasoning_data = {}
        for rule in self.rules.get_all():
            rule_data = rule.to_dict()
            if rule_data.get('type') == 'reasoning':
                config_name = rule_data.get('id', 'default')
                config_dict = {}
                for key in ['schwartz_weights', 'ostrom_weights', 'ostrom_sanctions', 'beliefs',
                            'peer_beliefs', 'discrepancy_flag', 'trust_threshold', 'cooperation_threshold']:
                    if key in rule_data:
                        config_dict[key] = rule_data[key]
                        reasoning_data[key] = rule_data[key]
                if config_dict:
                    self.reasoning_engine.configure(**config_dict)
                    print(f"[OK] Applied reasoning config: {config_name}")
        if reasoning_data:
            self.knowledge_base.update({'reasoning_config': reasoning_data})

    def _load_reasoning_model(self):
        self.reasoning_configs = {}
        for rule in self.rules.get_all():
            rule_data = rule.to_dict()
            if rule_data.get('type') == 'reasoning':
                config_id = rule_data.get('id', 'default')
                self.reasoning_configs[config_id] = {
                    'schwartz_weights': rule_data.get('schwartz_weights', {}),
                    'trust_threshold': rule_data.get('trust_threshold', 0.6),
                    'cooperation_threshold': rule_data.get('cooperation_threshold', 0.5),
                    'ostrom_weights': rule_data.get('ostrom_weights', {}),
                    'ostrom_sanctions': rule_data.get('ostrom_sanctions', {}),
                    'beliefs': rule_data.get('beliefs', {}),
                    'peer_beliefs': rule_data.get('peer_beliefs', {}),
                    'discrepancy_flag': rule_data.get('discrepancy_flag', False)
                }
        if self.reasoning_configs:
            first_config = list(self.reasoning_configs.values())[0]
            self.reasoning_engine.configure(**first_config)

    def clear_all(self):
        self.characters.clear_all()
        self.objects.clear_all()
        self.scenes.clear_all()
        self.rules.clear_all()
        self.world_states = DynamicEntity()
        self.knowledge_base = DynamicEntity()

    def load_corpora(self, characters_file: str = "characters.json", objects_file: str = "objects.json",
                     scenes_file: str = "scenes.json", rules_file: str = "rules.json",
                     world_states_file: str = "world_states.json",
                     knowledge_file: str = None, action_catalog_file: str = None,
                     character_graph_file: str = None, condition_registry_file: str = None):
        self.corpus_loader.load_all(characters_file, objects_file, scenes_file, rules_file,
                                    world_states_file, knowledge_file)

        for file_path in [knowledge_file, action_catalog_file, character_graph_file, condition_registry_file]:
            if file_path and os.path.exists(file_path):
                data = self._load_json(file_path)
                if data:
                    self.knowledge_base.update(data)
                    print(f"[OK] Loaded base file: {file_path}")

        if not self.knowledge_base.to_dict() and self.corpus_loader.knowledge_base:
            self.knowledge_base.update(self.corpus_loader.knowledge_base)
        if not self.world_states.to_dict():
            self.world_states.update(self.corpus_loader.world_states.to_dict())

    # ==================== GETTERS ====================

    def get_characters(self) -> List[DynamicEntity]:
        return self.characters.get_all()

    def get_characters_dict(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self.characters.get_all()]

    def get_objects(self) -> List[DynamicEntity]:
        return self.objects.get_all()

    def get_objects_dict(self) -> List[Dict[str, Any]]:
        return [o.to_dict() for o in self.objects.get_all()]

    def get_scenes(self) -> List[DynamicEntity]:
        return self.scenes.get_all()

    def get_rules(self) -> List[DynamicEntity]:
        return self.rules.get_all()

    def get_world_states(self) -> DynamicEntity:
        return self.world_states

    # ==================== SIMULATION CLOCK ====================

    def set_current_tick(self, tick: int):
        """Update the internal simulation clock. Should be called by the runner
        at the start of every epoch so that goal / emotion timers stay in sync."""
        self._current_tick = int(tick)

    def get_current_tick(self) -> int:
        return self._current_tick

    # ==================== WORLD STATE MANAGEMENT ====================

    def get_world_state(self, key: str, default: Any = None) -> Any:
        return self.world_states.get(key, default)

    def set_world_state(self, key: str, value: Any) -> None:
        self.world_states.set(key, value)

    def get_global_flag(self, flag_name: str, default: bool = False) -> bool:
        flags = self.world_states.get("persistent_flags", {})
        return flags.get(flag_name, default)

    def set_global_flag(self, flag_name: str, value: bool) -> None:
        flags = self.world_states.get("persistent_flags", {})
        flags[flag_name] = value
        self.world_states.set("persistent_flags", flags)

    # ==================== DELEGATED EMOTION METHODS ====================

    def get_character_emotion(self, char: DynamicEntity) -> str:
        return self.emotion_manager.get_character_emotion(char)

    def set_character_emotion(self, char: DynamicEntity, emotion: str,
                              intensity: float = 0.5, duration_ticks: int = 1):
        """Set an emotion with a bounded lifetime. Duration is expressed in ticks
        (1 tick = 1 simulated minute)."""
        # Pass the current tick so the manager can compute emotion_expires_at.
        try:
            self.emotion_manager.set_character_emotion(
                char, emotion, intensity,
                duration_ticks=duration_ticks,
                current_tick=self._current_tick,
            )
        except TypeError:
            # Backwards-compatible call if EmotionManager does not yet accept the new kwargs
            self.emotion_manager.set_character_emotion(char, emotion, intensity)

    def compute_emotion_from_appraisal(self, char: DynamicEntity, event_type: str) -> Tuple[str, float]:
        return self.emotion_manager.compute_emotion_from_appraisal(char, event_type)

    def get_emotion_action_tendency(self, emotion: str) -> str:
        return self.emotion_manager.get_emotion_action_tendency(emotion)

    def get_emotion_arousal(self, emotion: str) -> str:
        return self.emotion_manager.get_emotion_arousal(emotion)

    def tick_emotion_decay(self, char: DynamicEntity, current_tick: Optional[int] = None):
        """Decay the character's emotion towards neutral over time. Called each epoch."""
        if current_tick is None:
            current_tick = self._current_tick
        if hasattr(self.emotion_manager, 'tick_emotion_decay'):
            try:
                self.emotion_manager.tick_emotion_decay(char, current_tick)
            except Exception:
                pass

    # ==================== DELEGATED BEHAVIOR METHODS ====================

    def get_behavior_graph(self, char: DynamicEntity) -> Dict[str, Any]:
        return self.behavior_manager.get_behavior_graph(char)

    def get_behavior_state(self, char: DynamicEntity) -> str:
        return self.behavior_manager.get_behavior_state(char)

    def set_behavior_state(self, char: DynamicEntity, state: str):
        self.behavior_manager.set_behavior_state(char, state)

    def get_possible_transitions(self, char: DynamicEntity) -> List[Dict[str, Any]]:
        return self.behavior_manager.get_possible_transitions(char)

    def evaluate_condition(self, condition: str, char: DynamicEntity, status: Dict, flags: Dict) -> bool:
        return self.behavior_manager.evaluate_condition(condition, char, status, flags)

    def select_next_behavior_state(self, char: DynamicEntity) -> Optional[str]:
        return self.behavior_manager.select_next_behavior_state(char)

    # ==================== REASONING STACK METHODS ====================

    def get_reasoning_stack(self, char: DynamicEntity) -> Dict[str, Any]:
        memory = char.get('memory_perception', {})
        return memory.get('reasoning_stack', {})

    def update_reasoning_stack(self, char: DynamicEntity, updates: Dict[str, Any]):
        memory = char.get('memory_perception', {})
        reasoning = memory.get('reasoning_stack', {})
        reasoning.update(updates)
        memory['reasoning_stack'] = reasoning
        char.set('memory_perception', memory)

    def get_current_goal(self, char: DynamicEntity) -> str:
        return self.get_reasoning_stack(char).get('current_goal', 'survival')

    # ==================== GOAL MANAGEMENT ====================

    def update_goal_based_on_status(self, char: DynamicEntity):
        """
        Re-evaluate the character's current goal when its persistence window expires.
        Uses weighted random selection across all goals whose triggers are satisfied,
        so that lower-priority goals still surface occasionally instead of being
        permanently shadowed by higher-priority ones.
        """
        status = char.get('status_variables', {})
        reasoning = self.get_reasoning_stack(char)
        if not status:
            return

        current_tick = self._current_tick
        current_goal = reasoning.get('current_goal', 'survival')
        goal_expires_at = reasoning.get('goal_expires_at', 0)

        # Do nothing while the current goal is still within its persistence window.
        if current_tick < goal_expires_at:
            return

        goal_hierarchy = self.vocab.get('goal_hierarchy', {})
        if not goal_hierarchy:
            return

        # ---- Build derived conditions once and inject them into the character ----
        # This lets condition expressions such as "has_allies" or "resources_excess"
        # resolve against pre-computed booleans instead of failing silently.
        derived = {
            'has_allies': self._compute_has_allies(char),
            'enemy_nearby': self._compute_enemy_nearby(char),
            'resources_excess': len(char.get('contained_objects', [])) > 3,
            'safe': self.get_global_flag('safe', True),
        }
        char.set('_derived', derived)

        flags = self.world_states.get('persistent_flags', {})

        # ---- Collect candidate goals with a weight ----
        candidates = []  # list of (goal_name, weight, config)
        for goal, config in goal_hierarchy.items():
            triggers = config.get('triggers', [])
            priority = config.get('priority', 10) or 10
            matched = 0
            for t in triggers:
                try:
                    if self.evaluate_condition(t, char, status, flags):
                        matched += 1
                except Exception:
                    continue
            if matched > 0:
                weight = (matched ** 2) / priority
                candidates.append((goal, weight, config))

        if not candidates:
            # No trigger is satisfied; keep the current goal but give it a short
            # extension so we do not re-evaluate on every single tick.
            self.update_reasoning_stack(char, {
                'goal_expires_at': current_tick + 5
            })
            return

        # ---- Weighted random selection ----
        total_weight = sum(w for _, w, _ in candidates)
        if total_weight <= 0:
            return

        r = random.random() * total_weight
        acc = 0.0
        chosen_goal = candidates[-1][0]
        chosen_config = candidates[-1][2]
        for goal, w, config in candidates:
            acc += w
            if r <= acc:
                chosen_goal = goal
                chosen_config = config
                break

        # ---- Duration lookup with sanity checks ----
        min_dur = chosen_config.get('min_duration_ticks', 10)
        max_dur = chosen_config.get('max_duration_ticks', 720)
        if max_dur < min_dur:
            min_dur, max_dur = max_dur, min_dur
        duration = random.randint(min_dur, max_dur)

        # ---- Apply ----
        if chosen_goal != current_goal:
            history = reasoning.get('goal_history', [])
            history.append({
                'from': current_goal,
                'to': chosen_goal,
                'tick': current_tick,
                'duration_ticks': duration,
            })
            self.update_reasoning_stack(char, {
                'current_goal': chosen_goal,
                'goal_expires_at': current_tick + duration,
                'goal_history': history[-20:],
            })
        else:
            self.update_reasoning_stack(char, {
                'goal_expires_at': current_tick + duration,
            })

    # ==================== DERIVED CONDITION HELPERS ====================

    def _compute_has_allies(self, char: DynamicEntity) -> bool:
        """
        Return True if the character has at least one trusted ally in the
        character relationship graph (trust above the alliance threshold).
        """
        name = char.get('name')
        if not name:
            return False
        graph = self.get_character_relationship_graph()
        trust_map = self.get_reasoning_stack(char).get('trust_scores', {})
        for edge in graph.get('edges', []):
            other = None
            if edge.get('from') == name:
                other = edge.get('to')
            elif edge.get('to') == name:
                other = edge.get('from')
            if not other:
                continue
            trust = trust_map.get(other, edge.get('trust', 0.0))
            rel_type = edge.get('type', 'neutral')
            if rel_type == 'ally' and trust >= 0.6:
                return True
            if trust >= 0.7:
                return True
        return False

    def _compute_enemy_nearby(self, char: DynamicEntity) -> bool:
        """
        Return True if the character has an enemy/rival relationship with a
        character currently in the same location.
        """
        name = char.get('name')
        if not name:
            return False
        current_loc = char.get('navigation', {}).get('current_location')
        if not current_loc:
            return False
        graph = self.get_character_relationship_graph()
        edges = graph.get('edges', [])
        for other in self.characters.get_all():
            other_name = other.get('name')
            if not other_name or other_name == name:
                continue
            other_loc = other.get('navigation', {}).get('current_location')
            if other_loc != current_loc:
                continue
            for edge in edges:
                if (edge.get('from') == name and edge.get('to') == other_name) or \
                   (edge.get('from') == other_name and edge.get('to') == name):
                    if edge.get('type') in ('enemy', 'rival'):
                        return True
        return False

    # ==================== SOCIAL REASONING METHODS ====================

    def get_action_catalog(self) -> List[str]:
        return self.knowledge_base.get('action_catalog', [])

    def get_reasoning_config(self) -> Dict[str, Any]:
        return self.knowledge_base.get('reasoning_config', {})

    def validate_action(self, action: str) -> bool:
        catalog = self.get_action_catalog()
        return action in catalog if catalog else True

    def schwartz_evaluate_motivation(self, char: DynamicEntity, action: str) -> float:
        social_attrs = char.get('social_attributes', {})
        schwartz_values = social_attrs.get('schwartz_values', {})
        motor = SchwartzValueMotor()
        if schwartz_values:
            motor.motivational_weights.update(schwartz_values)
        return motor.evaluate_motivation(action)

    def ostrom_compute_normative_utility(self, char: DynamicEntity, action: str) -> float:
        motor = OstromGovernanceMotor()
        reasoning_config = self.get_reasoning_config()
        if 'ostrom_weights' in reasoning_config:
            motor.institutional_weights = reasoning_config['ostrom_weights']
        if 'ostrom_sanctions' in reasoning_config:
            motor.sanction_probabilities = reasoning_config['ostrom_sanctions']
        compliance_scores = {"rule_1": 1.0, "rule_2": 1.0}
        return motor.compute_normative_utility(action, compliance_scores)

    def montes_sierra_compute_deception_penalty(self, char: DynamicEntity) -> float:
        motor = MontesSierraBeliefMotor()
        reasoning_config = self.get_reasoning_config()
        if 'beliefs' in reasoning_config:
            motor.first_order_beliefs = reasoning_config['beliefs']
        if 'peer_beliefs' in reasoning_config:
            motor.inferred_peer_beliefs = reasoning_config['peer_beliefs']
        if 'discrepancy_flag' in reasoning_config:
            motor.communication_discrepancy_flag = reasoning_config['discrepancy_flag']
        return motor.compute_deception_penalty()

    def compute_shapley_coalition(self, char: DynamicEntity, allies: List[str]) -> float:
        if not allies:
            return 0.0
        total = sum(self.get_trust_score(char.get('name', ''), ally) for ally in allies)
        return total / len(allies) if allies else 0.0

    def get_trust_score(self, char1: str, char2: str) -> float:
        relationship = self.get_relationship_between(char1, char2)
        return relationship.get('trust', 0.5) if relationship else 0.5

    def get_relationship_between(self, char1: str, char2: str) -> Optional[Dict[str, Any]]:
        graph = self.get_character_relationship_graph()
        for edge in graph.get('edges', []):
            if (edge.get('from') == char1 and edge.get('to') == char2) or \
               (edge.get('from') == char2 and edge.get('to') == char1):
                return edge
        return None

    def get_character_relationship_graph(self) -> Dict[str, Any]:
        return self.knowledge_base.get('character_graph', {'nodes': [], 'edges': []})

    # ==================== PRINTING / SUMMARY ====================

    def print_characters_summary(self):
        print("\n" + "=" * 70)
        print("CHARACTERS SUMMARY")
        print("=" * 70)
        chars = self.characters.get_all()
        if not chars:
            print("  No characters loaded.")
            return
        for char in chars:
            name = char.get('name', 'Unknown')
            emotion = self.get_character_emotion(char)
            state = char.get('ai_state', 'IDLE')
            status = char.get('status_variables', {})
            health = status.get('health', '?')
            stamina = status.get('stamina', '?')
            morale = status.get('morale', '?')
            faction = char.get('social_attributes', {}).get('faction', 'Unknown')
            goal = self.get_current_goal(char)
            print(f"\n  {name} [{state}]")
            print(f"    Emotion: {emotion} | Goal: {goal}")
            print(f"    Health: {health} | Stamina: {stamina} | Morale: {morale}")
            print(f"    Faction: {faction}")
        print("=" * 70)

    def print_objects_summary(self):
        print("\n" + "=" * 70)
        print("OBJECTS SUMMARY")
        print("=" * 70)
        objs = self.objects.get_all()
        if not objs:
            print("  No objects loaded.")
            return
        for obj in objs:
            name = obj.get('name', 'Unknown')
            obj_vars = obj.get('object_variables', {})
            durability = obj_vars.get('durability', '?')
            value = obj_vars.get('value', '?')
            print(f"\n  {name}")
            print(f"    Durability: {durability} | Value: {value}")
        print("=" * 70)

    def print_corpus_summary(self):
        self.corpus_loader.print_corpus_summary()

    def print_emotion_summary(self):
        print("\n" + "=" * 70)
        print("EMOTION SUMMARY (Ekman Model)")
        print("=" * 70)
        emotion_counts = {e: 0 for e in self.emotion_manager.ekman_emotions}
        active_count = 0
        total = 0
        for char in self.characters.get_all():
            emotion = self.get_character_emotion(char)
            if emotion in emotion_counts:
                emotion_counts[emotion] += 1
                total += 1
            status = char.get('status_variables', {})
            if status.get('emotion_expires_at', 0) > self._current_tick:
                active_count += 1

        print(f"\n  Total Characters: {total}")
        print(f"  Active emotions (not yet decayed): {active_count}")
        print("\n  Emotion Distribution:")
        for emotion, count in emotion_counts.items():
            if count > 0:
                bar = "=" * int((count / max(1, total)) * 50)
                print(f"    {emotion:10} {bar} {count}")
            else:
                print(f"    {emotion:10} {0}")
        print("=" * 70)

    def print_goal_summary(self):
        print("\n" + "=" * 70)
        print("GOAL SUMMARY")
        print("=" * 70)
        goal_counts = {}
        for char in self.characters.get_all():
            goal = self.get_current_goal(char)
            goal_counts[goal] = goal_counts.get(goal, 0) + 1
        total = sum(goal_counts.values()) or 1
        for goal, count in sorted(goal_counts.items(), key=lambda x: -x[1]):
            bar = "=" * int((count / total) * 50)
            print(f"    {goal:25} {bar} {count}")
        print("=" * 70)

    def print_reasoning_summary(self):
        print("\n" + "=" * 70)
        print("SOCIAL REASONING SUMMARY")
        print("=" * 70)
        reasoning_config = self.get_reasoning_config()
        schwartz = reasoning_config.get('schwartz_weights', {})
        if schwartz:
            for key, value in schwartz.items():
                bar = "=" * int(value * 10)
                print(f"  {key:15} [{value:.1f}] {bar}")
        print("=" * 70)

    def print_action_catalog(self):
        print("\n" + "=" * 70)
        print("ACTION CATALOG")
        print("=" * 70)
        catalog = self.get_action_catalog()
        if catalog:
            for i, action in enumerate(catalog, 1):
                print(f"  {i}. {action}")
        else:
            print("  (No action catalog loaded)")
        print("=" * 70)

    def visualize_all(self):
        self.print_corpus_summary()
        self.print_characters_summary()
        self.print_objects_summary()
        self.print_action_catalog()
        self.print_emotion_summary()
        self.print_goal_summary()
        self.print_reasoning_summary()

    def close(self):
        self._stop_logging()


# ==========================================
# MAIN - Direct Execution Block
# ==========================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Simulated World Module')
    parser.add_argument('--world', type=str, help='World folder to load')
    parser.add_argument('--characters', type=str, help='Characters file path')
    parser.add_argument('--objects', type=str, help='Objects file path')
    parser.add_argument('--scenes', type=str, help='Scenes file path')
    parser.add_argument('--rules', type=str, help='Rules file path')
    parser.add_argument('--world-states', type=str, help='World states file path')
    parser.add_argument('--knowledge', type=str, help='Knowledge base file path')
    parser.add_argument('--action-catalog', type=str, help='Action catalog file path')
    parser.add_argument('--character-graph', type=str, help='Character graph file path')
    parser.add_argument('--condition-registry', type=str, help='Condition registry file path')
    parser.add_argument('--vocab', type=str, default='world_vocabulary.json', help='Vocabulary file')
    parser.add_argument('--reasoning', type=str, default='reasoning_tests.json', help='Reasoning tests file')
    parser.add_argument('--no-viz', action='store_true', help='Skip visualization')
    parser.add_argument('--summary', action='store_true', help='Print summary only')
    parser.add_argument('--no-log', action='store_true', help='Disable logging to file')
    parser.add_argument('--log-filename', type=str, default='world_summary.log', help='Log filename')
    args = parser.parse_args()

    if args.world:
        base = args.world
        characters_file = os.path.join(base, "characters.json")
        objects_file = os.path.join(base, "objects.json")
        scenes_file = os.path.join(base, "scenes.json")
        rules_file = os.path.join(base, "rules.json")
        world_states_file = os.path.join(base, "world_states.json")
        knowledge_file = os.path.join(base, "knowledge_base.json")
        action_catalog_file = os.path.join(base, "action_catalog.json")
        character_graph_file = os.path.join(base, "character_graph.json")
        condition_registry_file = os.path.join(base, "condition_registry.json")
    else:
        characters_file = args.characters or "characters.json"
        objects_file = args.objects or "objects.json"
        scenes_file = args.scenes or "scenes.json"
        rules_file = args.rules or "rules.json"
        world_states_file = args.world_states or "world_states.json"
        knowledge_file = args.knowledge or "knowledge_base.json"
        action_catalog_file = args.action_catalog or "action_catalog.json"
        character_graph_file = args.character_graph or "character_graph.json"
        condition_registry_file = args.condition_registry or "condition_registry.json"

    print("Creating Simulated World...")

    world = SimulatedWorldModule(
        characters_file=characters_file,
        objects_file=objects_file,
        scenes_file=scenes_file,
        rules_file=rules_file,
        world_states_file=world_states_file,
        knowledge_file=knowledge_file,
        action_catalog_file=action_catalog_file,
        character_graph_file=character_graph_file,
        condition_registry_file=condition_registry_file,
        vocab_file=args.vocab,
        reasoning_config=args.reasoning,
        log_to_file=not args.no_log,
        log_filename=args.log_filename
    )

    try:
        if args.summary:
            world.print_corpus_summary()
            world.print_reasoning_summary()
            world.print_action_catalog()
            world.print_goal_summary()
        elif not args.no_viz:
            world.visualize_all()
    finally:
        world.close()

    if not args.no_log and world.log_filepath:
        print(f"\n[OK] Summary saved to: {world.log_filepath}")


if __name__ == "__main__":
    main()