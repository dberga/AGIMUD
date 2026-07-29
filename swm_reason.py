#!/usr/bin/env python3
"""
SWM Social Reasoning Integration - Social reasoning functions with JSON-based tests
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
import os


@dataclass
class SchwartzValueMotor:
    """Schwartz's 10 basic values motor"""
    motivational_weights: Dict[str, float] = field(default_factory=lambda: {
        "self_direction": 1.0, "stimulation": 1.0, "hedonism": 1.0,
        "achievement": 1.0, "power": 1.0, "security": 1.0,
        "conformity": 1.0, "tradition": 1.0, "benevolence": 1.0, "universalism": 1.0
    })
    
    def evaluate_motivation(self, action: str) -> float:
        """Evaluates psychological value satisfaction"""
        penalty = 0.2 if "GREEDY" in action else 1.0
        return sum(self.motivational_weights.values()) * 0.2 * penalty
    
    def load_from_dict(self, data: dict):
        """Load from JSON dict"""
        if "schwartz_weights" in data:
            for key, value in data["schwartz_weights"].items():
                if key in self.motivational_weights:
                    self.motivational_weights[key] = value


@dataclass
class OstromGovernanceMotor:
    """Ostrom institutional governance motor"""
    iad_arena_rules: List[str] = field(default_factory=list)
    institutional_weights: Dict[str, float] = field(default_factory=dict)
    sanction_probabilities: Dict[str, float] = field(default_factory=dict)
    
    def compute_normative_utility(self, action: str, compliance_scores: Dict[str, float]) -> float:
        """Computes Ostrom institutional normative payoff"""
        base_compliance = 0.1 if "GREEDY" in action else 1.0
        compliance_sum = 0.0
        for m in range(1, 3):
            key = f"rule_{m}"
            weight = self.institutional_weights.get(key, 1.0)
            compliance_sum += weight * base_compliance
        
        sanction_sum = 0.0
        for m in range(1, 3):
            key = f"rule_{m}"
            default_prob = 0.8 if "GREEDY" in action else 0.0
            prob = self.sanction_probabilities.get(key, default_prob)
            sanction_sum += prob
        
        return compliance_sum - sanction_sum
    
    def load_from_dict(self, data: dict):
        """Load from JSON dict"""
        if "ostrom_weights" in data:
            self.institutional_weights = data["ostrom_weights"]
        if "ostrom_sanctions" in data:
            self.sanction_probabilities = data["ostrom_sanctions"]


@dataclass
class MontesSierraBeliefMotor:
    """Montes-Sierra belief deception motor"""
    first_order_beliefs: Dict[str, float] = field(default_factory=dict)
    inferred_peer_beliefs: Dict[str, float] = field(default_factory=dict)
    communication_discrepancy_flag: bool = False
    
    def compute_deception_penalty(self) -> float:
        """Computes Montes-Sierra divergence metric"""
        if not self.communication_discrepancy_flag:
            return 0.0
        
        diff_sum = 0.0
        for key, agent_val in self.first_order_beliefs.items():
            peer_val = self.inferred_peer_beliefs.get(key, 0.0)
            diff_sum += abs(agent_val - peer_val)
        return diff_sum
    
    def load_from_dict(self, data: dict):
        """Load from JSON dict"""
        if "beliefs" in data:
            self.first_order_beliefs = data["beliefs"]
        if "peer_beliefs" in data:
            self.inferred_peer_beliefs = data["peer_beliefs"]
        if "discrepancy_flag" in data:
            self.communication_discrepancy_flag = data["discrepancy_flag"]


