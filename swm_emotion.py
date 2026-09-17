#!/usr/bin/env python3
"""
SWM Emotion Module - Encapsulates emotion handling, appraisals, and Ekman models
"""

import os
import json
import time
from typing import Dict, Any, Tuple, List, Optional
from swm_corpus_loader import DynamicEntity, DynamicEntityCollection


class EmotionTestLoader:
    """Load emotion test configurations from JSON"""
    
    def __init__(self, test_file: str = "emotion_tests.json"):
        self.test_file = test_file
        self.configurations = []
        self.test_events = []
        self.status_test_cases = []
        self.memory_sequence = []
        self.emotion_sequence = []
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
            self.test_events = data.get('test_events', [])
            self.status_test_cases = data.get('status_test_cases', [])
            self.memory_sequence = data.get('memory_sequence', [])
            self.emotion_sequence = data.get('emotion_sequence', [])
            self.expected_outcomes = data.get('expected_outcomes', {})
            
            print(f"[OK] Loaded {len(self.configurations)} emotion configurations")
            print(f"[OK] Loaded {len(self.test_events)} test events")
            print(f"[OK] Loaded {len(self.status_test_cases)} status test cases")
            
        except Exception as e:
            print(f"[ERROR] Failed to load test file: {e}")
    
    def get_configuration(self, name: str) -> Optional[Dict[str, Any]]:
        for config in self.configurations:
            if config.get('name') == name:
                return config
        return None
    
    def get_configurations(self) -> List[Dict[str, Any]]:
        return self.configurations


