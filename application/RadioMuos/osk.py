"""On-screen keyboard cho muOS — go bang D-pad + button.

Layout cu the cho 640x480, font 24px.
"""
import sdl_helpers as h
from ctypes import byref


LAYOUTS = {
    "lower": [
        list("1234567890"),
        list("qwertyuiop"),
        list("asdfghjkl"),
        list("zxcvbnm,.-"),
    ],
    "upper": [
        list("1234567890"),
        list("QWERTYUIOP"),
        list("ASDFGHJKL "),
        list("ZXCVBNM,.-"),
    ],
}

KEY_W = 56
KEY_H = 50
KEY_GAP = 4
TOP_OFFSET = 140


class OSK:
    """On-screen keyboard widget.

    Cach dung:
        osk = OSK(renderer, text_cache, initial="")
        while running:
            ev = poll...
            result = osk.handle_event(ev)
            if result == "done":
                value = osk.value
                break
            if result == "cancel":
                break
            osk.draw()
    """

    def __init__(self, renderer, text_cache, title="Search:", initial=""):
        self.renderer = renderer
        self.text = text_cache
        self.title = title
        self.value = initial
        self.layout_name = "lower"
        self.cursor_row = 1
        self.cursor_col = 0

    def layout(self):
        return LAYOUTS[self.layout_name]

    def move(self, dx, dy):
        rows = self.layout()
        self.cursor_row = (self.cursor_row + dy) % len(rows)
        cols = len(rows[self.cursor_row])
        self.cursor_col = self.cursor_col % cols
        self.cursor_col = (self.cursor_col + dx) % cols

    def press_key(self):
        ch = self.layout()[self.cursor_row][self.cursor_col]
        if len(self.value) < 40:
            self.value += ch

    def backspace(self):
        self.value = self.value[:-1]

    def space(self):
        if len(self.value) < 40:
            self.value += " "

    def toggle_case(self):
        self.layout_name = "upper" if self.layout_name == "lower" else "lower"

    def handle_button(self, btn):
        """Tra ve: 'done' (Start/A on confirm row), 'cancel' (B), None."""
        # Button mapping: A=3 B=4 X=6 Y=5 L1=7 R1=8 SELECT=9 START=10
        if btn == 3:  # A
            self.press_key()
        elif btn == 4:  # B
            self.backspace()
        elif btn == 5:  # Y
            self.toggle_case()
        elif btn == 6:  # X
            self.space()
        elif btn == 7:  # L1 — cancel
            return "cancel"
        elif btn == 8:  # R1 — confirm
            return "done"
        elif btn == 10:  # Start — confirm
            return "done"
        elif btn == 9:  # Select — cancel
            return "cancel"
        return None

    def handle_hat(self, val):
        if val & 0x01:  # up
            self.move(0, -1)
        elif val & 0x04:  # down
            self.move(0, +1)
        elif val & 0x08:  # left
            self.move(-1, 0)
        elif val & 0x02:  # right
            self.move(+1, 0)

    def draw(self, screen_w=640, screen_h=480):
        r = self.renderer
        # Dim background
        h.sdl.SDL_SetRenderDrawColor(r, 0, 0, 0, 255)
        h.sdl.SDL_RenderClear(r)

        # Title bar
        h.fill_rect(r, 0, 0, screen_w, 40, (32, 36, 50))
        self.text.draw(self.title, (255, 200, 50), 28, 16, 6)

        # Input box
        h.fill_rect(r, 30, 60, screen_w - 60, 60, (24, 26, 36))
        self.text.draw(self.value + "_", (235, 235, 240), 28, 40, 75)

        # Layout grid
        rows = self.layout()
        # Center horizontally
        max_cols = max(len(row) for row in rows)
        grid_w = max_cols * KEY_W + (max_cols - 1) * KEY_GAP
        start_x = (screen_w - grid_w) // 2

        for ri, row in enumerate(rows):
            row_w = len(row) * KEY_W + (len(row) - 1) * KEY_GAP
            row_start_x = (screen_w - row_w) // 2
            for ci, ch in enumerate(row):
                x = row_start_x + ci * (KEY_W + KEY_GAP)
                y = TOP_OFFSET + ri * (KEY_H + KEY_GAP)
                is_cursor = (ri == self.cursor_row and ci == self.cursor_col)
                bg = (90, 110, 180) if is_cursor else (50, 55, 75)
                h.fill_rect(r, x, y, KEY_W, KEY_H, bg)
                color = (255, 255, 255) if is_cursor else (200, 200, 210)
                # Center key label
                tw, th = self.text.render(ch, color, 28)[1:]
                self.text.draw(ch, color, 28, x + (KEY_W - tw) // 2, y + (KEY_H - th) // 2)

        # Help footer
        help_y = screen_h - 32
        h.fill_rect(r, 0, help_y, screen_w, 32, (32, 36, 50))
        help_text = "A=key  B=del  X=space  Y=case  R1/Start=done  L1/Select=cancel"
        self.text.draw(help_text, (170, 175, 195), 14, 8, help_y + 10)

        h.sdl.SDL_RenderPresent(r)
