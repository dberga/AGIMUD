#!/usr/bin/env python3
"""
Simulated World Module - Main class with JSON loading
"""

from typing import List, Dict, Any, Optional
from swm_corpus_loader import SWMCorpusLoader, DynamicEntity, DynamicEntityCollection


class SimulatedWorldModule:
    """Main Simulated World Module with JSON loading"""
    
    def __init__(self, 
                 characters_file: str = "characters.json",
                 objects_file: str = "objects.json",
                 scenes_file: str = "scenes.json",
                 rules_file: str = "rules.json",
                 world_states_file: str = "world_states.json",
                 knowledge_file: str = None):
        """Initialize the Simulated World Module by loading JSON files"""
        
        # Store raw data collections
        self.corpus_loader = SWMCorpusLoader()
        
        # Game Entities
        self.characters: DynamicEntityCollection = self.corpus_loader.characters
        self.objects: DynamicEntityCollection = self.corpus_loader.objects
        self.scenes: DynamicEntityCollection = self.corpus_loader.scenes
        self.rules: DynamicEntityCollection = self.corpus_loader.rules
        self.other_users: DynamicEntityCollection = DynamicEntityCollection("user")
        
        # Global Elements - use the loaded world states from corpus_loader
        self.world_states = self.corpus_loader.world_states
        self.knowledge_base = DynamicEntity()
        self.sound_graphics = DynamicEntity()
        self.system_rules = DynamicEntity()
        
        # Load corpora from JSON files
        self.load_corpora(characters_file, objects_file, scenes_file, rules_file, world_states_file, knowledge_file)
        
        print("[INIT] Simulated World Module initialized")
    
    def clear_all(self):
        """Clear all data collections"""
        self.characters.clear_all()
        self.objects.clear_all()
        self.scenes.clear_all()
        self.rules.clear_all()
        self.world_states = DynamicEntity()
        self.knowledge_base = DynamicEntity()
    
    def load_corpora(self, characters_file: str, objects_file: str, 
                     scenes_file: str, rules_file: str,
                     world_states_file: str, knowledge_file: str = None):
        """Load corpora from JSON files"""
        self.corpus_loader.load_all(characters_file, objects_file, scenes_file, 
                                   rules_file, world_states_file, knowledge_file)
        
        # Load knowledge base into dynamic entity
        if self.corpus_loader.knowledge_base:
            self.knowledge_base.update(self.corpus_loader.knowledge_base)
        
        # Ensure world_states is properly set
        if not self.world_states.to_dict():
            self.world_states.update(self.corpus_loader.world_states.to_dict())
    
    # GETTERS
    
    def get_characters(self) -> List[DynamicEntity]:
        """Get all characters"""
        return self.characters.get_all()
    
    def get_objects(self) -> List[DynamicEntity]:
        """Get all objects"""
        return self.objects.get_all()
    
    def get_scenes(self) -> List[DynamicEntity]:
        """Get all scenes"""
        return self.scenes.get_all()
    
    def get_rules(self) -> List[DynamicEntity]:
        """Get all rules"""
        return self.rules.get_all()
    
    def get_world_states(self) -> DynamicEntity:
        """Get world states"""
        return self.world_states
    
    def find_characters(self, **kwargs) -> List[DynamicEntity]:
        """Find characters matching criteria"""
        return self.characters.find_entities(**kwargs)
    
    def find_objects(self, **kwargs) -> List[DynamicEntity]:
        """Find objects matching criteria"""
        return self.objects.find_entities(**kwargs)
    
    def get_character_attributes(self) -> List[str]:
        """Get all character attributes"""
        return self.characters.get_common_attributes()
    
    def get_object_attributes(self) -> List[str]:
        """Get all object attributes"""
        return self.objects.get_common_attributes()
    
    def get_scene_attributes(self) -> List[str]:
        """Get all scene attributes"""
        return self.scenes.get_common_attributes()
    
    def get_rule_attributes(self) -> List[str]:
        """Get all rule attributes"""
        return self.rules.get_common_attributes()
    
    # WORLD STATE MANAGEMENT
    
    def get_world_state(self, key: str, default: Any = None) -> Any:
        """Get a world state value"""
        return self.world_states.get(key, default)
    
    def set_world_state(self, key: str, value: Any) -> None:
        """Set a world state value"""
        self.world_states.set(key, value)
    
    def get_global_flag(self, flag_name: str, default: bool = False) -> bool:
        """Get a persistent flag value"""
        flags = self.world_states.get("persistent_flags", {})
        return flags.get(flag_name, default)
    
    def set_global_flag(self, flag_name: str, value: bool) -> None:
        """Set a persistent flag value"""
        flags = self.world_states.get("persistent_flags", {})
        flags[flag_name] = value
        self.world_states.set("persistent_flags", flags)
    
    # VISUALIZATION METHODS
    
    def print_knowledge_base(self):
        """Print the knowledge base"""
        print("\n" + "="*70)
        print("KNOWLEDGE BASE")
        print("="*70)
        
        kb_data = self.knowledge_base.to_dict()
        if kb_data:
            for key, value in kb_data.items():
                if isinstance(value, dict):
                    print(f"\n[{key.upper()}]")
                    for subkey, subvalue in value.items():
                        if isinstance(subvalue, dict):
                            print(f"  {subkey}: {{...}}")
                        elif isinstance(subvalue, list):
                            print(f"  {subkey}: [{len(subvalue)} items]")
                        else:
                            print(f"  {subkey}: {subvalue}")
                else:
                    print(f"\n[{key.upper()}]: {value}")
        else:
            print("  (No knowledge base data loaded)")
        
        print("="*70)
    
    def print_world_states(self):
        """Print the world states"""
        print("\n" + "="*70)
        print("WORLD STATES")
        print("="*70)
        
        ws = self.world_states.to_dict()
        if ws:
            for key, value in ws.items():
                if key == "persistent_flags" and isinstance(value, dict):
                    print(f"\n[PERSISTENT FLAGS]")
                    for flag, flag_value in value.items():
                        print(f"  {flag}: {flag_value}")
                elif key == "scene_states" and isinstance(value, dict):
                    print(f"\n[SCENE STATES]")
                    for scene, scene_value in value.items():
                        print(f"  {scene}: {scene_value}")
                elif key == "object_states" and isinstance(value, dict):
                    print(f"\n[OBJECT STATES]")
                    for obj_id, obj_state in value.items():
                        print(f"  {obj_id}: {obj_state}")
                elif key == "global_timers" and isinstance(value, dict):
                    print(f"\n[GLOBAL TIMERS]")
                    for timer, timer_value in value.items():
                        print(f"  {timer}: {timer_value}")
                elif key == "global_states" and isinstance(value, dict):
                    print(f"\n[GLOBAL STATES]")
                    for state, state_value in value.items():
                        print(f"  {state}: {state_value}")
                else:
                    if not isinstance(value, dict):
                        print(f"\n[{key.upper()}]: {value}")
        else:
            print("  (No world states loaded)")
        
        print("="*70)
    
    def print_rules(self):
        """Print all rules"""
        print("\n" + "="*70)
        print("SYSTEM RULES")
        print("="*70)
        
        if self.rules.count() == 0:
            print("  No rules loaded.")
        else:
            for i, rule in enumerate(self.rules.get_all(), 1):
                rule_data = rule.to_dict()
                print(f"\n[RULE {i}] {rule_data.get('name', 'Unnamed')}")
                print(f"  Type: {rule_data.get('type', 'N/A')}")
                print(f"  Description: {rule_data.get('description', 'N/A')}")
                
                if 'conditions' in rule_data:
                    print(f"  Conditions: {len(rule_data['conditions'])}")
                    for cond in rule_data['conditions'][:3]:
                        print(f"    - {cond}")
                
                if 'effects' in rule_data:
                    print(f"  Effects: {len(rule_data['effects'])}")
                    for effect in rule_data['effects'][:3]:
                        print(f"    - {effect}")
        
        print("="*70)
    
    def print_corpus_summary(self):
        """Print summary of all loaded corpora"""
        self.corpus_loader.print_corpus_summary()
    
    def print_scene_diagram(self):
        """Print a simple ASCII diagram of the current scene"""
        print("\n" + "="*70)
        print("SCENE DIAGRAM")
        print("="*70)
        
        scene_data = None
        if self.scenes.count() > 0:
            scene_data = self.scenes.get_entity(0)
        
        if scene_data:
            print(f"\n  Current Scene: {scene_data.get('current_scene', 'Unknown')}")
            
            waypoints = scene_data.get('waypoints', [])
            if waypoints:
                grid_size = 10
                grid = [['.' for _ in range(grid_size)] for _ in range(grid_size)]
                
                for i, wp in enumerate(waypoints[:5]):
                    if isinstance(wp, dict):
                        x = int(abs(wp.get('x', 0)) % grid_size)
                        y = int(abs(wp.get('y', 0)) % grid_size)
                        if 0 <= x < grid_size and 0 <= y < grid_size:
                            grid[y][x] = str(i + 1) if i < 9 else 'W'
                    elif isinstance(wp, (list, tuple)) and len(wp) >= 2:
                        x = int(abs(wp[0]) % grid_size)
                        y = int(abs(wp[1]) % grid_size)
                        if 0 <= x < grid_size and 0 <= y < grid_size:
                            grid[y][x] = str(i + 1) if i < 9 else 'W'
                
                print("\n  Scene Map:")
                for row in grid:
                    print("    " + " ".join(row))
            else:
                print("  (No waypoints defined)")
            
            zones = scene_data.get('zones', [])
            if zones:
                print("\n  Zones:")
                for zone in zones[:3]:
                    if isinstance(zone, dict):
                        name = zone.get('name', 'Unknown')
                        zone_type = zone.get('zone_type', 'N/A')
                        print(f"    - {name} ({zone_type})")
        else:
            print("  (No scene data loaded)")
        
        print("\n" + "="*70)
    
    def print_entity_hierarchy(self):
        """Print the entity hierarchy"""
        print("\n" + "="*70)
        print("ENTITY HIERARCHY")
        print("="*70)
        
        char_count = self.characters.count()
        user_count = self.other_users.count()
        obj_count = self.objects.count()
        rule_count = self.rules.count()
        
        print(f"""
  +-------------------------------------+
  |     SIMULATED WORLD HIERARCHY       |
  +-------------------------------------+
  |                                     |
  |  Game Entities                      |
  |  +-- Characters: {char_count:>3}                    |
  |  +-- Other Users: {user_count:>3}                    |
  |  +-- Objects: {obj_count:>3}                      |
  |  +-- Scenes: {self.scenes.count():>3}                      |
  |  +-- Rules: {rule_count:>3}                       |
  |                                     |
  |  Global Elements                    |
  |  +-- World States                   |
  |  +-- Knowledge Base                 |
  |  +-- Sound and Graphics             |
  |  +-- System Rules                   |
  |                                     |
  +-------------------------------------+
  |  Total Entities: {char_count + user_count + obj_count + rule_count:>3}       |
  +-------------------------------------+
        """)
    
    def visualize_all(self):
        """Run all visualizations"""
        self.print_corpus_summary()
        self.print_scene_diagram()
        self.print_rules()
        self.print_world_states()
        self.print_entity_hierarchy()
        self.print_knowledge_base()


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    print("Creating Simulated World...")
    world = SimulatedWorldModule()
    world.visualize_all()