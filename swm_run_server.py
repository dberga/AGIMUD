#!/usr/bin/env python3
"""
SWM Run Server - Centralized server for multiple clients
"""

import json
import os
import time
import socket
import sys
import argparse
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional
from swm_run import WorldRunner


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


class SWMServer:
    """Centralized server for SWM"""
    
    def __init__(self, config_file: str = "network_server_config.json", args: Any = None):
        self.config = self._load_config(config_file)
        self.running = False
        self.clients: Dict[str, socket.socket] = {}
        self.client_data: Dict[str, Dict[str, Any]] = {}
        self.world_runner = None
        self.args = args or {}
        self.last_render = 0
        self.render_interval = 1.0
        self.log_file = None
        
        # Server socket
        self.server_socket = None
        
        # Use world folder from config or default
        self.world_folder = self.config.get('world', {}).get('world_folder', 'world_centralized')
        
        # Ensure world folder exists
        if not os.path.exists(self.world_folder):
            os.makedirs(self.world_folder, exist_ok=True)
            print(f"[SERVER] Created world folder: {self.world_folder}")
        
        print(f"[SERVER] Initialized on {self.config['server']['host']}:{self.config['server']['port']}")
        print(f"[SERVER] Using world folder: {self.world_folder}")
    
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
            "server": {"host": "127.0.0.1", "port": 5000, "max_clients": 10, "update_interval": 1.0},
            "world": {"world_folder": "world_centralized", "default_fps": 1.0},
            "security": {"auth_required": False, "api_key": "swm_server_key_2026"}
        }
    
    def _log(self, text: str):
        """Write to log file in world folder"""
        if not self.world_folder:
            return
        log_filename = os.path.join(self.world_folder, "server.log")
        try:
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()} - {text}\n")
        except:
            pass
    
    def _check_required_files(self, folder: str) -> bool:
        """Check if required files exist in the world folder"""
        required = ["characters.json", "objects.json", "scenes.json", "rules.json", "world_states.json"]
        missing = []
        for f in required:
            if not os.path.exists(os.path.join(folder, f)):
                missing.append(f)
        
        if missing:
            print(f"[INFO] Missing files in {folder}: {', '.join(missing)}")
            return False
        return True
    
    def _generate_world(self):
        """Generate a new world using swm_generate.py"""
        try:
            print("[SERVER] Generating world...")
            result = subprocess.run(
                [sys.executable, "swm_generate.py", "--folder", self.world_folder],
                capture_output=True,
                text=True,
                cwd=os.getcwd()
            )
            if result.returncode != 0:
                print(f"[SERVER] Failed to generate world: {result.stderr}")
                return False
            
            print(f"[SERVER] World generated in {self.world_folder}")
            return True
        except Exception as e:
            print(f"[SERVER] Error generating world: {e}")
            return False
    
    def _get_global_tick(self) -> int:
        """Get the global tick (day_cycle) from the world state"""
        if not self.world_runner:
            return 0
        ws = self.world_runner.world.world_states.to_dict()
        timers = ws.get('global_timers', {})
        return timers.get('day_cycle', 0)
    
    def _render(self):
        """Render the current world state to console"""
        if not self.world_runner:
            return
        
        ws = self.world_runner.world.world_states.to_dict()
        chars = self.world_runner.world.characters.get_all()
        objs = self.world_runner.world.objects.get_all()
        timers = ws.get('global_timers', {})
        global_tick = timers.get('day_cycle', 0)
        
        output = []
        output.append("\n" + "="*60)
        output.append(f"SERVER WORLD - EPOCH {global_tick}")
        output.append(f"Clients: {len(self.clients)} | FPS: {self.world_runner.fps}")
        output.append(f"World: {self.world_folder}")
        output.append("="*60)
        
        # World State
        global_states = ws.get('global_states', {})
        output.append(f"\n[WORLD STATE]")
        output.append(f"  Scene: {ws.get('current_scene', '?')}")
        output.append(f"  Weather: {global_states.get('weather', '?')}")
        output.append(f"  Time: {global_states.get('time_of_day', '?')}")
        day_cycle = timers.get('day_cycle', 0)
        output.append(f"  Day Cycle: {day_cycle // 60:02d}:{day_cycle % 60:02d}")
        
        # Characters
        output.append(f"\n[CHARACTERS] ({len(chars)})")
        for char in chars[:5]:
            name = char.get('name', 'Unknown')
            ai_state = char.get('ai_state', 'IDLE')
            status = char.get('status_variables', {})
            health = status.get('health', '?')
            stamina = status.get('stamina', '?')
            location = char.get('navigation', {}).get('current_location', '?')
            output.append(f"  {name} [{ai_state}] HP:{health} ST:{stamina} @ {location}")
        if len(chars) > 5:
            output.append(f"  ... and {len(chars) - 5} more")
        
        # Objects
        output.append(f"\n[OBJECTS] ({len(objs)})")
        for obj in objs[:3]:
            name = obj.get('name', 'Unknown')
            props = obj.get('properties', {})
            if isinstance(props, dict):
                obj_type = props.get('type', 'item')
                if isinstance(obj_type, dict):
                    obj_type = obj_type.get('source', 'item')
                    if isinstance(obj_type, dict):
                        obj_type = 'item'
            else:
                obj_type = 'item'
            obj_vars = obj.get('object_variables', {})
            durability = obj_vars.get('durability', '?')
            if isinstance(durability, float):
                durability = int(round(durability))
            quality = obj_vars.get('quality', 'standard')
            output.append(f"  {name} ({obj_type}) [{quality}] Durability:{durability}")
        if len(objs) > 3:
            output.append(f"  ... and {len(objs) - 3} more")
        
        # Clients
        output.append(f"\n[CLIENTS] ({len(self.clients)})")
        for client_id in list(self.clients.keys())[:5]:
            output.append(f"  - {client_id}")
        if len(self.clients) > 5:
            output.append(f"  ... and {len(self.clients) - 5} more")
        
        # Events
        events = self.world_runner.event_history[-5:]
        if events:
            output.append(f"\n[RECENT EVENTS]")
            for event in events:
                output.append(f"  - {event.get('text', '')[:80]}")
        
        output.append("\n" + "="*60)
        output.append("Press Ctrl+C to stop")
        
        # Print to console
        for line in output:
            print(line)
        
        # Log to file
        for line in output:
            self._log(line)
    
    def start(self):
        """Start the server"""
        self.running = True
        
        # Check if world files exist, if not, generate them
        if not self._check_required_files(self.world_folder):
            print("[INFO] Generating world for server...")
            if not self._generate_world():
                print("[ERROR] Failed to generate world. Please run swm_generate.py manually.")
                return
            # Re-check after generation
            if not self._check_required_files(self.world_folder):
                print("[ERROR] World generation failed. Please run swm_generate.py manually.")
                return
        
        # Initialize world with the found folder
        load_existing = not getattr(self.args, 'new', False)
        self.world_runner = WorldRunner(
            fps=self.config['world'].get('default_fps', 1.0),
            load_existing=load_existing,
            world_folder=self.world_folder
        )
        
        # Start server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.config['server']['host'], self.config['server']['port']))
        self.server_socket.listen(self.config['server'].get('max_clients', 10))
        self.server_socket.setblocking(False)
        
        print(f"[SERVER] Listening on {self.config['server']['host']}:{self.config['server']['port']}")
        print("[SERVER] Press Ctrl+C to stop\n")
        
        try:
            while self.running:
                # Accept new connections
                try:
                    client_socket, addr = self.server_socket.accept()
                    client_socket.setblocking(False)
                    client_id = f"client_{addr[1]}"
                    self.clients[client_id] = client_socket
                    self.client_data[client_id] = {"address": addr, "connected": datetime.now().isoformat()}
                    print(f"[SERVER] Client connected: {client_id} from {addr}")
                except BlockingIOError:
                    pass
                
                # Handle client messages
                self._handle_clients()
                
                # Update world
                self.world_runner._update_world()
                
                # Render periodically
                current_time = time.time()
                if current_time - self.last_render >= self.render_interval:
                    self._render()
                    self.last_render = current_time
                
                # Broadcast world state to clients
                self._broadcast_world_state()
                
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down...")
        finally:
            self._cleanup()
    
    def _handle_clients(self):
        """Handle messages from clients"""
        to_remove = []
        for client_id, sock in self.clients.items():
            try:
                data = sock.recv(4096)
                if not data:
                    to_remove.append(client_id)
                    continue
                
                messages = data.decode('utf-8').strip().split('\n')
                for msg_str in messages:
                    if msg_str:
                        msg = NetworkMessage.from_json(msg_str)
                        self._process_client_message(client_id, msg)
                        
            except BlockingIOError:
                continue
            except Exception as e:
                print(f"[SERVER] Error handling client {client_id}: {e}")
                to_remove.append(client_id)
        
        for client_id in to_remove:
            if client_id in self.clients:
                self.clients[client_id].close()
                del self.clients[client_id]
                if client_id in self.client_data:
                    del self.client_data[client_id]
                print(f"[SERVER] Client disconnected: {client_id}")
    
    def _process_client_message(self, client_id: str, msg: NetworkMessage):
        """Process a message from a client"""
        msg_type = msg.type
        
        if msg_type == "HELLO":
            api_key = msg.payload.get('api_key', '')
            if self.config['security'].get('auth_required', False) and api_key != self.config['security'].get('api_key'):
                self._send_to_client(client_id, NetworkMessage("ERROR", {"message": "Authentication failed"}))
                return
            
            self._send_to_client(client_id, NetworkMessage("WELCOME", {
                "client_id": client_id,
                "world_state": self.world_runner.world.world_states.to_dict()
            }))
            print(f"[SERVER] Client {client_id} authenticated")
            
        elif msg_type == "GET_WORLD_STATE":
            self._send_to_client(client_id, NetworkMessage("WORLD_STATE", {
                "world_state": self.world_runner.world.world_states.to_dict(),
                "characters": [c.to_dict() for c in self.world_runner.world.characters.get_all()],
                "objects": [o.to_dict() for o in self.world_runner.world.objects.get_all()]
            }))
            
        elif msg_type == "ACTION":
            action = msg.payload.get('action')
            if action:
                print(f"[SERVER] Client {client_id} performed action: {action}")
                self.world_runner._add_event(f"[CLIENT] {client_id} performed '{action}'", 'action', 'client', client_id)
                
        elif msg_type == "PING":
            self._send_to_client(client_id, NetworkMessage("PONG", {"timestamp": datetime.now().isoformat()}))
    
    def _send_to_client(self, client_id: str, msg: NetworkMessage):
        """Send a message to a specific client"""
        if client_id in self.clients:
            try:
                self.clients[client_id].sendall((msg.to_json() + '\n').encode('utf-8'))
            except Exception as e:
                print(f"[SERVER] Error sending to {client_id}: {e}")
    
    def _broadcast_world_state(self):
        """Broadcast world state to all clients"""
        if not self.world_runner:
            return
        
        # Broadcast every 5 ticks
        if self.world_runner.tick_count % 5 == 0:
            ws = self.world_runner.world.world_states.to_dict()
            timers = ws.get('global_timers', {})
            global_tick = timers.get('day_cycle', 0)
            
            msg = NetworkMessage("WORLD_UPDATE", {
                "tick": self.world_runner.tick_count,
                "global_tick": global_tick,
                "world_state": ws,
                "events": self.world_runner.event_history[-5:]
            })
            for client_id in self.clients:
                self._send_to_client(client_id, msg)
    
    def _cleanup(self):
        """Clean up server resources"""
        for client_id, sock in self.clients.items():
            sock.close()
        self.clients.clear()
        if self.server_socket:
            self.server_socket.close()
        log_file = os.path.join(self.world_folder, "server.log")
        print(f"[SERVER] Cleanup complete. Log saved to {log_file}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='SWM Centralized Server')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    args = parser.parse_args()
    
    print("="*60)
    print("SWM CENTRALIZED SERVER")
    print("="*60)
    server = SWMServer(args=args)
    server.start()


if __name__ == "__main__":
    main()