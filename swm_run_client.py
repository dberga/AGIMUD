#!/usr/bin/env python3
"""
SWM Run Client - Centralized client with clean atomic epoch rendering and all imports
Supports all commands from swm_run.py
"""

import json
import os
import time
import socket
import sys
import argparse
import threading
import select
from datetime import datetime
from typing import Dict, List, Any, Optional


class NetworkMessage:
    """Network message format"""
    def __init__(self, msg_type: str, payload: Dict[str, Any] = None, sender: str = None):
        self.type = msg_type
        self.payload = payload or {}
        self.sender = sender
        self.timestamp = datetime.now().isoformat()
    
    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "payload": self.payload,
            "sender": self.sender,
            "timestamp": self.timestamp
        })
    
    @staticmethod
    def from_json(data: str) -> 'NetworkMessage':
        obj = json.loads(data)
        msg = NetworkMessage(obj['type'], obj.get('payload', {}), obj.get('sender'))
        msg.timestamp = obj.get('timestamp', '')
        return msg


class SWMClient:
    """Centralized client for SWM with atomic epoch output and command support"""
    
    def __init__(self, config_file: str = "network_client_config.json"):
        self.config = self._load_config(config_file)
        self.running = False
        self.socket = None
        self.received_data = ""
        self.connected = False
        self.world_state = {}
        self.characters = []
        self.last_events = []
        self.server_epoch = 0
        self.server_mode = "auto"
        self.command_queue = []
        self.input_thread = None
        self.waiting_for_response = False
        self.pause_mode = False
        self.last_render_time = 0
        self.prompt = "[CLIENT] > "
        self.show_prompt = True
        
        client_cfg = self.config.get('client', {})
        self.client_id = client_cfg.get('id', 'client_001')
        self.server_host = client_cfg.get('server_host', '127.0.0.1')
        self.server_port = client_cfg.get('server_port', 5000)
        
        # Get user name from config
        user_cfg = self.config.get('user', {})
        self.user_name = user_cfg.get('name', self.client_id)
        
        print(f"[CLIENT] Initialized as {self.client_id} ({self.user_name})")
        print(f"[CLIENT] Server at {self.server_host}:{self.server_port}")
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ERROR] Failed to load config: {e}")
                return self._get_default_config()
        else:
            print(f"[WARNING] {config_file} not found, using defaults")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "client": {"id": "client_001", "host": "127.0.0.1", "port": 5001, 
                      "server_host": "127.0.0.1", "server_port": 5000},
            "user": {"name": "Player", "initial_scene": "Castle"},
            "connection": {"reconnect_attempts": 5, "reconnect_delay": 2, "timeout": 10}
        }
    
    def connect(self):
        attempts = 0
        conn_cfg = self.config.get('connection', {})
        max_attempts = conn_cfg.get('reconnect_attempts', 5)
        delay = conn_cfg.get('reconnect_delay', 2)
        
        while attempts < max_attempts:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.server_host, self.server_port))
                self.socket.setblocking(False)
                self.connected = True
                print(f"[CLIENT] Connected to server")
                return True
            except Exception as e:
                attempts += 1
                print(f"[CLIENT] Connection attempt {attempts} failed: {e}")
                time.sleep(delay)
        
        print("[CLIENT] Failed to connect to server")
        return False
    
    def send_hello(self):
        sec_cfg = self.config.get('security', {})
        msg = NetworkMessage("HELLO", {
            "client_id": self.client_id,
            "user_name": self.user_name,
            "api_key": sec_cfg.get('api_key', '')
        })
        self._send(msg)
        print(f"[CLIENT] Sent HELLO to server as {self.user_name}")
    
    def _send(self, msg: NetworkMessage):
        if self.socket and self.connected:
            try:
                self.socket.sendall((msg.to_json() + '\n').encode('utf-8'))
            except Exception as e:
                print(f"[CLIENT] Error sending: {e}")
                self.connected = False
    
    def _receive(self) -> Optional[List[NetworkMessage]]:
        if not self.socket or not self.connected:
            return None
        
        try:
            data = self.socket.recv(65536)
            if not data:
                self.connected = False
                return None
            
            self.received_data += data.decode('utf-8')
            messages = []
            
            lines = self.received_data.split('\n')
            self.received_data = lines[-1]
            
            for line in lines[:-1]:
                if line.strip():
                    try:
                        messages.append(NetworkMessage.from_json(line))
                    except Exception as e:
                        print(f"[CLIENT] Error parsing message: {e}")
            
            return messages if messages else None
            
        except BlockingIOError:
            return None
        except Exception as e:
            print(f"[CLIENT] Receive error: {e}")
            self.connected = False
            return None
    
    def _render(self, force: bool = False):
        """Render client dashboard"""
        if self.pause_mode and not force:
            current_time = time.time()
            if current_time - self.last_render_time < 15:
                return
            self.last_render_time = current_time
            sys.stdout.write(f"\r[CLIENT] PAUSE MODE | Epoch: {self.server_epoch} | Connected: {self.connected} | Press Enter to resume    \n")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
            return
        
        sys.stdout.write("\r" + " " * 100 + "\r")
        
        output = []
        output.append("="*80)
        output.append(f"SWM CLIENT - EPOCH {self.server_epoch} | {self.user_name} ({self.client_id}) | Mode: {self.server_mode.upper()} | Connected: {self.connected}")
        if self.pause_mode:
            output.append("*** PAUSE MODE ACTIVE - Updates paused ***")
        output.append("="*80)
        
        global_states = self.world_state.get('global_states', {})
        timers = self.world_state.get('global_timers', {})
        day_cycle = timers.get('day_cycle', 0)
        hours = int(day_cycle // 60)
        minutes = int(day_cycle % 60)
        
        output.append(f"\n[WORLD STATE]")
        output.append(f"  Weather: {global_states.get('weather', 'Unknown')}")
        output.append(f"  Time of Day: {global_states.get('time_of_day', 'Unknown')}")
        output.append(f"  Mood: {global_states.get('mood', 'combat')}")
        output.append(f"  Clock: {hours:02d}:{minutes:02d}")
        
        if self.characters:
            output.append(f"\n[CHARACTERS] ({len(self.characters)})")
            for char in self.characters[:10]:
                name = char.get('name', 'Unknown') if isinstance(char, dict) else 'Unknown'
                ai_state = char.get('ai_state', 'IDLE') if isinstance(char, dict) else 'IDLE'
                goal = char.get('goal', 'social_belonging') if isinstance(char, dict) else 'social_belonging'
                emotion = char.get('emotion', 'neutral') if isinstance(char, dict) else 'neutral'
                status = char.get('status_variables', {}) if isinstance(char, dict) else {}
                health = int(round(status.get('health', 100))) if isinstance(status.get('health'), (int, float)) else '?'
                stamina = int(round(status.get('stamina', 100))) if isinstance(status.get('stamina'), (int, float)) else '?'
                nav = char.get('navigation', {}) if isinstance(char, dict) else {}
                location = nav.get('current_location', 'Unknown')
                
                output.append(f"  * {name} [{ai_state}] | Goal: {goal} | Emotion: {emotion} | HP:{health} | ST:{stamina} @ {location}")
            if len(self.characters) > 10:
                output.append(f"  ... and {len(self.characters) - 10} more")
        
        if self.last_events:
            output.append(f"\n[RECENT EVENTS]")
            for event in self.last_events[-5:]:
                tick = event.get('tick', '?')
                text = event.get('text', '')
                output.append(f"  [{tick}] {text}")
        
        output.append("\n" + "="*80)
        if self.pause_mode:
            output.append("Press Enter to resume updates | Commands: help, summary, catalog, var, list, action, set, save, mode, chat, q")
        else:
            output.append("Press Enter to pause updates | Commands: help, summary, catalog, var, list, action, set, save, mode, chat, q")
        
        print("\n".join(output))
        sys.stdout.flush()
        self.last_render_time = time.time()
        
        if self.show_prompt:
            sys.stdout.write(self.prompt)
            sys.stdout.flush()
    
    def _handle_chat_message(self, sender: str, message: str):
        """Handle incoming chat message"""
        print(f"\n[CHAT] {sender}: {message}")
        if self.show_prompt:
            sys.stdout.write(self.prompt)
            sys.stdout.flush()
    
    def _handle_message(self, msg: NetworkMessage):
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
            self._render()
            
        elif msg_type == "PONG":
            pass
            
        elif msg_type == "ERROR":
            self.waiting_for_response = False
            print(f"\n[CLIENT] Server error: {msg.payload.get('message')}")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
        
        elif msg_type == "COMMAND_RESULT":
            self.waiting_for_response = False
            cmd = msg.payload.get('command', '')
            result = msg.payload.get('result', '')
            print(f"\n[CLIENT] Result for '{cmd}':\n{result}")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
        
        elif msg_type == "CHAT":
            sender = msg.payload.get('sender', 'Unknown')
            message = msg.payload.get('message', '')
            self._handle_chat_message(sender, message)
    
    def _send_chat(self, message: str):
        """Send a chat message with user name"""
        msg = NetworkMessage("CHAT", {
            "sender": self.user_name,
            "message": message
        })
        self._send(msg)
    
    def _input_listener(self):
        """Listen for client input"""
        cmd_buffer = ""
        while self.running:
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    if msvcrt.kbhit():
                        char = msvcrt.getch()
                        if char == b'\r':  # Enter
                            print()
                            self.show_prompt = False
                            
                            if not cmd_buffer.strip():
                                self.pause_mode = not self.pause_mode
                                if self.pause_mode:
                                    print("[CLIENT] PAUSE MODE enabled. Updates paused. Press Enter to resume.")
                                else:
                                    print("[CLIENT] LIVE MODE enabled. Showing updates.")
                                    self._render(force=True)
                            else:
                                self.command_queue.append(cmd_buffer.strip())
                            
                            cmd_buffer = ""
                            self.show_prompt = True
                            if self.running:
                                sys.stdout.write(self.prompt)
                                sys.stdout.flush()
                        elif char == b'\x08':  # Backspace
                            if cmd_buffer:
                                cmd_buffer = cmd_buffer[:-1]
                                sys.stdout.write('\b \b')
                                sys.stdout.flush()
                        else:
                            try:
                                decoded = char.decode('utf-8')
                                if decoded.isprintable():
                                    cmd_buffer += decoded
                                    sys.stdout.write(decoded)
                                    sys.stdout.flush()
                            except UnicodeDecodeError:
                                pass
                else:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        char = sys.stdin.read(1)
                        if char == '\n' or char == '\r':
                            print()
                            self.show_prompt = False
                            
                            if not cmd_buffer.strip():
                                self.pause_mode = not self.pause_mode
                                if self.pause_mode:
                                    print("[CLIENT] PAUSE MODE enabled. Updates paused. Press Enter to resume.")
                                else:
                                    print("[CLIENT] LIVE MODE enabled. Showing updates.")
                                    self._render(force=True)
                            else:
                                self.command_queue.append(cmd_buffer.strip())
                            
                            cmd_buffer = ""
                            self.show_prompt = True
                            if self.running:
                                sys.stdout.write(self.prompt)
                                sys.stdout.flush()
                        elif char == '\x7f' or char == '\x08':
                            if cmd_buffer:
                                cmd_buffer = cmd_buffer[:-1]
                                sys.stdout.write('\b \b')
                                sys.stdout.flush()
                        elif char.isprintable():
                            cmd_buffer += char
                            sys.stdout.write(char)
                            sys.stdout.flush()
                time.sleep(0.01)
            except:
                time.sleep(0.1)
    
    def _process_command(self, cmd: str) -> bool:
        """Process a client command locally or send to server"""
        cmd = cmd.strip().lower()
        
        if not cmd:
            return False
        
        parts = cmd.split()
        command = parts[0].lower()
        
        if command in ['q', 'quit', 'exit']:
            print("\n[CLIENT] Disconnecting...")
            self.running = False
            return True
        
        if command == 'help':
            print("\n" + "="*60)
            print("CLIENT COMMANDS")
            print("="*60)
            print("  [Enter]              - Toggle PAUSE/LIVE mode")
            print("  help                 - Show this help menu")
            print("  summary              - Request world summary from server")
            print("  catalog              - List all available actions in catalog")
            print("  var                  - List all available variables")
            print("  list                 - List all characters, states, and HP")
            print("  action <Name> <ACTION> - Force character action intent")
            print("  set char <Name> <var> <val> - Modify character status variable")
            print("  set world <key> <val> - Modify global world state")
            print("  save                 - Save current world state on server")
            print("  mode                 - Show current server mode")
            print("  chat <message>       - Send a chat message to all clients")
            print("  resume               - Resume updates (exit pause mode)")
            print("  q / quit / exit      - Disconnect and exit")
            print("="*60)
            return False
        
        if command == 'mode':
            print(f"\n[SERVER MODE] {self.server_mode.upper()}")
            return False
        
        if command == 'resume':
            if self.pause_mode:
                self.pause_mode = False
                print("[CLIENT] LIVE MODE enabled. Showing updates.")
                self._render(force=True)
            else:
                print("[CLIENT] Already in LIVE mode.")
            return False
        
        if command == 'chat':
            if len(parts) < 2:
                print("[ERROR] Usage: chat <message>")
                return False
            if self.connected:
                message = ' '.join(parts[1:])
                self._send_chat(message)
                print(f"[CLIENT] Sent chat: {message}")
            else:
                print("[CLIENT] Not connected to server.")
            return False
        
        if self.connected:
            self._send_command(cmd)
            print(f"[CLIENT] Sent command to server: {cmd}")
        else:
            print("[CLIENT] Not connected to server.")
        
        return False
    
    def _send_command(self, command: str):
        """Send a command to the server"""
        msg = NetworkMessage("COMMAND", {
            "command": command
        })
        self._send(msg)
    
    def run(self):
        if not self.connect():
            return
        
        self.running = True
        self.send_hello()
        
        self.input_thread = threading.Thread(target=self._input_listener, daemon=True)
        self.input_thread.start()
        
        print("[CLIENT] Connected! Type 'help' for commands, 'q' to quit")
        print("[CLIENT] Press Enter to toggle PAUSE/LIVE mode (pause/resume updates)")
        sys.stdout.write(self.prompt)
        sys.stdout.flush()
        
        try:
            while self.running:
                while self.command_queue:
                    cmd = self.command_queue.pop(0)
                    self.show_prompt = False
                    if self._process_command(cmd):
                        return
                    self.show_prompt = True
                    if self.running:
                        sys.stdout.write(self.prompt)
                        sys.stdout.flush()
                
                if not self.connected:
                    print("\n[CLIENT] Disconnected from server. Attempting to reconnect...")
                    if self.connect():
                        self.send_hello()
                
                messages = self._receive()
                if messages:
                    for msg in messages:
                        self._handle_message(msg)
                
                time.sleep(0.05)
                
        except KeyboardInterrupt:
            print("\n[CLIENT] Disconnecting...")
        finally:
            self.running = False
            if self.socket:
                self.socket.close()
            print("[CLIENT] Disconnected")


def main():
    parser = argparse.ArgumentParser(description='SWM Centralized Client')
    parser.add_argument('--config', type=str, default='network_client_config.json', help='Config file')
    args = parser.parse_args()
    
    print("="*60)
    print("SWM CENTRALIZED CLIENT")
    print("="*60)
    client = SWMClient(args.config)
    client.run()


if __name__ == "__main__":
    main()