class EmotionManager:
    """Manages emotional states, appraisals, and tendencies for characters."""
    
    def __init__(self, vocab: Dict[str, Any], rules_collection: Any = None, test_file: str = "emotion_tests.json"):
        self.vocab = vocab
        self.rules = rules_collection
        self.test_loader = EmotionTestLoader(test_file)
        self.current_config_name = "default"
        
        self.ekman_emotions = []
        self.emotion_appraisals = {}
        self.emotion_appraisal_map = {}
        self.intensity_adjustments = {}
        self.event_base_intensities = {}
        self.global_intensity_multiplier = 1.0
        
        self._load_emotion_model()
        self._apply_config("default")
    
    def _load_emotion_model(self):
        """Load emotion model from vocabulary and rules"""
        self.ekman_emotions = self.vocab.get('ekman_emotions', ['anger', 'fear', 'disgust', 'sadness', 'joy', 'surprise'])
        
        self.emotion_appraisals = {}
        if self.rules:
            if hasattr(self.rules, 'get_all'):
                for rule in self.rules.get_all():
                    rule_data = rule.to_dict() if hasattr(rule, 'to_dict') else rule
                    if isinstance(rule_data, dict) and rule_data.get('type') == 'emotion':
                        emotion_mapping = rule_data.get('emotion_mapping', {})
                        for emotion, config in emotion_mapping.items():
                            self.emotion_appraisals[emotion] = {
                                'to_state': config.get('to_state', 'idle'),
                                'priority': config.get('priority', 3),
                                'arousal': config.get('arousal', 'medium')
                            }
            elif isinstance(self.rules, list):
                for rule in self.rules:
                    if isinstance(rule, dict) and rule.get('type') == 'emotion':
                        emotion_mapping = rule.get('emotion_mapping', {})
                        for emotion, config in emotion_mapping.items():
                            self.emotion_appraisals[emotion] = {
                                'to_state': config.get('to_state', 'idle'),
                                'priority': config.get('priority', 3),
                                'arousal': config.get('arousal', 'medium')
                            }
        
        if not self.emotion_appraisals:
            self.emotion_appraisals = {
                'anger': {'to_state': 'combat', 'priority': 5, 'arousal': 'high'},
                'fear': {'to_state': 'flee', 'priority': 4, 'arousal': 'high'},
                'disgust': {'to_state': 'flee', 'priority': 3, 'arousal': 'medium'},
                'sadness': {'to_state': 'rest', 'priority': 2, 'arousal': 'low'},
                'joy': {'to_state': 'socialize', 'priority': 4, 'arousal': 'high'},
                'surprise': {'to_state': 'explore', 'priority': 3, 'arousal': 'medium'}
            }
        
        self.emotion_appraisal_map = self.vocab.get('emotion_appraisal_map', {
            'goal_blocked': 'anger',
            'threat_detected': 'fear',
            'contamination_detected': 'disgust',
            'loss_experienced': 'sadness',
            'goal_achieved': 'joy',
            'novelty_detected': 'surprise'
        })
        
        # Default base intensities per event
        self.event_base_intensities = {
            'goal_blocked': 0.65,
            'threat_detected': 0.70,
            'contamination_detected': 0.55,
            'loss_experienced': 0.60,
            'goal_achieved': 0.75,
            'novelty_detected': 0.50,
        }
        
        self.global_intensity_multiplier = 1.0
        
        self.intensity_adjustments = self.vocab.get('emotion_intensity_adjustments', {
            'health_low': 0.2,
            'stamina_low': 0.1,
            'health_high': 0.1,
            'stamina_high': 0.1
        })
    
    def _apply_config(self, config_name: str):
        config = self.test_loader.get_configuration(config_name)
        if not config:
            print(f"[WARNING] Configuration '{config_name}' not found, using defaults")
            return
        
        self.current_config_name = config_name
        
        if 'ekman_emotions' in config:
            self.ekman_emotions = config['ekman_emotions']
        
        if 'emotion_appraisal_map' in config:
            self.emotion_appraisal_map = config['emotion_appraisal_map']
        
        if 'event_base_intensities' in config:
            self.event_base_intensities = config['event_base_intensities']
        
        if 'global_intensity_multiplier' in config:
            self.global_intensity_multiplier = config['global_intensity_multiplier']
        
        if 'emotion_intensity_adjustments' in config:
            self.intensity_adjustments = config['emotion_intensity_adjustments']
        
        if 'emotion_appraisals' in config:
            self.emotion_appraisals = config['emotion_appraisals']
        
        print(f"[OK] Applied emotion configuration: {config_name}")
    
    def configure(self, config_name: str = None, **kwargs):
        if config_name:
            self._apply_config(config_name)
        else:
            if 'ekman_emotions' in kwargs:
                self.ekman_emotions = kwargs['ekman_emotions']
            if 'emotion_appraisal_map' in kwargs:
                self.emotion_appraisal_map = kwargs['emotion_appraisal_map']
            if 'event_base_intensities' in kwargs:
                self.event_base_intensities = kwargs['event_base_intensities']
            if 'global_intensity_multiplier' in kwargs:
                self.global_intensity_multiplier = kwargs['global_intensity_multiplier']
            if 'emotion_intensity_adjustments' in kwargs:
                self.intensity_adjustments = kwargs['emotion_intensity_adjustments']
            if 'emotion_appraisals' in kwargs:
                self.emotion_appraisals = kwargs['emotion_appraisals']
            print("[OK] Emotion model configured directly")
    
    def get_character_emotion(self, char: DynamicEntity) -> str:
        status = char.get('status_variables', {})
        return status.get('current_emotion', 'neutral')
    
    def set_character_emotion(self, char, emotion, intensity=0.5, duration_ticks=1):
        if emotion not in self.ekman_emotions:
            emotion = 'neutral'
        status = char.get('status_variables', {})
        status['current_emotion'] = emotion
        status['emotion_intensity'] = intensity
        status['emotion_expires_at'] = getattr(self, '_current_tick', 0) + duration_ticks
        char.set('status_variables', status)
        
        memory = char.get('memory_perception', {})
        reasoning = memory.get('reasoning_stack', {})
        reasoning['emotional_state'] = emotion
        reasoning['emotion_intensity'] = min(1.0, max(0.0, intensity))
        
        if 'emotional_memory' not in reasoning:
            reasoning['emotional_memory'] = []
        reasoning['emotional_memory'].append({
            'emotion': emotion,
            'intensity': intensity,
            'timestamp': time.time()
        })
        if len(reasoning['emotional_memory']) > 20:
            reasoning['emotional_memory'] = reasoning['emotional_memory'][-20:]
        
        memory['reasoning_stack'] = reasoning
        char.set('memory_perception', memory)
    def tick_emotion_decay(self, char, current_tick):
        """Decay emotion over time; when expired, drift toward neutral."""
        status = char.get('status_variables', {})
        emotion = status.get('current_emotion', 'neutral')
        expires_at = status.get('emotion_expires_at', 0)
        intensity = status.get('emotion_intensity', 0.5)
        
        if emotion == 'neutral':
            return
        
        if current_tick >= expires_at:
            # Decay intensity first
            new_intensity = max(0.1, intensity - 0.15)
            if new_intensity <= 0.15:
                status['current_emotion'] = 'neutral'
                status['emotion_intensity'] = 0.0
                status['emotion_expires_at'] = 0
            else:
                status['emotion_intensity'] = new_intensity
                # Extend a bit
                status['emotion_expires_at'] = current_tick + 5
        char.set('status_variables', status)
    
    def compute_emotion_from_appraisal(self, char: DynamicEntity, event_type: str) -> Tuple[str, float]:
        """Compute emotion and intensity from an event."""
        emotion = self.emotion_appraisal_map.get(event_type, 'neutral')
        
        # Get base intensity for this event type
        base_intensity = self.event_base_intensities.get(event_type, 0.5)
        
        # Apply global intensity multiplier (personality factor)
        intensity = base_intensity * self.global_intensity_multiplier
        
        # Apply status-based modulation
        status = char.get('status_variables', {})
        if status:
            if 'health_low' in self.intensity_adjustments and status.get('health', 50) < 30:
                intensity = min(1.0, intensity + self.intensity_adjustments['health_low'])
            if 'stamina_low' in self.intensity_adjustments and status.get('stamina', 50) < 30:
                intensity = min(1.0, intensity + self.intensity_adjustments['stamina_low'])
            if 'health_high' in self.intensity_adjustments and status.get('health', 50) > 70:
                intensity = max(0.1, intensity - self.intensity_adjustments['health_high'])
            if 'stamina_high' in self.intensity_adjustments and status.get('stamina', 50) > 70:
                intensity = max(0.1, intensity - self.intensity_adjustments['stamina_high'])
        
        # Clamp intensity
        intensity = min(1.0, max(0.1, intensity))
        
        # Also consider previous emotion intensity (emotional momentum)
        reasoning = char.get('memory_perception', {}).get('reasoning_stack', {})
        prev_intensity = reasoning.get('emotion_intensity', 0.5)
        
        # Blend: 70% new intensity, 30% previous intensity (emotional persistence)
        final_intensity = 0.7 * intensity + 0.3 * prev_intensity
        final_intensity = min(1.0, max(0.1, final_intensity))
        
        return emotion, final_intensity
    
    def get_emotion_action_tendency(self, emotion: str) -> str:
        appraisal = self.emotion_appraisals.get(emotion, {})
        return appraisal.get('to_state', 'idle')
    
    def get_emotion_arousal(self, emotion: str) -> str:
        appraisal = self.emotion_appraisals.get(emotion, {})
        return appraisal.get('arousal', 'medium')
    
    def print_config(self):
        print("\n" + "="*60)
        print("EMOTION CONFIGURATION")
        print(f"Configuration: {self.current_config_name}")
        print("="*60)
        
        print("\n[EKMAN EMOTIONS]")
        print(f"  {', '.join(self.ekman_emotions)}")
        
        print("\n[APPRAISAL MAP]")
        for event, emotion in self.emotion_appraisal_map.items():
            print(f"  {event:25} -> {emotion}")
        
        print("\n[EVENT BASE INTENSITIES]")
        for event, intensity in self.event_base_intensities.items():
            print(f"  {event:25} -> {intensity:.2f}")
        
        print(f"\n[GLOBAL INTENSITY MULTIPLIER]")
        print(f"  {self.global_intensity_multiplier:.2f}")
        
        print("\n[INTENSITY ADJUSTMENTS]")
        for key, value in self.intensity_adjustments.items():
            print(f"  {key:20} -> {value}")
        
        print("\n[EMOTION APPRAISALS]")
        for emotion, config in self.emotion_appraisals.items():
            print(f"  {emotion:10} -> to_state: {config.get('to_state')}, "
                  f"priority: {config.get('priority')}, arousal: {config.get('arousal')}")
        
        print("="*60)


