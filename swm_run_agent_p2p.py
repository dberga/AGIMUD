#!/usr/bin/env python3
"""
SWM Run Agent P2P - AI-powered P2P node that generates chat messages and actions
using local LM Studio models based on world state context.
Supports both Host and Joiner roles.
"""

import sys
import os
# Add lmstudio-wrapper to path for run_lms imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lmstudio-wrapper'))

import json
import time
import argparse
import threading
import glob
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

# Import from swm_run_p2p
from swm_run_p2p import SWMP2PNode, NetworkMessage

# Import LM Studio functions
import lmstudio as lms
from run_lms import LMChat, build_prediction_config, build_load_config


class SimpleArgs:
    """Simple class to mimic argparse.Namespace for build_load_config and build_prediction_config"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class SWMAgentP2PNode(SWMP2PNode):
    """AI-powered P2P node that generates contextual chat and actions"""
    
    def __init__(self, config_file: str = "network_p2p_config.json", role: str = "host", args: Any = None):
        super().__init__(config_file, role, args)
        
        # Agent-specific configuration
        self.character_name: Optional[str] = None
        self.agent_chat_frequency: int = 3
        self.actions_enabled: bool = False
        self.last_chat_epoch: int = 0
        self.last_agent_eval_epoch: int = -1
        self.chat_history: List[Dict[str, str]] = []
        self.max_history: int = 20
        self.show_reasoning: bool = True
        self.chat_style: str = ""
        self.chat_history_file: Optional[str] = None
        self.loaded_chat_history: List[str] = []
        self.initialized: bool = False
        
        # LM Studio configuration
        self.model_key: Optional[str] = None
        self.system_prompt: Optional[str] = None
        self.temperature: float = 0.8
        self.max_tokens: int = 2000
        self.lm_chat: Optional[LMChat] = None
        self.mcp_servers: List[str] = []
        
        self._load_agent_config()
    
    def _load_agent_config(self):
        """Load agent-specific configuration from client config"""
        agent_cfg = self.config.get('agent', {})
        self.character_name = agent_cfg.get('character')
        self.agent_chat_frequency = agent_cfg.get('chat_frequency', 3)
        self.actions_enabled = agent_cfg.get('actions_enabled', False)
        self.model_key = agent_cfg.get('model')
        self.temperature = agent_cfg.get('temperature', 0.8)
        self.max_tokens = agent_cfg.get('max_tokens', 2000)
        self.show_reasoning = agent_cfg.get('show_reasoning', True)
        self.chat_style = agent_cfg.get('chat_style', "")
        self.mcp_servers = agent_cfg.get('mcp_servers', [])
        
        args = SimpleArgs(
            context_length=agent_cfg.get('context_length'),
            gpu_offload=agent_cfg.get('gpu_offload'),
            cache_type=agent_cfg.get('cache_type')
        )
        load_config = build_load_config(args)
        self.lm_chat = LMChat(model_key=self.model_key, load_config=load_config)
        
        if self.mcp_servers:
            self.lm_chat.set_mcp_servers(self.mcp_servers)
        
        self._update_system_prompt()
    
    def _update_system_prompt(self):
        """Update the system prompt based on current settings"""
        style_text = f"\nWrite in the following style: {self.chat_style}" if self.chat_style else ""
        
        if self.character_name:
            self.system_prompt = f"""You are {self.character_name}, a character in a dynamic world simulation. 
You are participating in a MUD-like chat with other characters and players.
Your responses should be:
- Short and immersive (1-3 sentences)
- In-character and consistent with your personality
- Reflective of your current emotional state, health, and situation
- You can narrate actions using *action descriptions* (e.g., *nods slowly*)
- Keep responses natural and conversational
- IMPORTANT: Output ONLY your character's dialogue or action. Do NOT include any thinking, reasoning, or meta-commentary.
{style_text}"""
        else:
            self.system_prompt = f"""You are an AI narrator and observer in a dynamic world simulation.