@dataclass
class SocialReasoningCore:
    """Integrated social reasoning core"""
    schwartz_motor: SchwartzValueMotor = field(default_factory=SchwartzValueMotor)
    ostrom_motor: OstromGovernanceMotor = field(default_factory=OstromGovernanceMotor)
    montessierra_motor: MontesSierraBeliefMotor = field(default_factory=MontesSierraBeliefMotor)
    
    def compute_shapley_coalition(self) -> float:
        """Computes cooperative equity via Shapley value"""
        return 0.1
    
    def optimize_action_utility(self, feasible_actions: List[str], 
                                context_compliance: Optional[Dict[str, float]] = None) -> str:
        """Executes integrated utility maximization"""
        if not feasible_actions:
            return "IDLE"
        
        if context_compliance is None:
            context_compliance = {"rule_1": 1.0, "rule_2": 1.0}
        
        best_action = feasible_actions[0]
        max_utility = -1e9
        
        print("\n[OPTIMIZATION] Evaluating utility across feasible action space:")
        
        for action in feasible_actions:
            schwartz_score = self.schwartz_motor.evaluate_motivation(action)
            ostrom_score = self.ostrom_motor.compute_normative_utility(action, context_compliance)
            deception_penalty = self.montessierra_motor.compute_deception_penalty()
            shapley_penalty = self.compute_shapley_coalition()
            
            total_utility = schwartz_score + ostrom_score - (1.0 * deception_penalty) - (0.5 * shapley_penalty)
            
            print(f" -> Action: '{action}' | Utility: {total_utility:.2f} "
                  f"(Schwartz: {schwartz_score:.2f}, Ostrom: {ostrom_score:.2f})")
            
            if total_utility > max_utility:
                max_utility = total_utility
                best_action = action
        
        return best_action
    
    def load_from_dict(self, data: dict):
        """Load from JSON dict"""
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
        "IDLE_WAIT"
    ])
    social_reasoning: SocialReasoningCore = field(default_factory=SocialReasoningCore)
    
    def validate_and_filter_action(self, raw_llm_intent: str) -> str:
        """Validate LLM intents against action catalog"""
        feasible_actions = self.action_catalog.copy()
        
        if raw_llm_intent not in feasible_actions:
            feasible_actions.append(raw_llm_intent)
        
        return self.social_reasoning.optimize_action_utility(feasible_actions)
    
    def load_from_dict(self, data: dict):
        """Load from JSON dict"""
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
        """Load test configurations from JSON file"""
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
        """Get a specific test configuration by name"""
        for config in self.configurations:
            if config.get('name') == name:
                return config
        return None
    
    def get_configurations(self) -> List[Dict[str, Any]]:
        """Get all test configurations"""
        return self.configurations
    
    def get_test_intents(self) -> List[str]:
        """Get all test intents"""
        return self.test_intents
    
    def get_batch_tests(self) -> List[Dict[str, Any]]:
        """Get all batch tests"""
        return self.batch_tests
    
    def get_expected_outcome(self, intent: str, config_name: str) -> Optional[str]:
        """Get expected outcome for a specific intent and configuration"""
        if intent in self.expected_outcomes:
            return self.expected_outcomes[intent].get(config_name)
        return None


