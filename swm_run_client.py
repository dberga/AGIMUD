#!/usr/bin/env python3
"""
SWM Run Client - Centralized client connecting to server
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
    """Centralized client for SWM"""
    
    def __init__(self, config_file: str = "network_client_config.json"):
        self.config = self._load_config(config_file)
        self.running = False
        self.socket = None
        self.received_data = ""
        self.connected = False
        self.last_render = 0
        self.render_interval = 1.0
        self.world_state = {}
        self.last_events = []
        self.server_epoch = 0
        
        print(f"[CLIENT] Initialized as {self.config['client']['id']}")
        print(f"[CLIENT] Server at {self.config['client']['server_host']}:{self.config['client']['server_port']}")
    
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
        """Connect to the server"""
        attempts = 0
        max_attempts = self.config['connection'].get('reconnect_attempts', 5)
        
        while attempts < max_attempts:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((
                    self.config['client']['server_host'],
                    self.config['client']['server_port']
                ))
                self.socket.setblocking(False)
                self.connected = True
                print(f"[CLIENT] Connected to server")
                return True
            except Exception as e:
                attempts += 1
                print(f"[CLIENT] Connection attempt {attempts} failed: {e}")
                time.sleep(self.config['connection'].get('reconnect_delay', 2))
        
        print("[CLIENT] Failed to connect to server")
        return False
    
    def send_hello(self):
        """Send HELLO message to authenticate"""
        msg = NetworkMessage("HELLO", {
            "client_id": self.config['client']['id'],
            "user_name": self.config['user'].get('name', 'Player'),
            "api_key": self.config.get('security', {}).get('api_key', '')
        })
        self._send(msg)
        print("[CLIENT] Sent HELLO to server")
    
    def _send(self, msg: NetworkMessage):
        """Send a message to the server"""
        if self.socket and self.connected:
            try:
                self.socket.sendall((msg.to_json() + '\n').encode('utf-8'))
            except Exception as e:
                print(f"[CLIENT] Error sending: {e}")
                self.connected = False
    
    def _receive(self) -> Optional[List[NetworkMessage]]:
        """Receive messages from the server"""
        if not self.socket or not self.connected:
            return None
        
        try:
            data = self.socket.recv(4096)
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
        """Render client status - minimal like P2P joiner"""
        print(f"\n[CLIENT] {self.config['client']['id']} - Connected: {self.connected}, EPOCH: {self.server_epoch}")
    
    def _handle_message(self, msg: NetworkMessage):
        """Handle a received message"""
        msg_type = msg.type
        
        if msg_type == "WELCOME":
            print(f"[CLIENT] Welcome! Client ID: {msg.payload.get('client_id')}")
            self.world_state = msg.payload.get('world_state', {})
            self.server_epoch = 0
            self._render()
            
        elif msg_type == "WORLD_STATE":
            self.world_state = msg.payload.get('world_state', {})
            self._render()
            
        elif msg_type == "WORLD_UPDATE":
            self.server_epoch = msg.payload.get('global_tick', 0)
            self.world_state = msg.payload.get('world_state', {})
            self.last_events = msg.payload.get('events', [])
            self._render()
            
        elif msg_type == "PONG":
            print(f"[CLIENT] PONG from server")
            
        elif msg_type == "ERROR":
            print(f"[CLIENT] Server error: {msg.payload.get('message')}")
    
    def run(self):
        """Main client loop"""
        if not self.connect():
            return
        
        self.running = True
        self.send_hello()
        
        print("[CLIENT] Connected! Press Ctrl+C to disconnect\n")
        
        try:
            while self.running:
                # Check connection
                if not self.connected:
                    print("[CLIENT] Disconnected from server. Attempting to reconnect...")
                    if self.connect():
                        self.send_hello()
                
                # Receive messages
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