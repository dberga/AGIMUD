#!/usr/bin/env python3
"""
SWM Run Client - Centralized client with clean atomic epoch rendering and all imports
"""

import json
import os
import time
import socket
import sys
import argparse
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
    """Centralized client for SWM with atomic epoch output"""
    
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
        
        client_cfg = self.config.get('client', {})
        self.client_id = client_cfg.get('id', 'client_001')
        self.server_host = client_cfg.get('server_host', '127.0.0.1')
        self.server_port = client_cfg.get('server_port', 5000)
        
        print(f"[CLIENT] Initialized as {self.client_id}")
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
        user_cfg = self.config.get('user', {})
        sec_cfg = self.config.get('security', {})
        msg = NetworkMessage("HELLO", {
            "client_id": self.client_id,
            "user_name": user_cfg.get('name', 'Player'),
            "api_key": sec_cfg.get('api_key', '')
        })
        self._send(msg)
        print("[CLIENT] Sent HELLO to server")
    
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
    
    def _render(self):
        """Render client dashboard atomically without clearing screen to prevent gaps"""
        output = []
        output.append("\n" + "="*80)
        output.append(f"SIMULATED WORLD CLIENT - EPOCH {self.server_epoch} | Dashboard: {self.client_id} | Connected: {self.connected}")
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
            for char in self.characters:
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
        
        if self.last_events:
            output.append(f"\n[RECENT EVENTS]")
            for event in self.last_events:
                tick = event.get('tick', '?')
                text = event.get('text', '')
                output.append(f"  [{tick}] {text}")
        
        output.append("\n" + "="*80)
        output.append("Press Ctrl+C to disconnect")
        
        full_render_string = "\n".join(output)
        print(full_render_string)
        sys.stdout.flush()
    
    def _handle_message(self, msg: NetworkMessage):
        msg_type = msg.type
        
        if msg_type in ["WELCOME", "WORLD_STATE", "WORLD_UPDATE"]:
            self.world_state = msg.payload.get('world_state', {})
            self.characters = msg.payload.get('characters', [])
            self.server_epoch = msg.payload.get('tick', msg.payload.get('global_tick', msg.payload.get('epoch', self.server_epoch)))
            if 'events' in msg.payload:
                self.last_events = msg.payload.get('events', [])
            self._render()
            
        elif msg_type == "PONG":
            pass
            
        elif msg_type == "ERROR":
            print(f"[CLIENT] Server error: {msg.payload.get('message')}")
    
    def run(self):
        if not self.connect():
            return
        
        self.running = True
        self.send_hello()
        
        print("[CLIENT] Connected! Press Ctrl+C to disconnect\n")
        
        try:
            while self.running:
                if not self.connected:
                    print("[CLIENT] Disconnected from server. Attempting to reconnect...")
                    if self.connect():
                        self.send_hello()
                
                messages = self._receive()
                if messages:
                    for msg in messages:
                        self._handle_message(msg)
                
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n[CLIENT] Disconnecting...")
        finally:
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