# ==========================================
# MAIN - Direct Execution Block
# ==========================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='SWM Emotion Module Tests')
    parser.add_argument('--config', type=str, default='default', help='Configuration to use')
    parser.add_argument('--list-configs', action='store_true', help='List available configurations')
    parser.add_argument('--test-file', type=str, default='emotion_tests.json', help='Test configuration file')
    args = parser.parse_args()
    
    print("="*70)
    print("SWM EMOTION MODULE TESTS")
    print(f"(Using {args.test_file})")
    print("="*70)
    
    test_loader = EmotionTestLoader(args.test_file)
    
    if args.list_configs:
        print("\nAvailable Configurations:")
        for config in test_loader.get_configurations():
            print(f"  * {config.get('name')}: {config.get('description', 'N/A')}")
        return
    
    vocab = {}
    rules = DynamicEntityCollection("rules")
    
    emotion_manager = EmotionManager(vocab, rules, args.test_file)
    emotion_manager.configure(config_name=args.config)
    emotion_manager.print_config()
    
    # Create test character with balanced status
    char = DynamicEntity()
    char.set('name', 'TestAgent')
    char.set('status_variables', {
        'health': 50,
        'stamina': 50,
        'current_emotion': 'neutral',
        'morale': 50
    })
    char.set('memory_perception', {
        'reasoning_stack': {
            'emotional_state': 'neutral',
            'emotion_intensity': 0.5,
            'emotional_memory': []
        }
    })
    
    # Test 1: Appraisal
    print("\n" + "-"*70)
    print("TEST 1: Emotion Appraisal from Events")
    print("-"*70)
    
    for event in test_loader.test_events:
        emotion, intensity = emotion_manager.compute_emotion_from_appraisal(char, event)
        expected = test_loader.expected_outcomes.get('appraisal', {}).get(event, 'N/A')
        match = "[OK]" if emotion == expected else "[FAIL]"
        print(f"  {match} Event: '{event:25}' -> Emotion: {emotion:10} (Intensity: {intensity:.2f})")
    
    # Test 2: Intensity Modulation by Status
    print("\n" + "-"*70)
    print("TEST 2: Intensity Modulation by Status Variables")
    print("-"*70)
    
    for case in test_loader.status_test_cases:
        label = case.get('label', 'unknown')
        health = case.get('health', 50)
        stamina = case.get('stamina', 50)
        
        # Reset character with different status
        char.set('status_variables', {
            'health': health,
            'stamina': stamina,
            'current_emotion': 'neutral',
            'morale': 50
        })
        char.set('memory_perception', {
            'reasoning_stack': {
                'emotional_state': 'neutral',
                'emotion_intensity': 0.5,
                'emotional_memory': []
            }
        })
        
        emotion, intensity = emotion_manager.compute_emotion_from_appraisal(char, 'goal_blocked')
        print(f"  Status: {label:25} | Health: {health:3} | Stamina: {stamina:3} -> {emotion:10} (Intensity: {intensity:.2f})")
    
    # Test 3: Emotional Memory Sequence (complete event sequence)
    print("\n" + "-"*70)
    print("TEST 3: Emotional Memory Sequence")
    print("-"*70)
    
    # Reset character
    char.set('status_variables', {
        'health': 50,
        'stamina': 50,
        'current_emotion': 'neutral',
        'morale': 50
    })
    char.set('memory_perception', {
        'reasoning_stack': {
            'emotional_state': 'neutral',
            'emotion_intensity': 0.5,
            'emotional_memory': []
        }
    })
    
    print("  Step | Event                    | Emotion    | Intensity")
    print("  -----|--------------------------|------------|----------")
    
    for i, event in enumerate(test_loader.memory_sequence, 1):
        emotion, intensity = emotion_manager.compute_emotion_from_appraisal(char, event)
        emotion_manager.set_character_emotion(char, emotion, intensity)
        
        # Show the event with its emotion and intensity
        print(f"  {i:4}  | {event:24} | {emotion:10} | {intensity:.2f}")
    
    # Show final emotional memory
    memory = char.get('memory_perception', {})
    reasoning = memory.get('reasoning_stack', {})
    em_memory = reasoning.get('emotional_memory', [])
    
    print("\n  Final Emotional Memory (last 20 entries):")
    for i, entry in enumerate(em_memory):
        print(f"    [{i+1}] {entry['emotion']:10} (Intensity: {entry['intensity']:.2f})")
    
    # Test 4: Action Tendency
    print("\n" + "-"*70)
    print("TEST 4: Emotion-to-Action Tendency Mapping")
    print("-"*70)
    
    for emotion in emotion_manager.ekman_emotions:
        tendency = emotion_manager.get_emotion_action_tendency(emotion)
        arousal = emotion_manager.get_emotion_arousal(emotion)
        print(f"  {emotion:10} -> {tendency:10} (Arousal: {arousal})")
    
    # Test 5: Emotion Sequence (for comparison across configs)
    print("\n" + "-"*70)
    print("TEST 5: Emotion Sequence Over Time")
    print("-"*70)
    
    # Reset character
    char.set('status_variables', {
        'health': 50,
        'stamina': 50,
        'current_emotion': 'neutral',
        'morale': 50
    })
    char.set('memory_perception', {
        'reasoning_stack': {
            'emotional_state': 'neutral',
            'emotion_intensity': 0.5,
            'emotional_memory': []
        }
    })
    
    print("  Step | Event                    | Emotion    | Intensity")
    print("  -----|--------------------------|------------|----------")
    
    for item in test_loader.emotion_sequence:
        event = item.get('event', '')
        step = item.get('step', 0)
        emotion, intensity = emotion_manager.compute_emotion_from_appraisal(char, event)
        emotion_manager.set_character_emotion(char, emotion, intensity)
        print(f"  {step:4}  | {event:24} | {emotion:10} | {intensity:.2f}")
    
    current = emotion_manager.get_character_emotion(char)
    print(f"\n  Final Current Emotion: {current}")
    
    print("\n" + "="*70)
    print("[OK] All emotion tests completed")
    print("="*70)

    # Test 6: Temporal persistence and decay
    print("\n" + "-"*70)
    print("TEST 6: Temporal Persistence and Decay")
    print("-"*70)

    char.set('status_variables', {
        'health': 50, 'stamina': 50,
        'current_emotion': 'neutral', 'morale': 50
    })
    char.set('memory_perception', {
        'reasoning_stack': {
            'emotional_state': 'neutral',
            'emotion_intensity': 0.5,
            'emotional_memory': []
        }
    })

    # Assign a strong emotion at tick 0 with a 40-tick lifetime
    emotion_manager._current_tick = 0
    emotion_manager.set_character_emotion(char, 'joy', 0.67, duration_ticks=40)
    print(f"  t=0  | Set joy (intensity 0.67, expires_at=40)")

    # Advance the clock and decay every tick, no new stimuli
    for tick in range(1, 61):
        emotion_manager.tick_emotion_decay(char, tick)
        if tick in (5, 10, 20, 30, 40, 41, 42, 43, 44, 45, 50, 60):
            status = char.get('status_variables', {})
            em = status.get('current_emotion', '?')
            inten = status.get('emotion_intensity', 0)
            exp = status.get('emotion_expires_at', 0)
            print(f"  t={tick:2} | emotion={em:8} intensity={inten:.2f} expires_at={exp}")
        
if __name__ == "__main__":
    main()