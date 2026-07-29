#!/usr/bin/env python3
"""
SWM Run P2P - P2P node for distributed SWM
Roles: --host (default) creates the world, --join connects to a host
"""

import json
import os
import time
import socket
import threading
import sys
import argparse
import shutil
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
    
    def __init__(self, host: str = "127.0.0.1", port: int = 7000):
        self.host = host
        self.port = port
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
        
        while self.running:
            try:
                client_socket, addr = self.socket.accept()
                client_socket.settimeout(5)
                data = client_socket.recv(65536).decode('utf-8')
                if data:
                    self._handle_request(data, client_socket)
                client_socket.close()
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"[SIGNALING] Error: {e}")
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
                    print(f"[SIGNALING] Node registered: {node_id} ({len(peers)} peers)")
                    
            elif msg.type == "GET_PEERS":
                node_id = msg.payload.get('node_id')
                peers = [{"id": nid, "host": info['host'], "port": info['port']} 
                        for nid, info in self.nodes.items() if nid != node_id]
                response = NetworkMessage("PEERS", {"peers": peers})
                sock.sendall((response.to_json() + '\n').encode('utf-8'))
                print(f"[SIGNALING] Sent peers to {node_id}: {len(peers)} peers")
                
        except Exception as e:
            print(f"[SIGNALING] Error: {e}")
    
    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()


