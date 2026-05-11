"""SDL2 ctypes helpers — tham khao tu HelloMuos.

Chi expose nhung gi UI can. Khong dung pip.
"""
import ctypes
import glob
import os
from ctypes import (POINTER, Structure, byref, c_char_p, c_int, c_uint32,
                    c_void_p)

sdl = ctypes.CDLL("libSDL2-2.0.so.0")
ttf = ctypes.CDLL("libSDL2_ttf-2.0.so.0")

# Constants
SDL_INIT_VIDEO = 0x00000020
SDL_INIT_JOYSTICK = 0x00000200
SDL_INIT_TIMER = 0x00000001
SDL_WINDOW_FULLSCREEN_DESKTOP = 0x00001001
SDL_QUIT = 0x100
SDL_KEYDOWN = 0x300
SDL_KEYUP = 0x301
SDL_JOYAXISMOTION = 0x600
SDL_JOYHATMOTION = 0x602
SDL_JOYBUTTONDOWN = 0x603
SDL_JOYBUTTONUP = 0x604
SDL_RENDERER_ACCELERATED = 0x00000002
SDL_RENDERER_PRESENTVSYNC = 0x00000004

SDLK_ESCAPE = 27
SDLK_RETURN = 13
SDLK_q = ord("q")
SDLK_UP = 0x40000052
SDLK_DOWN = 0x40000051
SDLK_LEFT = 0x40000050
SDLK_RIGHT = 0x4000004F


class SDL_Color(Structure):
    _fields_ = [("r", ctypes.c_ubyte), ("g", ctypes.c_ubyte),
                ("b", ctypes.c_ubyte), ("a", ctypes.c_ubyte)]


class SDL_Rect(Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("w", c_int), ("h", c_int)]


# Event = 56 bytes; layout depends on type
EVENT_SIZE = 56


class SDL_Event(Structure):
    _fields_ = [("type", c_uint32),
                ("padding", ctypes.c_ubyte * (EVENT_SIZE - 4))]


# ===== Signatures =====
sdl.SDL_Init.argtypes = [c_uint32]; sdl.SDL_Init.restype = c_int
sdl.SDL_Quit.argtypes = []
sdl.SDL_GetError.restype = c_char_p
sdl.SDL_CreateWindow.argtypes = [c_char_p, c_int, c_int, c_int, c_int, c_uint32]
sdl.SDL_CreateWindow.restype = c_void_p
sdl.SDL_DestroyWindow.argtypes = [c_void_p]
sdl.SDL_CreateRenderer.argtypes = [c_void_p, c_int, c_uint32]
sdl.SDL_CreateRenderer.restype = c_void_p
sdl.SDL_DestroyRenderer.argtypes = [c_void_p]
sdl.SDL_SetRenderDrawColor.argtypes = [c_void_p, ctypes.c_ubyte, ctypes.c_ubyte,
                                        ctypes.c_ubyte, ctypes.c_ubyte]
sdl.SDL_RenderClear.argtypes = [c_void_p]
sdl.SDL_RenderPresent.argtypes = [c_void_p]
sdl.SDL_RenderFillRect.argtypes = [c_void_p, POINTER(SDL_Rect)]
sdl.SDL_RenderDrawRect.argtypes = [c_void_p, POINTER(SDL_Rect)]
sdl.SDL_RenderCopy.argtypes = [c_void_p, c_void_p, POINTER(SDL_Rect), POINTER(SDL_Rect)]
sdl.SDL_PollEvent.argtypes = [POINTER(SDL_Event)]
sdl.SDL_PollEvent.restype = c_int
sdl.SDL_NumJoysticks.restype = c_int
sdl.SDL_JoystickOpen.argtypes = [c_int]
sdl.SDL_JoystickOpen.restype = c_void_p
sdl.SDL_CreateTextureFromSurface.argtypes = [c_void_p, c_void_p]
sdl.SDL_CreateTextureFromSurface.restype = c_void_p
sdl.SDL_FreeSurface.argtypes = [c_void_p]
sdl.SDL_DestroyTexture.argtypes = [c_void_p]
sdl.SDL_QueryTexture.argtypes = [c_void_p, POINTER(c_uint32), POINTER(c_int),
                                  POINTER(c_int), POINTER(c_int)]
sdl.SDL_Delay.argtypes = [c_uint32]
sdl.SDL_GetTicks.restype = c_uint32

ttf.TTF_Init.restype = c_int
ttf.TTF_Quit.argtypes = []
ttf.TTF_OpenFont.argtypes = [c_char_p, c_int]
ttf.TTF_OpenFont.restype = c_void_p
ttf.TTF_CloseFont.argtypes = [c_void_p]
ttf.TTF_RenderUTF8_Blended.argtypes = [c_void_p, c_char_p, SDL_Color]
ttf.TTF_RenderUTF8_Blended.restype = c_void_p


