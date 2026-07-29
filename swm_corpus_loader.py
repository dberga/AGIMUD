#!/usr/bin/env python3
"""
SWM Corpus Loader - Flexible JSON loading functions for the Simulated World Module
"""

import json
import os
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


class SWMJsonLoader:
    """Handles loading JSON data into the Simulated World Module"""
    
    @staticmethod
    def load_json_file(filepath: str) -> Dict[str, Any]:
        """Load any JSON file and return as dict"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"[OK] Loaded from {filepath}")
            return data
        except FileNotFoundError:
            print(f"[ERROR] File not found: {filepath}")
            return {}
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in {filepath}: {e}")
            return {}
        except Exception as e:
            print(f"[ERROR] Error loading {filepath}: {e}")
            return {}
    
    @staticmethod
    def save_json_file(data: Dict[str, Any], filepath: str) -> bool:
        """Save any data to a JSON file"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[OK] Saved to {filepath}")
            return True
        except Exception as e:
            print(f"[ERROR] Error saving to {filepath}: {e}")
            return False
    
    @staticmethod
    def load_corpus(filepath: str, key: str = None) -> List[Dict[str, Any]]:
        """Load a corpus from JSON file, optionally extracting a specific key"""
        data = SWMJsonLoader.load_json_file(filepath)
        if key and key in data:
            return data[key]
        elif not key:
            return data
        else:
            print(f"[WARNING] Key '{key}' not found in {filepath}")
            return []
    
    @staticmethod
    def get_field(data: Dict[str, Any], field_path: str, default: Any = None) -> Any:
        """Get a field from nested dict using dot notation (e.g., 'status_variables.health')"""
        keys = field_path.split('.')
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current
    
    @staticmethod
    def set_field(data: Dict[str, Any], field_path: str, value: Any) -> None:
        """Set a field in nested dict using dot notation"""
        keys = field_path.split('.')
        current = data
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value
    
    @staticmethod
    def extract_attributes(data: Dict[str, Any], 
                          attribute_list: List[str]) -> Dict[str, Any]:
        """Extract only specified attributes from a dict"""
        result = {}
        for attr in attribute_list:
            if attr in data:
                result[attr] = data[attr]
        return result
    
    @staticmethod
    def merge_data(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries"""
        result = base.copy()
        for key, value in override.items():
            if isinstance(value, dict) and key in result and isinstance(result[key], dict):
                result[key] = SWMJsonLoader.merge_data(result[key], value)
            else:
                result[key] = value
        return result


class DynamicEntity:
    """A flexible entity that can hold any attributes from JSON"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self._data = data or {}
        self._attributes = set(self._data.keys())
        self._modified = False
    
    def __getattr__(self, name: str) -> Any:
        """Get attribute dynamically"""
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{self.__class__.__name__}' has no attribute '{name}'")
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Set attribute dynamically"""
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            self._data[name] = value
            self._attributes.add(name)
            self._modified = True
    
    def __getitem__(self, key: str) -> Any:
        """Support dict-style access"""
        return self._data.get(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Support dict-style assignment"""
        self._data[key] = value
        self._attributes.add(key)
        self._modified = True
    
    def __contains__(self, key: str) -> bool:
        """Support 'in' operator"""
        return key in self._data
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value with default"""
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set value and mark as modified"""
        self._data[key] = value
        self._attributes.add(key)
        self._modified = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return self._data.copy()
    
    def update(self, data: Dict[str, Any]) -> None:
        """Update with new data"""
        for key, value in data.items():
            if isinstance(value, dict) and key in self._data and isinstance(self._data[key], dict):
                self._data[key] = SWMJsonLoader.merge_data(self._data[key], value)
            else:
                self._data[key] = value
            self._attributes.add(key)
        self._modified = True
    
    def get_attributes(self) -> List[str]:
        """Get list of all attribute names"""
        return list(self._attributes)
    
    def has_attribute(self, name: str) -> bool:
        """Check if attribute exists"""
        return name in self._data
    
    def is_modified(self) -> bool:
        """Check if entity has been modified"""
        return self._modified
    
    def clear_modified(self) -> None:
        """Clear the modified flag"""
        self._modified = False


class DynamicEntityCollection:
    """A collection of dynamic entities"""
    
    def __init__(self, entity_type: str = "entity"):
        self._entities: List[DynamicEntity] = []
        self._entity_type = entity_type
        self._common_attributes = set()
        self._modified = False
    
    def load_from_json(self, filepath: str, key: str = None) -> bool:
        """Load entities from JSON file"""
        data = SWMJsonLoader.load_json_file(filepath)
        if not data:
            return False
        
        # Clear existing entities before loading
        self.clear_all()
        
        # If key is provided, use it to extract the list
        if key:
            entity_list = data.get(key, [])
        else:
            entity_list = data
        
        if not isinstance(entity_list, list):
            print(f"[ERROR] Data is not a list for {filepath}")
            return False
        
        # Create entities from each item
        for item in entity_list:
            entity = DynamicEntity(item)
            self._entities.append(entity)
            for attr in entity.get_attributes():
                self._common_attributes.add(attr)
        
        self._modified = False
        print(f"[OK] Loaded {len(self._entities)} {self._entity_type}s from {filepath}")
        return True
    
    def save_to_json(self, filepath: str, root_key: str = None) -> bool:
        """Save entities to JSON file"""
        data = [e.to_dict() for e in self._entities]
        if root_key:
            data = {root_key: data}
        success = SWMJsonLoader.save_json_file(data, filepath)
        if success:
            self._modified = False
            for entity in self._entities:
                entity.clear_modified()
        return success
    
    def clear_all(self):
        """Clear all entities"""
        self._entities = []
        self._common_attributes = set()
        self._modified = False
    
    def add_entity(self, data: Dict[str, Any]) -> DynamicEntity:
        """Add a new entity"""
        entity = DynamicEntity(data)
        self._entities.append(entity)
        for attr in entity.get_attributes():
            self._common_attributes.add(attr)
        self._modified = True
        return entity
    
    def remove_entity(self, index: int) -> bool:
        """Remove entity by index"""
        if 0 <= index < len(self._entities):
            del self._entities[index]
            self._modified = True
            return True
        return False
    
    def get_entity(self, index: int) -> Optional[DynamicEntity]:
        """Get entity by index"""
        if 0 <= index < len(self._entities):
            return self._entities[index]
        return None
    
    def find_entities(self, **kwargs) -> List[DynamicEntity]:
        """Find entities matching criteria"""
        results = []
        for entity in self._entities:
            match = True
            for key, value in kwargs.items():
                if entity.get(key) != value:
                    match = False
                    break
            if match:
                results.append(entity)
        return results
    
    def get_all(self) -> List[DynamicEntity]:
        """Get all entities"""
        return self._entities.copy()
    
    def count(self) -> int:
        """Get number of entities"""
        return len(self._entities)
    
    def get_common_attributes(self) -> List[str]:
        """Get list of attributes that exist across all entities"""
        return list(self._common_attributes)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the collection"""
        stats = {
            "total": len(self._entities),
            "entity_type": self._entity_type,
            "common_attributes": list(self._common_attributes),
            "attribute_counts": {}
        }
        
        # Count how many entities have each attribute
        for attr in self._common_attributes:
            count = sum(1 for e in self._entities if e.has_attribute(attr))
            stats["attribute_counts"][attr] = count
        
        return stats
    
    def is_modified(self) -> bool:
        """Check if collection has been modified"""
        return self._modified or any(e.is_modified() for e in self._entities)
    
    def print_summary(self):
        """Print a summary of the collection"""
        stats = self.get_statistics()
        print(f"\n[{self._entity_type.upper()} COLLECTION SUMMARY]")
        print(f"  Total: {stats['total']}")
        print(f"  Common Attributes: {len(stats['common_attributes'])}")
        for attr, count in stats['attribute_counts'].items():
            print(f"    - {attr}: {count}/{stats['total']} entities")
        
        # Show first few entities
        if self._entities:
            print(f"\n  Sample Entity ({len(self._entities)} total):")
            sample = self._entities[0]
            for key in list(sample.get_attributes())[:5]:
                value = sample.get(key)
                if isinstance(value, dict):
                    value = f"{{...}} ({len(value)} fields)"
                elif isinstance(value, list):
                    value = f"[...] ({len(value)} items)"
                print(f"    {key}: {value}")


class SWMCorpusLoader:
    """Main corpus loader with flexible loading"""
    
    def __init__(self):
        self.characters = DynamicEntityCollection("character")
        self.objects = DynamicEntityCollection("object")
        self.scenes = DynamicEntityCollection("scene")
        self.rules = DynamicEntityCollection("rule")
        self.world_states = DynamicEntity()
        self.knowledge_base = {}
        self._raw_data = {}
    
    def load_all(self, 
                 characters_file: str = "characters.json",
                 objects_file: str = "objects.json",
                 scenes_file: str = "scenes.json",
                 rules_file: str = "rules.json",
                 world_states_file: str = "world_states.json",
                 knowledge_file: str = None) -> Dict[str, Any]:
        """Load all corpora from JSON files"""
        
        print("\nLoading corpora...")
        print("-" * 50)
        
        # Load characters
        if characters_file and os.path.exists(characters_file):
            self.characters.load_from_json(characters_file, "characters")
        else:
            print(f"[WARNING] Characters file not found: {characters_file}")
        
        # Load objects
        if objects_file and os.path.exists(objects_file):
            self.objects.load_from_json(objects_file, "objects")
        else:
            print(f"[WARNING] Objects file not found: {objects_file}")
        
        # Load scenes - handle both list and dict formats
        if scenes_file and os.path.exists(scenes_file):
            data = SWMJsonLoader.load_json_file(scenes_file)
            if data:
                # Check if data has a 'scenes' key that contains the actual scene data
                if 'scenes' in data:
                    scene_data = data['scenes']
                    # If scene_data has a 'scenes' key too, go deeper
                    if 'scenes' in scene_data and isinstance(scene_data['scenes'], dict):
                        scene_data = scene_data['scenes']
                    self.scenes.clear_all()
                    self.scenes.add_entity(scene_data)
                    print(f"[OK] Loaded scene from {scenes_file}")
                else:
                    self.scenes.clear_all()
                    self.scenes.add_entity(data)
                    print(f"[OK] Loaded scene from {scenes_file}")
            else:
                print(f"[WARNING] No data in {scenes_file}")
        else:
            print(f"[WARNING] Scenes file not found: {scenes_file}")
        
        # Load rules
        if rules_file and os.path.exists(rules_file):
            self.rules.load_from_json(rules_file, "rules")
        else:
            print(f"[WARNING] Rules file not found: {rules_file}")
        
        # Load world states from JSON - handle wrapped format
        if world_states_file and os.path.exists(world_states_file):
            world_data = SWMJsonLoader.load_json_file(world_states_file)
            if world_data:
                # Check if data has a 'world_states' key (wrapped)
                if 'world_states' in world_data:
                    self.world_states.update(world_data['world_states'])
                    print(f"[OK] Loaded world states from {world_states_file}")
                else:
                    self.world_states.update(world_data)
                    print(f"[OK] Loaded world states from {world_states_file}")
            else:
                print(f"[WARNING] No data in {world_states_file}")
        else:
            print(f"[WARNING] World states file not found: {world_states_file}")
            # Initialize with minimal default states
            self.world_states.update({
                "version": "1.0",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "current_scene": "UNKNOWN",
                "persistent_flags": {},
                "scene_states": {},
                "global_timers": {},
                "global_states": {},
                "object_states": {}
            })
        
        # Load knowledge base
        if knowledge_file and os.path.exists(knowledge_file):
            self.knowledge_base = SWMJsonLoader.load_json_file(knowledge_file)
        
        print("-" * 50)
        print(f"[OK] Loaded {self.characters.count()} characters, "
              f"{self.objects.count()} objects, "
              f"{self.scenes.count()} scenes, "
              f"{self.rules.count()} rules")
        
        return {
            "characters": self.characters,
            "objects": self.objects,
            "scenes": self.scenes,
            "rules": self.rules,
            "world_states": self.world_states,
            "knowledge_base": self.knowledge_base
        }
    
    def save_world_states(self, filepath: str = "world_states.json") -> bool:
        """Save current world states to file with wrapper"""
        data = {"world_states": self.world_states.to_dict()}
        return SWMJsonLoader.save_json_file(data, filepath)
    
    def save_all(self, 
                 characters_file: str = "characters.json",
                 objects_file: str = "objects.json",
                 scenes_file: str = "scenes.json",
                 rules_file: str = "rules.json",
                 world_states_file: str = "world_states.json") -> bool:
        """Save all corpora to JSON files"""
        success = True
        
        if self.characters.is_modified():
            if not self.characters.save_to_json(characters_file, "characters"):
                success = False
        
        if self.objects.is_modified():
            if not self.objects.save_to_json(objects_file, "objects"):
                success = False
        
        if self.scenes.is_modified():
            if not self.scenes.save_to_json(scenes_file, "scenes"):
                success = False
        
        if self.rules.is_modified():
            if not self.rules.save_to_json(rules_file, "rules"):
                success = False
        
        if self.world_states.is_modified():
            if not self.save_world_states(world_states_file):
                success = False
        
        if success:
            print("[OK] All data saved successfully")
        else:
            print("[ERROR] Some data failed to save")
        
        return success
    
    def get_character_attributes(self) -> List[str]:
        """Get all character attributes found in the data"""
        return self.characters.get_common_attributes()
    
    def get_object_attributes(self) -> List[str]:
        """Get all object attributes found in the data"""
        return self.objects.get_common_attributes()
    
    def get_scene_attributes(self) -> List[str]:
        """Get all scene attributes found in the data"""
        return self.scenes.get_common_attributes()
    
    def get_rule_attributes(self) -> List[str]:
        """Get all rule attributes found in the data"""
        return self.rules.get_common_attributes()
    
    def print_corpus_summary(self):
        """Print a summary of all loaded corpora"""
        print("\n" + "="*60)
        print("CORPUS SUMMARY")
        print("="*60)
        self.characters.print_summary()
        self.objects.print_summary()
        self.scenes.print_summary()
        self.rules.print_summary()
        
        # Print world states
        print(f"\n[WORLD STATES]")
        ws = self.world_states.to_dict()
        for key in list(ws.keys())[:8]:
            value = ws.get(key)
            if isinstance(value, dict):
                value = f"{{...}} ({len(value)} fields)"
            elif isinstance(value, list):
                value = f"[...] ({len(value)} items)"
            print(f"  {key}: {value}")
        
        if self.knowledge_base:
            print(f"\n[KNOWLEDGE BASE]")
            for key in list(self.knowledge_base.keys())[:5]:
                value = self.knowledge_base.get(key)
                if isinstance(value, dict):
                    value = f"{{...}} ({len(value)} fields)"
                elif isinstance(value, list):
                    value = f"[...] ({len(value)} items)"
                print(f"  {key}: {value}")
        print("="*60)


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":
    print("Testing SWM Corpus Loader...")
    loader = SWMCorpusLoader()
    loader.load_all()
    loader.print_corpus_summary()