class SWMP2PNode:
    def __init__(self, config_file: str = "network_p2p_config.json", 
                 role: str = "host", args: Any = None):
        self.config = self._load_config(config_file)
        self.role = role
        self.args = args or {}
        self.running = False
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.node_socket = None
        self.world_runner = None
        self.sync_interval = self.config['world'].get('sync_interval', 2.0)
        self.last_sync = 0
        self.last_render = 0
        self.render_interval = 1.0
        self.node_id = self.config['node']['id']
        self.node_host = self.config['node']['host']
        self.node_port = self.config['node']['port']
        self.world_folder = self.config['world'].get('world_folder', 'world_p2p')
        self.is_connected = False
        self.log_file = None
        
        if self.role == "host":
            print("[P2P] Starting signaling server...")
            threading.Thread(target=self._run_signaling_server, daemon=True).start()
            time.sleep(1)
        
        print(f"[P2P] Node initialized as {self.role.upper()} - {self.node_id}")
        print(f"[P2P] Listening on {self.node_host}:{self.node_port}")
    
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
            "world": {"world_folder": "world_p2p", "sync_interval": 2.0},
            "user": {"name": "P2P_Player", "initial_scene": "Castle"}
        }
    
    def _run_signaling_server(self):
        signaling = SignalingServer(
            self.config['signaling_server']['host'],
            self.config['signaling_server']['port']
        )
        signaling.start()
    
    def _log(self, text: str):
        """Write to log file in world folder"""
        if not self.world_folder:
            return
        log_filename = os.path.join(self.world_folder, f"p2p_{self.node_id}.log")
        try:
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()} - {text}\n")
        except:
            pass
    
    def _generate_world(self):
        try:
            print("[P2P] Generating world...")
            import subprocess
            result = subprocess.run([sys.executable, "swm_generate.py"], 
                                  capture_output=True, text=True, cwd=os.getcwd())
            if result.returncode != 0:
                print(f"[P2P] Failed to generate world: {result.stderr}")
                return
            
            world_folders = [d for d in os.listdir('.') if os.path.isdir(d) and d.startswith('world_')]
            if world_folders:
                world_folders.sort(reverse=True)
                latest = world_folders[0]
                if os.path.exists(self.world_folder):
                    shutil.rmtree(self.world_folder)
                os.rename(latest, self.world_folder)
                print(f"[P2P] World generated in {self.world_folder}")
        except Exception as e:
            print(f"[P2P] Error generating world: {e}")
    
    def _initialize_world(self):
        required = ["characters.json", "objects.json", "scenes.json", "rules.json", "world_states.json"]
        all_exist = all(os.path.exists(os.path.join(self.world_folder, f)) for f in required)
        
        if not all_exist:
            if self.role == "host":
                print(f"[P2P] Generating world for host...")
                self._generate_world()
            else:
                print(f"[P2P] Waiting for world sync from host...")
                return False
        
        load_existing = not getattr(self.args, 'new', False)
        self.world_runner = WorldRunner(
            fps=1.0,
            load_existing=load_existing,
            world_folder=self.world_folder
        )
        return True
    
    def register_with_signaling(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.config['signaling_server']['host'], 
                         self.config['signaling_server']['port']))
            
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
                    print(f"[P2P] Registered. Found {len(self.peers)} peers")
                    for peer_id, info in self.peers.items():
                        print(f"  - {peer_id} ({info['host']}:{info['port']})")
            
            sock.close()
            
        except Exception as e:
            print(f"[P2P] Failed to register with signaling: {e}")
    
    def _render_host(self):
        """Render for host - full visualization"""
        if not self.world_runner:
            return
        
        ws = self.world_runner.world.world_states.to_dict()
        chars = self.world_runner.world.characters.get_all()
        objs = self.world_runner.world.objects.get_all()
        timers = ws.get('global_timers', {})
        epoch = timers.get('day_cycle', 0)
        
        # Build output
        output = []
        output.append("\n" + "="*60)
        output.append(f"P2P NODE [HOST] {self.node_id} - EPOCH {epoch}")
        output.append(f"Peers: {len(self.peers)}")
        output.append("="*60)
        
        global_states = ws.get('global_states', {})
        output.append(f"\n[WORLD STATE]")
        output.append(f"  Scene: {ws.get('current_scene', '?')}")
        output.append(f"  Weather: {global_states.get('weather', '?')}")
        output.append(f"  Time: {global_states.get('time_of_day', '?')}")
        output.append(f"  Day Cycle: {epoch // 60:02d}:{epoch % 60:02d}")
        
        output.append(f"\n[CHARACTERS] ({len(chars)})")
        for char in chars[:3]:
            name = char.get('name', 'Unknown')
            ai_state = char.get('ai_state', 'IDLE')
            status = char.get('status_variables', {})
            health = status.get('health', '?')
            stamina = status.get('stamina', '?')
            location = char.get('navigation', {}).get('current_location', '?')
            output.append(f"  {name} [{ai_state}] HP:{health} ST:{stamina} @ {location}")
        if len(chars) > 3:
            output.append(f"  ... and {len(chars) - 3} more")
        
        output.append(f"\n[OBJECTS] ({len(objs)})")
        for obj in objs[:3]:
            name = obj.get('name', 'Unknown')
            props = obj.get('properties', {})
            obj_type = 'item'
            if isinstance(props, dict):
                obj_type = props.get('type', 'item')
                if isinstance(obj_type, dict):
                    obj_type = 'item'
            obj_vars = obj.get('object_variables', {})
            durability = obj_vars.get('durability', '?')
            if isinstance(durability, float):
                durability = int(round(durability))
            quality = obj_vars.get('quality', 'standard')
            output.append(f"  {name} ({obj_type}) [{quality}] Durability:{durability}")
        if len(objs) > 3:
            output.append(f"  ... and {len(objs) - 3} more")
        
        if self.peers:
            output.append(f"\n[PEERS] ({len(self.peers)})")
            for peer_id, peer_info in list(self.peers.items())[:3]:
                output.append(f"  - {peer_id} ({peer_info.get('host')}:{peer_info.get('port')})")
            if len(self.peers) > 3:
                output.append(f"  ... and {len(self.peers) - 3} more")
        
        events = self.world_runner.event_history[-3:]
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
    
    def _render_joiner(self):
        """Render for joiner - minimal connection status only"""
        epoch = 0
        if self.world_runner:
            ws = self.world_runner.world.world_states.to_dict()
            timers = ws.get('global_timers', {})
            epoch = timers.get('day_cycle', 0)
        
        print(f"\n[P2P JOINER] {self.node_id} - Connected: {self.is_connected}, Peers: {len(self.peers)}, EPOCH: {epoch}")
        self._log(f"[P2P JOINER] {self.node_id} - Connected: {self.is_connected}, Peers: {len(self.peers)}, EPOCH: {epoch}")
    
    def _send_world_state(self, sock: socket.socket):
        """Send the full world state to a joiner"""
        if not self.world_runner:
            return
        
        ws = self.world_runner.world.world_states.to_dict()
        timers = ws.get('global_timers', {})
        epoch = timers.get('day_cycle', 0)
        chars = [c.to_dict() for c in self.world_runner.world.characters.get_all()]
        objs = [o.to_dict() for o in self.world_runner.world.objects.get_all()]
        events = self.world_runner.event_history[-5:]
        
        response = NetworkMessage("WORLD_STATE", {
            "epoch": epoch,
            "world_state": ws,
            "characters": chars,
            "objects": objs,
            "events": events
        }, sender=self.node_id)
        sock.sendall((response.to_json() + '\n').encode('utf-8'))
        print(f"[P2P] Sent world state to joiner (epoch {epoch})")
        self._log(f"Sent world state to joiner (epoch {epoch})")
    
    def _handle_peer_message(self, msg: NetworkMessage, sock: socket.socket):
        msg_type = msg.type
        
        if msg_type == "REQUEST_WORLD":
            if self.role == "host":
                self._send_world_state(sock)
        
        elif msg_type == "WORLD_STATE":
            if self.role == "join":
                epoch = msg.payload.get('epoch', 0)
                ws = msg.payload.get('world_state', {})
                chars = msg.payload.get('characters', [])
                objs = msg.payload.get('objects', [])
                events = msg.payload.get('events', [])
                
                print(f"[P2P] Received world state from {msg.sender} at epoch {epoch}")
                self._log(f"Received world state from {msg.sender} at epoch {epoch}")
                
                # Update joiner's world state
                if self.world_runner:
                    world = self.world_runner.world
                    
                    # Update world states
                    for key, value in ws.items():
                        world.world_states.set(key, value)
                    
                    # Clear and reload characters
                    world.characters.clear_all()
                    for char_data in chars:
                        world.characters.add_entity(char_data)
                    
                    # Clear and reload objects
                    world.objects.clear_all()
                    for obj_data in objs:
                        world.objects.add_entity(obj_data)
                    
                    # Update event history
                    if events:
                        self.world_runner.event_history = events
                    
                    self.is_connected = True
                    print(f"[P2P] World state updated to epoch {epoch}")
                    self._log(f"World state updated to epoch {epoch}")
                    
                    # Render joiner immediately
                    self._render_joiner()
    
    def start(self):
        self.running = True
        
        if self.role == "host":
            self._initialize_world()
        else:
            self._initialize_world()
        
        self.register_with_signaling()
        
        self.node_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.node_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.node_socket.bind((self.node_host, self.node_port))
        self.node_socket.listen(10)
        self.node_socket.setblocking(False)
        
        print(f"[P2P] Node listening on port {self.node_port}")
        print("[P2P] Press Ctrl+C to stop\n")
        
        try:
            while self.running:
                self._accept_connections()
                self._sync_with_peers()
                
                if self.role == "host" and self.world_runner:
                    self.world_runner._update_world()
                    
                    # Broadcast to peers every 5 ticks
                    if self.world_runner.tick_count % 5 == 0:
                        self._broadcast_to_peers()
                
                # Render periodically
                current_time = time.time()
                if current_time - self.last_render >= self.render_interval:
                    if self.role == "host":
                        self._render_host()
                    else:
                        self._render_joiner()
                    self.last_render = current_time
                
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n[P2P] Shutting down...")
        finally:
            self._cleanup()
    
    def _accept_connections(self):
        try:
            client_socket, addr = self.node_socket.accept()
            client_socket.settimeout(5)
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
                    print(f"[P2P] Error decoding message: {e}")
            client_socket.close()
        except BlockingIOError:
            pass
        except socket.timeout:
            pass
        except Exception as e:
            print(f"[P2P] Error accepting connection: {e}")
    
    def _broadcast_to_peers(self):
        """Host: Broadcast world state to all peers"""
        if not self.world_runner:
            return
        
        ws = self.world_runner.world.world_states.to_dict()
        timers = ws.get('global_timers', {})
        epoch = timers.get('day_cycle', 0)
        chars = [c.to_dict() for c in self.world_runner.world.characters.get_all()]
        objs = [o.to_dict() for o in self.world_runner.world.objects.get_all()]
        events = self.world_runner.event_history[-5:]
        
        msg = NetworkMessage("WORLD_STATE", {
            "epoch": epoch,
            "world_state": ws,
            "characters": chars,
            "objects": objs,
            "events": events
        }, sender=self.node_id)
        
        # Keep connection open until data is sent
        for peer_id, peer_info in self.peers.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((peer_info['host'], peer_info['port']))
                sock.sendall((msg.to_json() + '\n').encode('utf-8'))
                sock.close()
                print(f"[P2P] Broadcast to {peer_id} at epoch {epoch}")
                self._log(f"Broadcast to {peer_id} at epoch {epoch}")
            except Exception as e:
                print(f"[P2P] Failed to broadcast to {peer_id}: {e}")
    
    def _sync_with_peers(self):
        current_time = time.time()
        if current_time - self.last_sync < self.sync_interval:
            return
        
        self.last_sync = current_time
        self.register_with_signaling()
        
        # Joiner: request world from peers
        if self.role == "join" and self.peers:
            for peer_id, peer_info in self.peers.items():
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
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
                    break  # Only request from first peer
                except Exception as e:
                    print(f"[P2P] Failed to request from {peer_id}: {e}")
    
    def _cleanup(self):
        if self.node_socket:
            self.node_socket.close()
        log_file = os.path.join(self.world_folder, f"p2p_{self.node_id}.log")
        print(f"[P2P] Cleanup complete. Log saved to {log_file}")
        self._log("Cleanup complete")


def main():
    parser = argparse.ArgumentParser(description='SWM P2P Node')
    parser.add_argument('--host', action='store_true', help='Run as host (creates world, default)')
    parser.add_argument('--join', action='store_true', help='Run as joiner (connects to host)')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    parser.add_argument('--config', type=str, default='network_p2p_config.json', help='Config file')
    args = parser.parse_args()
    
    if args.join:
        role = "join"
    else:
        role = "host"
    
    print("="*60)
    print(f"SWM P2P NODE - {role.upper()}")
    print("="*60)
    
    node = SWMP2PNode(config_file=args.config, role=role, args=args)
    node.start()


if __name__ == "__main__":
    main()