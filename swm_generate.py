#!/usr/bin/env python3
"""
SWM Knowledge Base Generator - Generate new JSON knowledge bases from name files and templates
All configuration from JSON, no hardcoding
"""

import json
import os
import random
import time
from typing import Dict, List, Any
from copy import deepcopy
from datetime import datetime


class TemplateEngine:
    """Template engine that resolves value specifications from JSON templates"""

    def __init__(self, generator):
        self.generator = generator

    def resolve(self, spec: Any, context: Dict[str, Any]) -> Any:
        """Resolve a value specification from the template"""
        if spec is None:
            return None

        if not isinstance(spec, dict):
            return spec

        spec_type = spec.get('type')

        if spec_type == 'constant':
            return spec.get('value')

        elif spec_type == 'random_int':
            return random.randint(spec.get('min', 0), spec.get('max', 10))

        elif spec_type == 'random_float':
            decimals = spec.get('decimals', 0)
            value = random.uniform(spec.get('min', 0.0), spec.get('max', 1.0))
            return round(value, decimals) if decimals > 0 else value

        elif spec_type == 'random_choice':
            values = spec.get('values')
            if not values:
                source = spec.get('source')
                if source:
                    values = self.generator._get_vocab(source)
            if not values:
                return None
            return random.choice(values)

        elif spec_type == 'random_sample':
            source = spec.get('source')
            if source:
                values = self.generator._get_vocab(source)
            else:
                values = spec.get('values', [])
            if not values:
                return []
            min_count = spec.get('min', 0)
            max_count = spec.get('max', len(values))
            count = random.randint(min_count, min(max_count, len(values)))
            return random.sample(values, count)

        elif spec_type == 'random_relationships':
            source = spec.get('source')
            if source:
                names = self.generator._get_vocab(source)
            else:
                names = spec.get('values', [])
            if not names:
                return {}

            max_count = spec.get('max_count', 4)
            exclude = context.get('exclude_name', '')

            available = [n for n in names if n != exclude]
            if not available:
                return {}

            count = random.randint(0, min(max_count, len(available)))
            selected = random.sample(available, count) if count > 0 else []

            relationships = {}
            for name in selected:
                # Use weighted random for relationship values (0-100)
                relationship_value = random.choices(
                    population=[random.randint(0, 30), random.randint(31, 70), random.randint(71, 100)],
                    weights=[0.2, 0.5, 0.3]
                )[0]
                relationships[name] = relationship_value
            return relationships

        elif spec_type == 'random_region_name':
            source = spec.get('source')
            if source:
                names = self.generator._get_vocab(source)
            else:
                names = self.generator.character_names

            if not names or len(names) == 0:
                names = ["Eldoria"]

            name = random.choice(names) if names else "Eldoria"
            prefixes = ['Kingdom', 'Empire', 'Land', 'Realm', 'Province', 'Domain']
            return f"{random.choice(prefixes)} of {name}"

        elif spec_type == 'random_description':
            source = spec.get('source')
            if source:
                types = self.generator._get_vocab(source)
            else:
                types = ['mysterious']

            if not types:
                types = ['mysterious']

            scene_type = random.choice(types)
            adjectives = ['ancient', 'mysterious', 'dark', 'enchanted', 'forgotten']
            return f"A {random.choice(adjectives)} {scene_type} realm with secrets."

        elif spec_type == 'random_building_name':
            source = spec.get('source')
            if source:
                names = self.generator._get_vocab(source)
            else:
                names = ['Keep']

            if not names:
                names = ['Keep']

            return f"{random.choice(names)} Keep"

        elif spec_type == 'current_timestamp':
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        elif spec_type == 'reference':
            path = spec.get('path', '')
            return self._resolve_path(path, context)

        elif spec_type == 'generate_zones':
            return self._generate_zones(spec, context)

        elif spec_type == 'generate_waypoints':
            return self._generate_waypoints(spec, context)

        elif spec_type == 'generate_spawns':
            return self._generate_spawns(spec, context)

        elif spec_type == 'generate_objects':
            return self._generate_scene_objects(spec, context)

        else:
            return spec

    def _resolve_path(self, path: str, context: Dict[str, Any]) -> Any:
        """Resolve a path in the context"""
        parts = path.split('.')
        current = context
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _generate_zones(self, spec: Dict[str, Any], context: Dict[str, Any]) -> List[Dict]:
        """Generate zones from template with connections"""
        count_spec = spec.get('count', {'min': 2, 'max': 6})
        count = self.resolve(count_spec, context)
        if count is None:
            count = random.randint(2, 6)

        template = spec.get('template', {})

        zones = []
        zone_ids = []
        for i in range(count):
            zone = {}
            for key, value in template.items():
                if key == 'zone_id' and isinstance(value, str):
                    zone[key] = value.replace('{index}', f'{i+1:03d}')
                elif isinstance(value, str) and '{index' in value:
                    zone[key] = value.replace('{index}', f'{i+1:03d}')
                else:
                    resolved = self.resolve(value, {'index': i + 1})
                    if resolved is not None:
                        zone[key] = resolved
                    elif isinstance(value, (str, int, float, bool)):
                        zone[key] = value
            zones.append(zone)
            zone_ids.append(zone.get('zone_id', f'ZONE_{i+1:03d}'))

        # Add zone names from locations
        location_names = self.generator._get_vocab('locations', ['Unknown'])
        for i, zone in enumerate(zones):
            if 'name' not in zone or zone['name'] is None:
                zone['name'] = random.choice(location_names) if location_names else f"Zone_{i+1}"

        context['zone_ids'] = zone_ids
        context['zones'] = zones
        context['zones.count'] = count
        return zones

    def _generate_waypoints(self, spec: Dict[str, Any], context: Dict[str, Any]) -> List[Dict]:
        """Generate waypoints from template"""
        count_spec = spec.get('count', {'min': 3, 'max': 8})
        count = self.resolve(count_spec, context)
        if count is None:
            count = random.randint(3, 8)

        template = spec.get('template', {})

        waypoints = []
        waypoint_ids = []
        zone_ids = context.get('zone_ids', [])

        for i in range(count):
            waypoint_context = {
                'index': i + 1,
                'zone_ids': zone_ids
            }
            waypoint = {}
            for key, value in template.items():
                if isinstance(value, str) and '{index' in value:
                    waypoint[key] = value.replace('{index}', f'{i+1:03d}')
                else:
                    resolved = self.resolve(value, waypoint_context)
                    if resolved is not None:
                        waypoint[key] = resolved
                    else:
                        waypoint[key] = value if isinstance(value, (str, int, float, bool)) else None

            if zone_ids and 'zone_id' in waypoint:
                waypoint['zone_id'] = random.choice(zone_ids)
            elif zone_ids:
                waypoint['zone_id'] = random.choice(zone_ids)

            waypoints.append(waypoint)
            waypoint_ids.append(waypoint.get('waypoint_id'))

        context['waypoint_ids'] = waypoint_ids
        context['waypoints'] = waypoints
        context['waypoints.count'] = count
        return waypoints

    def _generate_spawns(self, spec: Dict[str, Any], context: Dict[str, Any]) -> List[Dict]:
        """Generate spawns from template"""
        count_spec = spec.get('count', {'min': 2, 'max': 5})
        count = self.resolve(count_spec, context)
        if count is None:
            count = random.randint(2, 5)

        template = spec.get('template', {})

        spawns = []
        for i in range(count):
            spawn_context = {
                'index': i + 1,
                'zone_ids': context.get('zone_ids', []),
                'waypoint_ids': context.get('waypoint_ids', [])
            }
            spawn = {}
            for key, value in template.items():
                if isinstance(value, str) and '{index' in value:
                    if 'entity_id' in key or 'spawn_id' in key:
                        spawn[key] = value.replace('{index}', f'{i+1:04d}')
                    else:
                        spawn[key] = value.replace('{index}', f'{i+1:03d}')
                else:
                    resolved = self.resolve(value, spawn_context)
                    if resolved is not None:
                        spawn[key] = resolved
                    else:
                        spawn[key] = value if isinstance(value, (str, int, float, bool)) else None
            spawns.append(spawn)

        return spawns

    def _generate_scene_objects(self, spec: Dict[str, Any], context: Dict[str, Any]) -> List[Dict]:
        """Generate scene objects from template"""
        count_spec = spec.get('count', {'min': 3, 'max': 8})
        count = self.resolve(count_spec, context)
        if count is None:
            count = random.randint(3, 8)

        template = spec.get('template', {})

        objects = []
        for i in range(count):
            obj_context = {
                'index': i + 1,
                'zone_ids': context.get('zone_ids', []),
                'waypoint_ids': context.get('waypoint_ids', [])
            }
            obj = {}
            for key, value in template.items():
                if isinstance(value, str) and '{index' in value:
                    obj[key] = value.replace('{index}', f'{i+1:04d}')
                else:
                    resolved = self.resolve(value, obj_context)
                    if resolved is not None:
                        obj[key] = resolved
                    else:
                        obj[key] = value if isinstance(value, (str, int, float, bool)) else None
            objects.append(obj)

        return objects

    def build(self, template: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Build an object from a template with context"""
        result = {}
        for key, value in template.items():
            if isinstance(value, dict):
                if 'type' in value or any(k in value for k in ['min', 'max', 'source', 'values']):
                    result[key] = self.resolve(value, context)
                else:
                    result[key] = self.build(value, context)
            elif isinstance(value, list):
                result[key] = []
                for item in value:
                    if isinstance(item, dict):
                        result[key].append(self.build(item, context))
                    else:
                        result[key].append(item)
            else:
                if isinstance(value, str) and '{' in value:
                    try:
                        result[key] = value.format(**context)
                    except KeyError:
                        result[key] = value
                else:
                    result[key] = value
        return result


class KnowledgeBaseGenerator:
    """Generate knowledge bases from templates"""

    def __init__(self, config_file: str = "generation_config.json", output_folder: str = None):
        self.config = self._load_config(config_file)
        self._load_name_files()
        self._load_vocabulary()
        self.template_engine = TemplateEngine(self)
        self.output_folder = output_folder
        self.world_folder = None

        # Load condition registry from vocab
        self.condition_registry = self.vocab.get('condition_registry', {})

        # ---- Per-run uniqueness registries -------------------------------
        # These ensure that when a name is drawn more than once we append a
        # numeric suffix ("Gandalf", "Gandalf2", "Gandalf3", ...). The
        # registries live on the generator instance, so a single
        # generate_knowledge_base() call produces a self-consistent world.
        self._used_character_names: set = set()
        self._used_object_names: set = set()
        self._used_scene_names: set = set()

        print("[OK] Knowledge Base Generator initialized")
        print(f"  Loaded {len(self.character_names)} character names")
        print(f"  Loaded {len(self.object_names)} object names")
        print(f"  Loaded {len(self.scene_names)} scene names")
        print(f"  Loaded {len(self.condition_registry)} conditions from registry")

    # ------------------------------------------------------------------
    # Unique-name helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _unique_name(base_name: str, used: set) -> str:
        """Return a name that is not in `used`, adding 2, 3, 4, ... as needed.

        The returned name is added to `used`.
        """
        if base_name not in used:
            used.add(base_name)
            return base_name
        i = 2
        while f"{base_name}{i}" in used:
            i += 1
        new_name = f"{base_name}{i}"
        used.add(new_name)
        return new_name

    def reset_name_pools(self):
        """Clear the per-run uniqueness registries.

        Call this if you want to generate a brand-new world with the same
        generator instance and allow base names to be reused from scratch.
        """
        self._used_character_names.clear()
        self._used_object_names.clear()
        self._used_scene_names.clear()

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from JSON"""
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load {config_file}: {e}")
                return {}
        else:
            print(f"[WARNING] {config_file} not found, using minimal defaults")
            return self._get_minimal_config()

    def _get_minimal_config(self) -> Dict[str, Any]:
        """Return minimal configuration if file doesn't exist"""
        return {
            "data_sources": {
                "character_names": "characters_names.txt",
                "object_names": "objects_names.txt",
                "scene_names": "scenes_names.txt"
            },
            "character_template": {},
            "object_template": {},
            "scene_template": {},
            "world_states_template": {},
            "action_catalog": ["IDLE_WAIT"]
        }

    def _load_name_files(self):
        """Load names from text files"""
        data_sources = self.config.get('data_sources', {})

        char_file = data_sources.get('character_names', 'characters_names.txt')
        if os.path.exists(char_file):
            with open(char_file, 'r', encoding='utf-8') as f:
                self.character_names = [line.strip() for line in f if line.strip()]
            print(f"[OK] Loaded {len(self.character_names)} character names from {char_file}")
        else:
            print(f"[WARNING] {char_file} not found, using defaults")
            self.character_names = ["Arthur", "Eleanor", "Gareth"]

        obj_file = data_sources.get('object_names', 'objects_names.txt')
        if os.path.exists(obj_file):
            with open(obj_file, 'r', encoding='utf-8') as f:
                self.object_names = [line.strip() for line in f if line.strip()]
            print(f"[OK] Loaded {len(self.object_names)} object names from {obj_file}")
        else:
            print(f"[WARNING] {obj_file} not found, using defaults")
            self.object_names = ["Sword", "Shield", "Dagger"]

        scene_file = data_sources.get('scene_names', 'scenes_names.txt')
        if os.path.exists(scene_file):
            with open(scene_file, 'r', encoding='utf-8') as f:
                self.scene_names = [line.strip() for line in f if line.strip()]
            print(f"[OK] Loaded {len(self.scene_names)} scene names from {scene_file}")
        else:
            print(f"[WARNING] {scene_file} not found, using defaults")
            self.scene_names = ["Castle", "Forest", "Dungeon"]

    def _load_vocabulary(self):
        """Load vocabulary from world_vocabulary.json"""
        self._vocab_cache = {}
        if os.path.exists("world_vocabulary.json"):
            try:
                with open("world_vocabulary.json", 'r', encoding='utf-8') as f:
                    self._vocab_cache = json.load(f)
                self.vocab = self._vocab_cache
                print("[OK] Loaded vocabulary from world_vocabulary.json")
            except Exception as e:
                print(f"[WARNING] Failed to load world_vocabulary.json: {e}")
                self.vocab = {}
        else:
            print("[WARNING] world_vocabulary.json not found")
            self.vocab = {}

    def _get_vocab(self, key: str, default: list = None) -> list:
        """Get a vocabulary list from world_vocabulary.json"""
        if default is None:
            default = []

        if key == 'character_names':
            return self.character_names
        if key == 'object_names':
            return self.object_names
        if key == 'scene_names':
            return self.scene_names

        return self._vocab_cache.get(key, default)

    def _generate_behavior_graph(self, character_name: str) -> Dict[str, Any]:
        """Generate a behavior graph for a character based on config"""
        # Get behavior graph from rules template
        rules_template = self.config.get('rules_template', [])
        behavior_graph = None

        for rule in rules_template:
            if rule.get('type') == 'behavior_graph':
                behavior_graph = {
                    'nodes': rule.get('graph_nodes', []),
                    'edges': rule.get('graph_edges', [])
                }
                break

        # If no behavior graph in rules, use default
        if not behavior_graph:
            behavior_graph = {
                "nodes": [
                    {"id": "idle", "type": "state", "priority": 0, "description": "Default resting state"},
                    {"id": "explore", "type": "state", "priority": 1, "description": "Exploring the environment"},
                    {"id": "socialize", "type": "state", "priority": 2, "description": "Interacting with others"},
                    {"id": "gather", "type": "state", "priority": 3, "description": "Gathering resources"},
                    {"id": "combat", "type": "state", "priority": 4, "description": "Engaging in combat"},
                    {"id": "rest", "type": "state", "priority": 0, "description": "Resting to recover"},
                    {"id": "flee", "type": "state", "priority": 0, "description": "Fleeing from danger"},
                    {"id": "share", "type": "state", "priority": 2, "description": "Sharing with allies"}
                ],
                "edges": [
                    {"from": "idle", "to": "explore", "weight": 0.3, "condition": "stamina > 50 AND emotional_state != sadness AND emotional_state != fear"},
                    {"from": "idle", "to": "socialize", "weight": 0.2, "condition": "morale > 40 AND emotional_state == joy"},
                    {"from": "idle", "to": "rest", "weight": 0.5, "condition": "stamina < 30 OR emotional_state == sadness"},
                    {"from": "explore", "to": "gather", "weight": 0.4, "condition": "hunger > 50 OR thirst > 50"},
                    {"from": "explore", "to": "combat", "weight": 0.15, "condition": "health > 60 AND emotional_state == anger AND enemy_nearby"},
                    {"from": "explore", "to": "idle", "weight": 0.3, "condition": "stamina < 40"},
                    {"from": "socialize", "to": "gather", "weight": 0.3, "condition": "has_allies AND cooperativeness > 0.6"},
                    {"from": "socialize", "to": "share", "weight": 0.2, "condition": "has_allies AND benevolence > 0.7"},
                    {"from": "socialize", "to": "idle", "weight": 0.4, "condition": "true"},
                    {"from": "gather", "to": "share", "weight": 0.2, "condition": "resources_excess AND cooperativeness > 0.5"},
                    {"from": "gather", "to": "idle", "weight": 0.3, "condition": "true"},
                    {"from": "gather", "to": "combat", "weight": 0.25, "condition": "enemy_nearby AND emotional_state == anger"},
                    {"from": "combat", "to": "flee", "weight": 0.3, "condition": "health < 30 OR emotional_state == fear"},
                    {"from": "combat", "to": "idle", "weight": 0.3, "condition": "enemy_defeated"},
                    {"from": "combat", "to": "rest", "weight": 0.2, "condition": "stamina < 20"},
                    {"from": "rest", "to": "idle", "weight": 0.7, "condition": "stamina > 80 AND emotional_state != sadness"},
                    {"from": "rest", "to": "socialize", "weight": 0.1, "condition": "morale < 30 AND emotional_state == sadness"},
                    {"from": "flee", "to": "rest", "weight": 0.5, "condition": "stamina < 30"},
                    {"from": "flee", "to": "idle", "weight": 0.5, "condition": "safe"},
                    {"from": "share", "to": "socialize", "weight": 0.5, "condition": "true"},
                    {"from": "share", "to": "idle", "weight": 0.3, "condition": "stamina < 40"}
                ],
                "transition_rules": [
                    {"from": "idle", "to": "gather", "weight": 0.3, "condition": "(hunger > 60 OR thirst > 60) AND stamina > 40"},
                    {"from": "idle", "to": "flee", "weight": 0.8, "condition": "emotional_state == fear AND threat_nearby"},
                    {"from": "idle", "to": "combat", "weight": 0.7, "condition": "emotional_state == anger AND enemy_nearby"},
                    {"from": "socialize", "to": "combat", "weight": 0.15, "condition": "ally_attacked AND emotional_state == anger"},
                    {"from": "rest", "to": "explore", "weight": 0.3, "condition": "stamina > 70 AND emotional_state != sadness"},
                    {"from": "explore", "to": "socialize", "weight": 0.2, "condition": "emotional_state == joy AND morale > 60"},
                    {"from": "gather", "to": "share", "weight": 0.25, "condition": "resources_excess AND cooperativeness > 0.6"},
                    {"from": "share", "to": "socialize", "weight": 0.6, "condition": "morale > 50 AND emotional_state == joy"}
                ]
            }

        return behavior_graph

    def _generate_character_graphs(self, characters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate character relationship graph"""
        graph = {
            "nodes": [],
            "edges": []
        }

        # Add all characters as nodes
        for char in characters:
            name = char.get('name', 'Unknown')
            faction = char.get('social_attributes', {}).get('faction', 'Unknown')
            alignment = char.get('social_attributes', {}).get('alignment', 'Unknown')

            # Get Schwartz values
            schwartz = char.get('social_attributes', {}).get('schwartz_values', {})

            graph["nodes"].append({
                "id": name,
                "type": "character",
                "faction": faction,
                "alignment": alignment,
                "schwartz_values": schwartz
            })

        # Generate edges based on factions and random relationships
        for i, char1 in enumerate(characters):
            name1 = char1.get('name', 'Unknown')
            faction1 = char1.get('social_attributes', {}).get('faction', 'Unknown')
            schwartz1 = char1.get('social_attributes', {}).get('schwartz_values', {})

            for j, char2 in enumerate(characters):
                if i >= j:
                    continue

                name2 = char2.get('name', 'Unknown')
                faction2 = char2.get('social_attributes', {}).get('faction', 'Unknown')
                schwartz2 = char2.get('social_attributes', {}).get('schwartz_values', {})

                # Calculate similarity based on Schwartz values (if available)
                similarity = 0.5
                if schwartz1 and schwartz2:
                    common_values = set(schwartz1.keys()) & set(schwartz2.keys())
                    if common_values:
                        diff_sum = sum(abs(schwartz1.get(v, 0) - schwartz2.get(v, 0)) for v in common_values)
                        similarity = 1.0 - (diff_sum / (len(common_values) * 2))

                # Same faction: higher chance of positive relationship
                if faction1 == faction2:
                    weight = random.uniform(0.5, 0.9) * similarity
                    relationship_type = random.choices(
                        ['ally', 'friend', 'neutral', 'rival'],
                        weights=[0.3, 0.4, 0.2, 0.1]
                    )[0]
                else:
                    weight = random.uniform(0.1, 0.7) * similarity
                    relationship_type = random.choices(
                        ['neutral', 'rival', 'enemy', 'ally'],
                        weights=[0.3, 0.3, 0.2, 0.2]
                    )[0]

                # Calculate trust based on similarity and relationship type
                trust_base = {
                    'ally': 0.8,
                    'friend': 0.7,
                    'neutral': 0.5,
                    'rival': 0.3,
                    'enemy': 0.1
                }.get(relationship_type, 0.5)

                trust = round((trust_base * 0.7 + similarity * 0.3), 2)

                graph["edges"].append({
                    "from": name1,
                    "to": name2,
                    "weight": round(weight, 2),
                    "type": relationship_type,
                    "trust": trust,
                    "similarity": round(similarity, 2)
                })

        return graph

    def generate_character(self, name: str = None) -> Dict[str, Any]:
        """Generate a character from template.

        If `name` is None, a name is drawn from the character name pool and
        passed through _unique_name() so that duplicates get a numeric
        suffix (e.g. "Gandalf", "Gandalf2", "Gandalf3"). If `name` is given
        explicitly, it is also passed through _unique_name() so callers can
        request a base name and still get uniqueness.
        """
        base_name = name if name is not None else random.choice(self.character_names)
        name = self._unique_name(base_name, self._used_character_names)
        char_id = f"CHAR_{random.randint(1, 9999):04d}"

        template = self.config.get('character_template', {})
        if not template:
            return {"id": char_id, "name": name}

        context = {
            'id': char_id,
            'name': name,
            'exclude_name': name,
            'character_names': self.character_names,
            'object_names': self.object_names,
            'ekman_emotions': self.vocab.get('ekman_emotions', ['anger', 'fear', 'disgust', 'sadness', 'joy', 'surprise']),
            'ai_states': self.vocab.get('ai_states', ['IDLE', 'PATROLLING', 'RESTING', 'COMBAT', 'FLEEING'])
        }

        character = self.template_engine.build(template, context)
        character['id'] = char_id
        character['name'] = name

        # Generate behavior graph
        character['behavior_graph'] = self._generate_behavior_graph(name)
        character['behavior_graph_id'] = 'default'

        # Ensure reasoning stack exists with proper fields
        if 'memory_perception' not in character:
            character['memory_perception'] = {}
        if 'reasoning_stack' not in character['memory_perception']:
            character['memory_perception']['reasoning_stack'] = {
                "current_goal": random.choice(["survival", "exploration", "social_belonging", "power_achievement", "knowledge_acquisition", "altruism"]),
                "planned_actions": [],
                "decision_history": [],
                "trust_scores": {},
                "emotional_state": random.choice(self.vocab.get('ekman_emotions', ['neutral'])),
                "emotion_intensity": round(random.uniform(0.1, 1.0), 2),
                "risk_tolerance": round(random.uniform(0.1, 0.9), 2),
                "cooperativeness": round(random.uniform(0.1, 0.9), 2),
                "emotional_memory": [],
                "condition_cache": {}
            }

        # Add condition registry reference
        character['condition_registry'] = list(self.condition_registry.keys())

        return character

    def generate_object(self, name: str = None) -> Dict[str, Any]:
        """Generate an object from template.

        Names are uniquified the same way as characters, so repeated object
        names get a numeric suffix.
        """
        base_name = name if name is not None else random.choice(self.object_names)
        name = self._unique_name(base_name, self._used_object_names)
        obj_id = f"OBJ_{random.randint(1, 9999):04d}"

        template = self.config.get('object_template', {})
        if not template:
            return {"id": obj_id, "name": name}

        context = {
            'id': obj_id,
            'name': name,
            'object_names': self.object_names,
            'qualities': self.vocab.get('qualities', ['standard']),
            'materials': self.vocab.get('materials', ['steel']),
            'object_types': self.vocab.get('object_types', ['item']),
            'object_subtypes': self.vocab.get('object_subtypes', ['item'])
        }

        obj = self.template_engine.build(template, context)
        obj['id'] = obj_id
        obj['name'] = name

        return obj

    def generate_scene(self, name: str = None) -> Dict[str, Any]:
        """Generate a scene from template.

        Scene names are uniquified like characters/objects.
        """
        base_name = name if name is not None else random.choice(self.scene_names)
        name = self._unique_name(base_name, self._used_scene_names)

        template = self.config.get('scene_template', {})
        if not template:
            return {"scenes": {"current_scene": name}}

        context = {
            'name': name,
            'scene_name': name,
            'character_names': self.character_names,
            'object_names': self.object_names,
            'scene_names': self.scene_names,
            'locations': self.vocab.get('locations', ['Unknown']),
            'scene_types': self.vocab.get('scene_types', ['interior']),
            'climates': self.vocab.get('climates', ['temperate']),
            'terrain_types': self.vocab.get('terrain_types', ['plains'])
        }

        scene = self.template_engine.build(template, context)

        if 'scenes' in scene:
            scene['scenes']['current_scene'] = name
        else:
            scene = {"scenes": {"current_scene": name, **scene}}

        # Generate scene graph if not present
        if 'scene_graph' not in scene.get('scenes', {}):
            zone_ids = scene.get('scenes', {}).get('zone_ids', [])
            if zone_ids:
                scene_graph = {
                    "nodes": [
                        {"id": zid, "type": "zone", "name": f"Zone_{i+1}"}
                        for i, zid in enumerate(zone_ids)
                    ],
                    "edges": []
                }
                # Connect zones in a chain with conditions
                conditions = ['true', 'door_open', 'has_key', 'boss_defeated']
                for i in range(len(zone_ids) - 1):
                    scene_graph["edges"].append({
                        "from": zone_ids[i],
                        "to": zone_ids[i + 1],
                        "weight": round(random.uniform(0.5, 1.0), 2),
                        "condition": random.choice(conditions),
                        "cost": random.randint(1, 5)
                    })
                scene['scenes']['scene_graph'] = scene_graph

        return scene

    def generate_rules(self) -> List[Dict[str, Any]]:
        """Generate rules from template"""
        template = self.config.get('rules_template', [])
        rules = deepcopy(template) if template else []

        # Add any additional rules from config
        return rules

    def generate_world_states(self, scene_name: str = None) -> Dict[str, Any]:
        """Generate world states from template"""
        scene_name = scene_name or random.choice(self.scene_names)

        template = self.config.get('world_states_template', {})
        if not template:
            return {
                "version": "1.0",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "current_scene": scene_name,
                "current_state": "idle",
                "persistent_flags": {},
                "global_timers": {"day_cycle": 0, "world_time": 0},
                "global_states": {"weather": "clear", "time_of_day": "morning"},
                "object_states": {},
                "player_state": {"health": 100, "stamina": 100}
            }

        context = {
            'scene_name': scene_name,
            'scene_names': self.scene_names,
            'weather': self.vocab.get('weather', ['clear']),
            'time_of_day': self.vocab.get('time_of_day', ['morning']),
            'ekman_emotions': self.vocab.get('ekman_emotions', ['neutral'])
        }

        states = self.template_engine.build(template, context)
        states['current_scene'] = scene_name

        if 'global_timers' not in states:
            states['global_timers'] = {'day_cycle': 0, 'world_time': 0}
        if 'global_states' not in states:
            states['global_states'] = {'weather': 'clear', 'time_of_day': 'morning'}
        if 'persistent_flags' not in states:
            states['persistent_flags'] = {}
        if 'object_states' not in states:
            states['object_states'] = {}
        if 'player_state' not in states:
            states['player_state'] = {'health': 100, 'stamina': 100}

        return states

    def get_action_catalog(self) -> List[str]:
        """Get action catalog from config"""
        return self.config.get('action_catalog', ["IDLE_WAIT"])

    def generate_knowledge_base(self,
                               num_characters: int = 5,
                               num_objects: int = 10,
                               generate_scene: bool = True,
                               generate_rules: bool = True) -> Dict[str, Any]:
        """Generate a complete knowledge base"""
        # Reset uniqueness registries so a fresh call always starts from
        # the base names in the pool. This makes the generator behave the
        # same whether you reuse the instance or not.
        self.reset_name_pools()

        print(f"\nGenerating knowledge base with:")
        print(f"  * {num_characters} characters")
        print(f"  * {num_objects} objects")
        print(f"  * {'Yes' if generate_scene else 'No'} scene")
        print(f"  * {'Yes' if generate_rules else 'No'} rules")

        characters = [self.generate_character() for _ in range(num_characters)]
        objects = [self.generate_object() for _ in range(num_objects)]
        scene_data = self.generate_scene() if generate_scene else {}
        rules = self.generate_rules() if generate_rules else []

        # Generate character relationship graph
        character_graph = self._generate_character_graphs(characters) if characters else {"nodes": [], "edges": []}

        # Add relationship graph to each character's social attributes
        for char in characters:
            if 'social_attributes' not in char:
                char['social_attributes'] = {}
            char['social_attributes']['relationship_graph'] = character_graph

            # Add trust scores to reasoning stack
            memory = char.get('memory_perception', {})
            reasoning = memory.get('reasoning_stack', {})

            # Find relationships for this character
            trust_scores = {}
            for edge in character_graph.get('edges', []):
                if edge.get('from') == char.get('name'):
                    trust_scores[edge.get('to')] = edge.get('trust', 0.5)
                elif edge.get('to') == char.get('name'):
                    trust_scores[edge.get('from')] = edge.get('trust', 0.5)

            reasoning['trust_scores'] = trust_scores
            memory['reasoning_stack'] = reasoning
            char['memory_perception'] = memory

        scene_name = scene_data.get("scenes", {}).get("current_scene", "UNKNOWN") if scene_data else "UNKNOWN"
        world_states = self.generate_world_states(scene_name)

        knowledge_base = {
            "characters": characters,
            "objects": objects,
            "scenes": scene_data,
            "rules": rules,
            "world_states": world_states,
            "action_catalog": self.get_action_catalog(),
            "character_graph": character_graph,
            "condition_registry": self.condition_registry
        }

        print(f"[OK] Generated {len(characters)} characters, {len(objects)} objects")
        # Sanity check: names must be unique now.
        char_names = [c.get('name') for c in characters]
        if len(set(char_names)) != len(char_names):
            print("[WARN] Duplicate character names still present after uniquification!")
            for n in char_names:
                if char_names.count(n) > 1:
                    print(f"       -> {n} x{char_names.count(n)}")
        return knowledge_base

    def save_knowledge_base(self, kb: Dict[str, Any], folder: str = None) -> bool:
        """Save knowledge base to specified folder"""
        target_folder = folder or self.output_folder

        if target_folder:
            os.makedirs(target_folder, exist_ok=True)
            self.world_folder = target_folder
            print(f"\nSaving knowledge base to {target_folder}...")
        else:
            world_timestamp = datetime.now().strftime("%d_%m_%Y-%H_%M_%S")
            target_folder = f"world_{world_timestamp}"
            os.makedirs(target_folder, exist_ok=True)
            self.world_folder = target_folder
            print(f"\nSaving knowledge base to {target_folder}...")

        success = True

        if not self._save_json(kb, os.path.join(target_folder, "knowledge_base.json")):
            success = False

        components = {
            "characters": "characters",
            "objects": "objects",
            "scenes": "scenes",
            "rules": "rules",
            "action_catalog": "action_catalog",
            "character_graph": "character_graph",
            "condition_registry": "condition_registry"
        }

        for key, filename in components.items():
            if key in kb:
                if key == "action_catalog":
                    data = {"action_catalog": kb["action_catalog"]}
                elif key == "character_graph":
                    data = {"character_graph": kb["character_graph"]}
                elif key == "condition_registry":
                    data = {"condition_registry": kb["condition_registry"]}
                else:
                    data = {key: kb[key]}
                if not self._save_json(data, os.path.join(target_folder, f"{filename}.json")):
                    success = False

        if 'world_states' in kb:
            world_data = {"world_states": kb["world_states"]}
            if not self._save_json(world_data, os.path.join(target_folder, "world_states.json")):
                success = False

        if success:
            print(f"[OK] Saved knowledge base to {target_folder}")
        else:
            print("[ERROR] Some files failed to save")

        return success

    def _save_json(self, data: Dict[str, Any], filepath: str) -> bool:
        """Save data to JSON file"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  [OK] Saved to {filepath}")
            return True
        except Exception as e:
            print(f"  [ERROR] Error saving to {filepath}: {e}")
            return False


# ==========================================
# MAIN
# ==========================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='SWM Knowledge Base Generator')
    parser.add_argument('--folder', type=str, help='Output folder name (e.g., world_centralized)')
    parser.add_argument('--characters', type=int, default=8, help='Number of characters to generate (default: 8)')
    parser.add_argument('--objects', type=int, default=15, help='Number of objects to generate (default: 15)')
    parser.add_argument('--no-scene', action='store_true', help='Do not generate a scene')
    parser.add_argument('--no-rules', action='store_true', help='Do not generate rules')
    parser.add_argument('--config', type=str, default='generation_config.json', help='Configuration file')
    args = parser.parse_args()

    print("="*70)
    print("KNOWLEDGE BASE GENERATOR")
    if args.folder:
        print(f"Output folder: {args.folder}")
    else:
        print(f"Output folder: world_<timestamp> (default)")
    print("="*70)

    generator = KnowledgeBaseGenerator(config_file=args.config, output_folder=args.folder)

    print("\n" + "="*70)
    print("GENERATING KNOWLEDGE BASE")
    print("="*70)

    kb = generator.generate_knowledge_base(
        num_characters=args.characters,
        num_objects=args.objects,
        generate_scene=not args.no_scene,
        generate_rules=not args.no_rules
    )

    print("\n" + "="*70)
    print("SAVING KNOWLEDGE BASE")
    print("="*70)
    generator.save_knowledge_base(kb, args.folder)

    print("\n" + "="*70)
    print("GENERATED FILES:")
    target = args.folder or generator.world_folder
    print(f"  - {target}/knowledge_base.json (combined)")
    print(f"  - {target}/characters.json")
    print(f"  - {target}/objects.json")
    print(f"  - {target}/scenes.json")
    print(f"  - {target}/rules.json")
    print(f"  - {target}/world_states.json")
    print(f"  - {target}/action_catalog.json")
    print(f"  - {target}/character_graph.json")
    print(f"  - {target}/condition_registry.json")
    print("="*70)
    print("\n[OK] Generation complete")
    print("\nTo run the world:")
    print(f"  python swm.py --world {target}")


if __name__ == "__main__":
    main()