Your role is to:
- Provide immersive, atmospheric narration (1-3 sentences)
- Describe the world state and character interactions
- Make it engaging and vivid like a D&D narrator
- You can narrate actions and events using *descriptions*
- IMPORTANT: Output ONLY the narration. Do NOT include any thinking, reasoning, or meta-commentary.
{style_text}"""
    
    def _load_chat_history_from_file(self, file_path: Optional[str] = None) -> List[str]:
        """Load chat history from a file - supports run_*.txt pattern"""
        if not file_path:
            pattern = os.path.join(self.world_folder, "run_*.txt")
            files = glob.glob(pattern)
            if not files:
                pattern = os.path.join(self.world_folder, "p2p_*.log")
                files = glob.glob(pattern)
                if not files:
                    print(f"[AGENT] No chat history files found in {self.world_folder}")
                    return []
                    
            latest_file = max(files, key=os.path.getmtime)
            file_path = latest_file
            print(f"[AGENT] Using latest chat history file: {os.path.basename(file_path)}")
        
        if not os.path.exists(file_path):
            print(f"[AGENT] Chat history file not found: {file_path}")
            return []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            chat_lines = []
            chat_pattern = re.compile(r'\[CHAT\]\s+([^:]+):\s+(.+)')
            event_pattern = re.compile(r'\[(\d+)\]\s+(.+)')
            
            for line in lines:
                chat_match = chat_pattern.search(line)
                if chat_match:
                    sender = chat_match.group(1).strip()
                    message = chat_match.group(2).strip()
                    if sender != self.user_name:
                        chat_lines.append(f"{sender}: {message}")
                    continue
                
                event_match = event_pattern.search(line)
                if event_match:
                    event_text = event_match.group(2).strip()
                    if any(keyword in event_text.lower() for keyword in 
                          ['action', 'movement', 'social', 'chat', 'speak', 'talk']):
                        chat_lines.append(f"[Event] {event_text}")
            
            print(f"[AGENT] Loaded {len(chat_lines)} chat/event lines")
            return chat_lines
            
        except Exception as e:
            print(f"[AGENT] Error loading chat history: {e}")
            return []
            
    def _get_current_state(self) -> Tuple[Dict, List, List, int]:
        """Helper to get state regardless of host or joiner role"""
        if self.role == "host" and self.world_runner:
            ws = self.world_runner.world.world_states.to_dict()
            chars = [c.to_dict() for c in self.world_runner.world.characters.get_all()]
            events = self.world_runner.event_history
            tick = self.world_runner.tick_count
        else:
            ws = self.synced_world_state
            chars = self.synced_characters
            events = self.synced_events
            tick = self.synced_epoch
            
        return ws, chars, events, tick

    def _get_character_context(self) -> str:
        """Build context string for the character"""
        if not self.character_name:
            return ""
            
        _, chars, events, _ = self._get_current_state()
        
        char_data = None
        for char in chars:
            if isinstance(char, dict) and char.get('name') == self.character_name:
                char_data = char
                break
        
        if not char_data:
            return f"You are {self.character_name}, currently in this world."
        
        context_parts = []
        context_parts.append(f"Character: {self.character_name}")
        
        status = char_data.get('status_variables', {})
        if status:
            status_str = ", ".join([f"{k}: {v}" for k, v in status.items()])
            context_parts.append(f"Status: {status_str}")
        
        ai_state = char_data.get('ai_state', 'IDLE')
        context_parts.append(f"State: {ai_state}")
        
        emotion = char_data.get('emotion', 'neutral')
        context_parts.append(f"Emotion: {emotion}")
        
        goal = char_data.get('goal', 'social_belonging')
        context_parts.append(f"Goal: {goal}")
        
        nav = char_data.get('navigation', {})
        location = nav.get('current_location', 'Unknown')
        context_parts.append(f"Location: {location}")
        
        recent_actions = []
        for event in events[-5:]:
            if isinstance(event, dict):
                text = event.get('text', '')
                if text and (self.character_name in text or 'world' in text):
                    recent_actions.append(text)
        if recent_actions:
            context_parts.append(f"Recent events involving you: {'; '.join(recent_actions)}")
        
        return "\n".join(context_parts)
    
    def _get_world_context(self) -> str:
        """Build context string for the world state"""
        ws, chars, events, _ = self._get_current_state()
        context_parts = []
        
        global_states = ws.get('global_states', {})
        if global_states:
            state_str = ", ".join([f"{k}: {v}" for k, v in global_states.items()])
            context_parts.append(f"World state: {state_str}")
        
        timers = ws.get('global_timers', {})
        day_cycle = timers.get('day_cycle', 0)
        hours = int(day_cycle // 60)
        minutes = int(day_cycle % 60)
        context_parts.append(f"Time: {hours:02d}:{minutes:02d}")
        
        if chars:
            char_names = []
            for char in chars:
                if isinstance(char, dict):
                    name = char.get('name')
                    if name and name != self.character_name:
                        char_names.append(name)
            if char_names:
                context_parts.append(f"Other characters present: {', '.join(char_names[:5])}")
        
        if events:
            recent = []
            for event in events[-5:]:
                if isinstance(event, dict):
                    text = event.get('text', '')
                    if text:
                        recent.append(text)
            if recent:
                context_parts.append(f"Recent events: {'; '.join(recent)}")
        
        return "\n".join(context_parts)
    
    def _get_chat_history_context(self) -> str:
        """Get recent chat history from loaded file and live chat"""
        history_lines = []
        
        if self.loaded_chat_history:
            history_lines.append("--- Historical chat from log files ---")
            history_lines.extend(self.loaded_chat_history[-10:])
            history_lines.append("--- End of historical chat ---")
        
        if self.chat_history:
            history_lines.append("--- Recent live chat ---")
            for entry in self.chat_history[-5:]:
                sender = entry.get('sender', 'Unknown')
                message = entry.get('message', '')
                if sender != self.user_name:
                    history_lines.append(f"{sender}: {message}")
            history_lines.append("--- End of live chat ---")
        
        if not history_lines:
            return "No recent chat history."
        
        return "\n".join(history_lines)
    
    def _initialize_agent(self):
        """Initialize the agent - called once connected"""
        if self.initialized:
            return
            
        print("[AGENT] Initializing agent state...")
        self.initialized = True
        print("[AGENT] ✓ Initialization complete!")
    
    def _strip_lmstudio_internal(self, text: str) -> str:
        """Remove LM Studio internal markers from text - preserves spaces"""
        if not text:
            return text
        text = re.sub(r'__LM_STUDIO_INTERNAL_[A-Z_]+_[a-f0-9]+__', '', text)
        text = re.sub(r'__[A-Z_]+__', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text
    
    def _extract_answer_from_stream(self, full_text: str) -> Tuple[str, str]:
        """Extract reasoning and answer from the full stream text"""
        reasoning = ""
        answer = ""
        
        marker_pattern = r'__LM_STUDIO_INTERNAL_[A-Z_]+_[a-f0-9]+__'
        marker_match = re.search(marker_pattern, full_text)
        
        if marker_match:
            reasoning_raw = full_text[:marker_match.start()].strip()
            answer_raw = full_text[marker_match.end():].strip()
            
            reasoning = self._strip_lmstudio_internal(reasoning_raw)
            answer = self._strip_lmstudio_internal(answer_raw)
            
            if not answer:
                remaining = full_text[marker_match.end():].strip()
                if remaining:
                    answer = self._strip_lmstudio_internal(remaining)
        elif '<think>' in full_text:
            if '</think>' in full_text:
                think_match = re.search(r'<think>(.*?)</think>', full_text, re.DOTALL)
                if think_match:
                    reasoning = think_match.group(1).strip()
                    answer = full_text.replace(think_match.group(0), '').strip()
                    reasoning = self._strip_lmstudio_internal(reasoning)
                    answer = self._strip_lmstudio_internal(answer)
            else:
                reasoning = self._strip_lmstudio_internal(full_text.replace('<think>', '').strip())
                answer = ""
        else:
            answer = self._strip_lmstudio_internal(full_text.strip())
        
        if reasoning:
            reasoning = re.sub(r'__LM_STUDIO_INTERNAL_[A-Z_]+_[a-f0-9]+__', '', reasoning)
        if answer:
            answer = re.sub(r'__LM_STUDIO_INTERNAL_[A-Z_]+_[a-f0-9]+__', '', answer)
        
        return reasoning, answer
    
    def _generate_response(self, prompt_type: str = "chat", target: Optional[str] = None) -> str:
        """Generate a response using LM Studio with streaming and reasoning display"""
        if not self.lm_chat:
            print("[AGENT] LM Chat not initialized")
            return ""
        
        # Build context
        context_parts = []
        
        if self.character_name:
            context_parts.append(f"[CHARACTER CONTEXT]\n{self._get_character_context()}")
        
        context_parts.append(f"\n[WORLD CONTEXT]\n{self._get_world_context()}")
        context_parts.append(f"\n[CHAT HISTORY]\n{self._get_chat_history_context()}")
        
        # Build prompt
        if prompt_type == "chat":
            if self.character_name:
                if target:
                    prompt = f"""Based on the context above, respond as {self.character_name} speaking to {target}.
