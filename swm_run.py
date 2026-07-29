#!/usr/bin/env python3
"""
SWM Run Module - Main runner with visualization loop
All display and behavior from JSON files
"""

import json
import os
import time
import random
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional
from swm import SimulatedWorldModule
from swm_corpus_loader import DynamicEntity


class WorldRunner:
    """Main runner for the simulated world with visualization loop"""
    
    def __init__(self, fps: float = 1.0, load_existing: bool = True, world_folder: str = None):
        self.fps = fps
        self.tick_interval = 1.0 / fps
        self.running = False
        self.tick_count = 0
        self.world = None
        self.event_history = []
        self.max_history = 100
        self.world_folder = world_folder
        
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
        
        # Load action catalog from root folder
        self.action_catalog = self._load_action_catalog()
        
        # Load or create world
        self._initialize_world(load_existing)
        
        # Create log file in world folder
        run_timestamp = datetime.now().strftime("%d_%m_%Y-%H_%M_%S")
        self.run_id = f"run_{run_timestamp}"
        self.log_file = os.path.join(self.world_folder, f"{self.run_id}.log")
        self.log_lines = []
        
        print(f"[INIT] World Runner initialized at {fps} FPS")
        print(f"[WORLD] Using world folder: {self.world_folder}")
        print(f"[LOG] Writing to {self.log_file}")
        
    def _validate_world_folder(self) -> bool:
        """Validate that the world folder exists and contains required files"""
        if self.world_folder is None or self.world_folder == ".":
            return False
        
        if not os.path.exists(self.world_folder):
            print(f"[ERROR] World folder does not exist: {self.world_folder}")
            return False
        
        if not os.path.isdir(self.world_folder):
            print(f"[ERROR] Path is not a directory: {self.world_folder}")
            return False
        
        # Check for required files
        required_files = [
            "characters.json",
            "objects.json",
            "scenes.json",
            "rules.json",
            "world_states.json"
        ]
        
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
        """Find the latest world folder"""
        world_folders = [d for d in os.listdir('.') if os.path.isdir(d) and d.startswith('world_')]
        if world_folders:
            # Sort by name (which is timestamp) and get the latest
            world_folders.sort(reverse=True)
            print(f"[INFO] Found world folder: {world_folders[0]}")
            return world_folders[0]
        else:
            print("[WARNING] No world folder found. Please run swm_generate.py first.")
            return None
    
    def _load_json(self, filename: str) -> Dict[str, Any]:
        """Load JSON file with error handling"""
        # Try to load from current directory first, then from world folder
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load {filename}: {e}")
                return {}
        
        # Try from world folder
        world_path = os.path.join(self.world_folder, filename) if self.world_folder else filename
        if os.path.exists(world_path):
            try:
                with open(world_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load {world_path}: {e}")
                return {}
        
        print(f"[WARNING] {filename} not found")
        return {}
    
    def _get_vocab(self, key: str, default: list = None) -> list:
        """Get a vocabulary list from world_vocabulary.json"""
        return self.vocab.get(key, default or [])
    
    def _get_field_value(self, obj: Any, path: str, default: Any = None) -> Any:
        """Get a value from a nested object using dot notation"""
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
        """Get a formatted display field from config"""
        key = field_config.get('key', '')
        label = field_config.get('label', key)
        default = field_config.get('default', 'Unknown')
        format_str = field_config.get('format', '{label}: {value}')
        transform = field_config.get('transform', '')
        
        # Get value - handle nested paths
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
        
        # If value is None or default, try direct access
        if value is None or value == default:
            value = ws.get(key, default)
        
        # Apply transform
        if transform == 'day_cycle':
            if isinstance(value, (int, float)):
                hours = int(value // 60)
                minutes = int(value % 60)
                formatted = f"{hours:02d}:{minutes:02d}"
            else:
                formatted = str(value) if value else '00:00'
        else:
            formatted = str(value) if value is not None and value != default else '?'
        
        # Apply format
        try:
            return format_str.format(label=label, value=formatted)
        except:
            return f"{label}: {formatted}"
    
    def _log(self, text: str, console: bool = True):
        """Log text to both console and log file"""
        if console:
            print(text)
        self.log_lines.append(text)
    
    def _flush_log(self):
        """Write log to file"""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(self.log_lines))
        except Exception as e:
            print(f"[ERROR] Failed to write log: {e}")
    
    def _load_action_catalog(self) -> List[str]:
        """Load action catalog from root folder"""
        if os.path.exists("action_catalog.json"):
            try:
                with open("action_catalog.json", 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('action_catalog', [])
            except Exception as e:
                print(f"[ERROR] Failed to load action_catalog.json: {e}")
                return []
        else:
            print("[WARNING] action_catalog.json not found, using defaults")
            return [
                "GATHER_ALL_RESOURCES_GREEDY",
                "HARVEST_SUSTAINABLE_SHARED",
                "NEGOTIATE_COOPERATIVE_PACT",
                "IDLE_WAIT"
            ]
    
    def _validate_action(self, action: str) -> bool:
        """Check if an action is in the catalog"""
        if not self.action_catalog:
            return True  # If no catalog, allow all actions
        return action in self.action_catalog
    
    def _get_random_action(self) -> str:
        """Get a random action from the catalog"""
        if self.action_catalog:
            return random.choice(self.action_catalog)
        return "IDLE_WAIT"
        
    def _initialize_world(self, load_existing: bool):
        """Initialize the world, loading existing state if available"""
        # Get runtime state path in world folder
        runtime_path = os.path.join(self.world_folder, "world_state_runtime.json")
        
        if load_existing and os.path.exists(runtime_path):
            print("[INFO] Loading existing world state from world_state_runtime.json")
            # Load world from JSON files in world folder
            self.world = SimulatedWorldModule(
                characters_file=os.path.join(self.world_folder, "characters.json"),
                objects_file=os.path.join(self.world_folder, "objects.json"),
                scenes_file=os.path.join(self.world_folder, "scenes.json"),
                rules_file=os.path.join(self.world_folder, "rules.json"),
                world_states_file=os.path.join(self.world_folder, "world_states.json")
            )
            self._load_runtime_state()
        else:
            print("[INFO] Creating new world state from JSON files")
            self.world = SimulatedWorldModule(
                characters_file=os.path.join(self.world_folder, "characters.json"),
                objects_file=os.path.join(self.world_folder, "objects.json"),
                scenes_file=os.path.join(self.world_folder, "scenes.json"),
                rules_file=os.path.join(self.world_folder, "rules.json"),
                world_states_file=os.path.join(self.world_folder, "world_states.json")
            )
            self._record_initial_state()
            self._save_runtime_state()
    
    def _load_runtime_state(self):
        """Load runtime state from file"""
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
            
            print("[OK] Runtime state loaded successfully")
            
        except Exception as e:
            print(f"[ERROR] Failed to load runtime state: {e}")
            self.world = SimulatedWorldModule(
                characters_file=os.path.join(self.world_folder, "characters.json"),
                objects_file=os.path.join(self.world_folder, "objects.json"),
                scenes_file=os.path.join(self.world_folder, "scenes.json"),
                rules_file=os.path.join(self.world_folder, "rules.json"),
                world_states_file=os.path.join(self.world_folder, "world_states.json")
            )
            self._record_initial_state()
            self._save_runtime_state()
    
    def _save_runtime_state(self):
        """Save runtime state to file"""
        runtime_path = os.path.join(self.world_folder, "world_state_runtime.json")
        try:
            runtime_data = {
                "world_states": self.world.world_states.to_dict(),
                "characters": [c.to_dict() for c in self.world.characters.get_all()],
                "objects": [o.to_dict() for o in self.world.objects.get_all()],
                "event_history": self.event_history[-self.max_history:],
                "tick_count": self.tick_count,
                "last_saved": datetime.now().isoformat()
            }
            
            with open(runtime_path, 'w', encoding='utf-8') as f:
                json.dump(runtime_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save runtime state: {e}")
            return False
    
    def _record_initial_state(self):
        """Record the initial state as events using message templates"""
        templates = self.dynamics.get('message_templates', {})
        locations = self._get_vocab('locations', ['Unknown'])
        
        for char in self.world.characters.get_all():
            name = char.get('name', 'Unknown')
            faction = self._get_field_value(char, 'social_attributes.faction', 'Unknown')
            location = self._get_field_value(char, 'navigation.current_location', 'Unknown')
            
            template = templates.get('character_entry', '[ENTRY] {character_name} enters the world')
            try:
                event = template.format(character_name=name, faction=faction, location=location)
            except KeyError:
                event = f"[ENTRY] {name} enters the world"
            self._add_event(event, 'entry', 'character', name)
        
        for obj in self.world.objects.get_all():
            name = obj.get('name', 'Unknown')
            obj_type = self._get_field_value(obj, 'properties.type', 'item')
            quality = self._get_field_value(obj, 'object_variables.quality', 'standard')
            location = random.choice(locations) if locations else 'Unknown'
            
            template = templates.get('object_entry', '[ENTRY] An object appears')
            try:
                event = template.format(quality=quality, object_type=obj_type, object_name=name, location=location)
            except KeyError:
                event = f"[ENTRY] {name} appears"
            self._add_event(event, 'entry', 'object', name)
        
        if self.world.scenes.count() > 0:
            scene = self.world.scenes.get_entity(0)
            scene_name = scene.get('current_scene', 'Unknown')
            zones = scene.get('zones', [])
            zone_names = [z.get('name', 'Unknown') for z in zones[:3]]
            
            template = templates.get('scene_entry', '[SCENE] Welcome to {scene_name}')
            try:
                event = template.format(scene_name=scene_name, zone_names=', '.join(zone_names))
            except KeyError:
                event = f"[SCENE] Welcome to {scene_name}"
            self._add_event(event, 'scene', 'scene', scene_name)
    
    def _update_world(self):
        """Update the world state for one tick"""
        self.tick_count += 1
        
        timers = self.world.world_states.get('global_timers', {})
        timers['world_time'] = timers.get('world_time', 0) + 1
        timers['day_cycle'] = (timers.get('day_cycle', 0) + 1) % 1440
        self.world.world_states.set('global_timers', timers)
        
        self._update_time_of_day()
        self._process_global_events()
        
        for char in self.world.characters.get_all():
            self._update_character(char)
        
        for obj in self.world.objects.get_all():
            self._update_object(obj)
        
        if self.tick_count % 10 == 0:
            self._save_runtime_state()
    
    def _update_time_of_day(self):
        """Update time of day using world_dynamics.json"""
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
        """Process all global events from world_dynamics.json"""
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
        """Check if an event trigger condition is met"""
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
                        except:
                            pass
            return random.random() < probability
        
        return True
    
    def _process_event(self, event_config: Dict[str, Any]):
        """Process a single event from configuration"""
        event_id = event_config.get('id', 'event')
        
        if event_id == 'character_action':
            action = self._get_random_action()
            chars = self.world.characters.get_all()
            if chars:
                char = random.choice(chars)
                name = char.get('name', 'Unknown')
                location = char.get('navigation', {}).get('current_location', 'Unknown')
                message = f"[ACTION] {name} performs '{action}' at {location}"
                self._add_event(message, event_id, 'world')
                return
        
        # Regular event processing
        message = self._build_event_message(event_config)
        self._add_event(message, event_id, 'world')
        
        effects = event_config.get('effects', [])
        for effect in effects:
            self._apply_effect(effect)
    
    def _build_event_message(self, event_config: Dict[str, Any]) -> str:
        """Build event message from config"""
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
                if index >= 0 and index < len(names):
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
        """Apply an effect from config"""
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
        """Update a single character using status_changes from config"""
        self._update_character_status(char)
        self._update_character_movement(char)
        self._update_ai_state(char)
    
    def _update_character_status(self, char: DynamicEntity):
        """Update character status using status_changes from config"""
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
        """Update character movement using character_movement from config"""
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
                        template = movement_config.get('message_template', 
                            "[MOVEMENT] {character_name} moves from {old_location} to {new_location}")
                        try:
                            event = template.format(character_name=name, old_location=old_loc, new_location=new_loc)
                        except KeyError:
                            event = f"[MOVEMENT] {name} moves from {old_loc} to {new_loc}"
                        self._add_event(event, 'movement', 'character', name)
    
    def _update_ai_state(self, char: DynamicEntity):
        """Update AI state using ai_state_changes from config"""
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
        """Evaluate an AI condition from JSON config"""
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
        """Update a single object using object_status from config"""
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
        """Add an event to the history"""
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
        """Format a value for display"""
        if value is None:
            return '?'
        if isinstance(value, float):
            return str(int(round(value)))
        if isinstance(value, bool):
            return str(value)
        return str(value)
    
    def _render(self):
        """Render the current world state using display config from world_dynamics.json"""
        display = self.dynamics.get('display', {})
        header_width = display.get('header_width', 80)
        separator = display.get('header_separator', '=')
        title = display.get('title', 'SIMULATED WORLD')
        
        output_lines = []
        output_lines.append(separator * header_width)
        output_lines.append(f"{title} - EPOCH {self.tick_count}")
        output_lines.append(f"FPS: {self.fps} | Time: {datetime.now().strftime(display.get('date_format', '%Y-%m-%d %H:%M:%S'))}")
        output_lines.append(f"World: {self.world_folder}")
        output_lines.append(separator * header_width)
        
        # World State - from display config
        ws = self.world.world_states.to_dict()
        global_states = ws.get('global_states', {})
        timers = ws.get('global_timers', {})
        player_state = ws.get('player_state', {})
        
        world_state_display = display.get('world_state_display', {})
        output_lines.append(f"\n[{world_state_display.get('label', 'WORLD STATE')}]")
        
        for field in world_state_display.get('fields', []):
            formatted = self._get_display_field(field, ws, global_states, timers)
            output_lines.append(f"  {formatted}")
        
        # User State - from display config
        user_state_display = display.get('user_state_display', {})
        if user_state_display:
            output_lines.append(f"\n[{user_state_display.get('label', 'USER STATE')}]")
            for field in user_state_display.get('fields', []):
                key = field.get('key', '')
                label = field.get('label', key)
                default = field.get('default', 'Unknown')
                format_str = field.get('format', '{label}: {value}')
                
                if key.startswith('player_state.'):
                    parts = key.split('.')
                    value = player_state.get(parts[1], default)
                else:
                    value = ws.get(key, default)
                
                formatted = str(value) if value is not None and value != 'Unknown' else '?'
                try:
                    output_lines.append(f"  {format_str.format(label=label, value=formatted)}")
                except:
                    output_lines.append(f"  {label}: {formatted}")
        
        # Scene Information - from scene data
        output_lines.append("\n[SCENE INFORMATION]")
        if self.world.scenes.count() > 0:
            scene_entity = self.world.scenes.get_entity(0)
            if scene_entity:
                scene_dict = scene_entity.to_dict()
                if 'scenes' in scene_dict and isinstance(scene_dict['scenes'], dict):
                    scene_data = scene_dict['scenes']
                else:
                    scene_data = scene_dict
                
                scene_name = scene_data.get('current_scene', 'Unknown')
                if not scene_name or scene_name == 'Unknown':
                    scene_name = scene_entity.get('current_scene', '?')
                
                output_lines.append(f"  Name: {scene_name if scene_name and scene_name != 'Unknown' else '?'}")
                
                regions = scene_data.get('world_regions', [])
                if regions:
                    output_lines.append(f"  Regions ({len(regions)}):")
                    for region in regions:
                        region_name = region.get('name', 'Unknown')
                        climate = region.get('climate', 'Unknown')
                        terrain = region.get('terrain_type', 'Unknown')
                        output_lines.append(f"    - {region_name} ({climate}, {terrain})")
                
                zones = scene_data.get('zones', [])
                if zones:
                    output_lines.append(f"  Zones ({len(zones)}):")
                    for zone in zones:
                        name = zone.get('name', 'Unknown')
                        zone_type = zone.get('zone_type', 'N/A')
                        safe = "Safe" if zone.get('safe_zone', False) else "Dangerous"
                        output_lines.append(f"    - {name} ({zone_type}) [{safe}]")
                
                buildings = scene_data.get('buildings_containers', [])
                if buildings:
                    output_lines.append(f"  Buildings ({len(buildings)}):")
                    for building in buildings:
                        bname = building.get('name', 'Unknown')
                        floors = building.get('floors', '?')
                        rooms = building.get('rooms', [])
                        output_lines.append(f"    - {bname} ({floors} floors, {len(rooms)} rooms)")
                
                waypoints = scene_data.get('waypoints', [])
                if waypoints:
                    output_lines.append(f"  Waypoints ({len(waypoints)}):")
                    for wp in waypoints[:5]:
                        name = wp.get('name', 'Unknown')
                        output_lines.append(f"    - {name}")
            else:
                output_lines.append("  Scene entity is empty")
        else:
            output_lines.append("  No scene data loaded")
        
        # Characters
        char_display = display.get('character_display', {})
        chars = self.world.characters.get_all()
        output_lines.append(f"\n[{char_display.get('label', 'CHARACTERS')}] {char_display.get('count_format', '({count})').format(count=len(chars))}")
        
        for char in chars:
            name = char.get('name', 'Unknown')
            ai_state = char.get('ai_state', 'IDLE')
            status = char.get('status_variables', {})
            health = self._format_value(status.get('health', '?')) if status else '?'
            stamina = self._format_value(status.get('stamina', '?')) if status else '?'
            location = char.get('navigation', {}).get('current_location', 'Unknown')
            location = location if location and location != 'Unknown' else '?'
            
            item_format = char_display.get('item_format', '')
            if item_format:
                try:
                    display_str = item_format.format(
                        name=name,
                        ai_state=ai_state,
                        health=health,
                        stamina=stamina,
                        location=location
                    )
                except KeyError:
                    display_str = f"{name} [{ai_state}] HP:{health} ST:{stamina} @ {location}"
            else:
                display_str = f"{name} [{ai_state}] HP:{health} ST:{stamina} @ {location}"
            
            contained = char.get('contained_objects', [])
            if contained:
                display_str += f" [Carrying: {', '.join(contained)}]"
            
            output_lines.append(f"  {display_str}")
        
        # Objects
        obj_display = display.get('object_display', {})
        objs = self.world.objects.get_all()
        output_lines.append(f"\n[{obj_display.get('label', 'OBJECTS')}] {obj_display.get('count_format', '({count})').format(count=len(objs))}")
        
        for obj in objs:
            name = obj.get('name', 'Unknown')
            obj_type = self._get_field_value(obj, 'properties.type', 'item')
            obj_vars = obj.get('object_variables', {})
            durability = self._format_value(obj_vars.get('durability', '?')) if obj_vars else '?'
            quality = obj_vars.get('quality', 'standard') if obj_vars else 'standard'
            
            item_format = obj_display.get('item_format', '')
            if item_format:
                try:
                    display_str = item_format.format(
                        name=name,
                        type=obj_type,
                        durability=durability,
                        quality=quality
                    )
                except KeyError:
                    display_str = f"{name} ({obj_type}) [{quality}] Durability:{durability}"
            else:
                display_str = f"{name} ({obj_type}) [{quality}] Durability:{durability}"
            
            contained = obj.get('contained_objects', [])
            if contained:
                display_str += f" [Contains: {', '.join(contained)}]"
            
            output_lines.append(f"  {display_str}")
        
        # Events
        events_display = display.get('events_display', {})
        max_events = events_display.get('max_display', 10)
        
        output_lines.append(f"\n[{events_display.get('label', 'RECENT EVENTS')}] {events_display.get('count_format', '(last {count})').format(count=min(max_events, len(self.event_history)))}")
        
        for event in self.event_history[-max_events:]:
            tick = event.get('tick', '?')
            text = event.get('text', '')
            timestamp = event.get('timestamp', '')
            try:
                dt = datetime.fromisoformat(timestamp)
                timestamp = dt.strftime(events_display.get('timestamp_format', '%H:%M:%S'))
            except:
                timestamp = '??:??:??'
            
            item_format = events_display.get('item_format', '[{tick:4d}] {timestamp} - {text}')
            try:
                output_lines.append(f"  {item_format.format(tick=tick, timestamp=timestamp, text=text)}")
            except:
                output_lines.append(f"  [{tick:4d}] {text}")
        
        # Controls
        controls_display = display.get('controls_display', {})
        output_lines.append(f"\n[{controls_display.get('label', 'CONTROLS')}]")
        
        control_items = controls_display.get('items', [])
        control_parts = []
        for item in control_items:
            key = item.get('key', '')
            description = item.get('description', '')
            format_str = controls_display.get('format', '[{key}] {description}')
            control_parts.append(format_str.format(key=key, description=description))
        
        separator_str = controls_display.get('separator', ' | ')
        output_lines.append(f"  {separator_str.join(control_parts)}")
        output_lines.append(separator * header_width)
        
        # Print to console
        for line in output_lines:
            print(line)
        
        # Save to log
        self.log_lines.extend(output_lines)
        self._flush_log()
    
    def _handle_input(self):
        """Handle keyboard input - only Ctrl+C to quit"""
        try:
            import msvcrt
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key == b'\x03':
                    print("\n[Saving state and quitting...]")
                    self._save_runtime_state()
                    self.running = False
                    return
        except:
            pass
    
    def run(self):
        """Run the main loop"""
        self.running = True
        print(f"[START] World running at {self.fps} FPS")
        print("Press Ctrl+C to save and quit")
        time.sleep(1)
        
        try:
            while self.running:
                start_time = time.time()
                
                self._update_world()
                self._render()
                self._handle_input()
                
                elapsed = time.time() - start_time
                sleep_time = max(0, self.tick_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print("\n[STOP] Saving state before exit...")
            self._save_runtime_state()
            self._flush_log()
            print(f"[OK] World state saved. Ran for {self.tick_count} epochs")
            print(f"[OK] Log saved to {self.log_file}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Run the simulated world with visualization')
    parser.add_argument('--fps', type=float, default=1.0, help='Frames per second (default: 1.0)')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    parser.add_argument('--world', type=str, help='Specify a world folder to load')
    args = parser.parse_args()
    
    runner = WorldRunner(fps=args.fps, load_existing=not args.new, world_folder=args.world)
    runner.run()


if __name__ == "__main__":
    main()