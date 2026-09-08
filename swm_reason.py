#!/usr/bin/env python3
"""
SWM Social Reasoning Integration - Social reasoning functions with JSON-based tests
Enhanced with detailed output and comprehensive configuration support
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
import os
import sys
import random


# Fix Windows console encoding for Unicode
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


@dataclass
class SchwartzValueMotor:
    """Schwartz's 10 basic values motor"""
    motivational_weights: Dict[str, float] = field(default_factory=lambda: {
        "self_direction": 1.0, "stimulation": 1.0, "hedonism": 1.0,
        "achievement": 1.0, "power": 1.0, "security": 1.0,
        "conformity": 1.0, "tradition": 1.0, "benevolence": 1.0, "universalism": 1.0
    })
    action_weights: Dict[str, float] = field(default_factory=dict)
    
    def evaluate_motivation(self, action: str) -> float:
        """Evaluates psychological value satisfaction with action-specific weights"""
        greedy_penalty = 0.2 if any(word in action.upper() for word in ["GREEDY", "SELFISHLY", "AGGRESSIVE"]) else 1.0
        cooperative_bonus = 1.0 if any(word in action.upper() for word in ["SHARE", "COOPERATIVE", "PEACE"]) else 1.0
        
        base_score = sum(self.motivational_weights.values()) * 0.2
        weight = self.action_weights.get(action, 1.0)
        
        return base_score * greedy_penalty * cooperative_bonus * weight
    
    def load_from_dict(self, data: dict):
        if "schwartz_weights" in data:
            for key, value in data["schwartz_weights"].items():
                if key in self.motivational_weights:
                    self.motivational_weights[key] = value
        if "action_weights" in data:
            self.action_weights = data["action_weights"]


@dataclass
class OstromGovernanceMotor:
    """Ostrom institutional governance motor"""
    institutional_weights: Dict[str, float] = field(default_factory=dict)
    sanction_probabilities: Dict[str, float] = field(default_factory=dict)
    action_costs: Dict[str, Dict[str, float]] = field(default_factory=dict)
    action_rewards: Dict[str, float] = field(default_factory=dict)
    
    def compute_normative_utility(self, action: str, compliance_scores: Dict[str, float]) -> float:
        violates_rules = any(word in action.upper() for word in ["GREEDY", "AGGRESSIVE", "SELFISHLY", "WAR"])
        
        base_compliance = 0.1 if violates_rules else 1.0
        
        compliance_sum = 0.0
        for m in range(1, 3):
            key = f"rule_{m}"
            weight = self.institutional_weights.get(key, 1.0)
            compliance_sum += weight * base_compliance
            
            if action in self.action_costs and key in self.action_costs[action]:
                compliance_sum -= self.action_costs[action][key]
        
        sanction_sum = 0.0
        for m in range(1, 3):
            key = f"rule_{m}"
            default_prob = 0.8 if violates_rules else 0.0
            prob = self.sanction_probabilities.get(key, default_prob)
            sanction_sum += prob
        
        reward = self.action_rewards.get(action, 0.0)
        
        return compliance_sum - sanction_sum + reward
    
    def load_from_dict(self, data: dict):
        if "ostrom_weights" in data:
            self.institutional_weights = data["ostrom_weights"]
        if "ostrom_sanctions" in data:
            self.sanction_probabilities = data["ostrom_sanctions"]
        if "action_costs" in data:
            self.action_costs = data["action_costs"]
        if "action_rewards" in data:
            self.action_rewards = data["action_rewards"]


@dataclass
class MontesSierraBeliefMotor:
    """Montes-Sierra belief deception motor - Action-specific"""
    first_order_beliefs: Dict[str, float] = field(default_factory=dict)
    inferred_peer_beliefs: Dict[str, float] = field(default_factory=dict)
    communication_discrepancy_flag: bool = False
    action_belief_penalties: Dict[str, float] = field(default_factory=dict)
    
    def compute_deception_penalty(self, action: str = None) -> float:
        if not self.communication_discrepancy_flag:
            return 0.0
        
        diff_sum = 0.0
        common_keys = set(self.first_order_beliefs.keys()) & set(self.inferred_peer_beliefs.keys())
        for key in common_keys:
            agent_val = self.first_order_beliefs.get(key, 0.0)
            peer_val = self.inferred_peer_beliefs.get(key, 0.0)
            diff_sum += abs(agent_val - peer_val)
        
        if len(common_keys) == 0:
            base_penalty = 2.0 * len(self.first_order_beliefs)
        else:
            base_penalty = diff_sum
        
        if action and action in self.action_belief_penalties:
            base_penalty *= self.action_belief_penalties[action]
        elif action:
            if any(word in action.upper() for word in ["GREEDY", "AGGRESSIVE", "SELFISHLY", "WAR"]):
                base_penalty *= 1.5
            elif any(word in action.upper() for word in ["SHARE", "COOPERATIVE", "PEACE"]):
                base_penalty *= 0.3
            else:
                base_penalty *= 1.0
        
        return base_penalty
    
    def load_from_dict(self, data: dict):
        if "beliefs" in data:
            self.first_order_beliefs = data["beliefs"]
        if "peer_beliefs" in data:
            self.inferred_peer_beliefs = data["peer_beliefs"]
        if "discrepancy_flag" in data:
            self.communication_discrepancy_flag = data["discrepancy_flag"]
        if "action_belief_penalties" in data:
            self.action_belief_penalties = data["action_belief_penalties"]


