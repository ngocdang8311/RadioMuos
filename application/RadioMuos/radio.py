#!/usr/bin/env python3
"""RadioMuos v0.2 — stream radio internet tren muOS.

Phase 2: tab system + Radio Browser API search + history + persist state.

Tabs (chuyen bang L2 / R2):
  0 = SomaFM    (hardcoded SomaFM + public radio)
  1 = Search    (Radio Browser API search)
  2 = Favorites (saved URLs across all sources)
  3 = History   (recently played)
"""
import json
import os
import sys
import time
from ctypes import byref

import radio_browser as rb
import sdl_helpers as h
import state as state_mod
import stations
from mpv_client import MpvClient
from osk import OSK
from picker import Picker
from visualizer import Visualizer, VisualizerRenderer

SCREEN_W, SCREEN_H = 640, 480

# Colors
BG = (20, 22, 30)
PANEL_BG = (32, 36, 50)
HIGHLIGHT = (255, 200, 50)
TEXT = (235, 235, 240)
TEXT_DIM = (140, 145, 165)
GREEN = (120, 220, 130)
RED = (230, 100, 100)
ACCENT = (100, 180, 255)
TAB_ACTIVE = (90, 70, 30)
TAB_INACTIVE = (40, 44, 60)


class B:
    A = 3
    B = 4
    X = 6
    Y = 5
    L1 = 7
    R1 = 8
    L2 = 13
    R2 = 14
    SELECT = 9
    START = 10
    GUIDE = 11
    L3 = 12  # leftstick click
    R3 = 15  # rightstick click
    VOL_DOWN = 1
    VOL_UP = 2


HAT_UP = 0x01
HAT_RIGHT = 0x02
HAT_DOWN = 0x04
HAT_LEFT = 0x08


# Tab definitions
TAB_SOMAFM = 0
TAB_SEARCH = 1
TAB_FAVORITES = 2
TAB_HISTORY = 3
TAB_NAMES = ["SomaFM", "Search", "Favorites", "History"]
CACHE_TTL_SEC = 24 * 60 * 60
SLEEP_TIMER_MINUTES = [0, 15, 30, 60, 90]


def truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