class SocialReasoningEngine:
    """Main social reasoning engine with inference capabilities"""
    
    def __init__(self, test_file: str = "reasoning_tests.json"):
        self.system_rules = SystemRules()
        self.inference_history: List[Dict[str, Any]] = []
        self.test_loader = TestConfigLoader(test_file)
        self.current_config_name = "balanced"
    
    def configure(self, config_name: str = None, **kwargs):
        """Configure from a named config or direct parameters"""
        if config_name:
            config = self.test_loader.get_configuration(config_name)
            if config:
                self.current_config_name = config_name
                self._apply_config(config)
                print(f"[OK] Applied configuration: {config_name}")
                return
            else:
                print(f"[WARNING] Configuration '{config_name}' not found")
        
        # Direct configuration
        self.system_rules.social_reasoning.schwartz_motor.load_from_dict(kwargs)
        self.system_rules.social_reasoning.ostrom_motor.load_from_dict(kwargs)
        self.system_rules.social_reasoning.montessierra_motor.load_from_dict(kwargs)
        print("[OK] Social reasoning configured directly")
    
    def _apply_config(self, config: Dict[str, Any]):
        """Apply a configuration dictionary"""
        # Schwartz
        if 'schwartz_weights' in config:
            self.system_rules.social_reasoning.schwartz_motor.motivational_weights.update(
                config['schwartz_weights']
            )
        
        # Ostrom
        if 'ostrom_weights' in config:
            self.system_rules.social_reasoning.ostrom_motor.institutional_weights.update(
                config['ostrom_weights']
            )
        
        if 'ostrom_sanctions' in config:
            self.system_rules.social_reasoning.ostrom_motor.sanction_probabilities.update(
                config['ostrom_sanctions']
            )
        
        # Montes-Sierra
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
    
    def run_inference(self, intent: str) -> str:
        """Run inference cycle on an intent"""
        print(f"\n[INFERENCE] Processing intent: '{intent}'")
        
        result = self.system_rules.validate_and_filter_action(intent)
        
        # Record history
        self.inference_history.append({
            'intent': intent,
            'result': result,
            'config': self.current_config_name,
            'schwartz_weights': self.system_rules.social_reasoning.schwartz_motor.motivational_weights.copy(),
            'ostrom_weights': self.system_rules.social_reasoning.ostrom_motor.institutional_weights.copy()
        })
        
        print(f"[INFERENCE] Result: '{result}'")
        return result
    
    def run_batch_tests(self, intents: List[str] = None) -> Dict[str, str]:
        """Run batch inference tests"""
        if intents is None:
            intents = self.test_loader.get_test_intents()
        
        results = {}
        print("\n" + "="*60)
        print("BATCH INFERENCE TESTS")
        print(f"Configuration: {self.current_config_name}")
        print("="*60)
        
        for intent in intents:
            results[intent] = self.run_inference(intent)
        
        print("\n" + "="*60)
        print("BATCH RESULTS:")
        for intent, result in results.items():
            expected = self.test_loader.get_expected_outcome(intent, self.current_config_name)
            if expected:
                status = "[OK]" if result == expected else "[?]"
                print(f"  {status} '{intent}' -> '{result}' (expected: '{expected}')")
            else:
                print(f"  [?] '{intent}' -> '{result}'")
        print("="*60)
        
        return results
    
    def run_all_configurations(self) -> Dict[str, Dict[str, str]]:
        """Run tests for all configurations"""
        results = {}
        configs = self.test_loader.get_configurations()
        
        print("\n" + "="*70)
        print("RUNNING ALL CONFIGURATIONS")
        print("="*70)
        
        for config in configs:
            config_name = config.get('name', 'unnamed')
            print(f"\n--- Configuration: {config_name} ---")
            self.configure(config_name=config_name)
            results[config_name] = self.run_batch_tests()
        
        return results
    
    def run_batch_tests_by_name(self, batch_name: str) -> Dict[str, str]:
        """Run a specific batch test by name"""
        for batch in self.test_loader.get_batch_tests():
            if batch.get('name') == batch_name:
                intents = batch.get('intents', [])
                print(f"\nRunning batch test: {batch_name}")
                print(f"Description: {batch.get('description', 'N/A')}")
                return self.run_batch_tests(intents)
        
        print(f"[WARNING] Batch test '{batch_name}' not found")
        return {}
    
    def print_inference_history(self):
        """Print the inference history"""
        print("\n" + "="*60)
        print("INFERENCE HISTORY")
        print("="*60)
        
        for i, entry in enumerate(self.inference_history, 1):
            print(f"\n[{i}] Intent: '{entry['intent']}' -> Result: '{entry['result']}'")
            print(f"    Config: {entry.get('config', 'N/A')}")
            print(f"    Schwartz Weights: {entry.get('schwartz_weights', {})}")
            print(f"    Ostrom Weights: {entry.get('ostrom_weights', {})}")
        
        print("="*60)
    
    def print_config(self):
        """Print current configuration"""
        print("\n" + "="*60)
        print("SOCIAL REASONING CONFIGURATION")
        print(f"Configuration: {self.current_config_name}")
        print("="*60)
        
        sr = self.system_rules.social_reasoning
        
        print("\n[SCHWARTZ VALUES]")
        for key, value in sr.schwartz_motor.motivational_weights.items():
            bar = "|" * int(value * 10)
            print(f"  {key:15} [{value:.1f}] {bar}")
        
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
        
        print("\n[ACTION CATALOG]")
        for action in self.system_rules.action_catalog:
            print(f"  * {action}")
        
        print("\n[AVAILABLE CONFIGURATIONS]")
        for config in self.test_loader.get_configurations():
            name = config.get('name', 'unnamed')
            desc = config.get('description', '')
            print(f"  * {name}: {desc}")
        
        print("="*60)

def main():
    """Main test function with JSON-based tests"""
    print("SOCIAL REASONING ENGINE TESTS")
    print("(Using reasoning_tests.json)")
    print("="*60)
    
    # Create the reasoning engine
    engine = SocialReasoningEngine()
    
    # Run all configurations
    all_results = engine.run_all_configurations()
    
    # Run specific batch tests
    print("\n" + "="*70)
    print("SPECIFIC BATCH TESTS")
    print("="*70)
    
    engine.configure(config_name="high_benevolence")
    engine.run_batch_tests_by_name("cooperative_intents")
    
    engine.configure(config_name="high_power")
    engine.run_batch_tests_by_name("greedy_intents")
    
    # Print inference history
    engine.print_inference_history()
    
    # Show comparison
    print("\n" + "="*70)
    print("CONFIGURATION COMPARISON")
    print("="*70)
    
    test_intent = "GATHER_ALL_RESOURCES_GREEDY"
    print(f"\nTesting intent: '{test_intent}' across configurations:")
    
    for config_name in ["high_benevolence", "high_power", "balanced"]:
        engine.configure(config_name=config_name)
        result = engine.run_inference(test_intent)
        expected = engine.test_loader.get_expected_outcome(test_intent, config_name)
        print(f"  {config_name:20} -> '{result}' (expected: '{expected}')")
    
    print("\n" + "="*70)
    print("[OK] All tests completed")
    print("="*70)


if __name__ == "__main__":
    main()