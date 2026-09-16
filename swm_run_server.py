#!/usr/bin/env python3
"""
SWM Run Server - Centralized server with interactive/dynamic modes and real-time client updates
Supports --max-epoch (default 10000) which stops the simulation exactly like 'quit'
and exports all CSVs + charts via the delegated TimelinePlotter.
"""

import json
import os
import time
import socket
import sys
import argparse
import subprocess
import threading
import select
import io
import glob
from contextlib import redirect_stdout
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


class CustomLogger:
    """Custom logger that accumulates all epochs in a single file"""

    def __init__(self, world_folder: str):
        self.world_folder = world_folder
        self.log_file = None
        self.file_handle = None
        self.start_time = datetime.now()
        self._init_log_file()

    def _init_log_file(self):
        timestamp = self.start_time.strftime("%d_%m_%Y-%H_%M_%S")
        self.log_file = os.path.join(self.world_folder, f"run_{timestamp}.log")
        mode = 'a' if os.path.exists(self.log_file) else 'w'
        self.file_handle = open(self.log_file, mode, encoding='utf-8')
        if mode == 'w':
            self.file_handle.write("="*80 + "\n")
            self.file_handle.write(f"SWM RUN LOG - Started: {self.start_time.isoformat()}\n")
            self.file_handle.write("="*80 + "\n\n")
            self.file_handle.flush()

    def log_epoch(self, epoch_data: str):
        if not self.file_handle:
            return
        try:
            self.file_handle.write("\n" + "-"*80 + "\n")
            self.file_handle.write(f"EPOCH LOG - {datetime.now().isoformat()}\n")
            self.file_handle.write("-"*80 + "\n")
            self.file_handle.write(epoch_data + "\n")
            self.file_handle.flush()
        except Exception as e:
            print(f"[ERROR] Failed to write log: {e}")

    def close(self):
        if self.file_handle:
            self.file_handle.write("\n" + "="*80 + "\n")
            self.file_handle.write(f"LOG ENDED - {datetime.now().isoformat()}\n")
            self.file_handle.write("="*80 + "\n")
            self.file_handle.close()
            self.file_handle = None


