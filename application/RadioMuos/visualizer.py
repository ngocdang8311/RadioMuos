"""Audio visualizer dung ffmpeg subprocess + PPM pipe.

Workflow:
  1. ffmpeg fetch URL stream (cung URL voi mpv)
  2. ffmpeg apply showcqt/showspectrum/showwaves filter
  3. ffmpeg output PPM frames qua stdout
  4. Reader thread parse PPM header + RGB data
  5. Main thread doc latest_frame, convert thanh SDL2 texture, blit

PPM (P6) format:
    P6\n
    <width> <height>\n
    <max_val>\n          (255)
    <raw RGB bytes: w*h*3>
"""
import ctypes
import subprocess
import threading

from ctypes import POINTER, byref, c_int, c_uint32, c_void_p

import sdl_helpers as h


# Visualization modes — KHONG dung showcqt vi co bug "chi nua tren"
# tren ffmpeg build cua muOS. Spectrum is the default because it fills the
# whole viewport and gives more color variation on small handheld screens.
MODES = ["spectrum", "bars", "waves"]
DEFAULT_MODE = 0


def build_filter(mode_name, width, height, fps=8):
    """Build ffmpeg filter expression cho 1 mode.

    - spectrum = showspectrum (colorful scrolling field, fills every pixel)
    - bars     = showfreqs (frequency bars from bottom up)
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
        # Frequency bars — brighter dual-channel colors, smoother low levels.
        # showfreqs khong co param fps => phai chain fps filter de cap toc do
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

        flt = build_filter(self.mode_name(), self.width, self.height, self.fps)
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
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, bufsize=0,
            )
        except OSError as e:
            self.error = str(e)
            return False
        self.thread = threading.Thread(target=self._reader, daemon=True)
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

    def _reader(self):
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