Be natural, in-character, and immersive (1-3 sentences).
IMPORTANT: Output ONLY your character's dialogue or action. No thinking, no reasoning, no meta-commentary."""
                else:
                    prompt = f"""Based on the context above, respond as {self.character_name} to the current situation.
Be natural, in-character, and immersive (1-3 sentences).
IMPORTANT: Output ONLY your character's dialogue or action. No thinking, no reasoning, no meta-commentary."""
            else:
                prompt = f"""Based on the context above, provide a brief immersive narration of what's happening.
Be atmospheric, descriptive, and engaging (1-3 sentences) like a D&D narrator.
IMPORTANT: Output ONLY the narration. No thinking, no reasoning, no meta-commentary."""
        
        elif prompt_type == "action":
            if self.character_name:
                prompt = f"""Based on the context above, suggest a single action that {self.character_name} would take.
Format as: ACTION_NAME (e.g., MOVE, ATTACK, TALK, USE, PICKUP, DROP, EXAMINE)
IMPORTANT: Output ONLY the action name. No thinking, no reasoning, no explanation."""
            else:
                prompt = f"""Based on the context above, suggest an action that any character might take.
Format as: ACTION_NAME (e.g., MOVE, ATTACK, TALK, USE, PICKUP, DROP, EXAMINE)
IMPORTANT: Output ONLY the action name. No thinking, no reasoning, no explanation."""
        else:
            prompt = f"""Based on the context above, provide a brief response.
Keep it short and immersive.
IMPORTANT: Output ONLY the response. No thinking, no reasoning, no meta-commentary."""
        
        if self.chat_style:
            prompt += f"\n\nWrite in the following style: {self.chat_style}"
        
        full_prompt = f"{context_parts}\n\n{prompt}"
        
        pred_args = SimpleArgs(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=0.9,
            top_k=None,
            repeat_penalty=1.1,
            seed=None,
            stop=None
        )
        predict_config = build_prediction_config(pred_args)
        
        try:
            print(f"[AGENT] Generating response...")
            
            model = self.lm_chat.get_model()
            chat = lms.Chat(self.system_prompt)
            chat.add_user_message(full_prompt)
            
            print("Thinking...")
            
            all_fragments = []
            in_reasoning = False
            is_first_content = True
            
            for fragment in model.respond_stream(chat, config=predict_config):
                if isinstance(fragment, str):
                    content = fragment
                elif hasattr(fragment, 'content'):
                    content = fragment.content
                else:
                    content = str(fragment)
                    
                all_fragments.append(content)
                
                is_reasoning_fragment = (
                    hasattr(fragment, 'reasoning_type') and 
                    fragment.reasoning_type
                )
                
                if is_reasoning_fragment or '<think>' in content:
                    if not in_reasoning:
                        if self.show_reasoning:
                            print("\n[Reasoning]: ", end="", flush=True)
                        in_reasoning = True
                        content = content.replace('<think>', '')
                
                if '</think>' in content:
                    in_reasoning = False
                    content = content.replace('</think>', '')
                    if self.show_reasoning:
                        if content:
                            print(content, end="", flush=True)
                        print("\n\n[Answer]: ", end="", flush=True)
                        is_first_content = False
                    continue
                    
                if '__LM_STUDIO_INTERNAL' in content:
                    in_reasoning = False
                    content = re.sub(r'__LM_STUDIO_INTERNAL_[A-Z_]+_[a-f0-9]+__', '', content)
                    if self.show_reasoning:
                        if content:
                            print(content, end="", flush=True)
                        print("\n\n[Answer]: ", end="", flush=True)
                        is_first_content = False
                    continue
                
                if in_reasoning or is_reasoning_fragment:
                    if self.show_reasoning:
                        print(content, end="", flush=True)
                else:
                    if is_first_content:
                        if not self.show_reasoning:
                            print("\n[Answer]: ", end="", flush=True)
                        else:
                            print("\n\n[Answer]: ", end="", flush=True)
                        is_first_content = False
                    print(content, end="", flush=True)
            
            print("\n")
            
            full_text = ''.join(all_fragments)
            reasoning, answer = self._extract_answer_from_stream(full_text)
            
            if answer:
                answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.DOTALL)
                answer = re.sub(r'<think>|</think>', '', answer)
                answer = self._strip_lmstudio_internal(answer)
                
                if answer.startswith('"') and answer.endswith('"'):
                    answer = answer[1:-1]
                if answer.startswith("'") and answer.endswith("'"):
                    answer = answer[1:-1]
                
                answer = re.sub(r'^(?:\[Reasoning\]|Reasoning):\s*', '', answer, flags=re.IGNORECASE).strip()
                answer = re.sub(r'^(?:\[Answer\]|Answer):\s*', '', answer, flags=re.IGNORECASE).strip()
                answer = re.sub(r'\s+', ' ', answer).strip()
            
            if not answer or len(answer) < 10:
                if reasoning:
                    sentences = re.split(r'[.!?]+\s+', reasoning)
                    if len(sentences) > 1:
                        answer = '. '.join(sentences[-3:]).strip()
                        if answer and not answer.endswith('.'):
                            answer += '.'
                    else:
                        answer = reasoning
                
                if not answer or len(answer) < 10:
                    answer = "The scene unfolds before you in the twilight..."
            
            return answer
            
        except Exception as e:
            print(f"[AGENT] Error generating response: {e}")
            return "The scene unfolds before you in the twilight..."
    
    def _generate_chat_message(self) -> Optional[str]:
        """Generate a chat message based on current context"""
        if not self.initialized:
            return None
        
        _, _, _, epoch = self._get_current_state()
        if epoch - self.last_chat_epoch < self.agent_chat_frequency:
            return None
        
        response = self._generate_response("chat")
        
        if response and len(response) > 3:
            self.last_chat_epoch = epoch
            return response
        
        return None
    
    def _generate_action(self) -> Optional[str]:
        """Generate an action based on current context"""
        if not self.actions_enabled or not self.initialized:
            return None
            
        if self.role != "host":
            return None
        
        _, _, _, epoch = self._get_current_state()
        if epoch % 7 != 0:
            return None
        
        action = self._generate_response("action")
        
        if action and len(action) > 2:
            action = action.strip().upper()
            for prefix in ["ACTION:", "ACTION_NAME:", "ACTION NAME:", "SUGGESTED ACTION:"]:
                if action.startswith(prefix):
                    action = action[len(prefix):].strip()
            
            action = action.split()[0] if action.split() else action
            
            valid_actions = ["MOVE", "ATTACK", "TALK", "USE", "PICKUP", "DROP", "EXAMINE", 
                           "LOOK", "WAIT", "REST", "HELP", "GO", "TAKE", "OPEN", "CLOSE"]
            
            if action in valid_actions:
                return action
        
        return None
        
    def _execute_local_command(self, cmd: str) -> bool:
        """Override to add agent-specific commands"""
        cmd = cmd.strip().lower()
        parts = cmd.split()
        command = parts[0].lower() if parts else ""
        
        if command == 'agent':
            if len(parts) < 2:
                print("\n[AGENT] Agent commands:")
                print("  agent character <name>     - Set the character name")
                print("  agent frequency <N>        - Set chat frequency")
                print("  agent actions on/off       - Enable/disable actions (Host only)")
                print("  agent reasoning on/off     - Show/hide AI reasoning")
                print("  agent style <text>         - Set chat style")
                print("  agent history [file]       - Load chat history")
                print("  agent status               - Show agent status")
                print("  agent say <message>        - Force agent to say something")
                print("  agent act <action>         - Force agent to perform action (Host only)")
                return False
            
            subcmd = parts[1].lower()
            
            if subcmd == 'character' and len(parts) > 2:
                self.character_name = ' '.join(parts[2:])
                self._update_system_prompt()
                print(f"[AGENT] Character set to: {self.character_name}")
                return False
            
            elif subcmd == 'frequency' and len(parts) > 2:
                try:
                    self.agent_chat_frequency = int(parts[2])
                    print(f"[AGENT] Chat frequency set to: {self.agent_chat_frequency} epochs")
                except ValueError:
                    print("[AGENT] Invalid frequency value")
                return False
            
            elif subcmd == 'actions':
                if self.role != "host":
                    print("[AGENT] Note: P2P Actions are only fully supported when running as HOST.")
                if len(parts) > 2 and parts[2] == 'on':
                    self.actions_enabled = True
                    print("[AGENT] Actions enabled")
                elif len(parts) > 2 and parts[2] == 'off':
                    self.actions_enabled = False
                    print("[AGENT] Actions disabled")
                else:
                    print(f"[AGENT] Actions: {'enabled' if self.actions_enabled else 'disabled'}")
                return False
            
            elif subcmd == 'reasoning':
                if len(parts) > 2 and parts[2] == 'on':
                    self.show_reasoning = True
                    print("[AGENT] Reasoning display enabled")
                elif len(parts) > 2 and parts[2] == 'off':
                    self.show_reasoning = False
                    print("[AGENT] Reasoning display disabled")
                else:
                    print(f"[AGENT] Reasoning: {'enabled' if self.show_reasoning else 'disabled'}")
                return False
            
            elif subcmd == 'style' and len(parts) > 2:
                self.chat_style = ' '.join(parts[2:])
                self._update_system_prompt()
                print(f"[AGENT] Chat style set to: {self.chat_style}")
                return False
            
            elif subcmd == 'history':
                file_path = None
                if len(parts) > 2:
                    file_path = ' '.join(parts[2:])
                self.loaded_chat_history = self._load_chat_history_from_file(file_path)
                if self.loaded_chat_history:
                    print(f"[AGENT] Loaded {len(self.loaded_chat_history)} chat history entries")
                else:
                    print("[AGENT] No chat history loaded")
                return False
            
            elif subcmd == 'status':
                print("\n[AGENT STATUS]")
                print(f"  Character: {self.character_name or 'None (narrator)'}")
                print(f"  Role: {self.role.upper()}")
                print(f"  Chat frequency: Every {self.agent_chat_frequency} epochs")
                print(f"  Actions enabled: {self.actions_enabled}")
                print(f"  Show reasoning: {self.show_reasoning}")
                print(f"  Chat style: {self.chat_style or 'None'}")
                print(f"  Chat history loaded: {len(self.loaded_chat_history)} entries")
                print(f"  Model: {self.model_key or 'default'}")
                print(f"  Initialized: {self.initialized}")
                return False
            
            elif subcmd == 'say' and len(parts) > 2:
                message = ' '.join(parts[2:])
                self._broadcast_chat(self.node_id, message)
                return False
            
            elif subcmd == 'act' and len(parts) > 2:
                if self.role != "host":
                    print("[AGENT] Error: Actions can only be executed by the Host node.")
                    return False
                    
                action = parts[2].upper()
                if self.character_name:
                    self._execute_local_command(f"action {self.character_name} {action}")
                else:
                    print("[AGENT] No character set. Use 'agent character <name>' first.")
                return False
            
            else:
                print(f"[AGENT] Unknown agent command: {subcmd}")
                return False
        
        return super()._execute_local_command(cmd)

    def _handle_chat_message(self, sender: str, message: str):
        """Override to store chat history"""
        self.chat_history.append({
            "sender": sender,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        
        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]
            
        super()._handle_chat_message(sender, message)

    def _render(self, force: bool = False):
        """Throttled render to prevent terminal spam while waiting for host"""
        current_time = time.time()
        if not force and not self.is_connected and (current_time - self.last_render_time < 3.0):
            return
            
        super()._render(force)
        
        if not self.initialized:
            if self.role == "host" or self.is_connected:
                self._initialize_agent()
        
        _, _, _, current_epoch = self._get_current_state()
        if current_epoch != self.last_agent_eval_epoch:
            self.last_agent_eval_epoch = current_epoch
            if self.initialized and not self.pause_mode:
                self._generate_and_send_responses()
                
    def _sync_with_peers(self):
        """Prioritize connecting to the host node instead of other joiners"""
        current_time = time.time()
        if current_time - self.last_sync < self.sync_interval:
            return
        
        self.last_sync = current_time
        self.register_with_signaling(silent=True)
        
        if self.role == "join" and self.peers:
            sorted_peers = sorted(
                self.peers.items(), 
                key=lambda item: 0 if item[1]['port'] == 6000 or 'host' in item[0] else 1
            )
            
            for peer_id, peer_info in sorted_peers:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(self.timeout)
                    sock.connect((peer_info['host'], peer_info['port']))
                    
                    msg = NetworkMessage("REQUEST_WORLD", {}, sender=self.node_id)
                    sock.sendall((msg.to_json() + '\n').encode('utf-8'))
                    
                    data = sock.recv(65536)
                    if data:
                        try:
                            response = NetworkMessage.from_json(data.decode('utf-8'))
                            if response.type == "WORLD_STATE":
                                self._handle_peer_message(response, sock)
                                sock.close()
                                break
                        except json.JSONDecodeError:
                            pass
                    sock.close()
                except Exception:
                    self.sync_attempts += 1
                    if self.sync_attempts > 10:
                        self.is_connected = False
                    pass
                
    def _generate_and_send_responses(self):
        """Generate and send AI responses based on current state"""
        chat_message = self._generate_chat_message()
        if chat_message:
            self._broadcast_chat(self.node_id, chat_message)
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
        
        if self.actions_enabled and self.role == "host":
            action = self._generate_action()
            if action and self.character_name:
                self._execute_local_command(f"action {self.character_name} {action}")
                if self.show_prompt:
                    sys.stdout.write(self.prompt)
                    sys.stdout.flush()
                    
    def start(self):
        """Override start to initialize agent messaging details"""
        print("="*60)
        print(f"SWM AGENT P2P NODE - {self.role.upper()}")
        print("="*60)
        if self.character_name:
            print(f"Mode: Character Agent - {self.character_name}")
        else:
            print("Mode: Narrator Agent")
        print(f"Chat frequency: Every {self.agent_chat_frequency} epochs")
        print(f"Actions: {'Enabled' if self.actions_enabled else 'Disabled (Host only)'}")
        print(f"Show reasoning: {'Enabled' if self.show_reasoning else 'Disabled'}")
        if self.chat_style:
            print(f"Chat style: {self.chat_style}")
        print(f"Model: {self.model_key or 'default'}")
        print("="*60)
        
        if self.chat_history_file:
            self.loaded_chat_history = self._load_chat_history_from_file(self.chat_history_file)
        elif self.world_folder:
            self.loaded_chat_history = self._load_chat_history_from_file()
            
        if self.character_name:
            self.prompt = f"[{self.character_name}] > "
        else:
            self.prompt = "[NARRATOR] > "
            
        super().start()


def parse_agent_args():
    """Parse command line arguments for agent"""
    parser = argparse.ArgumentParser(
        description='SWM AI Agent P2P Node - AI-powered chat and actions',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--host', action='store_true', help='Run as host (creates world, default)')
    parser.add_argument('--join', action='store_true', help='Run as joiner (connects to host)')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    parser.add_argument('--world', type=str, help='Specify an existing world folder to load')
    parser.add_argument('--config', type=str, default='network_p2p_config.json', help='Config file')
    parser.add_argument('--interact', action='store_true', help='Interactive step-by-step mode (host only)')
    parser.add_argument('--dynamic', action='store_true', help='Dynamic mode: continuous with command input (host only)')

    parser.add_argument('--character', '-c', type=str, help='Character name to roleplay as')
    parser.add_argument('--agent_chat_frequency', '-f', type=int, default=3, help='Chat every N epochs (default: 3)')
    parser.add_argument('--actions_enabled', '-a', action='store_true', help='Enable AI-generated actions (Host only)')
    parser.add_argument('--no-reasoning', action='store_true', help='Disable showing AI reasoning/thinking process')
    parser.add_argument('--chat_style', type=str, default="", help='Style for chat responses (e.g., "dramatic", "funny")')
    parser.add_argument('--chat_history', nargs='?', const=True, default=None, help='Load chat history from file (uses latest if no path)')
    parser.add_argument('--world_folder', type=str, default='world_p2p', help='World folder path')
    parser.add_argument('--model', '-m', type=str, help='LM Studio model key')
    parser.add_argument('--temperature', '-t', type=float, default=0.8, help='Temperature for generation')
    parser.add_argument('--max_tokens', type=int, default=2000, help='Maximum tokens for generation (default: 2000)')
    parser.add_argument('--mcp', action='append', default=[], help='MCP server integration')
    
    return parser.parse_args()


def main():
    args = parse_agent_args()
    role = "join" if args.join else "host"
    
    agent_p2p = SWMAgentP2PNode(config_file=args.config, role=role, args=args)
    
    if args.character:
        agent_p2p.character_name = args.character
    if args.agent_chat_frequency:
        agent_p2p.agent_chat_frequency = args.agent_chat_frequency
    if args.actions_enabled:
        agent_p2p.actions_enabled = True
    if args.no_reasoning:
        agent_p2p.show_reasoning = False
    if args.chat_style:
        agent_p2p.chat_style = args.chat_style
    if args.chat_history is not None:
        agent_p2p.chat_history_file = args.chat_history if args.chat_history is not True else None
    if args.world_folder:
        agent_p2p.world_folder = args.world_folder
    if args.world:
        agent_p2p.world_folder = args.world
    if args.model:
        agent_p2p.model_key = args.model
        load_args = SimpleArgs(context_length=None, gpu_offload=None, cache_type=None)
        agent_p2p.lm_chat = LMChat(model_key=args.model, load_config=build_load_config(load_args))
    if args.temperature:
        agent_p2p.temperature = args.temperature
    if args.max_tokens:
        agent_p2p.max_tokens = args.max_tokens
    if args.mcp:
        agent_p2p.mcp_servers = args.mcp
        if agent_p2p.lm_chat:
            agent_p2p.lm_chat.set_mcp_servers(args.mcp)
    
    agent_p2p._update_system_prompt()
    agent_p2p.start()


if __name__ == "__main__":
    main()