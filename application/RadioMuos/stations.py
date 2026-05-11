"""Hardcoded SomaFM stations + curated public radio.

SomaFM URLs use the direct ICE streams (128 kbps MP3) to avoid PLS parsing.
All stations are free and public — no auth required.
"""

# SomaFM channels — chat luong cao, khong quang cao, free forever
SOMAFM = [
    ("Groove Salad",     "Ambient/Downtempo",   "https://ice6.somafm.com/groovesalad-128-mp3"),
    ("Drone Zone",       "Ambient",             "https://ice6.somafm.com/dronezone-128-mp3"),
    ("Deep Space One",   "Ambient Electronic",  "https://ice6.somafm.com/deepspaceone-128-mp3"),
    ("Lush",             "Vocal Trance",        "https://ice6.somafm.com/lush-128-mp3"),
    ("Indie Pop Rocks",  "Indie Pop",           "https://ice6.somafm.com/indiepop-128-mp3"),
    ("Underground 80s",  "Synth/New Wave 80s",  "https://ice6.somafm.com/u80s-128-mp3"),
    ("Suburbs of Goa",   "World/Lounge",        "https://ice6.somafm.com/suburbsofgoa-128-mp3"),
    ("Synphaera",        "Spacemusic/Ambient",  "https://ice6.somafm.com/synphaera-128-mp3"),
    ("Secret Agent",     "Lounge/Easy Beats",   "https://ice6.somafm.com/secretagent-128-mp3"),
    ("Boot Liquor",      "Americana Roots",     "https://ice6.somafm.com/bootliquor-128-mp3"),
    ("Left Coast 70s",   "Mellow 70s Rock",     "https://ice6.somafm.com/seventies-128-mp3"),
    ("Folk Forward",     "Indie Folk",          "https://ice6.somafm.com/folkfwd-128-mp3"),
    ("Beat Blender",     "Deep House",          "https://ice6.somafm.com/beatblender-128-mp3"),
    ("DEF CON Radio",    "Hacker/Electronic",   "https://ice6.somafm.com/defcon-128-mp3"),
    ("Mission Control",  "NASA Mission Audio",  "https://ice6.somafm.com/missioncontrol-128-mp3"),
    ("Vaporwaves",       "Vaporwave",           "https://ice6.somafm.com/vaporwaves-128-mp3"),
    ("Heavyweight Reggae","Reggae",             "https://ice6.somafm.com/reggae-128-mp3"),
    ("Sonic Universe",   "Avant-Jazz",          "https://ice6.somafm.com/sonicuniverse-128-mp3"),
    ("Cliqhop IDM",      "IDM",                 "https://ice6.somafm.com/cliqhop-128-mp3"),
    ("ThistleRadio",     "Celtic",              "https://ice6.somafm.com/thistle-128-mp3"),
]

# Public radio extras
EXTRAS = [
    ("BBC World Service", "News/World",         "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service"),
    ("NPR Now",           "News/US",            "https://npr-ice.streamguys1.com/live.mp3"),
    ("FIP",               "French Eclectic",    "http://icecast.radiofrance.fr/fip-midfi.mp3"),
    ("Radio Paradise",    "Eclectic/Curated",   "https://stream.radioparadise.com/mp3-128"),
    ("KEXP Seattle",      "Indie/Alt",          "https://kexp-mp3-128.streamguys1.com/kexp128.mp3"),
]


def all_stations():
    """Return list of dicts: {name, genre, url, source}"""
    out = []
    for name, genre, url in SOMAFM:
        out.append({"name": name, "genre": genre, "url": url, "source": "SomaFM"})
    for name, genre, url in EXTRAS:
        out.append({"name": name, "genre": genre, "url": url, "source": "Public"})
    return out