class SWMServer:
    """Centralized server for SWM with real-time client updates"""

    def __init__(self, config_file: str = "network_server_config.json", args: Any = None):
        self.config = self._load_config(config_file)
        self.running = False
        self.clients: Dict[str, socket.socket] = {}
        self.client_data: Dict[str, Dict[str, Any]] = {}
        self.world_runner = None
        self.args = args or {}
        self.last_render = 0
        self.render_interval = 0.5
        self.log_file = None
        self.server_socket = None
        self.client_lock = threading.Lock()
        self.continuous_mode = False
        self.command_queue = []
        self.input_thread = None
        self.client_messages = []

        # Chat history
        self.chat_history = []
        self.chatlog_file = None

        self.epoch_logger = None

        self.interactive_mode = getattr(self.args, 'interact', False)
        self.dynamic_mode = getattr(self.args, 'dynamic', False)

        # NEW: max_epoch
        self.max_epoch = getattr(self.args, 'max_epoch', 10000)
        self.max_epoch_reached = False

        server_cfg = self.config.get('server', {'host': '127.0.0.1', 'port': 5000,
                                                 'max_clients': 10, 'update_interval': 1.0})
        world_cfg = self.config.get('world', {'world_folder': 'world_centralized',
                                               'default_fps': 1.0})

        self.host = server_cfg.get('host', '127.0.0.1')
        self.port = server_cfg.get('port', 5000)
        self.max_clients = server_cfg.get('max_clients', 10)

        arg_world = getattr(self.args, 'world', None)
        if arg_world:
            self.world_folder = arg_world
        else:
            self.world_folder = world_cfg.get('world_folder', 'world_centralized')

        self.default_fps = getattr(self.args, 'fps', None) or world_cfg.get('default_fps', 1.0)

        if not os.path.exists(self.world_folder):
            os.makedirs(self.world_folder, exist_ok=True)
            print(f"[SERVER] Created world folder: {self.world_folder}")

        self.chatlog_file = os.path.join(self.world_folder, "chatlog.txt")
        self._load_chat_history()

        self.epoch_logger = CustomLogger(self.world_folder)

        print(f"[SERVER] Initialized on {self.host}:{self.port}")
        print(f"[SERVER] Using world folder: {self.world_folder}")
        print(f"[SERVER] Chat log: {self.chatlog_file}")
        print(f"[SERVER] Epoch log: {self.epoch_logger.log_file}")
        print(f"[SERVER] Interactive mode: {self.interactive_mode}, Dynamic mode: {self.dynamic_mode}")
        if self.max_epoch and self.max_epoch > 0:
            print(f"[SERVER] Max epochs: {self.max_epoch}")
        else:
            print(f"[SERVER] Max epochs: unlimited")

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
                print(f"[SERVER] Loaded {len(self.chat_history)} chat messages from history")
            except Exception as e:
                print(f"[WARNING] Could not load chat history: {e}")

    def _save_chat_message(self, sender: str, message: str):
        timestamp = datetime.now().isoformat()
        entry = {'timestamp': timestamp, 'sender': sender, 'message': message}
        self.chat_history.append(entry)
        try:
            with open(self.chatlog_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {sender}: {message}\n")
        except Exception as e:
            print(f"[WARNING] Could not save chat message: {e}")

    def _broadcast_chat(self, sender: str, message: str):
        chat_msg = NetworkMessage("CHAT", {
            "sender": sender,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        self._save_chat_message(sender, message)
        print(f"\n[CHAT] {sender}: {message}")
        self._log(f"[CHAT] {sender}: {message}")
        with self.client_lock:
            for client_id in list(self.clients.keys()):
                try:
                    self.clients[client_id].sendall((chat_msg.to_json() + '\n').encode('utf-8'))
                except Exception:
                    pass

    # ==================== CONFIG ====================

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
        except Exception:
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
                capture_output=True, text=True, cwd=os.getcwd()
            )
            if result.returncode != 0:
                print(f"[SERVER] Failed to generate world: {result.stderr}")
                return False
            print(f"[SERVER] World generated in {self.world_folder}")
            return True
        except Exception as e:
            print(f"[SERVER] Error generating world: {e}")
            return False

    def _get_latest_run_log_file(self) -> Optional[str]:
        patterns = [
            os.path.join(self.world_folder, "run_*.log"),
            os.path.join(self.world_folder, "run_*.txt"),
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

    # ==================== MAX EPOCH ====================

    def _check_max_epoch(self) -> bool:
        """Check if max epoch reached; if so, stop and save exactly like 'quit'."""
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

    def _save_all_on_exit(self):
        """Save everything: runtime state, statistics, CSVs, charts (same as 'quit')."""
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

    # ==================== RENDER ====================

    def _render(self, force: bool = False):
        """Render server dashboard with real-time client count"""
        if not self.world_runner:
            return

        if self.interactive_mode and not force and not self.continuous_mode:
            return

        ws = self.world_runner.world.world_states.to_dict()
        chars = self.world_runner.world.characters.get_all()
        objs = self.world_runner.world.objects.get_all()
        timers = ws.get('global_timers', {})
        global_tick = timers.get('day_cycle', 0)

        with self.client_lock:
            client_count = len(self.clients)
            client_list = list(self.clients.keys())

        output = []
        output.append("\n" + "="*80)
        epoch_str = f"EPOCH {self.world_runner.tick_count}"
        if self.max_epoch and self.max_epoch > 0:
            epoch_str += f" / {self.max_epoch}"
        output.append(f"SWM SERVER - {epoch_str}")
        output.append(f"FPS: {self.world_runner.fps} | Clients: {client_count} | Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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

        output.append(f"\n[CLIENTS] ({client_count})")
        for client_id in client_list:
            client_name = self.client_data.get(client_id, {}).get('user_name', client_id)
            output.append(f"  - {client_name} ({client_id})")

        events = self.world_runner.event_history[-10:]
        if events:
            output.append(f"\n[RECENT EVENTS]")
            for event in events:
                tick = event.get('tick', '?')
                text = event.get('text', '')
                output.append(f"  [{tick}] {text}")

        output.append("\n" + "="*80)

        if self.dynamic_mode:
            output.append("[SERVER] Dynamic mode: Running continuously. Type commands or press Enter for tick.")
        elif self.interactive_mode:
            if self.continuous_mode:
                output.append("[SERVER] Interactive mode (CONTINUOUS): Press Ctrl+C to stop continuous mode.")
            else:
                output.append("[SERVER] Interactive mode: Press Enter for next epoch, 'c' for continuous, 'q' to quit.")
        else:
            output.append("[SERVER] Auto mode: Running continuously.")

        full_render_string = "\n".join(output)

        if self.epoch_logger:
            self.epoch_logger.log_epoch(full_render_string)

        print(full_render_string)
        self._log(full_render_string)
        sys.stdout.flush()

    # ==================== CLIENT HANDLING ====================

    def _accept_clients(self):
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                client_socket.setblocking(False)
                client_id = f"client_{addr[1]}_{int(time.time())}"
                with self.client_lock:
                    self.clients[client_id] = client_socket
                    self.client_data[client_id] = {"address": addr, "connected": datetime.now().isoformat()}
                print(f"[SERVER] Client connected: {client_id} from {addr}")
                self._broadcast_world_state()
            except BlockingIOError:
                time.sleep(0.01)
            except Exception as e:
                if self.running:
                    print(f"[SERVER] Error accepting client: {e}")
                time.sleep(0.1)

    def _handle_clients(self):
        to_remove = []
        with self.client_lock:
            client_items = list(self.clients.items())

        for client_id, sock in client_items:
            try:
                try:
                    data = sock.recv(4096)
                except BlockingIOError:
                    continue
                except Exception:
                    to_remove.append(client_id)
                    continue

                if not data:
                    to_remove.append(client_id)
                    continue

                messages = data.decode('utf-8').strip().split('\n')
                for msg_str in messages:
                    if msg_str:
                        try:
                            msg = NetworkMessage.from_json(msg_str)
                            self._process_client_message(client_id, msg)
                        except Exception as e:
                            print(f"[SERVER] Error parsing message from {client_id}: {e}")
            except Exception as e:
                print(f"[SERVER] Error handling client {client_id}: {e}")
                to_remove.append(client_id)

        if to_remove:
            with self.client_lock:
                for client_id in to_remove:
                    if client_id in self.clients:
                        try:
                            self.clients[client_id].close()
                        except Exception:
                            pass
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

            user_name = msg.payload.get('user_name', client_id)
            with self.client_lock:
                if client_id in self.client_data:
                    self.client_data[client_id]['user_name'] = user_name

            mode = "dynamic" if self.dynamic_mode else "interactive" if self.interactive_mode else "auto"
            self._send_to_client(client_id, NetworkMessage("WELCOME", {
                "client_id": client_id,
                "world_state": self.world_runner.world.world_states.to_dict(),
                "mode": mode
            }))
            print(f"[SERVER] Client {client_id} authenticated as {user_name}")

        elif msg_type == "GET_WORLD_STATE":
            self._send_to_client(client_id, NetworkMessage("WORLD_STATE", {
                "world_state": self.world_runner.world.world_states.to_dict(),
                "characters": [c.to_dict() for c in self.world_runner.world.characters.get_all()],
                "objects": [o.to_dict() for o in self.world_runner.world.objects.get_all()]
            }))

        elif msg_type == "ACTION":
            action = msg.payload.get('action')
            char_name = msg.payload.get('character')
            if action:
                print(f"[SERVER] Client {client_id} performed action: {action}")
                if char_name:
                    self.world_runner._add_event(f"[CLIENT] {char_name} performed '{action}'", 'action', 'client', client_id)
                else:
                    self.world_runner._add_event(f"[CLIENT] Performed '{action}'", 'action', 'client', client_id)

        elif msg_type == "COMMAND":
            cmd = msg.payload.get('command', '')
            if cmd:
                print(f"[SERVER] Client {client_id} executed command: {cmd}")

                if cmd.strip().lower().startswith('chat '):
                    message = cmd[5:].strip()
                    if message:
                        client_name = self.client_data.get(client_id, {}).get('user_name', client_id)
                        self._broadcast_chat(client_name, message)
                        self._send_to_client(client_id, NetworkMessage("COMMAND_RESULT", {
                            "command": cmd,
                            "result": f" Chat sent: {message}"
                        }))
                    else:
                        self._send_to_client(client_id, NetworkMessage("ERROR", {
                            "message": "Chat message cannot be empty"
                        }))
                else:
                    result = self._execute_command_with_output(cmd)
                    self._send_to_client(client_id, NetworkMessage("COMMAND_RESULT", {
                        "command": cmd,
                        "result": result
                    }))

        elif msg_type == "CHAT":
            sender = msg.payload.get('sender', client_id)
            message = msg.payload.get('message', '')
            self._broadcast_chat(sender, message)

        elif msg_type == "PING":
            self._send_to_client(client_id, NetworkMessage("PONG", {"timestamp": datetime.now().isoformat()}))

    def _execute_command_with_output(self, cmd: str) -> str:
        cmd = cmd.strip()

        if not cmd:
            if self.interactive_mode and self.world_runner:
                self.world_runner._update_world(render=True)
                self._broadcast_world_state()
                self._render(force=True)
                if self._check_max_epoch():
                    return "✓ Tick executed (max epoch reached)"
                return "✓ Tick executed"
            return "No command"

        output_buffer = io.StringIO()
        with redirect_stdout(output_buffer):
            should_exit = self._execute_server_command(cmd)

        result = output_buffer.getvalue()
        if not result:
            if should_exit:
                return "Server shutting down..."
            result = "✓ Command executed successfully"
        return result

    def _execute_server_command(self, cmd: str) -> bool:
        cmd = cmd.strip().lower()

        if not cmd:
            if self.interactive_mode and self.world_runner:
                if self.max_epoch_reached:
                    print(f"[MAX_EPOCH] Cannot advance beyond {self.max_epoch}.")
                    return False
                self.world_runner._update_world(render=True)
                self._broadcast_world_state()
                self._render(force=True)
                self._check_max_epoch()
            return False

        parts = cmd.split()
        command = parts[0].lower()

        if command in ['q', 'quit', 'exit']:
            print("\n[STOP] Shutting down server...")
            self.running = False
            self._save_all_on_exit()
            return True

        if command == 'help':
            print("\n" + "="*60)
            print("AVAILABLE COMMANDS")
            print("="*60)
            print("  [Enter]              - Force an immediate tick update")
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
            print("  c / continue         - Enter continuous mode (interactive mode)")
            print("  stop                 - Stop continuous mode (interactive mode)")
            print("  chat <message>       - Send a chat message to all clients")
            print("  history              - Show the most recent run log file")
            print("  chatlog              - Show the chat history")
            print("  q / quit / exit      - Save and exit")
            print("="*60)
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

        if command == 'mode':
            print(f"\n[CURRENT MODE] {self.world_runner.mode.upper() if self.world_runner else 'unknown'}")
            if self.dynamic_mode:
                print(f"  - Running continuously at {self.default_fps} FPS")
            elif self.interactive_mode:
                print("  - Step-by-step mode")
                if self.continuous_mode:
                    print("  - Currently in CONTINUOUS mode")
            else:
                print("  - Automatic mode")
            if self.max_epoch and self.max_epoch > 0:
                print(f"  - Max epochs: {self.max_epoch} (reached: {self.max_epoch_reached})")
            return False

        if command in ['c', 'continue']:
            if self.interactive_mode and not self.continuous_mode:
                if self.max_epoch_reached:
                    print(f"[MAX_EPOCH] Cannot continue beyond {self.max_epoch}.")
                    return False
                self.continuous_mode = True
                print(f"[SERVER] Continuous mode activated at {self.default_fps} FPS. Type 'stop' to stop.")
            elif self.interactive_mode and self.continuous_mode:
                print("[SERVER] Already in continuous mode.")
            else:
                print("[SERVER] 'continue' command only available in interactive mode.")
            return False

        if command == 'stop':
            if self.interactive_mode and self.continuous_mode:
                self.continuous_mode = False
                print("[SERVER] Continuous mode stopped.")
                self._render(force=True)
            elif self.interactive_mode and not self.continuous_mode:
                print("[SERVER] Not in continuous mode.")
            else:
                print("[SERVER] 'stop' command only available in interactive mode.")
            return False

        if command == 'chat':
            if len(parts) < 2:
                print("[ERROR] Usage: chat <message>")
                return False
            message = ' '.join(parts[1:])
            self._broadcast_chat("SERVER", message)
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

        print(f"[SERVER] Unknown command: {cmd}. Type 'help' for available commands.")
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
                            if cmd_buffer.strip():
                                self.command_queue.append(cmd_buffer.strip())
                            else:
                                self.command_queue.append("")
                            cmd_buffer = ""
                            if not self.continuous_mode:
                                sys.stdout.write("\n[INTERACTIVE] > ")
                                sys.stdout.flush()
                        elif char == b'\x08':
                            if cmd_buffer:
                                cmd_buffer = cmd_buffer[:-1]
                                print("\b \b", end="", flush=True)
                        else:
                            try:
                                decoded = char.decode('utf-8')
                                if decoded.isprintable():
                                    cmd_buffer += decoded
                                    print(decoded, end="", flush=True)
                            except UnicodeDecodeError:
                                pass
                else:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        char = sys.stdin.read(1)
                        if char == '\n' or char == '\r':
                            if cmd_buffer.strip():
                                self.command_queue.append(cmd_buffer.strip())
                            else:
                                self.command_queue.append("")
                            cmd_buffer = ""
                            if not self.continuous_mode:
                                sys.stdout.write("\n[INTERACTIVE] > ")
                                sys.stdout.flush()
                        elif char == '\x7f' or char == '\x08':
                            if cmd_buffer:
                                cmd_buffer = cmd_buffer[:-1]
                                print("\b \b", end="", flush=True)
                        elif char.isprintable():
                            cmd_buffer += char
                            print(char, end="", flush=True)
                time.sleep(0.01)
            except Exception:
                time.sleep(0.1)

    def _send_to_client(self, client_id: str, msg: NetworkMessage):
        with self.client_lock:
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
        with self.client_lock:
            for client_id in list(self.clients.keys()):
                try:
                    self.clients[client_id].sendall((msg.to_json() + '\n').encode('utf-8'))
                except Exception:
                    pass

    def _cleanup(self):
        with self.client_lock:
            for client_id, sock in self.clients.items():
                try:
                    sock.close()
                except Exception:
                    pass
            self.clients.clear()
            self.client_data.clear()

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

        self._save_all_on_exit()

        if self.epoch_logger:
            self.epoch_logger.close()

        print(f"[SERVER] Cleanup complete. Log saved to {os.path.join(self.world_folder, 'server.log')}")
        print(f"[SERVER] Chat log saved to {self.chatlog_file}")
        print(f"[SERVER] Epoch log saved to {self.epoch_logger.log_file if self.epoch_logger else 'unknown'}")

    # ==================== RUN MODES ====================

    def _run_interactive_mode(self):
        print("\n" + "="*70)
        print("INTERACTIVE MODE")
        print("Commands: [Enter] / n / next - Step forward one epoch")
        print("          c / continue       - Run continuously (Ctrl+C to stop)")
        print("          chat <message>     - Send chat to all clients")
        print("          history / chatlog  - Show logs")
        if self.max_epoch and self.max_epoch > 0:
            print(f"          --max-epoch {self.max_epoch} will stop the sim automatically")
        print("          Type 'help' for all commands")
        print("="*70)

        self._render(force=True)

        self.input_thread = threading.Thread(target=self._input_listener, daemon=True)
        self.input_thread.start()

        sys.stdout.write("\n[INTERACTIVE] > ")
        sys.stdout.flush()

        while self.running:
            self._handle_clients()

            while self.command_queue:
                cmd = self.command_queue.pop(0)
                should_exit = self._execute_server_command(cmd)
                if should_exit:
                    return
                if self.running and not self.continuous_mode:
                    sys.stdout.write("\n[INTERACTIVE] > ")
                    sys.stdout.flush()

            if self.continuous_mode:
                if self.max_epoch_reached:
                    print(f"\n[MAX_EPOCH] Continuous mode stopped at Epoch {self.world_runner.tick_count}.")
                    self.continuous_mode = False
                    continue

                start_time = time.time()
                self.world_runner._update_world(render=True)
                self._broadcast_world_state()
                self._render(force=True)
                self._check_max_epoch()

                if self.max_epoch_reached:
                    self.continuous_mode = False
                    continue

                elapsed = time.time() - start_time
                sleep_time = max(0, self.world_runner.tick_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
            else:
                time.sleep(0.05)

    def _run_dynamic_mode(self):
        print("\n" + "="*70)
        print("DYNAMIC MODE ACTIVE")
        print(f"Running at {self.default_fps} FPS. Type commands anytime (press Enter to execute).")
        if self.max_epoch and self.max_epoch > 0:
            print(f"Will stop at epoch {self.max_epoch}.")
        print("Type 'help' for available commands, 'q' to quit.")
        print("="*70)

        self._render(force=True)

        self.input_thread = threading.Thread(target=self._input_listener, daemon=True)
        self.input_thread.start()

        while self.running:
            self._handle_clients()

            while self.command_queue:
                cmd = self.command_queue.pop(0)
                should_exit = self._execute_server_command(cmd)
                if should_exit:
                    return
                if self.max_epoch_reached:
                    self.running = False
                    return

            if self.max_epoch_reached:
                self.running = False
                return

            start_time = time.time()
            self.world_runner._update_world(render=True)
            self._broadcast_world_state()
            self._render(force=True)
            self._check_max_epoch()

            if self.max_epoch_reached:
                self.running = False
                return

            elapsed = time.time() - start_time
            sleep_time = max(0, self.world_runner.tick_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _run_auto_mode(self):
        print("[SERVER] Auto mode: Running continuously")
        if self.max_epoch and self.max_epoch > 0:
            print(f"[SERVER] Will stop automatically at epoch {self.max_epoch}")
        print("Press Ctrl+C to stop\n")

        try:
            while self.running:
                self._handle_clients()

                if self.max_epoch_reached:
                    print(f"\n[MAX_EPOCH] Auto mode stopped at Epoch {self.world_runner.tick_count}.")
                    self.running = False
                    break

                start_time = time.time()
                self.world_runner._update_world(render=True)
                self._broadcast_world_state()
                self._render(force=True)
                self._check_max_epoch()

                if self.max_epoch_reached:
                    self.running = False
                    break

                elapsed = time.time() - start_time
                sleep_time = max(0, self.world_runner.tick_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            pass

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
            world_folder=self.world_folder,
            max_epoch=self.max_epoch
        )

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(self.max_clients)
        self.server_socket.setblocking(False)

        print(f"[SERVER] Listening on {self.host}:{self.port}")

        accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        accept_thread.start()

        try:
            if self.dynamic_mode:
                self._run_dynamic_mode()
            elif self.interactive_mode:
                self._run_interactive_mode()
            else:
                self._run_auto_mode()
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down...")
        finally:
            self._cleanup()


def main():
    parser = argparse.ArgumentParser(description='SWM Centralized Server')
    parser.add_argument('--fps', type=float, default=1.0, help='Frames per second (default: 1.0)')
    parser.add_argument('--new', action='store_true', help='Create a new world state (ignore existing)')
    parser.add_argument('--world', type=str, help='Specify an existing world folder to load')
    parser.add_argument('--interact', action='store_true', help='Interactive step-by-step mode')
    parser.add_argument('--dynamic', action='store_true', help='Dynamic mode: continuous with command input')
    parser.add_argument('--max-epoch', type=int, default=10000,
                        help='Maximum number of epochs before stopping/saving (default: 10000, 0=unlimited)')
    args = parser.parse_args()

    print("="*60)
    print("SWM CENTRALIZED SERVER")
    print("="*60)
    server = SWMServer(args=args)
    server.start()


if __name__ == "__main__":
    main()