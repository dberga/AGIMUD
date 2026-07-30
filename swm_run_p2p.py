#!/usr/bin/env python3
"""
SWM Run P2P - P2P node for distributed SWM with dynamic config loading and 1-by-1 epoch streaming
"""

import json
import os
import time
import socket
import threading
import sys
import argparse
import shutil
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional
from swm_run import WorldRunner


class NetworkMessage:
    """Network message format for P2P"""
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


class SignalingServer:
    """Simple signaling server for P2P discovery"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 7000, timeout: int = 5):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.running = False
        self.socket = None
    
    def start(self):
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(100)
        self.socket.setblocking(False)
        
        print(f"[SIGNALING] Server started on {self.host}:{self.port}")
        sys.stdout.flush()
        
        while self.running:
            try:
                client_socket, addr = self.socket.accept()
                client_socket.settimeout(self.timeout)
                data = client_socket.recv(65536).decode('utf-8')
                if data:
                    self._handle_request(data, client_socket)
                client_socket.close()
            except BlockingIOError:
                pass
            except Exception as e:
                pass
            time.sleep(0.1)
    
    def _handle_request(self, data: str, sock: socket.socket):
        try:
            msg = NetworkMessage.from_json(data)
            if msg.type == "REGISTER":
                node_id = msg.payload.get('node_id')
                host = msg.payload.get('host')
                port = msg.payload.get('port')
                if node_id:
                    self.nodes[node_id] = {"host": host, "port": port, "last_seen": datetime.now().isoformat()}
                    peers = [{"id": nid, "host": info['host'], "port": info['port']} 
                            for nid, info in self.nodes.items() if nid != node_id]
                    response = NetworkMessage("PEERS", {"peers": peers})
                    sock.sendall((response.to_json() + '\n').encode('utf-8'))
                    sys.stdout.flush()
        except Exception as e:
            pass
    
    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()


class SWMP2PNode:
    """P2P Node with configuration-driven broadcast intervals and atomic rendering"""
    
    def __init__(self, config_file: str = "network_p2p_config.json", 
                 role: str = "host", args: Any = None):
        self.config = self._load_config(config_file)
        self.role = role
        self.args = args or {}
        self.running = False
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.node_socket = None
        self.world_runner = None
        
        world_cfg = self.config.get('world', {'world_folder': 'world_p2p', 'sync_interval': 2.0, 'broadcast_interval': 1})
        node_cfg = self.config.get('node', {'id': 'node_001', 'host': '127.0.0.1', 'port': 6000})
        conn_cfg = self.config.get('connection', {'timeout': 5})
        
        self.sync_interval = world_cfg.get('sync_interval', 2.0)
        self.broadcast_interval = world_cfg.get('broadcast_interval', 1)
        self.timeout = conn_cfg.get('timeout', 5)
        
        arg_world = getattr(self.args, 'world', None)
        if arg_world:
            self.world_folder = arg_world
        else:
            self.world_folder = world_cfg.get('world_folder', 'world_p2p')
            
        self.node_id = node_cfg.get('id', 'node_001')
        self.node_host = node_cfg.get('host', '127.0.0.1')
        self.node_port = node_cfg.get('port', 6000)
        
        self.last_sync = 0
        self.last_render = 0
        self.render_interval = 1.0
        self.is_connected = False
        
        self.synced_world_state = {}
        self.synced_characters = []
        self.synced_objects = []
        self.synced_events = []
        self.synced_epoch = 0
        
        if self.role == "host":
            print("[P2P] Starting signaling server...")
            sig_cfg = self.config.get('signaling_server', {'host': '127.0.0.1', 'port': 7000})
            threading.Thread(target=self._run_signaling_server, args=(sig_cfg['host'], sig_cfg['port'], self.timeout), daemon=True).start()
            time.sleep(1)
        
        print(f"[P2P] Node initialized as {self.role.upper()} - {self.node_id}")
        print(f"[P2P] Listening on {self.node_host}:{self.node_port}")
        print(f"[P2P] Broadcast Interval: every {self.broadcast_interval} tick(s)")
        sys.stdout.flush()
    
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
            "node": {"id": "node_001", "host": "127.0.0.1", "port": 6000},
            "signaling_server": {"host": "127.0.0.1", "port": 7000},
            "world": {"world_folder": "world_p2p", "sync_interval": 2.0, "broadcast_interval": 1},
            "connection": {"timeout": 5},
            "user": {"name": "P2P_Player", "initial_scene": "Castle"}
        }
    
    def _run_signaling_server(self, host: str, port: int, timeout: int):
        signaling = SignalingServer(host, port, timeout)
        signaling.start()
    
    def _log(self, text: str):
        if not self.world_folder:
            return
        os.makedirs(self.world_folder, exist_ok=True)
        log_filename = os.path.join(self.world_folder, f"p2p_{self.node_id}.log")
        try:
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()} - {text}\n")
        except:
            pass
    
    def _generate_world(self):
        try:
            print("[P2P] Generating world...")
            result = subprocess.run([sys.executable, "swm_generate.py", "--folder", self.world_folder], 
                                  capture_output=True, text=True, cwd=os.getcwd())
            if result.returncode != 0:
                print(f"[P2P] Failed to generate world: {result.stderr}")
                return
            print(f"[P2P] World generated in {self.world_folder}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[P2P] Error generating world: {e}")
    
    def _initialize_world(self):
        required = ["characters.json", "objects.json", "scenes.json", "rules.json", "world_states.json"]
        os.makedirs(self.world_folder, exist_ok=True)
        all_exist = all(os.path.exists(os.path.join(self.world_folder, f)) for f in required)
        
        if not all_exist:
            if self.role == "host":
                print(f"[P2P] Generating world for host...")
                self._generate_world()
            else:
                print(f"[P2P] Waiting for world sync from host...")
                sys.stdout.flush()
                return False
        
        load_existing = not getattr(self.args, 'new', False)
        self.world_runner = WorldRunner(
            fps=1.0,
            load_existing=load_existing,
            world_folder=self.world_folder
        )
        return True
    
    def register_with_signaling(self, silent: bool = False):
        try:
            sig_cfg = self.config.get('signaling_server', {'host': '127.0.0.1', 'port': 7000})
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((sig_cfg['host'], sig_cfg['port']))
            
            msg = NetworkMessage("REGISTER", {
                "node_id": self.node_id,
                "host": self.node_host,
                "port": self.node_port
            })
            sock.sendall((msg.to_json() + '\n').encode('utf-8'))
            
            data = sock.recv(4096).decode('utf-8')
            if data:
                response = NetworkMessage.from_json(data)
                if response.type == "PEERS":
                    peers = response.payload.get('peers', [])
                    self.peers.clear()
                    for peer in peers:
                        if peer['id'] != self.node_id:
                            self.peers[peer['id']] = {"host": peer['host'], "port": peer['port']}
                    if not silent:
                        print(f"[P2P] Registered. Found {len(self.peers)} peers")
                        sys.stdout.flush()
            sock.close()
        except Exception as e:
            pass
    
    def _render(self):
        """Unified atomic render block matching Server and Client layout"""
        output = []
        output.append("\n" + "="*80)
        
        if self.role == "host":
            ws = self.world_runner.world.world_states.to_dict() if self.world_runner else {}
            chars = self.world_runner.world.characters.get_all() if self.world_runner else []
            objs = self.world_runner.world.objects.get_all() if self.world_runner else []
            timers = ws.get('global_timers', {})
            epoch = timers.get('day_cycle', 0)
            tick = self.world_runner.tick_count if self.world_runner else 0
            events = self.world_runner.event_history[-10:] if self.world_runner else []
            
            output.append(f"SIMULATED WORLD P2P [HOST] - EPOCH {tick} | Node: {self.node_id} | Peers: {len(self.peers)}")
            output.append("="*80)
            
            global_states = ws.get('global_states', {})
            output.append(f"\n[WORLD STATE]")
            output.append(f"  Weather: {global_states.get('weather', 'Unknown')}")
            output.append(f"  Time of Day: {global_states.get('time_of_day', 'Unknown')}")
            output.append(f"  Mood: {global_states.get('mood', 'combat')}")
            output.append(f"  Day Cycle: {epoch // 60:02d}:{epoch % 60:02d}")
            
            output.append(f"\n[CHARACTERS] ({len(chars)})")
            for char in chars:
                name = char.get('name', 'Unknown')
                ai_state = char.get('ai_state', 'IDLE')
                goal = char.get('goal', 'social_belonging')
                emotion = char.get('emotion', 'neutral')
                status = char.get('status_variables', {})
                health = int(round(status.get('health', 100))) if isinstance(status.get('health'), (int, float)) else '?'
                stamina = int(round(status.get('stamina', 100))) if isinstance(status.get('stamina'), (int, float)) else '?'
                location = char.get('navigation', {}).get('current_location', 'Unknown')
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
            
            if events:
                output.append(f"\n[RECENT EVENTS]")
                for event in events:
                    t = event.get('tick', '?')
                    text = event.get('text', '')
                    output.append(f"  [{t}] {text}")
                    
        else:
            # Joiner view
            output.append(f"SIMULATED WORLD P2P [JOINER] - EPOCH {self.synced_epoch} | Node: {self.node_id} | Connected: {self.is_connected}")
            output.append("="*80)
            
            global_states = self.synced_world_state.get('global_states', {})
            timers = self.synced_world_state.get('global_timers', {})
            day_cycle = timers.get('day_cycle', 0)
            
            output.append(f"\n[WORLD STATE]")
            output.append(f"  Weather: {global_states.get('weather', 'Unknown')}")
            output.append(f"  Time of Day: {global_states.get('time_of_day', 'Unknown')}")
            output.append(f"  Mood: {global_states.get('mood', 'combat')}")
            output.append(f"  Day Cycle: {int(day_cycle // 60):02d}:{int(day_cycle % 60):02d}")
            
            if self.synced_characters:
                output.append(f"\n[CHARACTERS] ({len(self.synced_characters)})")
                for char in self.synced_characters:
                    name = char.get('name', 'Unknown') if isinstance(char, dict) else 'Unknown'
                    ai_state = char.get('ai_state', 'IDLE') if isinstance(char, dict) else 'IDLE'
                    goal = char.get('goal', 'social_belonging') if isinstance(char, dict) else 'social_belonging'
                    emotion = char.get('emotion', 'neutral') if isinstance(char, dict) else 'neutral'
                    status = char.get('status_variables', {}) if isinstance(char, dict) else {}
                    health = int(round(status.get('health', 100))) if isinstance(status.get('health'), (int, float)) else '?'
                    stamina = int(round(status.get('stamina', 100))) if isinstance(status.get('stamina'), (int, float)) else '?'
                    location = char.get('navigation', {}).get('current_location', 'Unknown')
                    output.append(f"  * {name} [{ai_state}] | Goal: {goal} | Emotion: {emotion} | HP:{health} | ST:{stamina} @ {location}")
            
            if self.synced_events:
                output.append(f"\n[RECENT EVENTS]")
                for event in self.synced_events:
                    t = event.get('tick', '?')
                    text = event.get('text', '')
                    output.append(f"  [{t}] {text}")
        
        output.append("\n" + "="*80)
        output.append("Press Ctrl+C to stop")
        
        full_render_string = "\n".join(output)
        print(full_render_string)
        self._log(full_render_string)
        sys.stdout.flush()
    
    def _handle_peer_message(self, msg: NetworkMessage, sock: socket.socket):
        msg_type = msg.type
        
        if msg_type == "REQUEST_WORLD":
            if self.role == "host" and self.world_runner:
                ws = self.world_runner.world.world_states.to_dict()
                timers = ws.get('global_timers', {})
                epoch = timers.get('day_cycle', 0)
                chars = [c.to_dict() for c in self.world_runner.world.characters.get_all()]
                objs = [o.to_dict() for o in self.world_runner.world.objects.get_all()]
                events = self.world_runner.event_history[-10:]
                
                response = NetworkMessage("WORLD_STATE", {
                    "epoch": epoch,
                    "tick": self.world_runner.tick_count,
                    "world_state": ws,
                    "characters": chars,
                    "objects": objs,
                    "events": events
                }, sender=self.node_id)
                sock.sendall((response.to_json() + '\n').encode('utf-8'))
                
        elif msg_type == "WORLD_STATE":
            if self.role == "join":
                self.synced_epoch = msg.payload.get('tick', msg.payload.get('epoch', 0))
                self.synced_world_state = msg.payload.get('world_state', {})
                self.synced_characters = msg.payload.get('characters', [])
                self.synced_objects = msg.payload.get('objects', [])
                self.synced_events = msg.payload.get('events', [])
                self.is_connected = True
                
                if self.world_runner:
                    world = self.world_runner.world
                    for key, value in self.synced_world_state.items():
                        world.world_states.set(key, value)
                    world.characters.clear_all()
                    for char_data in self.synced_characters:
                        world.characters.add_entity(char_data)
                    world.objects.clear_all()
                    for obj_data in self.synced_objects:
                        world.objects.add_entity(obj_data)
                    if self.synced_events:
                        self.world_runner.event_history = self.synced_events
                
                self._render()
    
    def start(self):
        self.running = True
        self._initialize_world()
        self.register_with_signaling(silent=False)
        
        self.node_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.node_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.node_socket.bind((self.node_host, self.node_port))
        self.node_socket.listen(10)
        self.node_socket.setblocking(False)
        
        print(f"[P2P] Node listening on port {self.node_port}")
        print("[P2P] Press Ctrl+C to stop\n")
        sys.stdout.flush()
        
        try:
            while self.running:
                self._accept_connections()
                self._sync_with_peers()
                
                if self.role == "host" and self.world_runner:
                    self.world_runner._update_world()
                    self._render()
                    
                    if self.world_runner.tick_count % self.broadcast_interval == 0:
                        self._broadcast_to_peers()
                
                time.sleep(1.0 / 1.0)
                
        except KeyboardInterrupt:
            print("\n[P2P] Shutting down...")
        finally:
            self._cleanup()
    
    def _accept_connections(self):
        try:
            client_socket, addr = self.node_socket.accept()
            client_socket.settimeout(self.timeout)
            data = b''
            while True:
                try:
                    chunk = client_socket.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                    if data.endswith(b'\n'):
                        break
                except socket.timeout:
                    break
            
            if data:
                try:
                    msg = NetworkMessage.from_json(data.decode('utf-8'))
                    self._handle_peer_message(msg, client_socket)
                except json.JSONDecodeError as e:
                    pass
            client_socket.close()
        except (BlockingIOError, socket.timeout):
            pass
        except Exception as e:
            pass
    
    def _broadcast_to_peers(self):
        if not self.world_runner:
            return
        
        ws = self.world_runner.world.world_states.to_dict()
        timers = ws.get('global_timers', {})
        epoch = timers.get('day_cycle', 0)
        chars = [c.to_dict() for c in self.world_runner.world.characters.get_all()]
        objs = [o.to_dict() for o in self.world_runner.world.objects.get_all()]
        events = self.world_runner.event_history[-10:]
        
        msg = NetworkMessage("WORLD_STATE", {
            "epoch": epoch,
            "tick": self.world_runner.tick_count,
            "world_state": ws,
            "characters": chars,
            "objects": objs,
            "events": events
        }, sender=self.node_id)
        
        for peer_id, peer_info in self.peers.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                sock.connect((peer_info['host'], peer_info['port']))
                sock.sendall((msg.to_json() + '\n').encode('utf-8'))
                sock.close()
            except Exception as e:
                pass
    
    def _sync_with_peers(self):
        current_time = time.time()
        if current_time - self.last_sync < self.sync_interval:
            return
        
        self.last_sync = current_time
        self.register_with_signaling(silent=True)
        
        if self.role == "join" and self.peers:
            for peer_id, peer_info in self.peers.items():
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
                        except:
                            pass
                    sock.close()
                    break
                except Exception as e:
                    pass
    
    def _cleanup(self):
        if self.node_socket:
            self.node_socket.close()
        print(f"[P2P] Cleanup complete. Log saved to {os.path.join(self.world_folder, f'p2p_{self.node_id}.log')}")


def main():
    parser = argparse.ArgumentParser(description='SWM P2P Node')
    parser.add_argument('--host', action='store_true', help='Run as host (creates world, default)')
    parser.add_argument('--join', action='store_true', help='Run as joiner (connects to host)')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    parser.add_argument('--world', type=str, help='Specify an existing world folder to load')
    parser.add_argument('--config', type=str, default='network_p2p_config.json', help='Config file')
    args = parser.parse_args()
    
    role = "join" if args.join else "host"
    
    print("="*60)
    print(f"SWM P2P NODE - {role.upper()}")
    print("="*60)
    
    node = SWMP2PNode(config_file=args.config, role=role, args=args)
    node.start()


if __name__ == "__main__":
    main()