#!/usr/bin/env python3
"""
SWM Behavior Module - Encapsulates AI states, behavior graphs, and transitions
"""

import random
import re
from typing import Dict, Any, List, Optional
from swm_corpus_loader import DynamicEntity

class BehaviorManager:
    """Manages AI states, behavior graphs, and condition evaluation."""
    
    def __init__(self, vocab: Dict[str, Any], rules_collection: Any, world_states: Any, condition_registry: Dict[str, Any]):
        self.vocab = vocab
        self.rules = rules_collection
        self.world_states = world_states
        self.condition_registry = condition_registry
        
        self.behavior_state_names = []
        self.behavior_graphs = {}
        self._load_behavior_model()

    def _load_behavior_model(self):
        """Load behavior model from vocabulary and rules"""
        self.behavior_state_names = self.vocab.get('ai_states', ['IDLE', 'PATROLLING', 'RESTING', 'COMBAT', 'FLEEING'])
        self.behavior_state_names = [s.lower() for s in self.behavior_state_names]
        
        self.behavior_graphs = {}
        for rule in self.rules.get_all():
            rule_data = rule.to_dict()
            if rule_data.get('type') == 'behavior_graph':
                graph_id = rule_data.get('id', 'default')
                self.behavior_graphs[graph_id] = {
                    'nodes': rule_data.get('graph_nodes', []),
                    'edges': rule_data.get('graph_edges', [])
                }

    def get_behavior_graph(self, char: DynamicEntity) -> Dict[str, Any]:
        graph_id = char.get('behavior_graph_id', 'default')
        return self.behavior_graphs.get(graph_id, {})
    
    def get_behavior_state(self, char: DynamicEntity) -> str:
        return char.get('ai_state', 'IDLE').lower()
    
    def set_behavior_state(self, char: DynamicEntity, state: str):
        char.set('ai_state', state.upper())
    
    def get_possible_transitions(self, char: DynamicEntity) -> List[Dict[str, Any]]:
        behavior_graph = self.get_behavior_graph(char)
        if not behavior_graph:
            return []
        
        current_state = self.get_behavior_state(char)
        edges = behavior_graph.get('edges', [])
        status = char.get('status_variables', {})
        flags = self.world_states.get('persistent_flags', {})
        
        possible = []
        for edge in edges:
            if edge.get('from') == current_state:
                condition = edge.get('condition', 'true')
                if self.evaluate_condition(condition, char, status, flags):
                    possible.append({
                        'to': edge.get('to'),
                        'weight': edge.get('weight', 0.5),
                        'condition': condition
                    })
        
        return possible
    
    def evaluate_condition(self, condition: str, char: DynamicEntity, status: Dict, flags: Dict) -> bool:
        if condition == 'true':
            return True
        
        if ' AND ' in condition:
            parts = condition.split(' AND ')
            return all(self.evaluate_condition(p.strip(), char, status, flags) for p in parts)
        
        if ' OR ' in condition:
            parts = condition.split(' OR ')
            return any(self.evaluate_condition(p.strip(), char, status, flags) for p in parts)
        
        if condition.startswith('NOT '):
            return not self.evaluate_condition(condition[4:], char, status, flags)
        
        for op in [' >= ', ' <= ', ' > ', ' < ', ' == ', ' != ']:
            if op in condition:
                parts = condition.split(op)
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    
                    left_val = self._get_condition_value(left, char, status, flags)
                    right_val = self._get_condition_value(right, char, status, flags)
                    
                    if op == ' > ': return left_val > right_val
                    elif op == ' < ': return left_val < right_val
                    elif op == ' >= ': return left_val >= right_val
                    elif op == ' <= ': return left_val <= right_val
                    elif op == ' == ': return left_val == right_val
                    elif op == ' != ': return left_val != right_val
        
        if condition in self.condition_registry:
            reg_entry = self.condition_registry[condition]
            reg_type = reg_entry.get('type')
            
            if reg_type == 'flag':
                flag_name = reg_entry.get('flag_name', condition)
                return flags.get(flag_name, False)
            elif reg_type == 'state':
                state_key = reg_entry.get('state_key', condition)
                return char.get(state_key, False)
            elif reg_type == 'function':
                eval_str = reg_entry.get('evaluation', 'False')
                eval_str = self._resolve_function_calls(eval_str, char, status, flags)
                try:
                    return eval(eval_str, {}, {'__builtins__': {}})
                except:
                    return False
        
        if condition in status:
            return status[condition] > 0
        
        return char.get(condition, False)
    
    def _get_condition_value(self, key: str, char: DynamicEntity, status: Dict, flags: Dict) -> Any:
        try:
            return float(key)
        except ValueError:
            pass
        
        if key in status:
            return status[key]
        if key in flags:
            return flags[key]
        
        if key in self.condition_registry:
            reg_entry = self.condition_registry[key]
            reg_type = reg_entry.get('type')
            if reg_type == 'flag':
                flag_name = reg_entry.get('flag_name', key)
                return flags.get(flag_name, False)
            elif reg_type == 'state':
                state_key = reg_entry.get('state_key', key)
                return char.get(state_key, False)
        
        return char.get(key, 0)
    
    def _resolve_function_calls(self, expr: str, char: DynamicEntity, status: Dict, flags: Dict) -> str:
        pattern = r'len\(([^)]+)\)'
        matches = re.findall(pattern, expr)
        for match in matches:
            value = self._get_condition_value(match.strip(), char, status, flags)
            if isinstance(value, list):
                expr = expr.replace(f'len({match})', str(len(value)))
            else:
                expr = expr.replace(f'len({match})', '0')
        
        pattern = r'any\(([^)]+)\)'
        matches = re.findall(pattern, expr)
        for match in matches:
            if ' == ' in match:
                parts = match.split(' == ')
                if len(parts) == 2:
                    collection = parts[0].strip()
                    target = parts[1].strip()
                    value = self._get_condition_value(collection, char, status, flags)
                    if isinstance(value, list):
                        expr = expr.replace(f'any({match})', str(any(str(target) in str(item) for item in value)))
                    else:
                        expr = expr.replace(f'any({match})', 'False')
            else:
                collection = match.strip()
                value = self._get_condition_value(collection, char, status, flags)
                if isinstance(value, list):
                    expr = expr.replace(f'any({match})', str(len(value) > 0))
                else:
                    expr = expr.replace(f'any({match})', 'False')
        
        return expr
    
    def select_next_behavior_state(self, char: DynamicEntity) -> Optional[str]:
        possible = self.get_possible_transitions(char)
        if not possible:
            return None
        
        total_weight = sum(p.get('weight', 0.5) for p in possible)
        if total_weight == 0:
            return None
        
        rand = random.random() * total_weight
        cumulative = 0
        for transition in possible:
            cumulative += transition.get('weight', 0.5)
            if rand <= cumulative:
                return transition.get('to')
        
        return possible[-1].get('to')