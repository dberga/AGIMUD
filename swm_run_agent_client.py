#!/usr/bin/env python3
"""
SWM Run Agent Client - AI-powered client that generates chat messages and actions
using local LM Studio models based on world state context.
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

# Import from swm_run_client
from swm_run_client import SWMClient, NetworkMessage

# Import LM Studio functions
import lmstudio as lms
from run_lms import LMChat, build_prediction_config, build_load_config


class SimpleArgs:
    """Simple class to mimic argparse.Namespace for build_load_config and build_prediction_config"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class SWMAgentClient(SWMClient):
    """AI-powered client that generates contextual chat and actions"""
    
    def __init__(self, config_file: str = "network_client_config.json"):
        super().__init__(config_file)
        
        # Agent-specific configuration
        self.character_name: Optional[str] = None
        self.agent_chat_frequency: int = 3
        self.actions_enabled: bool = False
        self.last_chat_epoch: int = 0
        self.chat_history: List[Dict[str, str]] = []
        self.max_history: int = 20
        self.show_reasoning: bool = True
        self.chat_style: str = ""
        self.chat_history_file: Optional[str] = None
        self.loaded_chat_history: List[str] = []
        self.initialized: bool = False
        self._initializing: bool = False
        
        # Server data cache
        self.server_summary: str = ""
        self.server_catalog: str = ""
        self.server_vars: str = ""
        self.server_list: str = ""
        
        # LM Studio configuration
        self.model_key: Optional[str] = None
        self.system_prompt: Optional[str] = None
        self.temperature: float = 0.8
        self.max_tokens: int = 2000
        self.lm_chat: Optional[LMChat] = None
        self.mcp_servers: List[str] = []
        
        # World folder
        self.world_folder: str = "world_centralized"
        
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
        self.world_folder = agent_cfg.get('world_folder', "world_centralized")
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
                print(f"[AGENT] No run_*.txt files found in {self.world_folder}")
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
    
    def _get_character_context(self) -> str:
        """Build context string for the character"""
        if not self.character_name:
            return ""
        
        char_data = None
        for char in self.characters:
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
        for event in self.last_events[-5:]:
            if isinstance(event, dict):
                text = event.get('text', '')
                if text and (self.character_name in text or 'world' in text):
                    recent_actions.append(text)
        if recent_actions:
            context_parts.append(f"Recent events involving you: {'; '.join(recent_actions)}")
        
        return "\n".join(context_parts)
    
    def _get_world_context(self) -> str:
        """Build context string for the world state"""
        context_parts = []
        
        global_states = self.world_state.get('global_states', {})
        if global_states:
            state_str = ", ".join([f"{k}: {v}" for k, v in global_states.items()])
            context_parts.append(f"World state: {state_str}")
        
        timers = self.world_state.get('global_timers', {})
        day_cycle = timers.get('day_cycle', 0)
        hours = int(day_cycle // 60)
        minutes = int(day_cycle % 60)
        context_parts.append(f"Time: {hours:02d}:{minutes:02d}")
        
        if self.characters:
            char_names = []
            for char in self.characters:
                if isinstance(char, dict):
                    name = char.get('name')
                    if name and name != self.character_name:
                        char_names.append(name)
            if char_names:
                context_parts.append(f"Other characters present: {', '.join(char_names[:5])}")
        
        if self.last_events:
            recent = []
            for event in self.last_events[-5:]:
                if isinstance(event, dict):
                    text = event.get('text', '')
                    if text:
                        recent.append(text)
            if recent:
                context_parts.append(f"Recent events: {'; '.join(recent)}")
        
        if self.server_summary:
            context_parts.append(f"\nServer Summary:\n{self.server_summary[:500]}")
        
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
    
    def _execute_server_command(self, cmd: str, timeout: float = 5.0) -> Optional[str]:
        """Execute a server command and return the result"""
        if not self.connected:
            return None
        
        msg = NetworkMessage("COMMAND", {"command": cmd})
        self._send(msg)
        self.waiting_for_response = True
        
        start_time = time.time()
        result = None
        
        while self.waiting_for_response and time.time() - start_time < timeout:
            time.sleep(0.1)
            messages = self._receive()
            if messages:
                for msg in messages:
                    if msg.type == "COMMAND_RESULT":
                        result = msg.payload.get('result', '')
                        self.waiting_for_response = False
                    elif msg.type in ["WELCOME", "WORLD_STATE", "WORLD_UPDATE"]:
                        self.world_state = msg.payload.get('world_state', {})
                        self.characters = msg.payload.get('characters', [])
                        self.server_epoch = msg.payload.get('tick', msg.payload.get('epoch', self.server_epoch))
                        self.last_events = msg.payload.get('events', [])
        
        return result
    
    def _initialize_agent(self):
        """Initialize the agent with server data - only called once"""
        if not self.connected or self.initialized or self._initializing:
            return
        
        self._initializing = True
        print("[AGENT] Initializing with server data...")
        
        result = self._execute_server_command("summary")
        if result:
            self.server_summary = result
            print("[AGENT] ✓ Loaded world summary")
        
        result = self._execute_server_command("catalog")
        if result:
            self.server_catalog = result
            print("[AGENT] ✓ Loaded action catalog")
        
        result = self._execute_server_command("var")
        if result:
            self.server_vars = result
            print("[AGENT] ✓ Loaded variable catalog")
        
        result = self._execute_server_command("list")
        if result:
            self.server_list = result
            print("[AGENT] ✓ Loaded character/object list")
        
        self.initialized = True
        self._initializing = False
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
        
        # Look for the marker first
        marker_pattern = r'__LM_STUDIO_INTERNAL_[A-Z_]+_[a-f0-9]+__'
        marker_match = re.search(marker_pattern, full_text)
        
        if marker_match:
            # Everything before the marker is reasoning
            reasoning_raw = full_text[:marker_match.start()].strip()
            # Everything after the marker is the answer
            answer_raw = full_text[marker_match.end():].strip()
            
            # Clean both parts
            reasoning = self._strip_lmstudio_internal(reasoning_raw)
            answer = self._strip_lmstudio_internal(answer_raw)
            
            # If answer is empty, try to find it after the marker in the original text
            if not answer:
                # Sometimes the marker is at the very end of reasoning and answer follows immediately
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
                # Unclosed think tag - generation was cut off!
                reasoning = self._strip_lmstudio_internal(full_text.replace('<think>', '').strip())
                answer = ""
        else:
            # No markers, everything is the answer
            answer = self._strip_lmstudio_internal(full_text.strip())
        
        # Final cleanup - remove any remaining marker fragments
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
        
        if self.server_summary:
            context_parts.append(f"[SERVER SUMMARY]\n{self.server_summary[:800]}")
        
        if self.server_catalog:
            context_parts.append(f"[ACTION CATALOG]\n{self.server_catalog[:500]}")
        
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
        
        # Build prediction config
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
            if predict_config:
                print(f"Prediction config: {predict_config}")
            
            # Collect all fragments
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
                
                # Check for start of reasoning
                if is_reasoning_fragment or '<think>' in content:
                    if not in_reasoning:
                        if self.show_reasoning:
                            print("\n[Reasoning]: ", end="", flush=True)
                        in_reasoning = True
                        content = content.replace('<think>', '')
                
                # Check for end of reasoning
                if '</think>' in content:
                    in_reasoning = False
                    content = content.replace('</think>', '')
                    if self.show_reasoning:
                        if content:
                            print(content, end="", flush=True)
                        print("\n\n[Answer]: ", end="", flush=True)
                        is_first_content = False
                    continue
                    
                # Handle LM Studio marker in stream to skip printing it
                if '__LM_STUDIO_INTERNAL' in content:
                    in_reasoning = False
                    content = re.sub(r'__LM_STUDIO_INTERNAL_[A-Z_]+_[a-f0-9]+__', '', content)
                    if self.show_reasoning:
                        if content:
                            print(content, end="", flush=True)
                        print("\n\n[Answer]: ", end="", flush=True)
                        is_first_content = False
                    continue
                
                # Live printing logic
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
            
            # Join all fragments for safe extraction
            full_text = ''.join(all_fragments)
            
            # Extract reasoning and answer perfectly using the fixed regex
            reasoning, answer = self._extract_answer_from_stream(full_text)
            
            # Clean up answer
            if answer:
                # Remove any remaining think tags
                answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.DOTALL)
                answer = re.sub(r'<think>|</think>', '', answer)
                
                # Remove internal markers
                answer = self._strip_lmstudio_internal(answer)
                
                # Remove quotes if present
                if answer.startswith('"') and answer.endswith('"'):
                    answer = answer[1:-1]
                if answer.startswith("'") and answer.endswith("'"):
                    answer = answer[1:-1]
                
                # Strip hallucinated reasoning/answer tags generated by the model itself
                answer = re.sub(r'^(?:\[Reasoning\]|Reasoning):\s*', '', answer, flags=re.IGNORECASE).strip()
                answer = re.sub(r'^(?:\[Answer\]|Answer):\s*', '', answer, flags=re.IGNORECASE).strip()
                
                # Clean up extra whitespace
                answer = re.sub(r'\s+', ' ', answer)
                answer = answer.strip()
            
            # If answer is empty or too short, try to extract from reasoning
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
            import traceback
            traceback.print_exc()
            return "The scene unfolds before you in the twilight..."
    
    def _generate_chat_message(self) -> Optional[str]:
        """Generate a chat message based on current context"""
        if not self.connected:
            return None
        
        if not self.initialized:
            return None
        
        if self.server_epoch - self.last_chat_epoch < self.agent_chat_frequency:
            return None
        
        response = self._generate_response("chat")
        
        if response and len(response) > 3:
            self.last_chat_epoch = self.server_epoch
            return response
        
        return None
    
    def _generate_action(self) -> Optional[str]:
        """Generate an action based on current context"""
        if not self.connected or not self.actions_enabled or not self.initialized:
            return None
        
        if self.server_epoch % 7 != 0:
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
    
    def _process_command(self, cmd: str) -> bool:
        """Override to add agent-specific commands"""
        cmd = cmd.strip().lower()
        parts = cmd.split()
        command = parts[0].lower() if parts else ""
        
        if command == 'agent':
            if len(parts) < 2:
                print("\n[AGENT] Agent commands:")
                print("  agent character <name>     - Set the character name")
                print("  agent frequency <N>        - Set chat frequency")
                print("  agent actions on/off       - Enable/disable actions")
                print("  agent reasoning on/off     - Show/hide AI reasoning")
                print("  agent style <text>         - Set chat style")
                print("  agent history [file]       - Load chat history")
                print("  agent status               - Show agent status")
                print("  agent say <message>        - Force agent to say something")
                print("  agent act <action>         - Force agent to perform action")
                print("  agent summary              - Get world summary")
                print("  agent catalog              - List actions in catalog")
                print("  agent var                  - List available variables")
                print("  agent list                 - List characters, states, HP")
                print("  agent init                 - Re-initialize with server data")
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
            
            elif subcmd == 'summary':
                if self.connected:
                    result = self._execute_server_command("summary")
                    if result:
                        self.server_summary = result
                        print(f"\n[WORLD SUMMARY]\n{result}")
                return False
            
            elif subcmd == 'catalog':
                if self.connected:
                    result = self._execute_server_command("catalog")
                    if result:
                        self.server_catalog = result
                        print(f"\n[ACTION CATALOG]\n{result}")
                return False
            
            elif subcmd == 'var':
                if self.connected:
                    result = self._execute_server_command("var")
                    if result:
                        self.server_vars = result
                        print(f"\n[VARIABLE CATALOG]\n{result}")
                return False
            
            elif subcmd == 'list':
                if self.connected:
                    result = self._execute_server_command("list")
                    if result:
                        self.server_list = result
                        print(f"\n[CHARACTERS, OBJECTS, WORLD STATES]\n{result}")
                return False
            
            elif subcmd == 'init':
                self.initialized = False
                self._initialize_agent()
                return False
            
            elif subcmd == 'status':
                print("\n[AGENT STATUS]")
                print(f"  Character: {self.character_name or 'None (narrator)'}")
                print(f"  Chat frequency: Every {self.agent_chat_frequency} epochs")
                print(f"  Actions enabled: {self.actions_enabled}")
                print(f"  Show reasoning: {self.show_reasoning}")
                print(f"  Chat style: {self.chat_style or 'None'}")
                print(f"  Chat history loaded: {len(self.loaded_chat_history)} entries")
                print(f"  Model: {self.model_key or 'default'}")
                print(f"  Temperature: {self.temperature}")
                print(f"  Max tokens: {self.max_tokens}")
                print(f"  Last chat epoch: {self.last_chat_epoch}")
                print(f"  Live chat history: {len(self.chat_history)} messages")
                print(f"  Initialized: {self.initialized}")
                if self.mcp_servers:
                    print(f"  MCP servers: {', '.join(self.mcp_servers)}")
                return False
            
            elif subcmd == 'say' and len(parts) > 2:
                message = ' '.join(parts[2:])
                self._send_chat(message)
                print(f"[AGENT] Sent: {message}")
                return False
            
            elif subcmd == 'act' and len(parts) > 2:
                action = parts[2].upper()
                if self.character_name:
                    self._send_command(f"action {self.character_name} {action}")
                    print(f"[AGENT] Sent action: {action}")
                else:
                    print("[AGENT] No character set. Use 'agent character <name>' first.")
                return False
            
            else:
                print(f"[AGENT] Unknown agent command: {subcmd}")
                return False
        
        return super()._process_command(cmd)
    
    def _handle_chat_message(self, sender: str, message: str):
        """Override to store chat history"""
        self.chat_history.append({
            "sender": sender,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        
        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]
        
        print(f"\n[CHAT] {sender}: {message}")
        if self.show_prompt:
            sys.stdout.write(self.prompt)
            sys.stdout.flush()
    
    def _handle_message(self, msg: NetworkMessage):
        """Override to handle world updates and trigger AI responses"""
        msg_type = msg.type
        
        if msg_type in ["WELCOME", "WORLD_STATE", "WORLD_UPDATE"]:
            self.world_state = msg.payload.get('world_state', {})
            self.characters = msg.payload.get('characters', [])
            self.server_epoch = msg.payload.get('tick', msg.payload.get('global_tick', msg.payload.get('epoch', self.server_epoch)))
            if 'events' in msg.payload:
                self.last_events = msg.payload.get('events', [])
            if 'mode' in msg.payload:
                self.server_mode = msg.payload.get('mode', self.server_mode)
            
            self.waiting_for_response = False
            
            if self.initialized:
                if not self.pause_mode:
                    self._render()
                
                if not self.pause_mode:
                    self._generate_and_send_responses()
        
        elif msg_type == "COMMAND_RESULT":
            self.waiting_for_response = False
            cmd = msg.payload.get('command', '')
            result = msg.payload.get('result', '')
            if cmd in ['summary', 'catalog', 'var', 'list']:
                if cmd == 'summary':
                    self.server_summary = result
                elif cmd == 'catalog':
                    self.server_catalog = result
                elif cmd == 'var':
                    self.server_vars = result
                elif cmd == 'list':
                    self.server_list = result
        
        elif msg_type == "CHAT":
            sender = msg.payload.get('sender', 'Unknown')
            message = msg.payload.get('message', '')
            self._handle_chat_message(sender, message)
            
            if self.initialized and not self.pause_mode and sender != self.user_name:
                self._generate_and_send_responses()
        
        else:
            super()._handle_message(msg)
    
    def _generate_and_send_responses(self):
        """Generate and send AI responses based on current state"""
        if not self.connected or self.pause_mode or not self.initialized:
            return
        
        chat_message = self._generate_chat_message()
        if chat_message:
            self._send_chat(chat_message)
            print(f"\n[AGENT] Sent: {chat_message}")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
        
        if self.actions_enabled:
            action = self._generate_action()
            if action and self.character_name:
                self._send_command(f"action {self.character_name} {action}")
                print(f"\n[AGENT] Sent action: {action}")
                if self.show_prompt:
                    sys.stdout.write(self.prompt)
                    sys.stdout.flush()
    
    def run(self):
        """Override run to initialize agent"""
        print("="*60)
        print("SWM AGENT CLIENT")
        print("="*60)
        if self.character_name:
            print(f"Mode: Character Agent - {self.character_name}")
        else:
            print("Mode: Narrator Agent")
        print(f"Chat frequency: Every {self.agent_chat_frequency} epochs")
        print(f"Actions: {'Enabled' if self.actions_enabled else 'Disabled'}")
        print(f"Show reasoning: {'Enabled' if self.show_reasoning else 'Disabled'}")
        if self.chat_style:
            print(f"Chat style: {self.chat_style}")
        if self.mcp_servers:
            print(f"MCP servers: {', '.join(self.mcp_servers)}")
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
        
        super().run()
    
    def connect(self):
        """Override connect to initialize agent after connection"""
        result = super().connect()
        if result:
            self._initialize_agent()
        return result


def parse_agent_args():
    """Parse command line arguments for agent"""
    parser = argparse.ArgumentParser(
        description='SWM AI Agent Client - AI-powered chat and actions',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--config', type=str, default='network_client_config.json', 
                       help='Config file')
    parser.add_argument('--character', '-c', type=str, help='Character name to roleplay as')
    parser.add_argument('--agent_chat_frequency', '-f', type=int, default=3,
                       help='Chat every N epochs (default: 3)')
    parser.add_argument('--actions_enabled', '-a', action='store_true',
                       help='Enable AI-generated actions')
    parser.add_argument('--no-reasoning', action='store_true',
                       help='Disable showing AI reasoning/thinking process')
    parser.add_argument('--chat_style', type=str, default="",
                       help='Style for chat responses (e.g., "dramatic", "funny")')
    parser.add_argument('--chat_history', nargs='?', const=True, default=None,
                       help='Load chat history from file (uses latest run_*.txt if no path)')
    parser.add_argument('--world_folder', type=str, default='world_centralized',
                       help='World folder path')
    parser.add_argument('--model', '-m', type=str, help='LM Studio model key')
    parser.add_argument('--temperature', '-t', type=float, default=0.8,
                       help='Temperature for generation')
    parser.add_argument('--max_tokens', type=int, default=2000,
                       help='Maximum tokens for generation (default: 2000)')
    parser.add_argument('--mcp', action='append', default=[],
                       help='MCP server integration')
    
    return parser.parse_args()


def main():
    args = parse_agent_args()
    
    agent = SWMAgentClient(args.config)
    
    if args.character:
        agent.character_name = args.character
    if args.agent_chat_frequency:
        agent.agent_chat_frequency = args.agent_chat_frequency
    if args.actions_enabled:
        agent.actions_enabled = True
    if args.no_reasoning:
        agent.show_reasoning = False
    if args.chat_style:
        agent.chat_style = args.chat_style
    if args.chat_history is not None:
        agent.chat_history_file = args.chat_history if args.chat_history is not True else None
    if args.world_folder:
        agent.world_folder = args.world_folder
    if args.model:
        agent.model_key = args.model
        load_args = SimpleArgs(context_length=None, gpu_offload=None, cache_type=None)
        agent.lm_chat = LMChat(model_key=args.model, load_config=build_load_config(load_args))
    if args.temperature:
        agent.temperature = args.temperature
    if args.max_tokens:
        agent.max_tokens = args.max_tokens
    if args.mcp:
        agent.mcp_servers = args.mcp
        if agent.lm_chat:
            agent.lm_chat.set_mcp_servers(args.mcp)
    
    agent._update_system_prompt()
    agent.run()


if __name__ == "__main__":
    main()