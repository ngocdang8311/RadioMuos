"""Audio visualizer dung ffmpeg subprocess + PPM/PCM pipe.

Workflow:
  1. ffmpeg fetch URL stream (cung URL voi mpv)
  2. bars mode reads raw PCM and draws neon equalizer frames in Python
  3. spectrum/waves mode uses ffmpeg video filters and PPM frames
  4. Main thread doc latest_frame, convert thanh SDL2 texture, blit

PPM (P6) format:
    P6\n
    <width> <height>\n
    <max_val>\n          (255)
    <raw RGB bytes: w*h*3>
"""
import array
import ctypes
import math
import subprocess
import sys
import threading

from ctypes import POINTER, byref, c_int, c_uint32, c_void_p

import sdl_helpers as h


# Visualization modes. Bars is default because it is cleaner on a 640x480
# handheld screen and leaves spectrum/waves available via R3.
MODES = ["bars", "spectrum", "waves"]
DEFAULT_MODE = 0
BAR_COUNT = 30
BAR_BG = (8, 9, 18)
BAR_PALETTE = [
    (113, 35, 255),   # violet
    (0, 145, 255),    # blue
    (0, 225, 255),    # cyan
    (255, 209, 80),   # warm yellow
    (255, 43, 173),   # pink
]


def _mix(a, b, t):
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _palette_color(position):
    position = max(0.0, min(1.0, position))
    scaled = position * (len(BAR_PALETTE) - 1)
    idx = int(scaled)
    if idx >= len(BAR_PALETTE) - 1:
        return BAR_PALETTE[-1]
    return _mix(BAR_PALETTE[idx], BAR_PALETTE[idx + 1], scaled - idx)


def build_filter(mode_name, width, height, fps=8):
    """Build ffmpeg filter expression cho 1 mode.

    - bars     = Python renderer in start(); this fallback is for dry-run only
    - spectrum = showspectrum (colorful scrolling field, fills every pixel)
    - waves    = showwaves (waveform line o giua, sang 2 ben)

    Khong dung showcqt vi build ffmpeg trong muOS render bi loi
    (chi ve dai ngang giua frame, phan tren+duoi mat data).
    """
    if mode_name == "spectrum":
        # Full-frame spectrum. plasma + gain/saturation gives richer colors
        # than rainbow while staying cheap enough at 8fps on RG35XXH.
        return (f"showspectrum=size={width}x{height}:slide=scroll"
                f":mode=combined:scale=cbrt:fscale=log:color=plasma"
                f":saturation=1.45:gain=3:fps={fps}")
    if mode_name == "bars":
        # Fallback only. Normal bars mode renders from PCM in Python so each
        # column can have its own neon color.
        return (f"showfreqs=size={width}x{height}:mode=bar"
                f":ascale=sqrt:fscale=log:colors=0x00e5ff|0xffd166|0xff4ecd"
                f":win_size=1024:averaging=1,fps={fps}")
    if mode_name == "waves":
        # Wide p2p waveform with stronger amplitude response.
        return (f"showwaves=size={width}x{height}:mode=p2p"
                f":colors=0x00f5d4|0xff4ecd:scale=sqrt:draw=full:rate={fps}")
    return f"showwaves=size={width}x{height}:rate={fps}"


