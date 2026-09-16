#!/usr/bin/env python3
"""
SWM Run P2P - P2P node for distributed SWM with dynamic config loading and 1-by-1 epoch streaming
Integrated with interactive commands, pause/live mode, and command responses.
Supports --max-epoch (default 10000) which stops the sim exactly like 'quit'
and exports all CSVs + charts via the delegated TimelinePlotter.
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
import select
import io
import glob
from contextlib import redirect_stdout
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
            except Exception:
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
        except Exception:
            pass

    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()


class SWMP2PNode:
    """P2P Node with integrated interactive commands and pause/live mode"""

    def __init__(self, config_file: str = "network_p2p_config.json",
                 role: str = "host", args: Any = None):
        self.config = self._load_config(config_file)
        self.role = role
        self.args = args or {}
        self.running = False
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.node_socket = None
        self.world_runner = None

        self.interactive_mode = getattr(self.args, 'interact', False)
        self.dynamic_mode = getattr(self.args, 'dynamic', False)
        self.continuous_mode = False

        self.known_clients = set()

        self.pause_mode = False
        self.show_prompt = True
        self.prompt = "[P2P] > "
        self.command_queue = []
        self.input_thread = None
        self.last_render_time = 0
        self.waiting_for_input = False

        self.chat_history = []
        self.chatlog_file = None
        self.max_history = 100

        self.cached_history = ""
        self.cached_chatlog = ""

        self.seen_chats = set()
        self.seen_chats_max = 100

        # NEW: max_epoch
        self.max_epoch = getattr(self.args, 'max_epoch', 10000)
        self.max_epoch_reached = False

        world_cfg = self.config.get('world', {'world_folder': 'world_p2p', 'sync_interval': 2.0, 'broadcast_interval': 1})
        node_cfg = self.config.get('node', {'id': 'node_001', 'host': '127.0.0.1', 'port': 6000})
        conn_cfg = self.config.get('connection', {'timeout': 5})
        user_cfg = self.config.get('user', {'name': f'P2P_{self.role}'})

        self.user_name = user_cfg.get('name', f'P2P_{self.role}')

        self.sync_interval = world_cfg.get('sync_interval', 2.0)
        self.broadcast_interval = world_cfg.get('broadcast_interval', 1)
        self.timeout = conn_cfg.get('timeout', 5)
        self.default_fps = 1.0

        arg_world = getattr(self.args, 'world', None)
        if arg_world:
            self.world_folder = arg_world
        else:
            self.world_folder = world_cfg.get('world_folder', 'world_p2p')

        if self.role == "host":
            self.node_id = node_cfg.get('id', 'node_host')
        else:
            self.node_id = node_cfg.get('id', 'node_join') + "_" + str(int(time.time()))[-4:]

        self.node_host = node_cfg.get('host', '127.0.0.1')
        if self.role == "host":
            self.node_port = node_cfg.get('port', 6000)
        else:
            self.node_port = node_cfg.get('port', 6000) + 1

        self.last_sync = 0
        self.last_render = 0
        self.render_interval = 1.0
        self.is_connected = False
        self.sync_attempts = 0

        self.synced_world_state = {}
        self.synced_characters = []
        self.synced_objects = []
        self.synced_events = []
        self.synced_epoch = 0

        os.makedirs(self.world_folder, exist_ok=True)
        self.chatlog_file = os.path.join(self.world_folder, "chatlog.txt")
        self._load_chat_history()

        if self.role == "host":
            print("[P2P] Starting signaling server...")
            sig_cfg = self.config.get('signaling_server', {'host': '127.0.0.1', 'port': 7000})
            threading.Thread(target=self._run_signaling_server,
                             args=(sig_cfg['host'], sig_cfg['port'], self.timeout),
                             daemon=True).start()
            time.sleep(1)

        print(f"[P2P] Node initialized as {self.role.upper()} - {self.node_id}")
        print(f"[P2P] Listening on {self.node_host}:{self.node_port}")
        print(f"[P2P] Broadcast Interval: every {self.broadcast_interval} tick(s)")
        print(f"[P2P] Chat log: {self.chatlog_file}")
        if self.max_epoch and self.max_epoch > 0:
            print(f"[P2P] Max epochs: {self.max_epoch}")
        else:
            print(f"[P2P] Max epochs: unlimited")

        if self.role == "host":
            if self.interactive_mode:
                print("[P2P] INTERACTIVE MODE: Press Enter for next epoch, 'c' for continuous")
            elif self.dynamic_mode:
                print("[P2P] DYNAMIC MODE: Running continuously with command input")
            else:
                print("[P2P] AUTO MODE: Running continuously")
        else:
            print("[P2P] JOINER MODE: Syncing with host")
            print("[P2P] Make sure host is running with --host flag")

        print("[P2P] Type 'help' for commands")
        sys.stdout.flush()

    # ==================== CHAT ====================

    def _load_chat_history(self):
        if os.path.exists(self.chatlog_file):
            try:
                with open(self.chatlog_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines:
                        line = line.strip()
                        if line:
                            try:
                                if '] ' in line and ': ' in line[line.index('] ')+2:]:
                                    timestamp_part = line[1:line.index('] ')]
                                    rest = line[line.index('] ')+2:]
                                    if ': ' in rest:
                                        sender, message = rest.split(': ', 1)
                                        self.chat_history.append({
                                            'timestamp': timestamp_part,
                                            'sender': sender,
                                            'message': message
                                        })
                            except Exception:
                                pass
                print(f"[P2P] Loaded {len(self.chat_history)} chat messages from history")
            except Exception as e:
                print(f"[WARNING] Could not load chat history: {e}")

    def _save_chat_message(self, sender: str, message: str):
        timestamp = datetime.now().isoformat()
        entry = {'timestamp': timestamp, 'sender': sender, 'message': message}
        self.chat_history.append(entry)
        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]
        try:
            with open(self.chatlog_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {sender}: {message}\n")
        except Exception as e:
            print(f"[WARNING] Could not save chat message: {e}")

    def _get_latest_run_log_file(self) -> Optional[str]:
        patterns = [
            os.path.join(self.world_folder, "run_*.log"),
            os.path.join(self.world_folder, "run_*.txt"),
            os.path.join(self.world_folder, "p2p_*.log"),
        ]
        all_files = []
        for pattern in patterns:
            files = glob.glob(pattern)
            if files:
                all_files.extend(files)
        if not all_files:
            return None
        all_files = [f for f in all_files if os.path.isfile(f)]
        if not all_files:
            return None
        all_files.sort(key=os.path.getmtime, reverse=True)
        return all_files[0]

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
            "node": {"id": "node_host", "host": "127.0.0.1", "port": 6000},
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
        except Exception:
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
            world_folder=self.world_folder,
            max_epoch=self.max_epoch
        )
        return True

    # ==================== MAX EPOCH ====================

    def _save_all_on_exit(self):
        """Save everything: runtime state, statistics, CSVs, charts."""
        if not self.world_runner:
            return
        try:
            self.world_runner._save_runtime_state()
        except Exception as e:
            print(f"[ERROR] Failed to save runtime state: {e}")
        try:
            self.world_runner._export_statistics()
        except Exception as e:
            print(f"[ERROR] Failed to export statistics: {e}")
        try:
            if hasattr(self.world_runner, 'plotter') and self.world_runner.plotter:
                self.world_runner.plotter.export_all_csv()
                self.world_runner.plotter.generate_all_charts()
        except Exception as e:
            print(f"[ERROR] Failed to export plotter data: {e}")
        try:
            self.world_runner._flush_log()
        except Exception:
            pass

    def _check_max_epoch(self) -> bool:
        """If max epoch reached, stop and save like 'quit'."""
        if self.world_runner is None:
            return False
        if self.max_epoch is None or self.max_epoch <= 0:
            return False
        if self.world_runner.tick_count < self.max_epoch:
            return False
        if self.max_epoch_reached:
            return True

        self.max_epoch_reached = True
        print(f"\n[MAX_EPOCH] Reached epoch limit ({self.max_epoch}). Saving state exactly like 'quit'...")
        self._save_all_on_exit()
        print(f"[MAX_EPOCH] State, statistics, CSVs and charts saved at Epoch {self.world_runner.tick_count}.")
        return True

    def _broadcast_chat(self, sender: str, message: str):
        display_name = sender
        if sender == self.node_id:
            display_name = self.user_name

        msg_key = f"{display_name}:{message}"
        self.seen_chats.add(msg_key)
        if len(self.seen_chats) > self.seen_chats_max:
            self.seen_chats = set(list(self.seen_chats)[-self.seen_chats_max:])

        self._save_chat_message(display_name, message)
        print(f"\n[CHAT] {display_name}: {message}")
        self._log(f"[CHAT] {display_name}: {message}")

        if self.show_prompt:
            sys.stdout.write(self.prompt)
            sys.stdout.flush()

        chat_msg = NetworkMessage("CHAT", {
            "sender": display_name,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }, sender=self.node_id)

        for peer_id, peer_info in self.peers.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                sock.connect((peer_info['host'], peer_info['port']))
                sock.sendall((chat_msg.to_json() + '\n').encode('utf-8'))
                sock.close()
            except Exception:
                pass

    def _handle_chat_message(self, sender: str, message: str):
        msg_key = f"{sender}:{message}"
        if msg_key in self.seen_chats:
            return
        self.seen_chats.add(msg_key)
        if len(self.seen_chats) > self.seen_chats_max:
            self.seen_chats = set(list(self.seen_chats)[-self.seen_chats_max:])

        self._save_chat_message(sender, message)
        print(f"\n[CHAT] {sender}: {message}")
        if self.show_prompt:
            sys.stdout.write(self.prompt)
            sys.stdout.flush()

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
            return True
        except Exception as e:
            if not silent:
                print(f"[P2P] Failed to register with signaling server: {e}")
            return False

    # ==================== RENDER ====================

    def _render(self, force: bool = False):
        if self.pause_mode and not force:
            current_time = time.time()
            if current_time - self.last_render_time < 15:
                return
            self.last_render_time = current_time

            if self.role == "host":
                tick = self.world_runner.tick_count if self.world_runner else 0
            else:
                tick = self.synced_epoch

            status = f"[P2P] PAUSE MODE | Epoch: {tick} | Peers: {len(self.peers)} | Press Enter to resume"
            sys.stdout.write(f"\r{status}    \n")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
            return

        output = []
        output.append("="*80)

        if self.role == "host":
            ws = self.world_runner.world.world_states.to_dict() if self.world_runner else {}
            chars = self.world_runner.world.characters.get_all() if self.world_runner else []
            objs = self.world_runner.world.objects.get_all() if self.world_runner else []
            timers = ws.get('global_timers', {})
            epoch = timers.get('day_cycle', 0)
            tick = self.world_runner.tick_count if self.world_runner else 0
            events = self.world_runner.event_history[-10:] if self.world_runner else []

            mode_str = "INTERACTIVE" if self.interactive_mode else "DYNAMIC" if self.dynamic_mode else "AUTO"
            epoch_str = f"EPOCH {tick}"
            if self.max_epoch and self.max_epoch > 0:
                epoch_str += f" / {self.max_epoch}"
            output.append(f"SWM P2P [HOST] - {mode_str} - {epoch_str} | Node: {self.node_id} | Peers: {len(self.peers)}")
            if self.continuous_mode:
                output.append("*** CONTINUOUS MODE ACTIVE ***")
            if self.pause_mode:
                output.append("*** PAUSE MODE ACTIVE - Updates paused ***")
            output.append("="*80)

            global_states = ws.get('global_states', {})
            output.append(f"\n[WORLD STATE]")
            output.append(f"  Weather: {global_states.get('weather', 'Unknown')}")
            output.append(f"  Time of Day: {global_states.get('time_of_day', 'Unknown')}")
            output.append(f"  Mood: {global_states.get('mood', 'combat')}")
            output.append(f"  Day Cycle: {epoch // 60:02d}:{epoch % 60:02d}")

            output.append(f"\n[CHARACTERS] ({len(chars)})")
            for char in chars[:10]:
                name = char.get('name', 'Unknown')
                ai_state = char.get('ai_state', 'IDLE')
                goal = char.get('goal', 'social_belonging')
                emotion = char.get('emotion', 'neutral')
                status = char.get('status_variables', {})
                health = int(round(status.get('health', 100))) if isinstance(status.get('health'), (int, float)) else '?'
                stamina = int(round(status.get('stamina', 100))) if isinstance(status.get('stamina'), (int, float)) else '?'
                location = char.get('navigation', {}).get('current_location', 'Unknown')
                output.append(f"  * {name} [{ai_state}] | Goal: {goal} | Emotion: {emotion} | HP:{health} | ST:{stamina} @ {location}")
            if len(chars) > 10:
                output.append(f"  ... and {len(chars) - 10} more")

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
                for event in events[-5:]:
                    t = event.get('tick', '?')
                    text = event.get('text', '')
                    output.append(f"  [{t}] {text}")
        else:
            if not self.is_connected:
                output.append(f"SWM P2P [JOINER] - WAITING FOR HOST... | Node: {self.node_id}")
                output.append("="*80)
                output.append("\n  [WAITING] Attempting to connect to host...")
                output.append("  [INFO] Make sure a host node is running (--host)")
                output.append(f"  [INFO] Sync interval: {self.sync_interval} seconds")
                output.append(f"  [INFO] Peers found: {len(self.peers)}")
                if self.peers:
                    output.append("  [INFO] Found peers:")
                    for pid, pinfo in self.peers.items():
                        output.append(f"    - {pid} at {pinfo['host']}:{pinfo['port']}")
                else:
                    output.append("  [INFO] No peers found. Make sure host is registered.")
            else:
                output.append(f"SWM P2P [JOINER] - EPOCH {self.synced_epoch} | Node: {self.node_id} | Connected: {self.is_connected}")
                if self.pause_mode:
                    output.append("*** PAUSE MODE ACTIVE - Updates paused ***")
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
                    for char in self.synced_characters[:10]:
                        name = char.get('name', 'Unknown') if isinstance(char, dict) else 'Unknown'
                        ai_state = char.get('ai_state', 'IDLE') if isinstance(char, dict) else 'IDLE'
                        goal = char.get('goal', 'social_belonging') if isinstance(char, dict) else 'social_belonging'
                        emotion = char.get('emotion', 'neutral') if isinstance(char, dict) else 'neutral'
                        status = char.get('status_variables', {}) if isinstance(char, dict) else {}
                        health = int(round(status.get('health', 100))) if isinstance(status.get('health'), (int, float)) else '?'
                        stamina = int(round(status.get('stamina', 100))) if isinstance(status.get('stamina'), (int, float)) else '?'
                        location = char.get('navigation', {}).get('current_location', 'Unknown')
                        output.append(f"  * {name} [{ai_state}] | Goal: {goal} | Emotion: {emotion} | HP:{health} | ST:{stamina} @ {location}")
                    if len(self.synced_characters) > 10:
                        output.append(f"  ... and {len(self.synced_characters) - 10} more")

                if self.synced_events:
                    output.append(f"\n[RECENT EVENTS]")
                    for event in self.synced_events[-5:]:
                        t = event.get('tick', '?')
                        text = event.get('text', '')
                        output.append(f"  [{t}] {text}")

        output.append("\n" + "="*80)

        if self.pause_mode:
            output.append("Press Enter to resume updates | Commands: help, summary, catalog, var, list, action, set, save, mode, history, chatlog, q")
        elif self.role == "host" and self.interactive_mode and not self.continuous_mode:
            output.append("[INTERACTIVE] Press Enter for next epoch | 'c' for continuous | Commands: help, summary, list, action, history, chatlog, q")
        elif self.role == "join" and not self.is_connected:
            output.append("WAITING FOR HOST... Press Enter to pause updates | Commands: help, mode, q")
        else:
            output.append("Press Enter to pause updates | Commands: help, summary, catalog, var, list, action, set, save, mode, history, chatlog, q")

        full_render_string = "\n".join(output)

        sys.stdout.write("\r" + " " * 100 + "\r")
        print(full_render_string)
        self._log(full_render_string)
        sys.stdout.flush()
        self.last_render_time = time.time()

        if self.show_prompt:
            sys.stdout.write(self.prompt)
            sys.stdout.flush()

    # ==================== COMMANDS ====================

    def _execute_command(self, cmd: str) -> str:
        cmd = cmd.strip()
        if not cmd:
            return ""
        output_buffer = io.StringIO()
        with redirect_stdout(output_buffer):
            self._execute_local_command(cmd)
        result = output_buffer.getvalue()
        return result if result else " Command executed"

    def _send_command_to_host(self, cmd_string: str):
        host_id = None
        for peer_id in self.peers:
            if 'host' in peer_id.lower() or peer_id.startswith('node_host'):
                host_id = peer_id
                break
        if not host_id and self.peers:
            host_id = list(self.peers.keys())[0]

        if host_id:
            try:
                host_info = self.peers[host_id]
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                sock.connect((host_info['host'], host_info['port']))
                msg = NetworkMessage("COMMAND", {"command": cmd_string}, sender=self.node_id)
                sock.sendall((msg.to_json() + '\n').encode('utf-8'))
                sock.close()
            except Exception as e:
                print(f"\n[ERROR] Could not send command to host: {e}")
                if self.show_prompt:
                    sys.stdout.write(self.prompt)
                    sys.stdout.flush()
        else:
            print("\n[ERROR] No host found to send command.")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()

    def _execute_local_command(self, cmd: str) -> bool:
        cmd_orig = cmd.strip()
        if not cmd_orig:
            return False

        parts = cmd_orig.split()
        command = parts[0].lower()

        remote_commands = ['summary', 'catalog', 'var', 'list', 'action', 'set', 'save']
        if self.role == "join" and command in remote_commands:
            self._send_command_to_host(cmd_orig)
            return False

        if command in ['q', 'quit', 'exit']:
            print("\n[P2P] Shutting down...")
            self.running = False
            self._save_all_on_exit()
            return True

        if command == 'help':
            print("\n" + "="*60)
            print("P2P NODE COMMANDS")
            print("="*60)
            print("  [Enter]              - Next epoch (interactive) or Toggle PAUSE/LIVE (other modes)")
            print("  c / continue         - Enter continuous mode (interactive mode)")
            print("  stop                 - Stop continuous mode (interactive mode)")
            print("  help                 - Show this help menu")
            print("  summary              - Print full world and character status summary")
            print("  catalog              - List all available actions in catalog")
            print("  var                  - List all available variables")
            print("  list                 - List all characters, states, and HP")
            print("  action <Name> <ACTION> - Force character action intent")
            print("  set char <Name> <var> <val> - Modify character status variable")
            print("  set world <key> <val> - Modify global world state")
            print("  save                 - Save current world state")
            print("  stats                - Export statistics to CSV and LaTeX")
            print("  charts               - Generate all timeline charts")
            print("  timelines            - Export all timeline CSVs")
            print("  mode                 - Show current mode")
            print("  resume               - Resume updates (exit pause mode)")
            print("  chat <message>       - Send a chat message to all peers")
            print("  history              - Show the most recent run log file")
            print("  chatlog              - Show the chat history")
            print("  q / quit / exit      - Save and exit")
            print("="*60)
            return False

        if command == 'chat':
            if len(parts) < 2:
                print("[ERROR] Usage: chat <message>")
                return False
            message = ' '.join(parts[1:])
            self._broadcast_chat(self.node_id, message)
            return False

        if command == 'history':
            log_file = self._get_latest_run_log_file()
            if not log_file:
                print(f"[ERROR] No run log files found in {self.world_folder}")
                return False
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                print(f"\n=== HISTORY LOG: {os.path.basename(log_file)} ===")
                print(content)
                print(f"\n=== END OF {os.path.basename(log_file)} ===")
            except Exception as e:
                print(f"[ERROR] Could not read log file: {e}")
            return False

        if command == 'chatlog':
            if not self.chat_history:
                print("\n[CHATLOG] No chat messages yet.")
                return False
            print(f"\n=== CHAT HISTORY ({len(self.chat_history)} messages) ===")
            for entry in self.chat_history:
                print(f"[{entry.get('timestamp', '?')}] {entry.get('sender', '?')}: {entry.get('message', '')}")
            print("=== END OF CHAT HISTORY ===")
            return False

        if command == 'stats':
            if self.world_runner:
                self.world_runner._export_statistics()
                print("[OK] Statistics exported")
            return False

        if command == 'charts':
            if self.world_runner and hasattr(self.world_runner, 'plotter'):
                self.world_runner.plotter.generate_all_charts()
                print("[OK] Charts generated")
            return False

        if command == 'timelines':
            if self.world_runner and hasattr(self.world_runner, 'plotter'):
                self.world_runner.plotter.export_all_csv()
                print("[OK] Timeline CSVs exported")
            return False

        if command == 'mode':
            print(f"\n[CURRENT MODE] {self.role.upper()}")
            print(f"  Node ID: {self.node_id}")
            print(f"  Peers: {len(self.peers)}")
            print(f"  Pause Mode: {'ON' if self.pause_mode else 'OFF'}")
            if self.role == "host":
                print(f"  Server Mode: {'INTERACTIVE' if self.interactive_mode else 'DYNAMIC' if self.dynamic_mode else 'AUTO'}")
                print(f"  Continuous: {'ON' if self.continuous_mode else 'OFF'}")
                if self.max_epoch and self.max_epoch > 0:
                    print(f"  Max epochs: {self.max_epoch} (reached: {self.max_epoch_reached})")
            else:
                print(f"  Connected to host: {self.is_connected}")
                print(f"  Synced Epoch: {self.synced_epoch}")
            if self.world_runner:
                print(f"  Local Epoch: {self.world_runner.tick_count}")
            print(f"  Chat messages: {len(self.chat_history)}")
            return False

        if command == 'c' or command == 'continue':
            if self.role == "host" and self.interactive_mode:
                if self.max_epoch_reached:
                    print(f"[MAX_EPOCH] Cannot continue beyond {self.max_epoch}.")
                    return False
                if not self.continuous_mode:
                    self.continuous_mode = True
                    print(f"[P2P] Continuous mode activated at {self.default_fps} FPS. Type 'stop' to stop.")
                else:
                    print("[P2P] Already in continuous mode.")
            else:
                print("[P2P] 'continue' command only available in interactive mode.")
            return False

        if command == 'stop':
            if self.role == "host" and self.interactive_mode and self.continuous_mode:
                self.continuous_mode = False
                print("[P2P] Continuous mode stopped.")
                self._render(force=True)
            elif self.role == "host" and self.interactive_mode and not self.continuous_mode:
                print("[P2P] Not in continuous mode.")
            else:
                print("[P2P] 'stop' command only available in interactive mode.")
            return False

        if command == 'resume':
            if self.pause_mode:
                self.pause_mode = False
                print("[P2P] LIVE MODE enabled. Showing updates.")
                self._render(force=True)
            else:
                print("[P2P] Already in LIVE mode.")
            return False

        if command == 'summary':
            if self.world_runner:
                self.world_runner._render()
            return False

        if command == 'catalog':
            if self.world_runner:
                print("\n[ACTION CATALOG]")
                for idx, act in enumerate(self.world_runner.action_catalog, 1):
                    print(f"  {idx}. {act}")
            return False

        if command == 'var':
            if self.world_runner:
                print("\n[VARIABLE CATALOG]")
                char_vars = self.world_runner.variable_catalog.get('character_variables', [])
                if char_vars:
                    print("\n  CHARACTER VARIABLES:")
                    for var in char_vars:
                        print(f"    - {var}")
                obj_vars = self.world_runner.variable_catalog.get('object_variables', [])
                if obj_vars:
                    print("\n  OBJECT VARIABLES:")
                    for var in obj_vars:
                        print(f"    - {var}")
                world_vars = self.world_runner.variable_catalog.get('world_states', [])
                if world_vars:
                    print("\n  WORLD STATES:")
                    for var in world_vars:
                        print(f"    - {var}")
                print()
            return False

        if command == 'list':
            if self.world_runner:
                print("\n[CHARACTERS]")
                for c in self.world_runner.world.characters.get_all():
                    status = c.get('status_variables', {})
                    status_str = ", ".join([f"{k}:{v}" for k, v in status.items()]) if status else "No status"
                    print(f"  - {c.get('name')} | State: {c.get('ai_state')} | {status_str} | Location: {c.get('navigation', {}).get('current_location')}")
                print("\n[OBJECTS]")
                for obj in self.world_runner.world.objects.get_all():
                    vars_str = ", ".join([f"{k}:{v}" for k, v in obj.get('object_variables', {}).items()]) if obj.get('object_variables') else "No variables"
                    print(f"  - {obj.get('name')} | Type: {obj.get('properties', {}).get('type', 'unknown')} | {vars_str}")
                print("\n[WORLD STATES]")
                ws = self.world_runner.world.world_states.to_dict()
                for key, value in ws.items():
                    if key not in ['global_timers', 'global_states']:
                        print(f"  - {key}: {value}")
                if 'global_states' in ws:
                    for key, value in ws['global_states'].items():
                        print(f"  - global_states.{key}: {value}")
                if 'global_timers' in ws:
                    for key, value in ws['global_timers'].items():
                        print(f"  - global_timers.{key}: {value}")
            return False

        if command == 'action':
            if not self.world_runner:
                return False
            if len(parts) < 3:
                print("[ERROR] Usage: action <CharacterName> <ACTION_NAME>")
                return False
            char_name = parts[1]
            action_intent = parts[2].upper()
            if self.world_runner.action_catalog and action_intent not in self.world_runner.action_catalog:
                print(f"[ERROR] '{action_intent}' is invalid. Type 'catalog' to check valid actions.")
                return False
            target_char = next((c for c in self.world_runner.world.characters.get_all() if c.get('name', '').lower() == char_name.lower()), None)
            if target_char:
                loc = target_char.get('navigation', {}).get('current_location', 'Unknown')
                msg = f"[ACTION] {target_char.get('name')} performs '{action_intent}' at {loc}"
                self.world_runner._add_event(msg, 'user_action', 'character', target_char.get('name'))
                print(f"[OK] {msg}")
            else:
                print(f"[ERROR] Character '{char_name}' not found.")
            return False

        if command == 'set':
            if not self.world_runner:
                return False
            if len(parts) < 4:
                print("[ERROR] Usage: set char <Name> <var> <val> OR set world <key> <val>")
                return False
            sub_target = parts[1].lower()

            if sub_target == 'char':
                if len(parts) < 5:
                    print("[ERROR] Usage: set char <CharacterName> <variable> <value>")
                    return False
                char_name = parts[2]
                var_name = parts[3]
                val_str = parts[4]
                target_char = next((c for c in self.world_runner.world.characters.get_all() if c.get('name', '').lower() == char_name.lower()), None)
                if target_char:
                    status = target_char.get('status_variables', {})
                    if var_name in status:
                        try:
                            orig_val = status[var_name]
                            if isinstance(orig_val, bool):
                                new_val = val_str.lower() in ['true', '1', 'yes']
                            elif isinstance(orig_val, int):
                                new_val = int(val_str)
                            elif isinstance(orig_val, float):
                                new_val = float(val_str)
                            else:
                                new_val = val_str
                            status[var_name] = new_val
                            target_char.set('status_variables', status)
                            print(f"[OK] Set {target_char.get('name')}'s {var_name} to {new_val}")
                        except ValueError:
                            print(f"[ERROR] Invalid number format for value '{val_str}'.")
                    else:
                        print(f"[ERROR] Status variable '{var_name}' not found.")
                else:
                    print(f"[ERROR] Character '{char_name}' not found.")
            elif sub_target == 'world':
                key = parts[2]
                val_str = parts[3]
                try:
                    if val_str.lower() in ['true', 'false']:
                        new_val = val_str.lower() == 'true'
                    else:
                        try:
                            new_val = float(val_str) if '.' in val_str else int(val_str)
                        except ValueError:
                            new_val = val_str
                    self.world_runner.world.world_states.set(key, new_val)
                    print(f"[OK] Set world state '{key}' to {new_val}")
                except Exception as e:
                    print(f"[ERROR] Failed to set world state: {e}")
            else:
                print("[ERROR] Unknown set target. Use 'set char' or 'set world'.")
            return False

        if command == 'save':
            if self.world_runner:
                self.world_runner._save_runtime_state()
                self.world_runner._export_statistics()
                print(f"[OK] World state saved at Epoch {self.world_runner.tick_count}")
            return False

        print(f"[P2P] Unknown command: {cmd_orig}. Type 'help' for available commands.")
        return False

    def _execute_command_with_output(self, cmd: str) -> str:
        cmd = cmd.strip()
        if not cmd:
            return "No command"
        output_buffer = io.StringIO()
        with redirect_stdout(output_buffer):
            self._execute_local_command(cmd)
        result = output_buffer.getvalue()
        return result if result else " Command executed"

    # ==================== PEER MESSAGES ====================

    def _handle_peer_message(self, msg: NetworkMessage, sock: socket.socket):
        msg_type = msg.type

        if msg_type == "REQUEST_WORLD":
            if self.role == "host" and self.world_runner:
                sender = msg.sender or 'unknown'
                if sender not in self.known_clients:
                    self.known_clients.add(sender)
                    print(f"\n[P2P] Client connected: {sender}")
                    if self.show_prompt:
                        sys.stdout.write(self.prompt)
                        sys.stdout.flush()

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
                return True

        elif msg_type == "WORLD_STATE":
            if self.role == "join":
                self.synced_epoch = msg.payload.get('tick', msg.payload.get('epoch', 0))
                self.synced_world_state = msg.payload.get('world_state', {})
                self.synced_characters = msg.payload.get('characters', [])
                self.synced_objects = msg.payload.get('objects', [])
                self.synced_events = msg.payload.get('events', [])
                self.is_connected = True
                self.sync_attempts = 0

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
                    self.world_runner.tick_count = self.synced_epoch

                self._render()
                return True

        elif msg_type == "CHAT":
            sender = msg.payload.get('sender', msg.sender or 'Unknown')
            message = msg.payload.get('message', '')
            self._handle_chat_message(sender, message)
            if self.role == "host":
                for peer_id, peer_info in self.peers.items():
                    if peer_id == msg.sender:
                        continue
                    try:
                        peer_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        peer_sock.settimeout(self.timeout)
                        peer_sock.connect((peer_info['host'], peer_info['port']))
                        peer_sock.sendall((msg.to_json() + '\n').encode('utf-8'))
                        peer_sock.close()
                    except Exception:
                        pass
            return True

        elif msg_type == "COMMAND":
            cmd = msg.payload.get('command', '')
            sender = msg.sender or 'unknown'

            print(f"\n[P2P] Client {sender} executed command: {cmd}")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()

            if self.role == "host":
                result = self._execute_command_with_output(cmd)
                response = NetworkMessage("COMMAND_RESULT", {
                    "command": cmd,
                    "result": result
                }, sender=self.node_id)

                if sender in self.peers:
                    try:
                        peer_info = self.peers[sender]
                        peer_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        peer_sock.settimeout(self.timeout)
                        peer_sock.connect((peer_info['host'], peer_info['port']))
                        peer_sock.sendall((response.to_json() + '\n').encode('utf-8'))
                        peer_sock.close()
                    except Exception as e:
                        print(f"[P2P] Could not send COMMAND_RESULT to {sender}: {e}")
            return True

        elif msg_type == "COMMAND_RESULT":
            cmd = msg.payload.get('command', '')
            result = msg.payload.get('result', '')
            print(f"\n[P2P] Command result for '{cmd}':\n{result}")
            if self.show_prompt:
                sys.stdout.write(self.prompt)
                sys.stdout.flush()
            return True

        return False

    def _input_listener(self):
        cmd_buffer = ""
        while self.running:
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    if msvcrt.kbhit():
                        char = msvcrt.getch()
                        if char == b'\r':
                            print()
                            self.show_prompt = False

                            if not cmd_buffer.strip():
                                if self.role == "host" and self.interactive_mode and not self.continuous_mode:
                                    if self.max_epoch_reached:
                                        print(f"[MAX_EPOCH] Cannot advance beyond {self.max_epoch}.")
                                    elif self.world_runner:
                                        self.world_runner._update_world()
                                        self._broadcast_to_peers()
                                        self._render()
                                        self._check_max_epoch()
                                else:
                                    self.pause_mode = not self.pause_mode
                                    if self.pause_mode:
                                        print("[P2P] PAUSE MODE enabled. Updates paused. Press Enter to resume.")
                                    else:
                                        print("[P2P] LIVE MODE enabled. Showing updates.")
                                        self._render(force=True)
                            else:
                                self.command_queue.append(cmd_buffer.strip())

                            cmd_buffer = ""
                            self.show_prompt = True
                            if self.running:
                                sys.stdout.write(self.prompt)
                                sys.stdout.flush()
                        elif char == b'\x08':
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
                                if self.role == "host" and self.interactive_mode and not self.continuous_mode:
                                    if self.max_epoch_reached:
                                        print(f"[MAX_EPOCH] Cannot advance beyond {self.max_epoch}.")
                                    elif self.world_runner:
                                        self.world_runner._update_world()
                                        self._broadcast_to_peers()
                                        self._render()
                                        self._check_max_epoch()
                                else:
                                    self.pause_mode = not self.pause_mode
                                    if self.pause_mode:
                                        print("[P2P] PAUSE MODE enabled. Updates paused. Press Enter to resume.")
                                    else:
                                        print("[P2P] LIVE MODE enabled. Showing updates.")
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
            except Exception:
                time.sleep(0.1)

    def start(self):
        self.running = True

        if not self._initialize_world() and self.role == "join":
            print("[P2P] No world folder found. Waiting for sync from host...")

        registered = self.register_with_signaling(silent=False)
        if not registered and self.role == "host":
            print("[P2P] Warning: Could not register with signaling server. Make sure it's running.")

        self.node_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.node_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.node_socket.bind((self.node_host, self.node_port))
        self.node_socket.listen(10)
        self.node_socket.setblocking(False)

        self.input_thread = threading.Thread(target=self._input_listener, daemon=True)
        self.input_thread.start()

        print(f"[P2P] Node listening on port {self.node_port}")

        if self.role == "host" and self.interactive_mode:
            print("[P2P] INTERACTIVE MODE: Press Enter for next epoch, 'c' for continuous")
            print("[P2P] Type 'help' for commands")
        else:
            print("[P2P] Press Enter to toggle PAUSE/LIVE mode, type 'help' for commands")

        sys.stdout.write(self.prompt)
        sys.stdout.flush()

        if self.role == "host":
            self._render()

        try:
            while self.running:
                self._accept_connections()
                self._sync_with_peers()

                if self.role == "host" and self.world_runner:
                    if self.max_epoch_reached:
                        print(f"\n[MAX_EPOCH] Host stopped at Epoch {self.world_runner.tick_count}.")
                        self.running = False
                        break

                    if not self.interactive_mode or self.continuous_mode:
                        self.world_runner._update_world()
                        self._render()

                        if self.world_runner.tick_count % self.broadcast_interval == 0:
                            self._broadcast_to_peers()

                        if self._check_max_epoch():
                            self.running = False
                            break

                while self.command_queue:
                    cmd = self.command_queue.pop(0)
                    self.show_prompt = False
                    self._execute_local_command(cmd)
                    self.show_prompt = True
                    if self.running:
                        sys.stdout.write(self.prompt)
                        sys.stdout.flush()

                    if self.max_epoch_reached:
                        self.running = False
                        break

                if not self.running:
                    break

                if self.role == "host" and self.interactive_mode and not self.continuous_mode:
                    time.sleep(0.05)
                else:
                    time.sleep(0.5)

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
                except json.JSONDecodeError:
                    pass
            client_socket.close()
        except (BlockingIOError, socket.timeout):
            pass
        except Exception:
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
            except Exception:
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
                                break
                        except Exception:
                            pass
                    sock.close()
                except Exception:
                    self.sync_attempts += 1
                    if self.sync_attempts > 5:
                        self.is_connected = False
                        self._render(force=True)

    def _cleanup(self):
        if self.node_socket:
            self.node_socket.close()
        self._save_all_on_exit()
        print(f"[P2P] Cleanup complete. Log saved to {os.path.join(self.world_folder, f'p2p_{self.node_id}.log')}")
        print(f"[P2P] Chat log saved to {self.chatlog_file}")


def main():
    parser = argparse.ArgumentParser(description='SWM P2P Node')
    parser.add_argument('--host', action='store_true', help='Run as host (creates world, default)')
    parser.add_argument('--join', action='store_true', help='Run as joiner (connects to host)')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    parser.add_argument('--world', type=str, help='Specify an existing world folder to load')
    parser.add_argument('--config', type=str, default='network_p2p_config.json', help='Config file')
    parser.add_argument('--interact', action='store_true', help='Interactive step-by-step mode (host only)')
    parser.add_argument('--dynamic', action='store_true', help='Dynamic mode: continuous with command input (host only)')
    parser.add_argument('--max-epoch', type=int, default=10000,
                        help='Maximum number of epochs before stopping/saving (default: 10000, 0=unlimited)')
    args = parser.parse_args()

    role = "join" if args.join else "host"

    print("="*60)
    print(f"SWM P2P NODE - {role.upper()}")
    print("="*60)

    node = SWMP2PNode(config_file=args.config, role=role, args=args)
    node.start()


if __name__ == "__main__":
    main()