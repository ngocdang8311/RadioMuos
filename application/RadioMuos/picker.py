"""Generic picker UI — chon 1 item tu 1 list.

Dung cho:
  - Browse by tag
  - Browse by country
  - Recent searches
  - Action menu

Cach dung:
    picker = Picker(renderer, text_cache, title="Choose tag", items=[("pop", "5313 stations"), ...])
    result = picker.run()  # blocking, tra ve item value hoac None
"""
import time
from ctypes import byref

import sdl_helpers as h

HAT_UP = 0x01
HAT_DOWN = 0x04
HAT_LEFT = 0x08
HAT_RIGHT = 0x02


class Picker:
    """Modal picker showing scrollable list, A=select B=cancel."""
    ROW_H = 32
    VISIBLE_ROWS = 11

    def __init__(self, renderer, text_cache, title, items, screen_w=640, screen_h=480):
        """items: list of (display_label, value_or_subtitle).

        - Neu element la str, label = value
        - Neu element la tuple, (label, subtitle) — subtitle hien mo de
        - Neu cell chua "value", value = label
        """
        self.renderer = renderer
        self.text = text_cache
        self.title = title
        self.items = items
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.cursor = 0
        self.scroll_top = 0
        self.last_dpad_dir = 0
        self.dpad_next_repeat = 0.0
        self.dpad_initial_delay = 0.35
        self.dpad_repeat_rate = 0.05

    def _label_and_subtitle(self, item):
        if isinstance(item, tuple):
            return item[0], item[1] if len(item) > 1 else ""
        return item, ""

    def _value(self, item):
        # Item is the "value" itself for str, or tuple[0] otherwise
        if isinstance(item, tuple):
            return item[0]
        return item

    def move(self, delta):
        if not self.items:
            return
        self.cursor = (self.cursor + delta) % len(self.items)
        if self.cursor < self.scroll_top:
            self.scroll_top = self.cursor
        elif self.cursor >= self.scroll_top + self.VISIBLE_ROWS:
            self.scroll_top = self.cursor - self.VISIBLE_ROWS + 1

    def draw(self):
        r = self.renderer
        # Dim full background
        h.sdl.SDL_SetRenderDrawColor(r, 10, 12, 18, 255)
        h.sdl.SDL_RenderClear(r)

        # Title bar
        h.fill_rect(r, 0, 0, self.screen_w, 40, (32, 36, 50))
        self.text.draw(self.title, (255, 200, 50), 24, 16, 8)
        count_text = f"{len(self.items)} items"
        tw = self.text.render(count_text, (140, 145, 165), 16)[1]
        self.text.draw(count_text, (140, 145, 165), 16, self.screen_w - tw - 16, 13)

        # List body
        list_top = 50
        list_h = self.VISIBLE_ROWS * self.ROW_H
        h.fill_rect(r, 0, list_top, self.screen_w, list_h, (24, 26, 36))

        if not self.items:
            self.text.draw("(empty)", (140, 145, 165), 20, self.screen_w // 2,
                           list_top + 40, center=True)
        else:
            for i in range(self.VISIBLE_ROWS):
                idx = self.scroll_top + i
                if idx >= len(self.items):
                    break
                label, subtitle = self._label_and_subtitle(self.items[idx])
                row_y = list_top + i * self.ROW_H
                is_cursor = (idx == self.cursor)
                if is_cursor:
                    h.fill_rect(r, 0, row_y, self.screen_w, self.ROW_H, (60, 60, 90))
                color = (255, 200, 50) if is_cursor else (235, 235, 240)
                sub_color = (200, 200, 100) if is_cursor else (140, 145, 165)
                # Label left, subtitle right
                self.text.draw(label[:38], color, 20, 16, row_y + 6)
                if subtitle:
                    sw = self.text.render(subtitle[:22], sub_color, 16)[1]
                    self.text.draw(subtitle[:22], sub_color, 16,
                                   self.screen_w - sw - 16, row_y + 9)

        # Scroll indicator
        if len(self.items) > self.VISIBLE_ROWS:
            bar_h = max(20, list_h * self.VISIBLE_ROWS // len(self.items))
            bar_y = list_top + (list_h - bar_h) * self.scroll_top // max(1, len(self.items) - self.VISIBLE_ROWS)
            h.fill_rect(r, self.screen_w - 6, bar_y, 4, bar_h, (100, 180, 255))

        # Footer
        footer_y = self.screen_h - 32
        h.fill_rect(r, 0, footer_y, self.screen_w, 32, (32, 36, 50))
        help_text = "A=select   B=cancel   D-pad=move"
        self.text.draw(help_text, (170, 175, 195), 16, 10, footer_y + 8)

        h.sdl.SDL_RenderPresent(r)

    def run(self):
        """Blocking event loop. Returns selected value or None."""
        ev = h.SDL_Event()
        running = True
        last_draw = 0
        result = None

        while running:
            while h.sdl.SDL_PollEvent(byref(ev)):
                t = ev.type
                if t == h.SDL_QUIT:
                    return None
                if t == h.SDL_KEYDOWN:
                    key = h.event_keysym(ev)
                    if key == h.SDLK_ESCAPE:
                        return None
                    if key == h.SDLK_RETURN:
                        if self.items:
                            return self._value(self.items[self.cursor])
                        return None
                    if key == h.SDLK_UP:
                        self.move(-1)
                    elif key == h.SDLK_DOWN:
                        self.move(+1)
                elif t == h.SDL_JOYBUTTONDOWN:
                    btn = h.event_jsbutton(ev)
                    if btn == 3:  # A
                        if self.items:
                            return self._value(self.items[self.cursor])
                        return None
                    if btn == 4:  # B
                        return None
                    if btn == 10:  # Start — also confirm
                        if self.items:
                            return self._value(self.items[self.cursor])
                        return None
                elif t == h.SDL_JOYHATMOTION:
                    _hat, val = h.event_jshat(ev)
                    if val & HAT_UP:
                        self.move(-1)
                        self.last_dpad_dir = -1
                        self.dpad_next_repeat = time.time() + self.dpad_initial_delay
                    elif val & HAT_DOWN:
                        self.move(+1)
                        self.last_dpad_dir = +1
                        self.dpad_next_repeat = time.time() + self.dpad_initial_delay
                    elif val == 0:
                        self.last_dpad_dir = 0

            if self.last_dpad_dir != 0 and time.time() >= self.dpad_next_repeat:
                self.move(self.last_dpad_dir)
                self.dpad_next_repeat = time.time() + self.dpad_repeat_rate

            now = h.sdl.SDL_GetTicks()
            if now - last_draw > 33:
                self.draw()
                last_draw = now
            else:
                h.sdl.SDL_Delay(10)

        return result