class Visualizer:
    """Run ffmpeg, parse PPM frames in background, expose latest frame."""

    def __init__(self, width=320, height=80, fps=12):
        self.width = width
        self.height = height
        self.fps = fps
        self.mode_idx = DEFAULT_MODE
        self.proc = None
        self.thread = None
        self.lock = threading.Lock()
        self.latest_frame = None  # raw RGB bytes width*height*3
        self.current_url = None
        self._stop = False
        self.frame_count = 0
        self.error = None
        self.reader_mode = "ppm"
        self._bar_levels = [0.0] * BAR_COUNT
        self._bar_peak = 0.08
        self._frame_index = 0

    def mode_name(self):
        return MODES[self.mode_idx]

    def cycle_mode(self):
        self.mode_idx = (self.mode_idx + 1) % len(MODES)
        # Restart if currently running
        if self.current_url:
            url = self.current_url
            self.stop()
            self.start(url)
        return self.mode_name()

    def start(self, url):
        if self.proc and self.proc.poll() is None:
            self.stop()
        self.current_url = url
        self._stop = False
        self.latest_frame = None
        self.frame_count = 0
        self.error = None
        self._bar_levels = [0.0] * BAR_COUNT
        self._bar_peak = 0.08
        self._frame_index = 0

        mode = self.mode_name()
        if mode == "bars":
            self.reader_mode = "pcm"
            cmd = [
                "ffmpeg",
                "-hide_banner", "-loglevel", "quiet",
                "-nostdin",
                "-re",
                "-i", url,
                "-vn",
                "-ac", "1",
                "-ar", "8000",
                "-f", "s16le",
                "-",
            ]
            target = self._pcm_reader
        else:
            self.reader_mode = "ppm"
            flt = build_filter(mode, self.width, self.height, self.fps)
            cmd = [
                "ffmpeg",
                "-hide_banner", "-loglevel", "quiet",
                "-nostdin",
                # HLS radio streams arrive in multi-second segments. Without -re,
                # ffmpeg decodes a whole segment in a burst, then stdout goes quiet,
                # which makes the visualizer appear frozen between segment fetches.
                "-re",
                "-i", url,
                "-filter_complex", flt,
                "-f", "image2pipe",
                "-vcodec", "ppm",
                "-",
            ]
            target = self._ppm_reader
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, bufsize=0,
            )
        except OSError as e:
            self.error = str(e)
            return False
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return True

    def _read_exact(self, n):
        """Read exactly n bytes from ffmpeg stdout."""
        data = b""
        while len(data) < n and not self._stop:
            chunk = self.proc.stdout.read(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def _read_until_newline(self):
        out = b""
        while not self._stop:
            c = self.proc.stdout.read(1)
            if not c:
                return None
            if c == b"\n":
                return out
            out += c
            if len(out) > 64:  # sanity
                return None

    def _ppm_reader(self):
        """Parse PPM stream and update latest_frame."""
        while not self._stop and self.proc and self.proc.poll() is None:
            try:
                # Magic "P6"
                magic = self._read_exact(2)
                if magic != b"P6":
                    break
                self._read_exact(1)  # newline after P6
                dims = self._read_until_newline()
                if not dims:
                    break
                # Width height (maybe comments — skip those start with #)
                while dims and dims.startswith(b"#"):
                    dims = self._read_until_newline()
                if not dims:
                    break
                parts = dims.split()
                if len(parts) < 2:
                    break
                w = int(parts[0])
                hh = int(parts[1])
                # Max value line
                self._read_until_newline()
                # Raw RGB
                pixels = self._read_exact(w * hh * 3)
                if pixels is None:
                    break
                with self.lock:
                    self.latest_frame = pixels
                    self.frame_count += 1
            except (ValueError, OSError):
                break

    def _pcm_reader(self):
        """Read raw PCM chunks and draw simple neon equalizer frames."""
        bytes_per_frame = max(512, int(8000 / self.fps) * 2)
        while not self._stop and self.proc and self.proc.poll() is None:
            try:
                chunk = self._read_exact(bytes_per_frame)
                if not chunk:
                    break
                samples = array.array("h")
                samples.frombytes(chunk)
                if sys.byteorder != "little":
                    samples.byteswap()
                frame = self._render_bars(samples)
                with self.lock:
                    self.latest_frame = frame
                    self.frame_count += 1
            except (EOFError, OSError, ValueError):
                break

    def _render_bars(self, samples):
        """Render colorful bar visualizer into raw RGB bytes."""
        if not samples:
            return bytes(BAR_BG) * (self.width * self.height)

        levels = []
        sample_count = len(samples)
        for i in range(BAR_COUNT):
            start = i * sample_count // BAR_COUNT
            end = max(start + 1, (i + 1) * sample_count // BAR_COUNT)
            segment = samples[start:end]
            avg = sum(abs(v) for v in segment) / (len(segment) * 32768.0)
            levels.append(avg)

        peak = max(levels) if levels else 0.0
        self._bar_peak = max(0.035, self._bar_peak * 0.94, peak)

        frame = bytearray(bytes(BAR_BG) * (self.width * self.height))
        baseline = self.height - 8
        top_margin = 8
        gap = max(5, self.width // 105)
        bar_w = max(6, (self.width - 14 - (BAR_COUNT - 1) * gap) // BAR_COUNT)
        total_w = BAR_COUNT * bar_w + (BAR_COUNT - 1) * gap
        x_start = max(0, (self.width - total_w) // 2)

        # Subtle floor line, visible enough to make the bars feel anchored.
        self._draw_rect(frame, 6, baseline + 2, self.width - 12, 1, (35, 32, 64))

        max_h = baseline - top_margin
        for i, raw in enumerate(levels):
            norm = min(1.0, raw / self._bar_peak * 1.35)
            motion = 0.88 + 0.12 * math.sin(self._frame_index * 0.32 + i * 0.7)
            target = (norm ** 0.55) * motion
            target_h = 6 + target * (max_h - 6)
            old_h = self._bar_levels[i]
            smooth = 0.62 if target_h > old_h else 0.22
            new_h = old_h + (target_h - old_h) * smooth
            self._bar_levels[i] = new_h

            bar_h = max(3, int(new_h))
            x = x_start + i * (bar_w + gap)
            y = baseline - bar_h
            color = _palette_color(i / max(1, BAR_COUNT - 1))

            glow = _mix(BAR_BG, color, 0.28)
            self._draw_rect(frame, x - 1, y - 1, bar_w + 2, bar_h + 2, glow)

            for yy in range(y, baseline):
                t = 1.0 - (yy - y) / max(1, bar_h)
                col = _mix(color, (255, 255, 255), 0.20 * t)
                self._draw_rect(frame, x, yy, bar_w, 1, col)

            cap = _mix(color, (255, 255, 255), 0.32)
            self._draw_rect(frame, x, y, bar_w, 2, cap)

        self._frame_index += 1
        return bytes(frame)

    def _draw_rect(self, frame, x, y, w, h, color):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.width, int(x + w))
        y1 = min(self.height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        r, g, b = color
        row = bytes((r, g, b)) * (x1 - x0)
        for yy in range(y0, y1):
            offset = (yy * self.width + x0) * 3
            frame[offset:offset + len(row)] = row

    def get_frame_rgb(self):
        """Return raw RGB bytes or None."""
        with self.lock:
            return self.latest_frame

    def stop(self):
        self._stop = True
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None
        self.current_url = None
        self.latest_frame = None


# ===== SDL helpers for blitting RGB pixels =====
SDL_PIXELFORMAT_RGB24 = 0x17101803  # 24bpp RGB packed


def _ensure_sdl_signatures():
    """Add signatures we need on top of sdl_helpers."""
    sdl = h.sdl
    if not hasattr(_ensure_sdl_signatures, "_done"):
        sdl.SDL_CreateTexture.argtypes = [c_void_p, c_uint32, c_int, c_int, c_int]
        sdl.SDL_CreateTexture.restype = c_void_p
        sdl.SDL_UpdateTexture.argtypes = [c_void_p, c_void_p, c_void_p, c_int]
        sdl.SDL_UpdateTexture.restype = c_int
        sdl.SDL_SetTextureBlendMode.argtypes = [c_void_p, c_int]
        sdl.SDL_SetTextureBlendMode.restype = c_int
        _ensure_sdl_signatures._done = True


SDL_TEXTUREACCESS_STREAMING = 1


class VisualizerRenderer:
    """Manages SDL2 texture for visualizer frames."""

    def __init__(self, renderer, width, height):
        _ensure_sdl_signatures()
        self.renderer = renderer
        self.width = width
        self.height = height
        self.texture = h.sdl.SDL_CreateTexture(
            renderer, SDL_PIXELFORMAT_RGB24, SDL_TEXTUREACCESS_STREAMING,
            width, height,
        )

    def update(self, rgb_bytes):
        if not self.texture or not rgb_bytes:
            return
        expected = self.width * self.height * 3
        if len(rgb_bytes) != expected:
            return
        buf = (ctypes.c_ubyte * len(rgb_bytes)).from_buffer_copy(rgb_bytes)
        h.sdl.SDL_UpdateTexture(self.texture, None, buf, self.width * 3)

    def draw(self, x, y):
        if not self.texture:
            return
        rect = h.SDL_Rect(x, y, self.width, self.height)
        h.sdl.SDL_RenderCopy(self.renderer, self.texture, None, byref(rect))

    def cleanup(self):
        if self.texture:
            h.sdl.SDL_DestroyTexture(self.texture)
            self.texture = None