def event_keysym(ev):
    """Doc keycode tu KEYDOWN event."""
    return ctypes.cast(ctypes.addressof(ev) + 20, POINTER(c_int))[0]


def event_jsbutton(ev):
    """Doc button index tu JOYBUTTONDOWN event."""
    return ctypes.cast(ctypes.addressof(ev) + 12, POINTER(ctypes.c_ubyte))[0]


def event_jshat(ev):
    """Doc (hat_index, value) tu JOYHATMOTION."""
    addr = ctypes.addressof(ev)
    hat = ctypes.cast(addr + 12, POINTER(ctypes.c_ubyte))[0]
    val = ctypes.cast(addr + 13, POINTER(ctypes.c_ubyte))[0]
    return hat, val


def event_jsaxis(ev):
    """Doc (axis_index, value -32768..32767) tu JOYAXISMOTION."""
    addr = ctypes.addressof(ev)
    axis = ctypes.cast(addr + 12, POINTER(ctypes.c_ubyte))[0]
    val = ctypes.cast(addr + 16, POINTER(ctypes.c_int16))[0]
    return axis, val


def find_font(prefer_bold=False):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansHK-VF.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf" if prefer_bold else
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    found = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    return found[0] if found else None


class TextCache:
    """Cache rendered text textures de tranh re-render moi frame."""

    def __init__(self, renderer):
        self.renderer = renderer
        self.cache = {}  # (text, color, size) -> (tex, w, h)
        self.fonts = {}  # size -> font ptr
        self.font_path = find_font()

    def get_font(self, size):
        if size not in self.fonts:
            self.fonts[size] = ttf.TTF_OpenFont(self.font_path.encode(), size)
        return self.fonts[size]

    def render(self, text, color, size):
        if not text:
            return None, 0, 0
        key = (text, color, size)
        if key in self.cache:
            return self.cache[key]
        font = self.get_font(size)
        c = SDL_Color(color[0], color[1], color[2], 255)
        surf = ttf.TTF_RenderUTF8_Blended(font, text.encode("utf-8"), c)
        if not surf:
            return None, 0, 0
        tex = sdl.SDL_CreateTextureFromSurface(self.renderer, surf)
        sdl.SDL_FreeSurface(surf)
        w, h = c_int(), c_int()
        sdl.SDL_QueryTexture(tex, None, None, byref(w), byref(h))
        result = (tex, w.value, h.value)
        self.cache[key] = result
        return result

    def draw(self, text, color, size, x, y, center=False):
        tex, w, h = self.render(text, color, size)
        if not tex:
            return w, h
        dx = x - w // 2 if center else x
        rect = SDL_Rect(dx, y, w, h)
        sdl.SDL_RenderCopy(self.renderer, tex, None, byref(rect))
        return w, h

    def cleanup(self):
        for tex, _, _ in self.cache.values():
            if tex:
                sdl.SDL_DestroyTexture(tex)
        self.cache.clear()
        for f in self.fonts.values():
            ttf.TTF_CloseFont(f)
        self.fonts.clear()


def fill_rect(renderer, x, y, w, h, color):
    sdl.SDL_SetRenderDrawColor(renderer, color[0], color[1], color[2], 255)
    rect = SDL_Rect(x, y, w, h)
    sdl.SDL_RenderFillRect(renderer, byref(rect))


def draw_rect(renderer, x, y, w, h, color):
    sdl.SDL_SetRenderDrawColor(renderer, color[0], color[1], color[2], 255)
    rect = SDL_Rect(x, y, w, h)
    sdl.SDL_RenderDrawRect(renderer, byref(rect))


def init_window(title, w, h):
    """Init SDL2 + window + renderer voi mali driver."""
    os.environ["SDL_VIDEODRIVER"] = "mali"
    if sdl.SDL_Init(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_TIMER) != 0:
        raise RuntimeError(f"SDL_Init failed: {sdl.SDL_GetError().decode()}")
    if ttf.TTF_Init() != 0:
        raise RuntimeError("TTF_Init failed")

    window = sdl.SDL_CreateWindow(
        title.encode(), 0, 0, w, h, SDL_WINDOW_FULLSCREEN_DESKTOP
    )
    if not window:
        raise RuntimeError(f"CreateWindow failed: {sdl.SDL_GetError().decode()}")

    renderer = sdl.SDL_CreateRenderer(
        window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC
    )
    if not renderer:
        raise RuntimeError(f"CreateRenderer failed: {sdl.SDL_GetError().decode()}")

    if sdl.SDL_NumJoysticks() > 0:
        sdl.SDL_JoystickOpen(0)

    return window, renderer
