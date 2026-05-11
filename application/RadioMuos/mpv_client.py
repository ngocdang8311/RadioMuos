"""Minimal mpv IPC client qua Unix socket.

Khong dung pip — chi dung stdlib (socket, json, subprocess, threading).
"""
import json
import os
import socket
import subprocess
import threading
import time

SOCKET_PATH = "/tmp/radiomuos_mpv.sock"


class MpvClient:
    def __init__(self):
        self.proc = None
        self.sock = None
        self.lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.event_buffer = []
        self.last_metadata = {}
        self.last_title = ""
        self.stream_state = "idle"
        self.last_error = ""
        self.last_end_reason = ""
        self.loading_since = 0.0
        self._reader_thread = None
        self._reader_stop = False

    def start(self):
        """Khoi dong mpv background voi IPC socket."""
        if self.proc and self.proc.poll() is None:
            return
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

        cmd = [
            "mpv",
            f"--input-ipc-server={SOCKET_PATH}",
            "--idle=yes",
            "--no-video",
            "--no-terminal",
            "--really-quiet",
            "--cache=yes",
            "--cache-secs=5",
            "--demuxer-max-bytes=4MiB",
            # Try default audio output (PipeWire / ALSA — let mpv choose)
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

        # Wait for socket to appear (max 3s)
        for _ in range(30):
            if os.path.exists(SOCKET_PATH):
                break
            time.sleep(0.1)

        # Connect
        for _ in range(10):
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(SOCKET_PATH)
                self.sock.settimeout(0.05)
                break
            except OSError:
                time.sleep(0.1)
                self.sock = None

        if self.sock:
            self._reader_thread = threading.Thread(target=self._reader, daemon=True)
            self._reader_thread.start()

    def _reader(self):
        """Doc event tu socket trong background, parse JSON line."""
        buf = b""
        while not self._reader_stop and self.sock:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    self._handle_event(msg)
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_event(self, msg):
        ev = msg.get("event")
        if ev == "start-file":
            with self.state_lock:
                self.stream_state = "loading"
                self.last_error = ""
                self.last_end_reason = ""
                self.loading_since = time.time()
        elif ev == "file-loaded":
            with self.state_lock:
                self.stream_state = "playing"
                self.last_error = ""
                self.last_end_reason = ""
            # Re-fetch metadata
            self.send({"command": ["get_property", "metadata"]})
            self.send({"command": ["get_property", "media-title"]})
        elif ev == "metadata-update":
            self.send({"command": ["get_property", "metadata"]})
            self.send({"command": ["get_property", "media-title"]})
        elif "data" in msg and "request_id" in msg:
            # Response to a get_property
            data = msg.get("data")
            with self.state_lock:
                if isinstance(data, dict):
                    self.last_metadata = data
                elif isinstance(data, str):
                    self.last_title = data
        elif ev == "end-file":
            reason = msg.get("reason") or msg.get("error") or ""
            with self.state_lock:
                self.last_title = ""
                self.last_metadata = {}
                self.last_end_reason = reason
                if reason in ("", "stop", "quit", "eof"):
                    self.stream_state = "idle"
                    self.last_error = ""
                else:
                    self.stream_state = "error"
                    self.last_error = f"Stream ended: {reason}"

    def send(self, command_dict):
        """Send JSON command qua socket. Khong cho doc response."""
        if not self.sock:
            return False
        with self.lock:
            try:
                payload = (json.dumps(command_dict) + "\n").encode()
                self.sock.sendall(payload)
                return True
            except OSError:
                return False

    def play(self, url):
        with self.state_lock:
            self.stream_state = "loading"
            self.last_error = ""
            self.last_end_reason = ""
            self.loading_since = time.time()
            self.last_title = ""
            self.last_metadata = {}
        if not self.send({"command": ["loadfile", url]}):
            with self.state_lock:
                self.stream_state = "error"
                self.last_error = "mpv IPC unavailable"

    def stop(self):
        self.send({"command": ["stop"]})
        with self.state_lock:
            self.stream_state = "idle"
            self.last_error = ""
            self.last_end_reason = "stop"
            self.last_title = ""
            self.last_metadata = {}

    def set_volume(self, vol):
        """0-100"""
        v = max(0, min(100, int(vol)))
        self.send({"command": ["set_property", "volume", v]})

    def is_playing(self):
        with self.state_lock:
            return self.stream_state == "playing"

    def stream_status(self):
        with self.state_lock:
            return self.stream_state, self.last_error, self.loading_since

    def now_playing_text(self):
        """Tao chuoi 'Artist - Title' tu ICY metadata."""
        with self.state_lock:
            md = dict(self.last_metadata or {})
            last_title = self.last_title
        # ICY-style: icy-title is common for shoutcast/icecast
        for key in ("icy-title", "title", "Title"):
            if key in md:
                return md[key]
        artist = md.get("artist") or md.get("Artist")
        title = md.get("title") or md.get("Title")
        if artist and title:
            return f"{artist} - {title}"
        if title:
            return title
        return last_title or ""

    def quit(self):
        self._reader_stop = True
        try:
            self.send({"command": ["quit"]})
        except Exception:
            pass
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
