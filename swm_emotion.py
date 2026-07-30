#!/usr/bin/env python3
"""
SWM Emotion Module - Encapsulates emotion handling, appraisals, and Ekman models
"""

import time
from typing import Dict, Any, Tuple
from swm_corpus_loader import DynamicEntity

class EmotionManager:
    """Manages emotional states, appraisals, and tendencies for characters."""
    
    def __init__(self, vocab: Dict[str, Any], rules_collection: Any):
        self.vocab = vocab
        self.rules = rules_collection
        self.ekman_emotions = []
        self.emotion_appraisals = {}
        self.emotion_appraisal_map = {}
        self._load_emotion_model()

    def _load_emotion_model(self):
        """Load emotion model from vocabulary and rules"""
        self.ekman_emotions = self.vocab.get('ekman_emotions', ['anger', 'fear', 'disgust', 'sadness', 'joy', 'surprise'])
        
        self.emotion_appraisals = {}
        for rule in self.rules.get_all():
            rule_data = rule.to_dict()
            if rule_data.get('type') == 'emotion':
                emotion_mapping = rule_data.get('emotion_mapping', {})
                for emotion, config in emotion_mapping.items():
                    self.emotion_appraisals[emotion] = {
                        'to_state': config.get('to_state', 'idle'),
                        'priority': config.get('priority', 3),
                        'arousal': config.get('arousal', 'medium')
                    }
        
        if not self.emotion_appraisals:
            default_appraisals = {
                'anger': {'to_state': 'combat', 'priority': 5, 'arousal': 'high'},
                'fear': {'to_state': 'flee', 'priority': 4, 'arousal': 'high'},
                'disgust': {'to_state': 'flee', 'priority': 3, 'arousal': 'medium'},
                'sadness': {'to_state': 'rest', 'priority': 2, 'arousal': 'low'},
                'joy': {'to_state': 'socialize', 'priority': 4, 'arousal': 'high'},
                'surprise': {'to_state': 'explore', 'priority': 3, 'arousal': 'medium'}
            }
            for emotion, config in default_appraisals.items():
                if emotion not in self.emotion_appraisals:
                    self.emotion_appraisals[emotion] = config
        
        self.emotion_appraisal_map = self.vocab.get('emotion_appraisal_map', {
            'goal_blocked': 'anger',
            'threat_detected': 'fear',
            'contamination_detected': 'disgust',
            'loss_experienced': 'sadness',
            'goal_achieved': 'joy',
            'novelty_detected': 'surprise'
        })

    def get_character_emotion(self, char: DynamicEntity) -> str:
        status = char.get('status_variables', {})
        return status.get('current_emotion', 'neutral')
    
    def set_character_emotion(self, char: DynamicEntity, emotion: str, intensity: float = 0.5):
        if emotion not in self.ekman_emotions:
            emotion = 'neutral'
        
        status = char.get('status_variables', {})
        status['current_emotion'] = emotion
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
    
    def compute_emotion_from_appraisal(self, char: DynamicEntity, event_type: str) -> Tuple[str, float]:
        emotion = self.emotion_appraisal_map.get(event_type, 'neutral')
        reasoning = char.get('memory_perception', {}).get('reasoning_stack', {})
        intensity = reasoning.get('emotion_intensity', 0.5)
        
        intensity_adjustments = self.vocab.get('emotion_intensity_adjustments', {})
        status = char.get('status_variables', {})
        if status:
            if 'health_low' in intensity_adjustments and status.get('health', 50) < 30:
                intensity = min(1.0, intensity + intensity_adjustments['health_low'])
            if 'stamina_low' in intensity_adjustments and status.get('stamina', 50) < 30:
                intensity = min(1.0, intensity + intensity_adjustments['stamina_low'])
            if 'health_high' in intensity_adjustments and status.get('health', 50) > 70:
                intensity = max(0.1, intensity - intensity_adjustments['health_high'])
            if 'stamina_high' in intensity_adjustments and status.get('stamina', 50) > 70:
                intensity = max(0.1, intensity - intensity_adjustments['stamina_high'])
        
        return emotion, intensity
    
    def get_emotion_action_tendency(self, emotion: str) -> str:
        appraisal = self.emotion_appraisals.get(emotion, {})
        return appraisal.get('to_state', 'idle')
    
    def get_emotion_arousal(self, emotion: str) -> str:
        appraisal = self.emotion_appraisals.get(emotion, {})
        return appraisal.get('arousal', 'medium')