@dataclass
class SocialReasoningCore:
    """Integrated social reasoning core"""
    schwartz_motor: SchwartzValueMotor = field(default_factory=SchwartzValueMotor)
    ostrom_motor: OstromGovernanceMotor = field(default_factory=OstromGovernanceMotor)
    montessierra_motor: MontesSierraBeliefMotor = field(default_factory=MontesSierraBeliefMotor)
    last_utilities: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    def compute_shapley_coalition(self) -> float:
        return 0.1
    
    def optimize_action_utility(self, feasible_actions: List[str], 
                                context_compliance: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        if not feasible_actions:
            return {"action": "IDLE", "utilities": {}, "all_max_actions": ["IDLE"]}
        
        if context_compliance is None:
            context_compliance = {"rule_1": 1.0, "rule_2": 1.0}
        
        best_action = feasible_actions[0]
        max_utility = -1e9
        utility_tracking = {}
        
        print("\n[OPTIMIZATION] Evaluating utility across feasible action space:")
        
        for action in feasible_actions:
            schwartz_score = self.schwartz_motor.evaluate_motivation(action)
            ostrom_score = self.ostrom_motor.compute_normative_utility(action, context_compliance)
            deception_penalty = self.montessierra_motor.compute_deception_penalty(action)
            shapley_penalty = self.compute_shapley_coalition()
            
            total_utility = schwartz_score + ostrom_score - deception_penalty - (0.5 * shapley_penalty)
            
            utility_tracking[action] = {
                "schwartz": schwartz_score,
                "ostrom": ostrom_score,
                "montes": -deception_penalty,
                "shapley": -0.5 * shapley_penalty,
                "total": total_utility
            }
            
            print(f" -> Action: '{action}' | Utility: {total_utility:.2f} "
                  f"(Schwartz: {schwartz_score:.2f}, Ostrom: {ostrom_score:.2f}, "
                  f"Montes: {-deception_penalty:.2f})")
            
            if total_utility > max_utility:
                max_utility = total_utility
                best_action = action
        
        max_actions = [a for a, u in utility_tracking.items() if abs(u["total"] - max_utility) < 0.001]
        
        self.last_utilities = utility_tracking
        
        return {
            "action": best_action,
            "utility": max_utility,
            "all_max_actions": max_actions,
            "utilities": utility_tracking
        }
    
    def load_from_dict(self, data: dict):
        self.schwartz_motor.load_from_dict(data)
        self.ostrom_motor.load_from_dict(data)
        self.montessierra_motor.load_from_dict(data)


@dataclass
class SystemRules:
    """System rules for action validation"""
    action_catalog: List[str] = field(default_factory=lambda: [
        "GATHER_ALL_RESOURCES_GREEDY",
        "HARVEST_SUSTAINABLE_SHARED",
        "NEGOTIATE_COOPERATIVE_PACT",
        "IDLE_WAIT",
        "ATTACK_ENEMY_GREEDY",
        "SHARE_RESOURCES_WITH_ALLIES",
        "HOARD_RESOURCES_SELFISHLY",
        "PROPOSE_PEACE_TREATY",
        "DECLARE_WAR_AGGRESSIVE"
    ])
    social_reasoning: SocialReasoningCore = field(default_factory=SocialReasoningCore)
    
    def validate_and_filter_action(self, raw_llm_intent: str) -> Dict[str, Any]:
        feasible_actions = self.action_catalog.copy()
        
        if raw_llm_intent not in feasible_actions:
            feasible_actions.append(raw_llm_intent)
        
        return self.social_reasoning.optimize_action_utility(feasible_actions)
    
    def load_from_dict(self, data: dict):
        if "action_catalog" in data:
            self.action_catalog = data["action_catalog"]


class TestConfigLoader:
    """Load test configurations from JSON"""
    
    def __init__(self, test_file: str = "reasoning_tests.json"):
        self.test_file = test_file
        self.configurations = []
        self.test_intents = []
        self.batch_tests = []
        self.expected_outcomes = {}
        self._load_tests()
    
    def _load_tests(self):
        if not os.path.exists(self.test_file):
            print(f"[WARNING] Test file not found: {self.test_file}")
            return
        
        try:
            with open(self.test_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.configurations = data.get('test_configurations', [])
            self.test_intents = data.get('test_intents', [])
            self.batch_tests = data.get('batch_tests', [])
            self.expected_outcomes = data.get('expected_outcomes', {})
            
            print(f"[OK] Loaded {len(self.configurations)} test configurations")
            print(f"[OK] Loaded {len(self.test_intents)} test intents")
            print(f"[OK] Loaded {len(self.batch_tests)} batch tests")
            
        except Exception as e:
            print(f"[ERROR] Failed to load test file: {e}")
    
    def get_configuration(self, name: str) -> Optional[Dict[str, Any]]:
        for config in self.configurations:
            if config.get('name') == name:
                return config
        return None
    
    def get_configurations(self) -> List[Dict[str, Any]]:
        return self.configurations
    
    def get_test_intents(self) -> List[str]:
        return self.test_intents
    
    def get_batch_tests(self) -> List[Dict[str, Any]]:
        return self.batch_tests
    
    def get_expected_outcome(self, intent: str, config_name: str) -> Optional[str]:
        if intent in self.expected_outcomes:
            return self.expected_outcomes[intent].get(config_name)
        return None


class SocialReasoningEngine:
    """Main social reasoning engine with inference capabilities"""
    
    def __init__(self, test_file: str = "reasoning_tests.json"):
        self.system_rules = SystemRules()
        self.inference_history: List[Dict[str, Any]] = []
        self.test_loader = TestConfigLoader(test_file)
        self.current_config_name = "balanced_scenario"
        self.results_matrix = {}
    
    def configure(self, config_name: str = None, **kwargs):
        if config_name:
            config = self.test_loader.get_configuration(config_name)
            if config:
                self.current_config_name = config_name
                self._apply_config(config)
                print(f"[OK] Applied configuration: {config_name}")
                return
            else:
                print(f"[WARNING] Configuration '{config_name}' not found")
        
        self.system_rules.social_reasoning.schwartz_motor.load_from_dict(kwargs)
        self.system_rules.social_reasoning.ostrom_motor.load_from_dict(kwargs)
        self.system_rules.social_reasoning.montessierra_motor.load_from_dict(kwargs)
        print("[OK] Social reasoning configured directly")
    
    def _apply_config(self, config: Dict[str, Any]):
        if 'schwartz_weights' in config:
            self.system_rules.social_reasoning.schwartz_motor.motivational_weights.update(
                config['schwartz_weights']
            )
        if 'action_weights' in config:
            self.system_rules.social_reasoning.schwartz_motor.action_weights = config['action_weights']
        
        if 'ostrom_weights' in config:
            self.system_rules.social_reasoning.ostrom_motor.institutional_weights.update(
                config['ostrom_weights']
            )
        if 'ostrom_sanctions' in config:
            self.system_rules.social_reasoning.ostrom_motor.sanction_probabilities.update(
                config['ostrom_sanctions']
            )
        if 'action_costs' in config:
            self.system_rules.social_reasoning.ostrom_motor.action_costs = config['action_costs']
        if 'action_rewards' in config:
            self.system_rules.social_reasoning.ostrom_motor.action_rewards = config['action_rewards']
        
        if 'beliefs' in config:
            self.system_rules.social_reasoning.montessierra_motor.first_order_beliefs.update(
                config['beliefs']
            )
        if 'peer_beliefs' in config:
            self.system_rules.social_reasoning.montessierra_motor.inferred_peer_beliefs.update(
                config['peer_beliefs']
            )
        if 'discrepancy_flag' in config:
            self.system_rules.social_reasoning.montessierra_motor.communication_discrepancy_flag = \
                config['discrepancy_flag']
        if 'action_belief_penalties' in config:
            self.system_rules.social_reasoning.montessierra_motor.action_belief_penalties = config['action_belief_penalties']
    
    def run_inference(self, intent: str) -> Dict[str, Any]:
        print(f"\n[INFERENCE] Processing intent: '{intent}'")
        
        result = self.system_rules.validate_and_filter_action(intent)
        
        history_entry = {
            'intent': intent,
            'result': result['action'],
            'utility': result['utility'],
            'all_max_actions': result.get('all_max_actions', []),
            'utilities': result.get('utilities', {}),
            'config': self.current_config_name,
            'schwartz_weights': self.system_rules.social_reasoning.schwartz_motor.motivational_weights.copy(),
            'ostrom_weights': self.system_rules.social_reasoning.ostrom_motor.institutional_weights.copy()
        }
        self.inference_history.append(history_entry)
        
        # Store in results matrix
        if self.current_config_name not in self.results_matrix:
            self.results_matrix[self.current_config_name] = {}
        self.results_matrix[self.current_config_name][intent] = result['action']
        
        print(f"[INFERENCE] Result: '{result['action']}' (Utility: {result['utility']:.2f})")
        if len(result.get('all_max_actions', [])) > 1:
            print(f"[INFERENCE] Note: Multiple actions tied at max utility: {result['all_max_actions']}")
        
        return result
    
    def run_batch_tests(self, intents: List[str] = None) -> Dict[str, str]:
        if intents is None:
            intents = self.test_loader.get_test_intents()
        
        results = {}
        print("\n" + "="*60)
        print("BATCH INFERENCE TESTS")
        print(f"Configuration: {self.current_config_name}")
        print("="*60)
        
        for intent in intents:
            result = self.run_inference(intent)
            results[intent] = result['action']
        
        print("\n" + "="*60)
        print("BATCH RESULTS:")
        for intent, result in results.items():
            expected = self.test_loader.get_expected_outcome(intent, self.current_config_name)
            if expected:
                status = "[OK]" if result == expected else "[NO]"
                print(f"  {status} '{intent}' -> '{result}' (expected: '{expected}')")
            else:
                print(f"  [?] '{intent}' -> '{result}'")
        print("="*60)
        
        return results
    
    def run_all_configurations(self) -> Dict[str, Dict[str, str]]:
        """Run tests for ALL configurations from JSON"""
        results = {}
        configs = self.test_loader.get_configurations()
        
        print("\n" + "="*70)
        print("RUNNING ALL CONFIGURATIONS")
        print("="*70)
        
        # Run ALL configurations from the JSON file
        for config in configs:
            config_name = config.get('name', 'unnamed')
            if not config_name:
                continue
            print(f"\n--- Configuration: {config_name} ---")
            self.configure(config_name=config_name)
            results[config_name] = self.run_batch_tests()
        
        print(f"\n[DEBUG] Ran {len(results)} configurations: {list(results.keys())}")
        return results
    
    def run_batch_tests_by_name(self, batch_name: str) -> Dict[str, str]:
        for batch in self.test_loader.get_batch_tests():
            if batch.get('name') == batch_name:
                intents = batch.get('intents', [])
                print(f"\nRunning batch test: {batch_name}")
                print(f"Description: {batch.get('description', 'N/A')}")
                return self.run_batch_tests(intents)
        
        print(f"[WARNING] Batch test '{batch_name}' not found")
        return {}
    
    def print_inference_history(self):
        print("\n" + "="*60)
        print("INFERENCE HISTORY")
        print("="*60)
        
        for i, entry in enumerate(self.inference_history, 1):
            print(f"\n[{i}] Intent: '{entry['intent']}' -> Result: '{entry['result']}'")
            print(f"    Utility: {entry['utility']:.2f}")
            print(f"    Config: {entry.get('config', 'N/A')}")
            if len(entry.get('all_max_actions', [])) > 1:
                print(f"    Tied with: {entry['all_max_actions']}")
            print(f"    Schwartz Weights: {entry.get('schwartz_weights', {})}")
            print(f"    Ostrom Weights: {entry.get('ostrom_weights', {})}")
        
        print("="*60)
    
    def print_config(self):
        print("\n" + "="*60)
        print("SOCIAL REASONING CONFIGURATION")
        print(f"Configuration: {self.current_config_name}")
        print("="*60)
        
        sr = self.system_rules.social_reasoning
        
        print("\n[SCHWARTZ VALUES]")
        for key, value in sr.schwartz_motor.motivational_weights.items():
            bar = "|" * int(value * 10)
            print(f"  {key:15} [{value:.1f}] {bar}")
        
        print("\n[ACTION WEIGHTS]")
        for key, value in sr.schwartz_motor.action_weights.items():
            print(f"  {key:20} -> {value:.2f}")
        
        print("\n[OSTROM INSTITUTIONAL WEIGHTS]")
        for key, value in sr.ostrom_motor.institutional_weights.items():
            print(f"  {key}: {value}")
        
        print("\n[SANCTION PROBABILITIES]")
        for key, value in sr.ostrom_motor.sanction_probabilities.items():
            print(f"  {key}: {value}")
        
        print("\n[MONTES-SIERRA BELIEFS]")
        print(f"  First-order: {sr.montessierra_motor.first_order_beliefs}")
        print(f"  Inferred peers: {sr.montessierra_motor.inferred_peer_beliefs}")
        print(f"  Discrepancy flag: {sr.montessierra_motor.communication_discrepancy_flag}")
        print(f"  Action belief penalties: {sr.montessierra_motor.action_belief_penalties}")
        
        print("\n[ACTION CATALOG]")
        for action in self.system_rules.action_catalog:
            print(f"  * {action}")
        
        print("\n[AVAILABLE CONFIGURATIONS]")
        for config in self.test_loader.get_configurations():
            name = config.get('name', 'unnamed')
            desc = config.get('description', '')
            print(f"  * {name}: {desc}")
        
        print("="*60)
    
    def print_results_matrix(self):
        """Print the full results matrix with proper formatting"""
        print("\n" + "="*80)
        print("FULL RESULTS MATRIX: All Intents x All Configurations")
        print("="*80)
        
        if not self.results_matrix:
            print("No results available. Run inference first.")
            return
        
        # Get configurations from results_matrix keys
        configs = list(self.results_matrix.keys())
        if not configs:
            print("No configurations found.")
            return
        
        # Get all unique intents from all configs
        all_intents = set()
        for config_results in self.results_matrix.values():
            all_intents.update(config_results.keys())
        
        # Print header
        header = "| Intent".ljust(35) + " | "
        for config in configs:
            header += f"{config[:20].ljust(20)} | "
        print(header)
        print("-" * (35 + 3 + len(configs) * 24))
        
        # Print each intent
        for intent in sorted(all_intents):
            row = f"| {intent[:30].ljust(30)} | "
            for config in configs:
                result = self.results_matrix.get(config, {}).get(intent, "N/A")
                expected = self.test_loader.get_expected_outcome(intent, config)
                
                if len(result) > 18:
                    display_result = result[:15] + "..."
                else:
                    display_result = result
                
                if expected and result == expected:
                    row += f"{display_result.ljust(18)}[OK] | "
                elif expected:
                    row += f"{display_result.ljust(18)}[NO] | "
                else:
                    row += f"{display_result.ljust(18)}    | "
            print(row)
        
        print("="*80)
        print("[OK] = matches expected outcome, [NO] = does not match expected outcome")


def main():
    """Main test function with JSON-based tests"""
    print("SOCIAL REASONING ENGINE TESTS")
    print("(Using reasoning_tests.json)")
    print("="*60)
    
    engine = SocialReasoningEngine()
    
    # Run all configurations
    all_results = engine.run_all_configurations()
    
    # Print the results matrix
    engine.print_results_matrix()
    
    # Run specific batch tests
    print("\n" + "="*70)
    print("SPECIFIC BATCH TESTS")
    print("="*70)
    
    engine.configure(config_name="high_benevolence")
    engine.run_batch_tests_by_name("cooperative_intents")
    
    engine.configure(config_name="high_power")
    engine.run_batch_tests_by_name("greedy_intents")
    
    engine.configure(config_name="balanced_scenario")
    engine.run_batch_tests_by_name("mixed_intents")
    
    # Print inference history
    engine.print_inference_history()
    
    # Show comparison
    print("\n" + "="*70)
    print("CONFIGURATION COMPARISON")
    print("="*70)
    
    test_intent = "GATHER_ALL_RESOURCES_GREEDY"
    print(f"\nTesting intent: '{test_intent}' across configurations:")
    
    configs_to_test = ["high_benevolence", "high_power", "balanced_scenario", 
                       "high_belief_discrepancy", "cooperative_utopia"]
    
    for config_name in configs_to_test:
        engine.configure(config_name=config_name)
        result = engine.run_inference(test_intent)
        expected = engine.test_loader.get_expected_outcome(test_intent, config_name)
        status = "[OK]" if result['action'] == expected else "[NO]"
        print(f"  {config_name:20} -> '{result['action']}' (expected: '{expected}') {status}")
    
    print("\n" + "="*70)
    print("[OK] All tests completed")
    print("="*70)


if __name__ == "__main__":
    main()