class RadioApp:
    LIST_VISIBLE_ROWS = 7
    ROW_H = 28

    def __init__(self):
        self.window, self.renderer = h.init_window("RadioMuos", SCREEN_W, SCREEN_H)
        self.text = h.TextCache(self.renderer)

        # Persistent state
        self.state = state_mod.load()
        self.volume = self.state["volume"]
        self.tab = int(self.state.get("last_tab", 0))
        if self.tab < 0 or self.tab >= len(TAB_NAMES):
            self.tab = 0

        # Stations per tab
        self.somafm_list = stations.all_stations()
        self.search_results = []  # populated by search
        self.last_search_query = ""

        # Cursor state per tab
        self.cursors = [0, 0, 0, 0]
        self.scrolls = [0, 0, 0, 0]

        # Currently playing
        self.current_url = self.state.get("last_url")
        self.current_station = self._find_station_by_url(self.current_url) if self.current_url else None

        # Status flash
        self.status_msg = ""
        self.status_until = 0.0

        # Sleep timer
        self.sleep_until = 0  # 0 = disabled
        self.sleep_timer_idx = 0
        self.stream_error_seen = ""

        # Background search
        self.async_search = rb.AsyncSearch()

        # mpv
        self.mpv = MpvClient()
        self.mpv.start()
        self.mpv.set_volume(self.volume)

        # Visualizer — toggle bang L3, doi mode bang R3
        # Size va fps thap de nhe cho CPU (ffmpeg song song voi mpv)
        self.viz_enabled = self.state.get("viz_enabled", True)
        self.viz_w = SCREEN_W - 8
        self.viz_h = 128
        self.visualizer = Visualizer(width=self.viz_w, height=self.viz_h, fps=8)
        self.viz_renderer = VisualizerRenderer(self.renderer, self.viz_w, self.viz_h)

        # D-pad repeat
        self.last_dpad_dir = 0
        self.dpad_next_repeat = 0.0
        self.dpad_initial_delay = 0.35
        self.dpad_repeat_rate = 0.08

    # ---------- Station retrieval per tab ----------
    def _find_station_by_url(self, url):
        if not url:
            return None
        for s in self.somafm_list:
            if s["url"] == url:
                return s
        for s in self.search_results:
            if s["url"] == url:
                return s
        for s in state_mod.favorite_station_list(self.state):
            if s["url"] == url:
                return s
        for h in self.state["history"]:
            if h["url"] == url:
                return {"name": h["name"], "genre": h["genre"], "url": url, "source": h["source"]}
        return None

    def tab_items(self):
        if self.tab == TAB_SOMAFM:
            return self.somafm_list
        if self.tab == TAB_SEARCH:
            return self.search_results
        if self.tab == TAB_FAVORITES:
            fav_urls = set(state_mod.favorite_urls(self.state))
            collected = []
            seen = set()
            for s in state_mod.favorite_station_list(self.state):
                if s["url"] in fav_urls and s["url"] not in seen:
                    collected.append(s); seen.add(s["url"])
            for s in self.somafm_list:
                if s["url"] in fav_urls and s["url"] not in seen:
                    collected.append(s); seen.add(s["url"])
            for s in self.search_results:
                if s["url"] in fav_urls and s["url"] not in seen:
                    collected.append(s); seen.add(s["url"])
            for hi in self.state["history"]:
                if hi["url"] in fav_urls and hi["url"] not in seen:
                    collected.append({"name": hi["name"], "genre": hi["genre"],
                                      "url": hi["url"], "source": hi["source"]})
                    seen.add(hi["url"])
            return collected
        if self.tab == TAB_HISTORY:
            return [{"name": hi["name"], "genre": hi["genre"], "url": hi["url"],
                     "source": hi["source"]} for hi in self.state["history"]]
        return []

    def current_station_from_list(self):
        items = self.tab_items()
        c = self.cursors[self.tab]
        if 0 <= c < len(items):
            return items[c]
        return None

    # ---------- Actions ----------
    def play_current(self):
        s = self.current_station_from_list()
        if not s:
            return
        self.mpv.play(s["url"])
        self.current_url = s["url"]
        self.current_station = s
        self.stream_error_seen = ""
        state_mod.add_to_history(self.state, s)
        self.state["last_url"] = s["url"]
        self._save()
        if self.viz_enabled:
            self.visualizer.start(s["url"])
        self.flash(f"> {s['name']}")

    def stop_playback(self):
        self.mpv.stop()
        self.visualizer.stop()
        self.current_url = None
        self.current_station = None
        self.stream_error_seen = ""
        self.flash("Stopped")

    def toggle_visualizer(self):
        self.viz_enabled = not self.viz_enabled
        self.state["viz_enabled"] = self.viz_enabled
        self._save()
        if self.viz_enabled:
            if self.current_url:
                self.visualizer.start(self.current_url)
            self.flash(f"Visualizer ON ({self.visualizer.mode_name()})")
        else:
            self.visualizer.stop()
            self.flash("Visualizer OFF")

    def cycle_visualizer_mode(self):
        new_mode = self.visualizer.cycle_mode()
        self.flash(f"Visualizer: {new_mode}")

    def toggle_fav(self):
        s = self.current_station_from_list()
        if not s:
            return
        if state_mod.is_favorite(self.state, s["url"]):
            state_mod.remove_favorite(self.state, s["url"])
            self.flash(f"Removed favorite: {s['name']}")
        else:
            state_mod.add_favorite(self.state, s)
            self.flash(f"Favorited: {s['name']}")
        self._save()

    def adjust_volume(self, delta):
        self.volume = max(0, min(100, self.volume + delta))
        self.mpv.set_volume(self.volume)
        self.state["volume"] = self.volume
        self._save()
        self.flash(f"Volume: {self.volume}%")

    def switch_tab(self, delta):
        self.tab = (self.tab + delta) % len(TAB_NAMES)
        self.state["last_tab"] = self.tab
        self._save()
        items = self.tab_items()
        # Clamp cursor
        if self.cursors[self.tab] >= len(items):
            self.cursors[self.tab] = max(0, len(items) - 1)
        self._adjust_scroll()

    def move_cursor(self, delta):
        items = self.tab_items()
        if not items:
            return
        self.cursors[self.tab] = (self.cursors[self.tab] + delta) % len(items)
        self._adjust_scroll()

    def _adjust_scroll(self):
        c = self.cursors[self.tab]
        top = self.scrolls[self.tab]
        if c < top:
            self.scrolls[self.tab] = c
        elif c >= top + self.LIST_VISIBLE_ROWS:
            self.scrolls[self.tab] = c - self.LIST_VISIBLE_ROWS + 1

    def flash(self, msg, duration=2.0):
        self.status_msg = msg
        self.status_until = time.time() + duration

    def _save(self):
        state_mod.save(self.state)

    def toggle_sleep_timer(self):
        self.sleep_timer_idx = (self.sleep_timer_idx + 1) % len(SLEEP_TIMER_MINUTES)
        minutes = SLEEP_TIMER_MINUTES[self.sleep_timer_idx]
        if minutes <= 0:
            self.sleep_until = 0
            self.flash("Sleep timer OFF")
        else:
            self.sleep_until = time.time() + minutes * 60
            self.flash(f"Sleep in {minutes} min")

    # ---------- Search ----------
    def open_search_menu(self):
        """Hien picker cho user chon loai search."""
        items = [
            ("Search by name (keyboard)", "type query"),
            ("Browse by tag", "pop / rock / jazz / …"),
            ("Browse by country", "Vietnam / Japan / …"),
            ("Recent searches", f"{len(self.state['recent_searches'])} saved"),
            ("Top 30 stations worldwide", "by click count"),
        ]
        picker = Picker(self.renderer, self.text, "Search / Browse Radio", items)
        choice = picker.run()
        if not choice:
            return
        if choice == "Search by name (keyboard)":
            self._run_keyboard_search()
        elif choice == "Browse by tag":
            self._run_tag_browse()
        elif choice == "Browse by country":
            self._run_country_browse()
        elif choice == "Recent searches":
            self._run_recent_search()
        elif choice == "Top 30 stations worldwide":
            self._run_top_stations()

    def _run_keyboard_search(self):
        query = self._show_keyboard("Search radio:", self.last_search_query)
        if query:
            self.perform_search_by_name(query)

    def _cached_picker_values(self, key, fetcher, loading_label):
        self.flash(loading_label, 3)
        self.draw()
        cached = state_mod.cache_get(self.state, key, CACHE_TTL_SEC)
        if cached:
            return cached, None

        values, err = fetcher()
        if err:
            stale = state_mod.cache_get(self.state, key, None)
            if stale:
                self.flash("Using cached list", 2)
                return stale, None
            return None, err
        if values:
            state_mod.cache_set(self.state, key, values)
            self._save()
        return values, None

    def _run_tag_browse(self):
        tags, err = self._cached_picker_values(
            "radio_browser_tags_v1",
            lambda: rb.list_tags(limit=80),
            "Loading tags...",
        )
        if err:
            self.flash(f"Tag API error: {err[:30]}", 3)
            return
        if not tags:
            self.flash("No tags returned", 3)
            return
        picker = Picker(self.renderer, self.text, "Browse by Tag", tags)
        choice = picker.run()
        if choice:
            self.async_search.start(rb.search_by_tag, choice, 50)
            self.flash(f"Loading tag '{choice}'...", 5)
            self.last_search_query = f"tag:{choice}"

    def _run_country_browse(self):
        countries, err = self._cached_picker_values(
            "radio_browser_countries_v1",
            lambda: rb.list_countries(limit=120),
            "Loading countries...",
        )
        if err:
            self.flash(f"Country API error: {err[:30]}", 3)
            return
        if not countries:
            self.flash("No countries returned", 3)
            return
        picker = Picker(self.renderer, self.text, "Browse by Country", countries)
        choice = picker.run()
        if choice:
            self.async_search.start(rb.search_by_country, choice, 50)
            self.flash(f"Loading {choice}...", 5)
            self.last_search_query = f"country:{choice}"

    def _run_recent_search(self):
        recents = self.state.get("recent_searches", [])
        if not recents:
            self.flash("No recent searches yet", 3)
            return
        items = [(s, "previous query") for s in recents]
        picker = Picker(self.renderer, self.text, "Recent Searches", items)
        choice = picker.run()
        if choice:
            self.perform_search_by_name(choice)

    def _run_top_stations(self):
        self.flash("Loading top stations…", 3)
        self.draw()
        self.async_search.start(rb.top_stations, 30)
        self.last_search_query = "top:worldwide"

    def _show_keyboard(self, title, initial):
        """Generic keyboard modal — tra ve string hoac None."""
        osk = OSK(self.renderer, self.text, title=title, initial=initial)
        ev = h.SDL_Event()
        while True:
            while h.sdl.SDL_PollEvent(byref(ev)):
                if ev.type == h.SDL_QUIT:
                    return None
                if ev.type == h.SDL_KEYDOWN:
                    key = h.event_keysym(ev)
                    if key == h.SDLK_ESCAPE:
                        return None
                    if key == h.SDLK_RETURN:
                        return osk.value
                    if key == h.SDLK_UP:
                        osk.move(0, -1)
                    elif key == h.SDLK_DOWN:
                        osk.move(0, +1)
                    elif key == h.SDLK_LEFT:
                        osk.move(-1, 0)
                    elif key == h.SDLK_RIGHT:
                        osk.move(+1, 0)
                elif ev.type == h.SDL_JOYBUTTONDOWN:
                    btn = h.event_jsbutton(ev)
                    result = osk.handle_button(btn)
                    if result == "done":
                        return osk.value
                    if result == "cancel":
                        return None
                elif ev.type == h.SDL_JOYHATMOTION:
                    _hat, val = h.event_jshat(ev)
                    osk.handle_hat(val)
            osk.draw(SCREEN_W, SCREEN_H)
            h.sdl.SDL_Delay(16)

    def perform_search_by_name(self, query):
        self.last_search_query = query.strip()
        if not self.last_search_query:
            return
        state_mod.add_recent_search(self.state, self.last_search_query)
        self._save()
        self.async_search.start(rb.search_by_name, self.last_search_query, 50)
        self.flash(f"Searching '{self.last_search_query}'…", 5)

    def poll_async_search(self):
        if not self.async_search.in_progress and self.async_search.results:
            self.search_results = self.async_search.results
            self.async_search.results = []  # mark consumed
            self.cursors[TAB_SEARCH] = 0
            self.scrolls[TAB_SEARCH] = 0
            if self.async_search.error:
                self.flash(f"API error: {self.async_search.error[:30]}", 4)
            else:
                self.flash(f"Found {len(self.search_results)} stations")
        elif not self.async_search.in_progress and self.async_search.error:
            self.flash(f"Search failed: {self.async_search.error[:30]}", 4)
            self.async_search.error = None

    def poll_stream_status(self):
        if not self.current_url:
            return
        state, err, _loading_since = self.mpv.stream_status()
        if state == "error" and err and err != self.stream_error_seen:
            self.stream_error_seen = err
            self.visualizer.stop()
            self.flash(err[:54], 5)

    # ---------- Rendering ----------
    def draw(self):
        r = self.renderer
        h.sdl.SDL_SetRenderDrawColor(r, BG[0], BG[1], BG[2], 255)
        h.sdl.SDL_RenderClear(r)

        # Header
        h.fill_rect(r, 0, 0, SCREEN_W, 36, PANEL_BG)
        h.fill_rect(r, 12, 8, 22, 18, (16, 18, 24))
        h.draw_rect(r, 12, 8, 22, 18, ACCENT)
        h.fill_rect(r, 16, 13, 9, 4, HIGHLIGHT)
        h.fill_rect(r, 28, 12, 3, 3, TEXT_DIM)
        h.fill_rect(r, 28, 19, 3, 3, TEXT_DIM)
        self.text.draw("RadioMuos", HIGHLIGHT, 22, 42, 6)

        # Volume bar (visual)
        vbar_w = 140
        vbar_x = SCREEN_W - vbar_w - 12
        vbar_y = 12
        vbar_h = 12
        # bar background
        h.fill_rect(r, vbar_x, vbar_y, vbar_w, vbar_h, (50, 55, 75))
        # fill
        fill_w = vbar_w * self.volume // 100
        # color gradient: green low, yellow mid, orange high
        if self.volume < 50:
            vcol = GREEN
        elif self.volume < 80:
            vcol = HIGHLIGHT
        else:
            vcol = (255, 140, 80)
        h.fill_rect(r, vbar_x, vbar_y, fill_w, vbar_h, vcol)
        # tick at top of bar
        self.text.draw(f"{self.volume}%", TEXT, 14, vbar_x - 36, vbar_y - 1)

        # Sleep timer indicator (m:ss countdown)
        if self.sleep_until:
            remaining = max(0, int(self.sleep_until - time.time()))
            mins, secs = divmod(remaining, 60)
            if remaining > 0:
                self.text.draw(f"Sleep {mins}:{secs:02d}", RED, 14,
                               SCREEN_W // 2 - 45, 12)

        # Tab bar
        tab_top = 36
        tab_h = 28
        tab_w = SCREEN_W // len(TAB_NAMES)
        for i, name in enumerate(TAB_NAMES):
            x = i * tab_w
            color = TAB_ACTIVE if i == self.tab else TAB_INACTIVE
            h.fill_rect(r, x, tab_top, tab_w, tab_h, color)
            tc = HIGHLIGHT if i == self.tab else TEXT_DIM
            label = name
            if i == TAB_FAVORITES:
                fav_count = len(state_mod.favorite_urls(self.state))
                if fav_count:
                    label = f"{name} ({fav_count})"
            elif i == TAB_HISTORY:
                hc = len(self.state["history"])
                if hc:
                    label = f"{name} ({hc})"
            tw = self.text.render(label, tc, 16)[1]
            self.text.draw(label, tc, 16, x + (tab_w - tw) // 2, tab_top + 6)

        # Station list
        list_top = tab_top + tab_h + 4
        list_h = self.LIST_VISIBLE_ROWS * self.ROW_H
        h.fill_rect(r, 0, list_top, SCREEN_W, list_h, (24, 26, 36))

        items = self.tab_items()
        cursor = self.cursors[self.tab]
        scroll_top = self.scrolls[self.tab]

        if not items:
            empty_msg = {
                TAB_SOMAFM: "(empty)",
                TAB_SEARCH: "Press R2 to browse/search Radio Browser…",
                TAB_FAVORITES: "(no favorites yet — press Y on a station)",
                TAB_HISTORY: "(no history yet)",
            }[self.tab]
            self.text.draw(empty_msg, TEXT_DIM, 18, SCREEN_W // 2, list_top + 30, center=True)
        else:
            for i in range(self.LIST_VISIBLE_ROWS):
                idx = scroll_top + i
                if idx >= len(items):
                    break
                s = items[idx]
                row_y = list_top + i * self.ROW_H
                is_cursor = (idx == cursor)
                is_playing = (s["url"] == self.current_url)

                if is_cursor:
                    bg = (60, 60, 90) if not is_playing else (90, 70, 30)
                    h.fill_rect(r, 0, row_y, SCREEN_W, self.ROW_H, bg)

                fav_char = "*" if state_mod.is_favorite(self.state, s["url"]) else " "
                play_char = ">" if is_playing else " "

                color = HIGHLIGHT if is_cursor else TEXT
                if is_playing and not is_cursor:
                    color = GREEN

                line = f"{play_char} {fav_char}  {truncate(s['name'], 26):26s}  {truncate(s['genre'], 22)}"
                self.text.draw(line, color, 18, 12, row_y + 5)

        # Scroll indicator
        if len(items) > self.LIST_VISIBLE_ROWS:
            bar_h = max(20, list_h * self.LIST_VISIBLE_ROWS // len(items))
            bar_y = list_top + (list_h - bar_h) * scroll_top // max(1, len(items) - self.LIST_VISIBLE_ROWS)
            h.fill_rect(r, SCREEN_W - 6, bar_y, 4, bar_h, ACCENT)

        # Now playing card
        np_top = list_top + list_h + 4
        np_h = 46
        h.fill_rect(r, 0, np_top, SCREEN_W, np_h, PANEL_BG)
        h.fill_rect(r, 9, np_top + 15, 4, 16, ACCENT)
        h.fill_rect(r, 17, np_top + 9, 4, 22, HIGHLIGHT)
        h.fill_rect(r, 25, np_top + 18, 4, 13, ACCENT)

        if self.current_station:
            self.text.draw(truncate(self.current_station["name"], 32), TEXT, 20, 36, np_top + 2)
            np_text = self.mpv.now_playing_text()
            stream_state, stream_err, loading_since = self.mpv.stream_status()
            if np_text:
                self.text.draw(truncate(np_text, 54), GREEN, 16, 36, np_top + 28)
            elif stream_state == "error":
                self.text.draw(truncate(stream_err or "Stream error", 54), RED, 14, 36, np_top + 28)
            elif stream_state == "loading":
                elapsed = int(time.time() - loading_since) if loading_since else 0
                msg = f"(buffering {elapsed}s...)" if elapsed > 3 else "(buffering...)"
                self.text.draw(msg, ACCENT, 14, 36, np_top + 28)
            else:
                if self.visualizer.frame_count > 0:
                    self.text.draw("(streaming - no track metadata)", TEXT_DIM, 14, 36, np_top + 28)
                else:
                    self.text.draw("(waiting for stream)", TEXT_DIM, 14, 36, np_top + 28)
        else:
            self.text.draw("(stopped)", TEXT_DIM, 18, 36, np_top + 14)
            if self.async_search.in_progress:
                self.text.draw("Loading Radio Browser…", ACCENT, 14, 200, np_top + 18)

        # Visualizer area (just below NP card)
        viz_top = np_top + np_h + 2
        viz_x = (SCREEN_W - self.viz_w) // 2
        h.fill_rect(r, 0, viz_top, SCREEN_W, self.viz_h + 4, (16, 18, 24))
        if self.viz_enabled and self.current_station:
            frame = self.visualizer.get_frame_rgb()
            if frame:
                self.viz_renderer.update(frame)
                self.viz_renderer.draw(viz_x, viz_top + 2)
            else:
                self.text.draw(f"Visualizer starting ({self.visualizer.mode_name()})...",
                               TEXT_DIM, 14, SCREEN_W // 2, viz_top + 22, center=True)
        elif self.viz_enabled and not self.current_station:
            self.text.draw("Press A on a station to start", TEXT_DIM, 14,
                           SCREEN_W // 2, viz_top + 22, center=True)
        else:
            self.text.draw("Visualizer disabled (R3 to enable)", TEXT_DIM, 14,
                           SCREEN_W // 2, viz_top + 22, center=True)

        # Footer
        footer_y = SCREEN_H - 26
        h.fill_rect(r, 0, footer_y, SCREEN_W, 26, PANEL_BG)

        if self.status_msg and time.time() < self.status_until:
            self.text.draw(self.status_msg, HIGHLIGHT, 16, 8, footer_y + 5)
        else:
            self.text.draw("A Play  B Stop  Y Fav  R2 Search", TEXT_DIM, 12, 6, footer_y + 7)
            self.text.draw("X Sleep  L3 Viz  R3 Mode  Start Quit", TEXT_DIM, 12, 336, footer_y + 7)

        h.sdl.SDL_RenderPresent(r)

    # ---------- Event handling ----------
    def handle_button(self, btn):
        if btn == B.A:
            self.play_current()
        elif btn == B.B:
            self.stop_playback()
        elif btn == B.Y:
            self.toggle_fav()
        elif btn == B.X:
            self.toggle_sleep_timer()
        elif btn == B.L1:
            self.switch_tab(-1)
        elif btn == B.R1:
            self.switch_tab(+1)
        elif btn == B.R2:
            # Open search/browse menu
            self.tab = TAB_SEARCH
            self.state["last_tab"] = TAB_SEARCH
            self.open_search_menu()
        elif btn == B.L2 or btn == B.VOL_DOWN:
            self.adjust_volume(-5)
        elif btn == B.SELECT or btn == B.VOL_UP:
            self.adjust_volume(+5)
        elif btn == B.L3:
            self.toggle_visualizer()
        elif btn == B.R3:
            if self.viz_enabled:
                self.cycle_visualizer_mode()
                if self.current_url:
                    self.visualizer.start(self.current_url)
            else:
                self.flash("Enable visualizer first (L3)")
        elif btn == B.START:
            return False
        return True

    def handle_key(self, key):
        if key == h.SDLK_ESCAPE:
            return False
        if key == h.SDLK_UP:
            self.move_cursor(-1)
        elif key == h.SDLK_DOWN:
            self.move_cursor(+1)
        elif key == h.SDLK_LEFT:
            self.switch_tab(-1)
        elif key == h.SDLK_RIGHT:
            self.switch_tab(+1)
        elif key == h.SDLK_RETURN:
            self.play_current()
        elif key == h.SDLK_q:
            return False
        return True

    def run(self):
        ev = h.SDL_Event()
        running = True
        last_draw = 0

        while running:
            # Sleep timer check
            if self.sleep_until and time.time() >= self.sleep_until:
                self.stop_playback()
                self.sleep_until = 0
                self.flash("Sleep timer fired — stopped")

            # Poll async search
            self.poll_async_search()
            self.poll_stream_status()

            # Events
            while h.sdl.SDL_PollEvent(byref(ev)):
                t = ev.type
                if t == h.SDL_QUIT:
                    running = False
                elif t == h.SDL_KEYDOWN:
                    if not self.handle_key(h.event_keysym(ev)):
                        running = False
                elif t == h.SDL_JOYBUTTONDOWN:
                    btn = h.event_jsbutton(ev)
                    if not self.handle_button(btn):
                        running = False
                elif t == h.SDL_JOYHATMOTION:
                    _hat, val = h.event_jshat(ev)
                    if val & HAT_UP:
                        self.move_cursor(-1)
                        self.last_dpad_dir = -1
                        self.dpad_next_repeat = time.time() + self.dpad_initial_delay
                    elif val & HAT_DOWN:
                        self.move_cursor(+1)
                        self.last_dpad_dir = +1
                        self.dpad_next_repeat = time.time() + self.dpad_initial_delay
                    elif val & HAT_LEFT:
                        self.switch_tab(-1)
                        self.last_dpad_dir = 0
                    elif val & HAT_RIGHT:
                        self.switch_tab(+1)
                        self.last_dpad_dir = 0
                    elif val == 0:
                        self.last_dpad_dir = 0

            if self.last_dpad_dir != 0 and time.time() >= self.dpad_next_repeat:
                self.move_cursor(self.last_dpad_dir)
                self.dpad_next_repeat = time.time() + self.dpad_repeat_rate

            now = h.sdl.SDL_GetTicks()
            # When visualizer active: 12fps UI redraw (~83ms) — visualizer is 8fps anyway
            # When idle: 20fps (50ms) for responsive D-pad
            target_ms = 83 if (self.viz_enabled and self.current_url) else 50
            if now - last_draw > target_ms:
                self.draw()
                last_draw = now
            else:
                h.sdl.SDL_Delay(15)

        self.cleanup()

    def cleanup(self):
        self._save()
        self.visualizer.stop()
        self.viz_renderer.cleanup()
        self.mpv.quit()
        self.text.cleanup()
        h.sdl.SDL_DestroyRenderer(self.renderer)
        h.sdl.SDL_DestroyWindow(self.window)
        h.ttf.TTF_Quit()
        h.sdl.SDL_Quit()


def main():
    print(f"RadioMuos v0.2 starting (Python {sys.version.split()[0]})", file=sys.stderr)
    app = RadioApp()
    try:
        app.run()
    except KeyboardInterrupt:
        app.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
