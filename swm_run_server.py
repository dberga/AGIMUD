#!/usr/bin/env python3
"""
SWM Run Server - Centralized server rendering every single epoch 1 by 1 with full world folder support
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
    """Centralized server for SWM rendering every epoch with custom world folder support"""
    
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
        
        server_cfg = self.config.get('server', {'host': '127.0.0.1', 'port': 5000, 'max_clients': 10, 'update_interval': 1.0})
        world_cfg = self.config.get('world', {'world_folder': 'world_centralized', 'default_fps': 1.0})
        
        self.host = server_cfg.get('host', '127.0.0.1')
        self.port = server_cfg.get('port', 5000)
        self.max_clients = server_cfg.get('max_clients', 10)
        
        # Support command-line world folder specification just like swm_run.py
        arg_world = getattr(self.args, 'world', None)
        if arg_world:
            self.world_folder = arg_world
        else:
            self.world_folder = world_cfg.get('world_folder', 'world_centralized')
            
        self.default_fps = getattr(self.args, 'fps', None) or world_cfg.get('default_fps', 1.0)
        self.server_socket = None
        
        if not os.path.exists(self.world_folder):
            os.makedirs(self.world_folder, exist_ok=True)
            print(f"[SERVER] Created world folder: {self.world_folder}")
        
        print(f"[SERVER] Initialized on {self.host}:{self.port}")
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
        if not self.world_folder:
            return
        log_filename = os.path.join(self.world_folder, "server.log")
        try:
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()} - {text}\n")
        except:
            pass
    
    def _check_required_files(self, folder: str) -> bool:
        required = ["characters.json", "objects.json", "scenes.json", "rules.json", "world_states.json"]
        for f in required:
            if not os.path.exists(os.path.join(folder, f)):
                return False
        return True
    
    def _generate_world(self):
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
    
    def _render(self):
        if not self.world_runner:
            return
        
        ws = self.world_runner.world.world_states.to_dict()
        chars = self.world_runner.world.characters.get_all()
        objs = self.world_runner.world.objects.get_all()
        timers = ws.get('global_timers', {})
        global_tick = timers.get('day_cycle', 0)
        
        output = []
        output.append("\n" + "="*80)
        output.append(f"SIMULATED WORLD - EPOCH {self.world_runner.tick_count}")
        output.append(f"FPS: {self.world_runner.fps} | Clients: {len(self.clients)} | Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append(f"World: {self.world_folder}")
        output.append("="*80)
        
        global_states = ws.get('global_states', {})
        output.append(f"\n[WORLD STATE]")
        output.append(f"  Weather: {global_states.get('weather', '?')}")
        output.append(f"  Time: {global_states.get('time_of_day', '?')}")
        output.append(f"  Mood: {global_states.get('mood', 'combat')}")
        output.append(f"  Day Cycle: {global_tick // 60:02d}:{global_tick % 60:02d}")
        
        output.append(f"\n[CHARACTERS] ({len(chars)})")
        for char in chars:
            name = char.get('name', 'Unknown')
            ai_state = char.get('ai_state', 'IDLE')
            goal = char.get('goal', 'social_belonging')
            emotion = char.get('emotion', 'neutral')
            status = char.get('status_variables', {})
            health = int(round(status.get('health', 100))) if isinstance(status.get('health'), (int, float)) else '?'
            stamina = int(round(status.get('stamina', 100))) if isinstance(status.get('stamina'), (int, float)) else '?'
            location = char.get('navigation', {}).get('current_location', '?')
            output.append(f"  * {name} [{ai_state}] | Goal: {goal} | Emotion: {emotion} | HP:{health} | ST:{stamina} @ {location}")
        
        output.append(f"\n[OBJECTS] ({len(objs)})")
        for obj in objs[:3]:
            name = obj.get('name', 'Unknown')
            props = obj.get('properties', {})
            obj_type = props.get('type', 'item') if isinstance(props, dict) else 'item'
            obj_vars = obj.get('object_variables', {})
            durability = int(round(obj_vars.get('durability', 0))) if isinstance(obj_vars.get('durability'), float) else obj_vars.get('durability', '?')
            quality = obj_vars.get('quality', 'standard')
            output.append(f"  - {name} ({obj_type}) [{quality}] Durability:{durability}")
        if len(objs) > 3:
            output.append(f"  ... and {len(objs) - 3} more")
        
        output.append(f"\n[CLIENTS] ({len(self.clients)})")
        for client_id in list(self.clients.keys()):
            output.append(f"  - {client_id}")
        
        events = self.world_runner.event_history[-10:]
        if events:
            output.append(f"\n[RECENT EVENTS]")
            for event in events:
                tick = event.get('tick', '?')
                text = event.get('text', '')
                output.append(f"  [{tick}] {text}")
        
        output.append("\n" + "="*80)
        
        full_render_string = "\n".join(output)
        print(full_render_string)
        self._log(full_render_string)
        sys.stdout.flush()
    
    def start(self):
        self.running = True
        
        if not self._check_required_files(self.world_folder):
            print(f"[INFO] Generating world for server in {self.world_folder}...")
            if not self._generate_world() or not self._check_required_files(self.world_folder):
                print("[ERROR] World setup failed.")
                return
        
        load_existing = not getattr(self.args, 'new', False)
        self.world_runner = WorldRunner(
            fps=self.default_fps,
            load_existing=load_existing,
            world_folder=self.world_folder
        )
        
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(self.max_clients)
        self.server_socket.setblocking(False)
        
        print(f"[SERVER] Listening on {self.host}:{self.port}")
        print("[SERVER] Press Ctrl+C to stop\n")
        sys.stdout.flush()
        
        try:
            while self.running:
                try:
                    client_socket, addr = self.server_socket.accept()
                    client_socket.setblocking(False)
                    client_id = f"client_{addr[1]}"
                    self.clients[client_id] = client_socket
                    self.client_data[client_id] = {"address": addr, "connected": datetime.now().isoformat()}
                    print(f"[SERVER] Client connected: {client_id} from {addr}")
                except BlockingIOError:
                    pass
                
                self._handle_clients()
                
                # Advance simulation by 1 epoch
                self.world_runner._update_world()
                
                # Render every single epoch 1 by 1
                self._render()
                
                self._broadcast_world_state()
                time.sleep(1.0 / self.world_runner.fps)
                
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down...")
            if self.world_runner:
                self.world_runner._save_runtime_state()
        finally:
            self._cleanup()
    
    def _handle_clients(self):
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
        msg_type = msg.type
        sec_cfg = self.config.get('security', {})
        
        if msg_type == "HELLO":
            api_key = msg.payload.get('api_key', '')
            if sec_cfg.get('auth_required', False) and api_key != sec_cfg.get('api_key'):
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
        if client_id in self.clients:
            try:
                self.clients[client_id].sendall((msg.to_json() + '\n').encode('utf-8'))
            except Exception as e:
                print(f"[SERVER] Error sending to {client_id}: {e}")
    
    def _broadcast_world_state(self):
        if not self.world_runner:
            return
        
        ws = self.world_runner.world.world_states.to_dict()
        timers = ws.get('global_timers', {})
        global_tick = timers.get('day_cycle', 0)
        
        msg = NetworkMessage("WORLD_UPDATE", {
            "tick": self.world_runner.tick_count,
            "global_tick": global_tick,
            "world_state": ws,
            "characters": [c.to_dict() for c in self.world_runner.world.characters.get_all()],
            "events": self.world_runner.event_history[-5:]
        })
        for client_id in self.clients:
            self._send_to_client(client_id, msg)
    
    def _cleanup(self):
        for client_id, sock in self.clients.items():
            sock.close()
        self.clients.clear()
        if self.server_socket:
            self.server_socket.close()
        print(f"[SERVER] Cleanup complete. Log saved to {os.path.join(self.world_folder, 'server.log')}")


def main():
    parser = argparse.ArgumentParser(description='SWM Centralized Server')
    parser.add_argument('--fps', type=float, default=1.0, help='Frames per second (default: 1.0)')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    parser.add_argument('--world', type=str, help='Specify an existing world folder to load')
    args = parser.parse_args()
    
    print("="*60)
    print("SWM CENTRALIZED SERVER")
    print("="*60)
    server = SWMServer(args=args)
    server.start()


if __name__ == "__main__":
    main()