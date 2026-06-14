import time
import os
import datetime
import re
import random
import threading
import sys
import json
import hashlib
import secrets

try:
    from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
except ImportError:
    print("\n" + "!"*60)
    print("FEHLER: 'flask' ist nicht installiert!")
    print("Bitte tippe zuerst diesen Befehl ins Terminal: py -m pip install flask")
    print("!"*60 + "\n")
    input("Drücke Enter zum Beenden...")
    sys.exit()

try:
    import requests as req_lib
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[WARN] 'requests' nicht installiert – Live-Scores deaktiviert. Installiere mit: pip install requests")

# ==========================================
# KONFIGURATION
# ==========================================
DATA_FILE = "wm2026_data.json"
LIVESCORES_CACHE_FILE = "livescores_cache.json"

app = Flask(__name__)
app.secret_key = "wm2026_griefergames_ultra_secret_1337"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

live_scores_cache = {}

ADMIN_USER = "Lattenrost1234"
ADMIN_DEFAULT_PASSWORD = "12345678"

# ==========================================
# PASSWORT-HASHING
# ==========================================
def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return salt, pw_hash

def verify_password(password, salt, pw_hash):
    if not salt or not pw_hash:
        return False
    _, check_hash = hash_password(password, salt)
    return check_hash == pw_hash

# ==========================================
# PERSISTENTER DATENSPEICHER
# ==========================================
def save_data():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[FEHLER] Kann Daten nicht speichern: {e}")

def load_data():
    global user_db
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                user_db = json.load(f)
            print(f"[OK] {len(user_db)} Benutzer geladen aus {DATA_FILE}")
        except Exception as e:
            print(f"[WARN] Kann {DATA_FILE} nicht laden: {e}")
            user_db = {}
    else:
        user_db = {}
        print(f"[INFO] Neue Datenbankdatei wird angelegt: {DATA_FILE}")

load_data()

# ==========================================
# ADMIN-ACCOUNT SICHERSTELLEN
# ==========================================
def ensure_admin_account():
    """Stellt sicher, dass der Admin-Account Lattenrost1234 immer existiert
    und ein gültiges Passwort hat. Falls noch kein Passwort gesetzt ist,
    wird das Standardpasswort 12345678 vergeben."""
    changed = False
    if ADMIN_USER not in user_db:
        user_db[ADMIN_USER] = {
            "points": 1000,
            "tipps": {},
            "lieblingsteam": None,
            "registered": datetime.datetime.now().strftime("%d.%m.%Y"),
            "salt": None,
            "pw_hash": None,
            "is_admin": True
        }
        changed = True
    if not user_db[ADMIN_USER].get("pw_hash"):
        salt, pw_hash = hash_password(ADMIN_DEFAULT_PASSWORD)
        user_db[ADMIN_USER]["salt"] = salt
        user_db[ADMIN_USER]["pw_hash"] = pw_hash
        changed = True
    user_db[ADMIN_USER]["is_admin"] = True
    if "points" not in user_db[ADMIN_USER]:
        user_db[ADMIN_USER]["points"] = 1000
    if "tipps" not in user_db[ADMIN_USER]:
        user_db[ADMIN_USER]["tipps"] = {}
    if changed:
        save_data()

ensure_admin_account()

# ==========================================
# PUNKTE-SYSTEM
# ==========================================
PUNKTE_SYSTEM = {
    "perfekt":     1000,
    "tendenz_tor": 500,
    "tendenz":     200,
    "falsch":      0,
    "einsatz":     50,
    "deadline_min": 0
}

# ==========================================
# FLAGGEN
# ==========================================
def flag_img(code, size=32):
    code_lower = code.lower()
    special = {"sco": "gb-sct", "eng": "gb-eng", "wal": "gb-wls"}
    if code_lower in special:
        code_lower = special[code_lower]
    return f'<img src="https://flagcdn.com/h{size}/{code_lower}.png" width="{size}" height="{int(size*0.667)}" style="border-radius:3px;vertical-align:middle;object-fit:cover;" alt="" onerror="this.style.display=\'none\'">'

def flag_url(code):
    """Gibt nur die URL zurück für CSS background-image."""
    code_lower = code.lower()
    special = {"sco": "gb-sct", "eng": "gb-eng", "wal": "gb-wls"}
    if code_lower in special:
        code_lower = special[code_lower]
    return f"https://flagcdn.com/h120/{code_lower}.png"

# ==========================================
# WM 2026 GRUPPEN & SPIELE
# ==========================================
WM_GRUPPEN = {
    "A": {
        "teams": [
            {"name": "Mexiko",      "code": "mx"},
            {"name": "Südkorea",    "code": "kr"},
            {"name": "Südafrika",   "code": "za"},
            {"name": "Tschechien",  "code": "cz"},
        ],
        "spiele": [
            {"id": "A1", "heim": "Mexiko",     "gast": "Südafrika",  "datum": "11.06.2026", "uhrzeit": "21:00"},
            {"id": "A2", "heim": "Südkorea",   "gast": "Tschechien", "datum": "12.06.2026", "uhrzeit": "21:00"},
            {"id": "A3", "heim": "Mexiko",     "gast": "Tschechien", "datum": "16.06.2026", "uhrzeit": "21:00"},
            {"id": "A4", "heim": "Südkorea",   "gast": "Südafrika",  "datum": "16.06.2026", "uhrzeit": "00:00"},
            {"id": "A5", "heim": "Mexiko",     "gast": "Südkorea",   "datum": "21.06.2026", "uhrzeit": "21:00"},
            {"id": "A6", "heim": "Tschechien", "gast": "Südafrika",  "datum": "21.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "B": {
        "teams": [
            {"name": "Schweiz",  "code": "ch"},
            {"name": "Kanada",   "code": "ca"},
            {"name": "Katar",    "code": "qa"},
            {"name": "Bosnien",  "code": "ba"},
        ],
        "spiele": [
            {"id": "B1", "heim": "Kanada",  "gast": "Katar",   "datum": "12.06.2026", "uhrzeit": "00:00"},
            {"id": "B2", "heim": "Schweiz", "gast": "Bosnien", "datum": "12.06.2026", "uhrzeit": "21:00"},
            {"id": "B3", "heim": "Kanada",  "gast": "Bosnien", "datum": "16.06.2026", "uhrzeit": "21:00"},
            {"id": "B4", "heim": "Schweiz", "gast": "Katar",   "datum": "17.06.2026", "uhrzeit": "00:00"},
            {"id": "B5", "heim": "Schweiz", "gast": "Kanada",  "datum": "21.06.2026", "uhrzeit": "21:00"},
            {"id": "B6", "heim": "Bosnien", "gast": "Katar",   "datum": "21.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "C": {
        "teams": [
            {"name": "Brasilien", "code": "br"},
            {"name": "Marokko",   "code": "ma"},
            {"name": "Schottland","code": "sco"},
            {"name": "Haiti",     "code": "ht"},
        ],
        "spiele": [
            {"id": "C1", "heim": "Brasilien", "gast": "Marokko",    "datum": "13.06.2026", "uhrzeit": "00:00"},
            {"id": "C2", "heim": "Schottland","gast": "Haiti",      "datum": "13.06.2026", "uhrzeit": "21:00"},
            {"id": "C3", "heim": "Brasilien", "gast": "Haiti",      "datum": "17.06.2026", "uhrzeit": "21:00"},
            {"id": "C4", "heim": "Marokko",   "gast": "Schottland", "datum": "18.06.2026", "uhrzeit": "00:00"},
            {"id": "C5", "heim": "Brasilien", "gast": "Schottland", "datum": "22.06.2026", "uhrzeit": "21:00"},
            {"id": "C6", "heim": "Marokko",   "gast": "Haiti",      "datum": "22.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "D": {
        "teams": [
            {"name": "USA",       "code": "us"},
            {"name": "Paraguay",  "code": "py"},
            {"name": "Australien","code": "au"},
            {"name": "Türkei",    "code": "tr"},
        ],
        "spiele": [
            {"id": "D1", "heim": "USA",        "gast": "Australien", "datum": "13.06.2026", "uhrzeit": "21:00"},
            {"id": "D2", "heim": "Paraguay",   "gast": "Türkei",     "datum": "14.06.2026", "uhrzeit": "00:00"},
            {"id": "D3", "heim": "USA",        "gast": "Türkei",     "datum": "18.06.2026", "uhrzeit": "21:00"},
            {"id": "D4", "heim": "Paraguay",   "gast": "Australien", "datum": "18.06.2026", "uhrzeit": "21:00"},
            {"id": "D5", "heim": "USA",        "gast": "Paraguay",   "datum": "22.06.2026", "uhrzeit": "21:00"},
            {"id": "D6", "heim": "Australien", "gast": "Türkei",     "datum": "22.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "E": {
        "teams": [
            {"name": "Deutschland",    "code": "de"},
            {"name": "Elfenbeinküste", "code": "ci"},
            {"name": "Ecuador",        "code": "ec"},
            {"name": "Ungarn",         "code": "hu"},
        ],
        "spiele": [
            {"id": "E1", "heim": "Deutschland",    "gast": "Ecuador",        "datum": "14.06.2026", "uhrzeit": "19:00"},
            {"id": "E2", "heim": "Elfenbeinküste", "gast": "Ungarn",         "datum": "14.06.2026", "uhrzeit": "21:00"},
            {"id": "E3", "heim": "Deutschland",    "gast": "Ungarn",         "datum": "18.06.2026", "uhrzeit": "21:00"},
            {"id": "E4", "heim": "Elfenbeinküste", "gast": "Ecuador",        "datum": "19.06.2026", "uhrzeit": "00:00"},
            {"id": "E5", "heim": "Deutschland",    "gast": "Elfenbeinküste", "datum": "23.06.2026", "uhrzeit": "21:00"},
            {"id": "E6", "heim": "Ecuador",        "gast": "Ungarn",         "datum": "23.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "F": {
        "teams": [
            {"name": "Niederlande", "code": "nl"},
            {"name": "Japan",       "code": "jp"},
            {"name": "Tunesien",    "code": "tn"},
            {"name": "Schweden",    "code": "se"},
        ],
        "spiele": [
            {"id": "F1", "heim": "Niederlande", "gast": "Japan",       "datum": "14.06.2026", "uhrzeit": "21:00"},
            {"id": "F2", "heim": "Tunesien",    "gast": "Schweden",    "datum": "15.06.2026", "uhrzeit": "00:00"},
            {"id": "F3", "heim": "Niederlande", "gast": "Schweden",    "datum": "19.06.2026", "uhrzeit": "21:00"},
            {"id": "F4", "heim": "Japan",       "gast": "Tunesien",    "datum": "19.06.2026", "uhrzeit": "21:00"},
            {"id": "F5", "heim": "Niederlande", "gast": "Tunesien",    "datum": "23.06.2026", "uhrzeit": "21:00"},
            {"id": "F6", "heim": "Japan",       "gast": "Schweden",    "datum": "23.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "G": {
        "teams": [
            {"name": "Belgien",    "code": "be"},
            {"name": "Ägypten",    "code": "eg"},
            {"name": "Iran",       "code": "ir"},
            {"name": "Neuseeland", "code": "nz"},
        ],
        "spiele": [
            {"id": "G1", "heim": "Belgien",    "gast": "Iran",       "datum": "15.06.2026", "uhrzeit": "21:00"},
            {"id": "G2", "heim": "Ägypten",    "gast": "Neuseeland", "datum": "15.06.2026", "uhrzeit": "00:00"},
            {"id": "G3", "heim": "Belgien",    "gast": "Neuseeland", "datum": "19.06.2026", "uhrzeit": "21:00"},
            {"id": "G4", "heim": "Ägypten",    "gast": "Iran",       "datum": "19.06.2026", "uhrzeit": "21:00"},
            {"id": "G5", "heim": "Belgien",    "gast": "Ägypten",    "datum": "23.06.2026", "uhrzeit": "21:00"},
            {"id": "G6", "heim": "Iran",       "gast": "Neuseeland", "datum": "23.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "H": {
        "teams": [
            {"name": "Spanien",       "code": "es"},
            {"name": "Uruguay",       "code": "uy"},
            {"name": "Saudi-Arabien", "code": "sa"},
            {"name": "Kap Verde",     "code": "cv"},
        ],
        "spiele": [
            {"id": "H1", "heim": "Spanien",       "gast": "Uruguay",       "datum": "15.06.2026", "uhrzeit": "21:00"},
            {"id": "H2", "heim": "Saudi-Arabien", "gast": "Kap Verde",     "datum": "16.06.2026", "uhrzeit": "00:00"},
            {"id": "H3", "heim": "Spanien",       "gast": "Kap Verde",     "datum": "20.06.2026", "uhrzeit": "00:00"},
            {"id": "H4", "heim": "Uruguay",       "gast": "Saudi-Arabien", "datum": "19.06.2026", "uhrzeit": "21:00"},
            {"id": "H5", "heim": "Spanien",       "gast": "Saudi-Arabien", "datum": "24.06.2026", "uhrzeit": "21:00"},
            {"id": "H6", "heim": "Uruguay",       "gast": "Kap Verde",     "datum": "24.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "I": {
        "teams": [
            {"name": "Frankreich", "code": "fr"},
            {"name": "Senegal",    "code": "sn"},
            {"name": "Norwegen",   "code": "no"},
            {"name": "Kroatien",   "code": "hr"},
        ],
        "spiele": [
            {"id": "I1", "heim": "Frankreich", "gast": "Senegal",    "datum": "16.06.2026", "uhrzeit": "21:00"},
            {"id": "I2", "heim": "Norwegen",   "gast": "Kroatien",   "datum": "16.06.2026", "uhrzeit": "21:00"},
            {"id": "I3", "heim": "Frankreich", "gast": "Kroatien",   "datum": "20.06.2026", "uhrzeit": "21:00"},
            {"id": "I4", "heim": "Senegal",    "gast": "Norwegen",   "datum": "20.06.2026", "uhrzeit": "21:00"},
            {"id": "I5", "heim": "Frankreich", "gast": "Norwegen",   "datum": "25.06.2026", "uhrzeit": "21:00"},
            {"id": "I6", "heim": "Kroatien",   "gast": "Senegal",    "datum": "25.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "J": {
        "teams": [
            {"name": "England",   "code": "eng"},
            {"name": "Kolumbien", "code": "co"},
            {"name": "Serbien",   "code": "rs"},
            {"name": "Venezuela", "code": "ve"},
        ],
        "spiele": [
            {"id": "J1", "heim": "England",   "gast": "Serbien",    "datum": "16.06.2026", "uhrzeit": "21:00"},
            {"id": "J2", "heim": "Kolumbien", "gast": "Venezuela",  "datum": "17.06.2026", "uhrzeit": "00:00"},
            {"id": "J3", "heim": "England",   "gast": "Venezuela",  "datum": "20.06.2026", "uhrzeit": "21:00"},
            {"id": "J4", "heim": "Kolumbien", "gast": "Serbien",    "datum": "21.06.2026", "uhrzeit": "00:00"},
            {"id": "J5", "heim": "England",   "gast": "Kolumbien",  "datum": "25.06.2026", "uhrzeit": "21:00"},
            {"id": "J6", "heim": "Serbien",   "gast": "Venezuela",  "datum": "25.06.2026", "uhrzeit": "21:00"},
        ]
    },
    "K": {
        "teams": [
            {"name": "Portugal",    "code": "pt"},
            {"name": "Argentinien", "code": "ar"},
            {"name": "Chile",       "code": "cl"},
            {"name": "Albanien",    "code": "al"},
        ],
        "spiele": [
            {"id": "K1", "heim": "Portugal",    "gast": "Chile",       "datum": "17.06.2026", "uhrzeit": "00:00"},
            {"id": "K2", "heim": "Argentinien", "gast": "Albanien",    "datum": "17.06.2026", "uhrzeit": "21:00"},
            {"id": "K3", "heim": "Portugal",    "gast": "Albanien",    "datum": "21.06.2026", "uhrzeit": "21:00"},
            {"id": "K4", "heim": "Argentinien", "gast": "Chile",       "datum": "21.06.2026", "uhrzeit": "21:00"},
            {"id": "K5", "heim": "Portugal",    "gast": "Argentinien", "datum": "26.06.2026", "uhrzeit": "00:00"},
            {"id": "K6", "heim": "Chile",       "gast": "Albanien",    "datum": "26.06.2026", "uhrzeit": "00:00"},
        ]
    },
    "L": {
        "teams": [
            {"name": "Italien",    "code": "it"},
            {"name": "Kamerun",    "code": "cm"},
            {"name": "Nigeria",    "code": "ng"},
            {"name": "Österreich", "code": "at"},
        ],
        "spiele": [
            {"id": "L1", "heim": "Italien",    "gast": "Nigeria",    "datum": "17.06.2026", "uhrzeit": "21:00"},
            {"id": "L2", "heim": "Kamerun",    "gast": "Österreich", "datum": "18.06.2026", "uhrzeit": "00:00"},
            {"id": "L3", "heim": "Italien",    "gast": "Österreich", "datum": "21.06.2026", "uhrzeit": "21:00"},
            {"id": "L4", "heim": "Kamerun",    "gast": "Nigeria",    "datum": "22.06.2026", "uhrzeit": "00:00"},
            {"id": "L5", "heim": "Italien",    "gast": "Kamerun",    "datum": "26.06.2026", "uhrzeit": "21:00"},
            {"id": "L6", "heim": "Nigeria",    "gast": "Österreich", "datum": "26.06.2026", "uhrzeit": "21:00"},
        ]
    },
}

ALLE_TEAMS = []
for gruppe_key, gruppe_data in WM_GRUPPEN.items():
    for team in gruppe_data["teams"]:
        ALLE_TEAMS.append({**team, "gruppe": gruppe_key})

TEAM_CODE = {t["name"]: t["code"] for t in ALLE_TEAMS}

# ==========================================
# LIVE-SCORES CACHE LADEN
# ==========================================
if os.path.exists(LIVESCORES_CACHE_FILE):
    try:
        with open(LIVESCORES_CACHE_FILE, 'r') as f:
            live_scores_cache = json.load(f)
        print(f"[OK] Live-Score-Cache geladen ({len(live_scores_cache)} Einträge)")
    except:
        pass

def persist_live_cache():
    try:
        with open(LIVESCORES_CACHE_FILE, 'w') as f:
            json.dump(live_scores_cache, f)
    except Exception as e:
        print(f"[WARN] Cache nicht gespeichert: {e}")

# ==========================================
# HELPER: Spielzeit / Status (komplett Admin-gesteuert)
# ==========================================
# Mögliche manuelle Status: "upcoming", "live", "halbzeit", "nachspielzeit", "final"
# Diese werden ausschließlich vom Admin im Adminpanel gesetzt.

def parse_spiel_datetime(spiel):
    try:
        dt_str = f"{spiel['datum']} {spiel['uhrzeit']}"
        dt_cest = datetime.datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
        dt_utc = dt_cest - datetime.timedelta(hours=2)
        return dt_utc
    except:
        return None

def get_now_local():
    return datetime.datetime.now()

def get_cache_entry(sid):
    entry = live_scores_cache.get(sid)
    if not entry:
        entry = {"status": "upcoming", "heim": None, "gast": None, "minuto": None, "nachspielzeit": 0}
        live_scores_cache[sid] = entry
    if "nachspielzeit" not in entry:
        entry["nachspielzeit"] = 0
    return entry

def get_spiel_status(spiel):
    """Status wird ausschließlich vom Admin über das Cache gesetzt.
    Standard ist 'upcoming', solange der Admin nichts geändert hat."""
    sid = spiel["id"]
    entry = live_scores_cache.get(sid)
    if entry:
        status = entry.get("status", "upcoming")
        if status in ("live", "halbzeit", "nachspielzeit", "final", "upcoming"):
            return status
    return "upcoming"

def is_spiel_aktiv(spiel):
    """True wenn das Spiel gerade läuft (live, Halbzeit oder Nachspielzeit) -
    in diesem Fall darf NICHT mehr getippt werden."""
    return get_spiel_status(spiel) in ("live", "halbzeit", "nachspielzeit")

def tipp_erlaubt(spiel):
    status = get_spiel_status(spiel)
    return status == "upcoming"

def get_live_score(spiel_id):
    entry = live_scores_cache.get(spiel_id)
    if entry and entry.get("heim") is not None:
        return entry
    return None

def minuten_bis_spiel(spiel):
    dt_local = parse_spiel_datetime(spiel)
    if dt_local is None:
        return 9999
    jetzt = get_now_local()
    return int((dt_local - jetzt).total_seconds() / 60)

def get_day_label(spiel):
    try:
        spiel_dt = datetime.datetime.strptime(spiel["datum"], "%d.%m.%Y").date()
    except:
        return None, None
    heute = datetime.date.today()
    morgen = heute + datetime.timedelta(days=1)
    if spiel_dt == heute:
        return "HEUTE", "day-today"
    elif spiel_dt == morgen:
        return "MORGEN", "day-tomorrow"
    return None, None

# ==========================================
# LEADERBOARD
# ==========================================
def get_leaderboard():
    lb = []
    for username, data in user_db.items():
        if data.get("is_admin"):
            continue
        lb.append({
            "username": username,
            "points": data.get("points", 0),
            "tipps": len(data.get("tipps", {})),
            "lieblingsteam": data.get("lieblingsteam")
        })
    lb.sort(key=lambda x: x["points"], reverse=True)
    return lb

# ==========================================
# DESIGN SYSTEM — WM 2026 ULTRA
# ==========================================

BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Exo+2:ital,wght@0,300;0,400;0,600;0,700;0,800;0,900;1,700&family=Rajdhani:wght@400;500;600;700&display=swap');

:root {
  --g1: #0a0e1a;
  --g2: #0d1220;
  --g3: #111828;
  --g4: #161f35;
  --g5: #1c2a45;
  --card: #131a2e;
  --card2: #0f1525;
  --gold: #f5c842;
  --gold2: #e8b020;
  --gold3: #ffd966;
  --copper: #e07b39;
  --fire: #ff5722;
  --fire2: #ff7043;
  --neon: #00e5a0;
  --neon2: #00c580;
  --sky: #29b6f6;
  --live: #f44336;
  --live2: #ef9a9a;
  --border: rgba(245,200,66,0.15);
  --border2: rgba(255,255,255,0.07);
  --border3: rgba(255,255,255,0.04);
  --text: #eaf0ff;
  --text2: #8fa0c0;
  --muted: #3d4f6e;
  --r1: #f5c842;
  --r2: #b8cce0;
  --r3: #cd8b4a;
}

*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}

body{
  background:var(--g1);
  color:var(--text);
  font-family:'Exo 2',sans-serif;
  min-height:100vh;
  overflow-x:hidden;
}

body::before{
  content:'';
  position:fixed;inset:0;z-index:0;
  background:
    radial-gradient(ellipse 120% 60% at 50% -10%, rgba(0,229,160,0.06) 0%,transparent 55%),
    radial-gradient(ellipse 80% 50% at 5% 70%, rgba(41,182,246,0.04) 0%,transparent 45%),
    radial-gradient(ellipse 60% 50% at 95% 30%, rgba(245,200,66,0.04) 0%,transparent 45%),
    repeating-linear-gradient(0deg,transparent,transparent 44px,rgba(0,229,160,0.018) 44px,rgba(0,229,160,0.018) 45px),
    repeating-linear-gradient(90deg,transparent,transparent 80px,rgba(0,229,160,0.01) 80px,rgba(0,229,160,0.01) 81px);
  pointer-events:none;
  animation:bgPulse 12s ease-in-out infinite;
}
@keyframes bgPulse{0%,100%{opacity:1}50%{opacity:0.7}}

body::after{
  content:'';
  position:fixed;
  width:600px;height:600px;
  border-radius:50%;
  background:radial-gradient(circle,rgba(245,200,66,0.04) 0%,transparent 70%);
  top:-200px;right:-200px;
  pointer-events:none;
  animation:orbFloat 20s ease-in-out infinite;
  z-index:0;
}
@keyframes orbFloat{0%,100%{transform:translate(0,0) scale(1)}33%{transform:translate(-60px,40px) scale(1.1)}66%{transform:translate(30px,-50px) scale(0.9)}}

/* ── NAVBAR ── */
.navbar{
  position:sticky;top:0;z-index:900;
  height:62px;
  display:flex;align-items:center;gap:20px;padding:0 28px;
  background:rgba(10,14,26,0.95);
  border-bottom:1px solid rgba(245,200,66,0.12);
  backdrop-filter:blur(32px) saturate(180%);
}
.navbar::after{
  content:'';
  position:absolute;bottom:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(245,200,66,0.4),transparent);
  animation:scanline 6s linear infinite;
}
@keyframes scanline{0%{background-position:0% 0%}100%{background-position:200% 0%}}
.nb-logo-wrap{display:flex;align-items:center;gap:12px;flex-shrink:0;}
.nb-icon{
  width:34px;height:34px;
  background:linear-gradient(135deg,var(--gold),var(--copper));
  border-radius:8px;
  display:flex;align-items:center;justify-content:center;
  font-size:17px;
  box-shadow:0 0 16px rgba(245,200,66,0.35);
  animation:iconPulse 3s ease-in-out infinite;
}
@keyframes iconPulse{0%,100%{box-shadow:0 0 16px rgba(245,200,66,0.35)}50%{box-shadow:0 0 28px rgba(245,200,66,0.6)}}
.nb-title{
  font-family:'Bebas Neue';font-size:22px;letter-spacing:4px;
  background:linear-gradient(90deg,var(--gold3),var(--gold),var(--copper));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}
.nb-sep{width:1px;height:26px;background:rgba(255,255,255,0.07);flex-shrink:0;}
.nb-links{display:flex;gap:2px;}
.nb-link{
  padding:6px 14px;border-radius:7px;text-decoration:none;
  font-family:'Rajdhani';font-weight:700;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;
  color:var(--muted);transition:all .15s;position:relative;
}
.nb-link:hover{color:var(--text2);background:rgba(255,255,255,0.04);}
.nb-link.active{color:var(--gold);}
.nb-link.active::after{
  content:'';position:absolute;bottom:4px;left:14px;right:14px;
  height:2px;background:linear-gradient(90deg,var(--gold),var(--copper));
  border-radius:1px;
}
.nb-right{display:flex;align-items:center;gap:10px;margin-left:auto;}
.nb-coins{
  display:flex;align-items:center;gap:7px;
  background:linear-gradient(135deg,rgba(245,200,66,0.14),rgba(224,123,57,0.08));
  border:1px solid rgba(245,200,66,0.3);border-radius:20px;
  padding:5px 14px 5px 8px;
  font-family:'Bebas Neue';font-size:17px;letter-spacing:2px;color:var(--gold);
}
.coin-dot{
  width:20px;height:20px;background:linear-gradient(135deg,var(--gold3),var(--copper));
  border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:10px;font-weight:900;color:#000;flex-shrink:0;
  box-shadow:0 0 8px rgba(245,200,66,0.4);
}
.nb-avatar{width:30px;height:30px;border-radius:7px;image-rendering:pixelated;border:2px solid rgba(245,200,66,0.3);}
.nb-user{font-family:'Rajdhani';font-weight:700;font-size:15px;letter-spacing:.5px;}
.nb-logout{
  font-size:12px;color:var(--muted);text-decoration:none;
  padding:5px 11px;border-radius:6px;border:1px solid transparent;
  transition:all .2s;font-family:'Rajdhani';font-weight:600;letter-spacing:.5px;
}
.nb-logout:hover{color:var(--fire);border-color:rgba(255,87,34,0.35);background:rgba(255,87,34,0.06);}

/* ── HERO ── */
.hero{
  padding:90px 20px 80px;
  text-align:center;
  position:relative;z-index:1;
  overflow:hidden;
}
.hero-field{
  position:absolute;inset:0;
  background:
    linear-gradient(180deg,transparent 60%,rgba(10,14,26,0.8) 100%),
    repeating-linear-gradient(90deg,transparent,transparent 100px,rgba(0,229,160,0.03) 100px,rgba(0,229,160,0.03) 101px),
    repeating-linear-gradient(0deg,transparent,transparent 100px,rgba(0,229,160,0.02) 100px,rgba(0,229,160,0.02) 101px);
}
.hero-chip{
  display:inline-flex;align-items:center;gap:8px;
  font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:4px;text-transform:uppercase;
  color:var(--neon);border:1px solid rgba(0,229,160,0.3);
  background:rgba(0,229,160,0.07);
  padding:7px 20px;border-radius:100px;margin-bottom:28px;
  animation:chipGlow 3s ease-in-out infinite;
}
@keyframes chipGlow{0%,100%{box-shadow:0 0 0 0 rgba(0,229,160,0)}50%{box-shadow:0 0 20px rgba(0,229,160,0.2)}}
.hero-h1{
  font-family:'Bebas Neue';
  font-size:clamp(70px,14vw,160px);line-height:.85;
  letter-spacing:4px;
  position:relative;z-index:1;
  margin-bottom:24px;
}
.hero-h1-inner{
  background:linear-gradient(170deg,#ffffff 0%,var(--gold3) 35%,var(--gold2) 60%,var(--copper) 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  display:block;
  animation:titleShimmer 4s ease-in-out infinite;
  background-size:200% 200%;
}
@keyframes titleShimmer{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.hero-sub{
  color:var(--text2);font-size:16px;font-weight:400;
  max-width:440px;margin:0 auto 48px;line-height:1.9;
}
.hero-ctas{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;}

/* ── BUTTONS ── */
.btn{
  display:inline-flex;align-items:center;gap:10px;
  font-family:'Rajdhani';font-weight:700;font-size:15px;letter-spacing:2px;text-transform:uppercase;
  text-decoration:none;padding:13px 34px;border-radius:5px;border:none;
  cursor:pointer;transition:all .2s;position:relative;overflow:hidden;
}
.btn::before{
  content:'';position:absolute;inset:0;
  background:linear-gradient(45deg,transparent 30%,rgba(255,255,255,0.12) 50%,transparent 70%);
  transform:translateX(-200%);transition:transform .5s;
}
.btn:hover::before{transform:translateX(200%);}
.btn-primary{
  background:linear-gradient(135deg,var(--fire2),var(--fire),var(--copper));
  color:#fff;
  box-shadow:0 4px 24px rgba(255,87,34,0.4),inset 0 1px 0 rgba(255,255,255,0.1);
  clip-path:polygon(0 0,calc(100% - 10px) 0,100% 100%,10px 100%);
}
.btn-primary:hover{transform:translateY(-3px);box-shadow:0 10px 36px rgba(255,87,34,0.55);}
.btn-outline{
  background:transparent;color:var(--neon);
  border:1.5px solid rgba(0,229,160,0.4);
  box-shadow:0 0 16px rgba(0,229,160,0.1);
}
.btn-outline:hover{background:rgba(0,229,160,0.07);box-shadow:0 0 30px rgba(0,229,160,0.25);}
.btn-gold{
  background:linear-gradient(135deg,var(--gold3),var(--gold2));
  color:#000;font-weight:800;
}
.btn-gold:hover{transform:translateY(-2px);box-shadow:0 8px 28px rgba(245,200,66,0.45);}
.btn-sm{padding:8px 16px;font-size:12px;letter-spacing:1.5px;border-radius:5px;}

/* ── CARDS ── */
.card{
  background:var(--card);
  border:1px solid var(--border2);
  border-radius:12px;padding:22px;
  position:relative;overflow:hidden;
}
.card-glow::before{
  content:'';position:absolute;top:-40px;left:-40px;
  width:160px;height:160px;border-radius:50%;
  background:radial-gradient(circle,rgba(245,200,66,0.06) 0%,transparent 70%);
  pointer-events:none;
}

/* ── LAYOUT ── */
.wrap{max-width:1280px;margin:0 auto;padding:0 28px;position:relative;z-index:1;}
.wrap-sm{max-width:560px;margin:0 auto;padding:0 24px;position:relative;z-index:1;}
.page{padding:32px 0 100px;}

/* ── SECTION HEADER ── */
.sec-eyebrow{
  display:inline-flex;align-items:center;gap:6px;
  font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:4px;text-transform:uppercase;
  color:var(--copper);background:rgba(224,123,57,0.09);border:1px solid rgba(224,123,57,0.25);
  padding:4px 12px;border-radius:4px;margin-bottom:8px;
}
.sec-title{font-family:'Bebas Neue';font-size:36px;letter-spacing:2px;color:var(--text);}
.sec-sub{color:var(--muted);font-size:13px;margin-top:3px;font-weight:500;}

/* ── TABS ── */
.tabs-wrap{
  display:flex;gap:4px;flex-wrap:wrap;margin-bottom:18px;
  padding:5px;background:var(--g3);border-radius:10px;
  border:1px solid var(--border3);
}
.tab{
  padding:7px 13px;border-radius:7px;cursor:pointer;
  font-family:'Rajdhani';font-weight:700;font-size:12px;letter-spacing:2px;text-transform:uppercase;
  white-space:nowrap;transition:all .15s;text-decoration:none;color:var(--muted);
}
.tab:hover{color:var(--text2);background:rgba(255,255,255,0.04);}
.tab.active{
  background:linear-gradient(135deg,rgba(245,200,66,0.18),rgba(224,123,57,0.1));
  border:1px solid rgba(245,200,66,0.3);color:var(--gold);
  box-shadow:0 0 12px rgba(245,200,66,0.08);
}

/* ── DAY LABELS ── */
.day-badge{
  display:inline-flex;align-items:center;gap:5px;
  font-family:'Rajdhani';font-weight:800;font-size:9px;letter-spacing:2.5px;text-transform:uppercase;
  padding:3px 10px;border-radius:100px;
}
.day-today{
  background:rgba(255,87,34,0.25);
  border:1px solid rgba(255,87,34,0.6);
  color:#ff8a65;
  animation:todayPulse 2s ease-in-out infinite;
  box-shadow:0 0 10px rgba(255,87,34,0.2);
}
@keyframes todayPulse{0%,100%{box-shadow:0 0 8px rgba(255,87,34,0.2)}50%{box-shadow:0 0 20px rgba(255,87,34,0.45)}}
.day-tomorrow{
  background:rgba(224,123,57,0.18);
  border:1px solid rgba(224,123,57,0.45);
  color:var(--copper);
}

/* ── MATCH CARDS ── */
.match-list{display:flex;flex-direction:column;gap:8px;}
.match-card{
  display:grid;
  grid-template-columns:1fr 200px 1fr 260px;
  align-items:center;
  background:var(--card2);
  border:1px solid var(--border3);
  border-radius:10px;overflow:hidden;
  transition:all .2s;position:relative;
}
.match-card:hover{
  border-color:rgba(255,255,255,0.09);
  transform:translateY(-1px);
  box-shadow:0 8px 30px rgba(0,0,0,0.5);
  background:linear-gradient(90deg,rgba(22,31,53,0.8),var(--card2));
}

/* Past games: grayed out */
.match-card.is-final{
  opacity:0.38;
  filter:saturate(0.3);
}
.match-card.is-final:hover{
  opacity:0.65;
  filter:saturate(0.5);
  transform:none;
}

.match-card.is-today{
  border-color:rgba(255,87,34,0.25);
  background:linear-gradient(90deg,rgba(255,87,34,0.05),var(--card2) 50%);
}
.match-card.is-live{
  background:linear-gradient(90deg,rgba(244,67,54,0.09),var(--card2) 50%);
  border-color:rgba(244,67,54,0.3);
}
.match-card.is-tipped{border-color:rgba(0,229,160,0.18);}

.mc-accent{position:absolute;left:0;top:0;bottom:0;width:3px;}
.acc-upcoming{background:linear-gradient(180deg,var(--sky),rgba(41,182,246,0.3));}
.acc-soon{background:linear-gradient(180deg,var(--copper),var(--fire));}
.acc-live{background:var(--live);animation:accPulse 1s ease-in-out infinite;}
.acc-final{background:rgba(61,79,110,0.3);}
.acc-tipped{background:linear-gradient(180deg,var(--neon),rgba(0,229,160,0.3));}
.acc-today{background:linear-gradient(180deg,var(--fire2),var(--copper));}
@keyframes accPulse{0%,100%{opacity:1}50%{opacity:0.2}}

.mc-home,.mc-away{
  padding:14px 18px 14px 22px;
  display:flex;align-items:center;gap:10px;
}
.mc-home{justify-content:flex-end;flex-direction:row-reverse;}
.mc-away{justify-content:flex-start;}
.mc-team-name{
  font-family:'Rajdhani';font-weight:700;font-size:16px;
  letter-spacing:.5px;text-transform:uppercase;white-space:nowrap;
}

.mc-mid{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:10px 4px;gap:4px;
}
.mc-score-row{display:flex;align-items:center;gap:5px;}
.mc-num{
  font-family:'Bebas Neue';font-size:38px;line-height:1;
  min-width:28px;text-align:center;letter-spacing:1px;
}
.mc-colon{font-family:'Bebas Neue';font-size:30px;color:var(--g5);line-height:1;}
.num-live{color:var(--live2);}
.num-final{color:var(--text);}
.num-up{color:var(--muted);font-size:20px;}

.status-badge{
  display:inline-flex;align-items:center;gap:4px;
  font-family:'Rajdhani';font-weight:700;font-size:9px;letter-spacing:2px;text-transform:uppercase;
  padding:3px 9px;border-radius:100px;
}
.sb-live{background:rgba(244,67,54,0.2);border:1px solid rgba(244,67,54,0.45);color:#ef9a9a;}
.sb-final{background:rgba(61,79,110,0.25);border:1px solid rgba(61,79,110,0.4);color:var(--muted);}
.sb-soon{background:rgba(224,123,57,0.2);border:1px solid rgba(224,123,57,0.4);color:var(--copper);}
.sb-up{background:rgba(41,182,246,0.12);border:1px solid rgba(41,182,246,0.25);color:var(--sky);}
.sb-halbzeit{background:rgba(245,200,66,0.18);border:1px solid rgba(245,200,66,0.4);color:var(--gold);}
.sb-nachspielzeit{background:rgba(244,67,54,0.25);border:1px solid rgba(244,67,54,0.55);color:#ffab91;}
.dot-blink{
  width:5px;height:5px;border-radius:50%;background:currentColor;
  animation:dotBlink 1s step-end infinite;
}
@keyframes dotBlink{0%,100%{opacity:1}50%{opacity:0}}

/* Big time display for today's games */
.mc-time-today{
  font-family:'Bebas Neue';font-size:28px;color:#ff8a65;letter-spacing:3px;line-height:1;
  text-shadow:0 0 16px rgba(255,87,34,0.4);
}
.mc-time{font-family:'Bebas Neue';font-size:20px;color:var(--text2);letter-spacing:2px;}
.mc-date{font-family:'Rajdhani';font-size:10px;font-weight:700;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;}
.mc-vs{font-family:'Bebas Neue';font-size:14px;letter-spacing:3px;color:var(--muted);}

.mc-action{padding:12px 16px;}
.tipp-row{display:flex;align-items:center;gap:5px;justify-content:flex-end;margin-top:4px;}
.score-in{
  width:42px;height:38px;
  background:var(--g3);border:1px solid rgba(255,255,255,0.1);
  color:#fff;border-radius:7px;text-align:center;
  font-family:'Bebas Neue';font-size:22px;
  -moz-appearance:textfield;appearance:none;transition:all .15s;
}
.score-in::-webkit-inner-spin-button,.score-in::-webkit-outer-spin-button{-webkit-appearance:none;}
.score-in:focus{outline:none;border-color:var(--gold);background:var(--g2);box-shadow:0 0 0 3px rgba(245,200,66,0.12);}
.score-sep{font-family:'Bebas Neue';font-size:20px;color:var(--muted);}
.tipp-btn{
  background:linear-gradient(135deg,var(--gold3),var(--gold2));
  color:#000;border:none;border-radius:6px;
  padding:7px 13px;font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;
  cursor:pointer;transition:all .2s;white-space:nowrap;
}
.tipp-btn:hover{transform:scale(1.05);box-shadow:0 4px 14px rgba(245,200,66,0.45);}

.tipp-saved{display:flex;flex-direction:column;align-items:flex-end;gap:3px;}
.saved-score{font-family:'Bebas Neue';font-size:18px;color:var(--neon);letter-spacing:1px;display:flex;align-items:center;gap:7px;}
.eval-label{font-family:'Rajdhani';font-size:11px;font-weight:700;letter-spacing:1px;}
.ev-perfekt{color:var(--gold);}
.ev-gut{color:var(--neon2);}
.ev-tendenz{color:var(--sky);}
.ev-falsch{color:var(--fire);}
.ev-open{color:var(--muted);}

.badge-locked{font-family:'Rajdhani';font-size:12px;font-weight:700;color:var(--live);display:flex;align-items:center;gap:5px;}
.badge-missed{font-family:'Rajdhani';font-size:12px;font-weight:700;color:var(--muted);}
.badge-warn{font-family:'Rajdhani';font-size:11px;font-weight:700;color:var(--copper);letter-spacing:.5px;}

/* ── LIVE BANNER ── */
.live-banner{
  background:linear-gradient(90deg,rgba(244,67,54,0.14),rgba(244,67,54,0.04));
  border:1px solid rgba(244,67,54,0.35);border-radius:10px;
  padding:11px 18px;margin-bottom:14px;
  display:flex;align-items:center;gap:14px;overflow:hidden;
  position:relative;
}
.live-banner::before{
  content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,rgba(244,67,54,0.05),transparent 40%,transparent 60%,rgba(244,67,54,0.05));
  animation:bannerScan 3s linear infinite;
}
@keyframes bannerScan{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.lb-label{
  font-family:'Bebas Neue';font-size:14px;letter-spacing:3px;color:var(--live);
  display:flex;align-items:center;gap:8px;flex-shrink:0;
}
.lb-items{display:flex;gap:24px;overflow:hidden;flex:1;}
.lb-item{font-family:'Rajdhani';font-weight:700;font-size:14px;white-space:nowrap;color:var(--text2);}
.lb-score{color:var(--live2);font-family:'Bebas Neue';font-size:17px;letter-spacing:1px;}

/* ── TODAY BANNER ── */
.today-banner{
  background:linear-gradient(90deg,rgba(255,87,34,0.1),rgba(255,87,34,0.02));
  border:1px solid rgba(255,87,34,0.3);border-radius:10px;
  padding:10px 18px;margin-bottom:14px;
  display:flex;align-items:center;gap:12px;
}
.today-banner-icon{font-size:20px;}
.today-banner-text{font-family:'Rajdhani';font-weight:700;font-size:14px;color:#ff8a65;letter-spacing:.5px;}
.today-banner-count{
  margin-left:auto;font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;color:var(--copper);
}

/* ── GRUPPE HEADER ── */
.gruppe-header{
  display:flex;align-items:center;gap:18px;padding-bottom:18px;margin-bottom:18px;
  border-bottom:1px solid var(--border3);
}
.gr-letter{
  font-family:'Bebas Neue';font-size:72px;line-height:1;
  background:linear-gradient(160deg,var(--gold3),var(--copper));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  min-width:52px;filter:drop-shadow(0 0 20px rgba(245,200,66,0.2));
}
.gr-pills{display:flex;gap:7px;flex-wrap:wrap;}
.gr-pill{
  display:flex;align-items:center;gap:6px;
  background:var(--g3);border:1px solid var(--border2);
  border-radius:6px;padding:5px 12px 5px 8px;
  font-family:'Rajdhani';font-weight:700;font-size:12px;letter-spacing:.5px;
  transition:all .15s;
}
.gr-pill.my-team{
  background:rgba(245,200,66,0.09);border-color:rgba(245,200,66,0.35);color:var(--gold);
  box-shadow:0 0 10px rgba(245,200,66,0.06);
}

/* ── STATS ── */
.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px;}
.stat-box{
  background:var(--card);border:1px solid var(--border3);border-radius:12px;
  padding:18px 14px;text-align:center;position:relative;overflow:hidden;
}
.stat-box::after{
  content:'';position:absolute;bottom:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--gold),transparent);opacity:.25;
}
.stat-num{
  font-family:'Bebas Neue';font-size:52px;line-height:1;
  background:linear-gradient(135deg,var(--gold3),var(--copper));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  letter-spacing:2px;
}
.stat-label{font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-top:3px;}

/* ── PROGRESS ── */
.prog-track{height:5px;background:var(--g3);border-radius:3px;overflow:hidden;}
.prog-fill{
  height:100%;border-radius:3px;
  background:linear-gradient(90deg,var(--neon2),var(--neon));
  transition:width 1.2s cubic-bezier(.34,1.56,.64,1);
  box-shadow:0 0 8px rgba(0,229,160,0.4);
}

/* ── PROFILE CARD ── */
.profile-card{
  background:var(--card);border:1px solid var(--border2);border-radius:12px;padding:22px;text-align:center;
}
.profile-head{
  width:80px;height:80px;border-radius:10px;image-rendering:pixelated;
  border:2px solid transparent;
  background:linear-gradient(var(--card),var(--card)) padding-box,
              linear-gradient(135deg,var(--gold3),var(--copper)) border-box;
}
.profile-name{font-family:'Bebas Neue';font-size:26px;letter-spacing:3px;margin-top:10px;}
.profile-sub{font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--neon2);margin-top:2px;}
.fav-row{
  display:flex;align-items:center;gap:9px;
  background:rgba(245,200,66,0.06);border:1px solid rgba(245,200,66,0.18);
  border-radius:8px;padding:9px 13px;margin-top:14px;text-align:left;
}
.fav-name{font-family:'Rajdhani';font-weight:800;font-size:15px;color:var(--gold);letter-spacing:.5px;}
.fav-sub{font-size:11px;color:var(--muted);font-weight:600;}

/* ── LEADERBOARD ── */
.lb-search-wrap{position:relative;margin-bottom:14px;}
.lb-search{
  width:100%;padding:11px 16px 11px 44px;
  background:var(--g3);border:1px solid var(--border2);
  border-radius:10px;color:var(--text);font-family:'Exo 2';font-size:14px;font-weight:500;
  outline:none;transition:all .2s;
}
.lb-search:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(245,200,66,0.08);}
.lb-search::placeholder{color:var(--muted);}
.lb-search-icon{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:17px;pointer-events:none;}

.lb-head-row{
  display:grid;grid-template-columns:56px 1fr 80px 110px;
  gap:12px;padding:6px 16px;
  font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;text-transform:uppercase;
  color:var(--muted);margin-bottom:8px;
}
.lb-row{
  display:grid;grid-template-columns:56px 1fr 80px 110px;
  align-items:center;gap:12px;
  padding:12px 16px;border-radius:10px;border:1px solid transparent;
  margin-bottom:6px;transition:all .2s;cursor:default;
}
.lb-row:hover{background:rgba(255,255,255,0.025);border-color:var(--border2);}
.lb-row.rk-1{background:linear-gradient(90deg,rgba(245,200,66,0.1),rgba(224,123,57,0.04));border-color:rgba(245,200,66,0.28);}
.lb-row.rk-2{background:rgba(184,204,224,0.04);border-color:rgba(184,204,224,0.15);}
.lb-row.rk-3{background:rgba(205,139,74,0.06);border-color:rgba(205,139,74,0.2);}
.lb-row.rk-me{border-color:rgba(41,182,246,0.4);background:rgba(41,182,246,0.04);}
.lb-row.lb-hidden{display:none;}

.lb-rank{font-family:'Bebas Neue';font-size:30px;text-align:center;line-height:1;color:var(--muted);}
.lb-rank.r1{color:var(--r1);filter:drop-shadow(0 0 8px rgba(245,200,66,0.5));}
.lb-rank.r2{color:var(--r2);}
.lb-rank.r3{color:var(--r3);}

.lb-user-cell{display:flex;align-items:center;gap:11px;}
.lb-av{width:32px;height:32px;border-radius:6px;image-rendering:pixelated;}
.lb-username{font-family:'Rajdhani';font-weight:800;font-size:16px;letter-spacing:.5px;}
.lb-team-sm{font-size:12px;color:var(--muted);font-weight:600;display:flex;align-items:center;gap:4px;}
.lb-me-chip{
  font-family:'Rajdhani';font-weight:800;font-size:9px;letter-spacing:2px;
  background:rgba(41,182,246,0.15);color:var(--sky);border:1px solid rgba(41,182,246,0.3);
  padding:2px 8px;border-radius:4px;text-transform:uppercase;
}
.lb-tipps-cell{font-family:'Rajdhani';font-weight:700;font-size:14px;color:var(--muted);text-align:center;}
.lb-pts{
  font-family:'Bebas Neue';font-size:26px;text-align:right;letter-spacing:1px;
  background:linear-gradient(135deg,var(--gold3),var(--copper));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}

/* Podium */
.podium-wrap{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:32px;}
.podium-card{border-radius:12px;padding:22px 14px;text-align:center;position:relative;overflow:hidden;border:1px solid;}
.po-1{background:linear-gradient(160deg,rgba(245,200,66,0.14),rgba(224,123,57,0.06));border-color:rgba(245,200,66,0.38);order:1;}
.po-1::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--gold3),transparent);}
.po-2{background:rgba(184,204,224,0.04);border-color:rgba(184,204,224,0.2);order:0;margin-top:24px;}
.po-3{background:rgba(205,139,74,0.06);border-color:rgba(205,139,74,0.2);order:2;margin-top:38px;}
.po-medal{font-size:38px;margin-bottom:10px;}
.po-head{width:56px;height:56px;border-radius:8px;image-rendering:pixelated;border:2px solid rgba(245,200,66,0.3);margin:0 auto 10px;}
.po-name{font-family:'Bebas Neue';font-size:20px;letter-spacing:2px;}
.po-pts{font-family:'Bebas Neue';font-size:30px;letter-spacing:1px;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-top:6px;}

/* ── PUNKTE PAGE ── */
.pts-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px;}
.pts-row{
  display:flex;align-items:center;justify-content:space-between;
  background:var(--g3);border:1px solid var(--border2);border-radius:8px;padding:15px 18px;gap:12px;
}
.pts-row.top{border-color:rgba(0,229,160,0.3);background:rgba(0,229,160,0.04);}
.pts-label{font-weight:700;font-size:14px;}
.pts-sub{font-size:12px;color:var(--muted);margin-top:2px;font-weight:500;}
.pts-val{font-family:'Bebas Neue';font-size:28px;letter-spacing:1px;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;white-space:nowrap;}
.pts-val.neg{background:linear-gradient(135deg,var(--fire2),var(--fire));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}

/* ── LOGIN / REGISTER ── */
.auth-input-wrap{margin-bottom:14px;text-align:left;}
.auth-label{
  display:block;font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:2px;
  text-transform:uppercase;color:var(--muted);margin-bottom:6px;
}
.auth-input{
  width:100%;padding:13px 16px;
  background:var(--g3);border:1px solid var(--border2);
  border-radius:8px;color:var(--text);font-family:'Exo 2';font-size:15px;font-weight:500;
  outline:none;transition:all .2s;
}
.auth-input:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(245,200,66,0.08);}
.auth-input::placeholder{color:var(--muted);}
.alert-fire{background:rgba(255,87,34,0.08);border:1px solid rgba(255,87,34,0.3);color:#ff8a65;}

/* ── REGISTER (alt) ── */
.code-display{
  font-family:'Bebas Neue';font-size:80px;letter-spacing:24px;
  color:var(--neon);text-align:center;padding:26px 20px;
  background:rgba(0,229,160,0.05);border:2px solid rgba(0,229,160,0.28);border-radius:12px;
  margin:22px 0;animation:codeGlow 2s ease-in-out infinite;
}
@keyframes codeGlow{0%,100%{text-shadow:0 0 20px rgba(0,229,160,0.4)}50%{text-shadow:0 0 50px rgba(0,229,160,0.9),0 0 80px rgba(0,229,160,0.3)}}
.step-card{background:var(--g3);border:1px solid var(--border2);border-radius:10px;padding:18px;line-height:2.4;font-size:14px;}
.step-card code{background:rgba(41,182,246,0.12);color:var(--sky);border:1px solid rgba(41,182,246,0.25);border-radius:5px;padding:2px 10px;font-size:12px;font-family:'Courier New',monospace;}
.spinner{width:36px;height:36px;margin:14px auto;border:3px solid rgba(255,255,255,0.07);border-top-color:var(--neon);border-radius:50%;animation:spin .8s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.alert{padding:13px 18px;border-radius:8px;margin-bottom:12px;font-size:14px;font-weight:600;}
.alert-neon{background:rgba(0,229,160,0.07);border:1px solid rgba(0,229,160,0.28);color:var(--neon);}
.alert-gold{background:rgba(245,200,66,0.07);border:1px solid rgba(245,200,66,0.22);color:var(--gold);text-align:center;}
.prog-anim{height:3px;background:var(--g3);border-radius:2px;margin-top:14px;overflow:hidden;}
.prog-anim-fill{height:100%;width:0%;background:linear-gradient(90deg,var(--neon2),var(--neon));animation:prog 60s linear forwards;border-radius:2px;}
@keyframes prog{to{width:100%}}

/* ── TEAM CHOOSER — FLAG CARDS ── */
.team-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(152px,1fr));gap:12px;}

.team-btn{
  position:relative;overflow:hidden;
  border:1px solid rgba(255,255,255,0.1);border-radius:11px;
  padding:0;cursor:pointer;min-height:140px;
  display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
  font-family:inherit;transition:transform .2s ease,box-shadow .2s ease,border-color .2s;
  box-shadow:0 4px 20px rgba(0,0,0,0.6);
  background:#0a0e1a;
}

/* Flag fills the entire card background */
.team-btn-flag-bg{
  position:absolute;inset:0;
  background-size:cover;background-position:center;background-repeat:no-repeat;
  transition:transform .3s ease,filter .3s ease;
  filter:brightness(0.55) saturate(1.1);
}
.team-btn:hover .team-btn-flag-bg{
  transform:scale(1.08);
  filter:brightness(0.75) saturate(1.3);
}

/* Bottom gradient for text readability */
.team-btn-overlay{
  position:absolute;inset:0;
  background:linear-gradient(180deg,
    transparent 0%,
    transparent 40%,
    rgba(0,0,0,0.45) 70%,
    rgba(0,0,0,0.88) 100%
  );
  z-index:1;
}

/* Subtle gold border glow on hover */
.team-btn:hover{
  transform:translateY(-6px) scale(1.04);
  box-shadow:0 16px 40px rgba(0,0,0,0.8),0 0 0 2px rgba(245,200,66,0.5);
  border-color:rgba(245,200,66,0.4);
}

.team-btn-group-badge{
  position:absolute;top:10px;right:10px;z-index:3;
  font-family:'Bebas Neue';font-size:13px;letter-spacing:2px;
  background:rgba(0,0,0,0.6);
  color:rgba(255,255,255,0.7);
  border:1px solid rgba(255,255,255,0.15);
  border-radius:5px;padding:2px 8px;
  backdrop-filter:blur(4px);
}

.team-btn-name{
  position:relative;z-index:3;
  color:#fff;
  font-family:'Rajdhani';font-weight:800;font-size:14px;
  letter-spacing:.5px;text-transform:uppercase;
  text-shadow:0 1px 10px rgba(0,0,0,1),0 0 20px rgba(0,0,0,0.8);
  padding:0 10px;text-align:center;line-height:1.2;
  margin-bottom:12px;
}

/* ── ENTER ANIMATIONS ── */
.fade-in{opacity:0;transform:translateY(16px);animation:fadeIn .45s ease forwards;}
.d1{animation-delay:.05s}.d2{animation-delay:.1s}.d3{animation-delay:.15s}
.d4{animation-delay:.2s}.d5{animation-delay:.25s}.d6{animation-delay:.3s}
@keyframes fadeIn{to{opacity:1;transform:translateY(0)}}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:6px;}
::-webkit-scrollbar-track{background:var(--g1);}
::-webkit-scrollbar-thumb{background:rgba(245,200,66,0.2);border-radius:3px;}
::-webkit-scrollbar-thumb:hover{background:rgba(245,200,66,0.4);}

/* ── DIVIDER ── */
.divider{height:1px;background:var(--border2);margin:22px 0;}

/* ── RESPONSIVE ── */
@media(max-width:1000px){
  .match-card{grid-template-columns:1fr 160px 1fr;}
  .match-card .mc-action{display:none;}
}
@media(max-width:700px){
  .navbar{padding:0 14px;}
  .nb-links{display:none;}
  .stats-grid{grid-template-columns:repeat(3,1fr);}
  .match-card{grid-template-columns:1fr 110px 1fr;}
  .mc-team-name{font-size:13px;}
  .mc-num{font-size:28px;}
  .pts-grid{grid-template-columns:1fr;}
  .podium-wrap{gap:7px;}
  .po-2,.po-3{margin-top:0;}
  .lb-row{grid-template-columns:44px 1fr 100px;}
  .lb-tipps-cell{display:none;}
}
</style>
"""

BASE_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>WM 2026 — GrieferGames Tipp-Portal</title>
""" + BASE_CSS + """
</head>
<body>
"""

# ==========================================
# NAVBAR
# ==========================================
def get_navbar(username, points, lieblingsteam, active_page="dashboard"):
    team_code = TEAM_CODE.get(lieblingsteam, "")
    team_flag = flag_img(team_code, 18) if team_code else ""
    pages = [
        ("dashboard", "/dashboard", "⚽ Tipps"),
        ("leaderboard", "/leaderboard", "🏆 Rangliste"),
        ("punkte", "/punkte", "📋 Regeln"),
    ]
    if username == ADMIN_USER:
        pages.append(("adminpanel", "/adminpanel", "🛠️ Admin"))
    links = ""
    for pid, url, label in pages:
        ac = "active" if active_page == pid else ""
        links += f'<a href="{url}" class="nb-link {ac}">{label}</a>'
    return f"""
    <nav class="navbar">
      <div class="nb-logo-wrap">
        <div class="nb-icon">⚽</div>
        <span class="nb-title">WM 2026</span>
      </div>
      <div class="nb-sep"></div>
      <div class="nb-links">{links}</div>
      <div class="nb-right">
        {team_flag}
        <img class="nb-avatar" src="https://mc-heads.net/avatar/{username}/32" alt="" onerror="this.style.display='none'">
        <span class="nb-user">{username}</span>
        <div class="nb-coins"><div class="coin-dot">◈</div>{points:,}</div>
        <a href="/logout" class="nb-logout">Abmelden</a>
      </div>
    </nav>
    """

# ==========================================
# HOME
# ==========================================
HOME_HTML = BASE_HTML + """
<canvas id="pcanvas" style="position:fixed;inset:0;z-index:0;pointer-events:none;"></canvas>

<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;position:relative;z-index:1;">
  <div class="hero">
    <div class="hero-field"></div>
    <div class="hero-chip fade-in">⚡ GrieferGames × FIFA World Cup 2026</div>
    <div style="position:relative;display:inline-block;">
      <div class="hero-h1 fade-in d1">
        <span class="hero-h1-inner">WM 2026<br>TIPP<br>PORTAL</span>
      </div>
    </div>
    <p class="hero-sub fade-in d2">Tippe alle 72 Gruppenspiele der Weltmeisterschaft und beweise, dass du der beste Fußball-Prophet auf GrieferGames bist.</p>
    <div class="hero-ctas fade-in d3">
      <a href="/login" class="btn btn-primary">⚡ Jetzt einloggen</a>
      <a href="#features" class="btn btn-outline">↓ Mehr erfahren</a>
    </div>
  </div>

  <div id="features" class="wrap" style="padding-bottom:100px;max-width:960px;">
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px;">
      <div class="card fade-in d1" style="border-color:rgba(0,229,160,0.14);text-align:center;padding:32px 16px;">
        <div style="font-size:44px;margin-bottom:10px;">🌍</div>
        <div style="font-family:'Bebas Neue';font-size:52px;line-height:1;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:2px;">48</div>
        <div style="font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:3px;color:var(--muted);text-transform:uppercase;margin-top:4px;">Teams · 12 Gruppen</div>
      </div>
      <div class="card fade-in d2" style="border-color:rgba(245,200,66,0.14);text-align:center;padding:32px 16px;">
        <div style="font-size:44px;margin-bottom:10px;">⚽</div>
        <div style="font-family:'Bebas Neue';font-size:52px;line-height:1;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:2px;">72</div>
        <div style="font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:3px;color:var(--muted);text-transform:uppercase;margin-top:4px;">Spiele Gruppenphase</div>
      </div>
      <div class="card fade-in d3" style="border-color:rgba(255,87,34,0.14);text-align:center;padding:32px 16px;">
        <div style="font-size:44px;margin-bottom:10px;">🏆</div>
        <div style="font-family:'Bebas Neue';font-size:52px;line-height:1;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:2px;">1K</div>
        <div style="font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:3px;color:var(--muted);text-transform:uppercase;margin-top:4px;">Punkte pro Tipp Max</div>
      </div>
    </div>

    <div class="card fade-in d4" style="border-color:rgba(245,200,66,0.14);padding:28px 32px;">
      <div style="font-family:'Bebas Neue';font-size:18px;letter-spacing:4px;color:var(--muted);margin-bottom:20px;text-align:center;">PUNKTESYSTEM ÜBERSICHT</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;text-align:center;">
        <div>
          <div style="font-family:'Bebas Neue';font-size:48px;line-height:1;color:var(--neon);letter-spacing:2px;text-shadow:0 0 20px rgba(0,229,160,0.4);">1.000</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:5px;">🎯 Perfekt</div>
        </div>
        <div>
          <div style="font-family:'Bebas Neue';font-size:48px;line-height:1;color:var(--gold);letter-spacing:2px;">500</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:5px;">⚡ Tordifferenz</div>
        </div>
        <div>
          <div style="font-family:'Bebas Neue';font-size:48px;line-height:1;color:var(--sky);letter-spacing:2px;">200</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:5px;">✅ Tendenz</div>
        </div>
        <div>
          <div style="font-family:'Bebas Neue';font-size:48px;line-height:1;color:var(--fire);letter-spacing:2px;">-50</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:5px;">💸 Einsatz</div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const cv = document.getElementById('pcanvas');
const cx = cv.getContext('2d');
cv.width = window.innerWidth; cv.height = window.innerHeight;
window.addEventListener('resize',()=>{cv.width=window.innerWidth;cv.height=window.innerHeight;});
const EMOJIS=['⚽','🏆','⭐','🔥','🌍'];
const pts=Array.from({length:22},()=>({
  x:Math.random()*cv.width, y:Math.random()*cv.height,
  vx:(Math.random()-.5)*.35, vy:-(0.18+Math.random()*.5),
  size:12+Math.random()*20, op:0.03+Math.random()*.06,
  e:EMOJIS[Math.floor(Math.random()*EMOJIS.length)],
  r:Math.random()*Math.PI*2, rs:(Math.random()-.5)*.012
}));
(function anim(){
  cx.clearRect(0,0,cv.width,cv.height);
  pts.forEach(p=>{
    p.y+=p.vy; p.x+=p.vx; p.r+=p.rs;
    if(p.y<-50){p.y=cv.height+50;p.x=Math.random()*cv.width;}
    cx.save();cx.globalAlpha=p.op;cx.font=p.size+'px serif';
    cx.translate(p.x,p.y);cx.rotate(p.r);
    cx.fillText(p.e,-p.size/2,p.size/2);cx.restore();
  });
  requestAnimationFrame(anim);
})();
</script>
</body></html>
"""

# ==========================================
# ROUTES
# ==========================================
@app.route('/')
def home():
    if "username" in session:
        return redirect(url_for('dashboard'))
    return HOME_HTML

@app.route('/login', methods=['GET', 'POST'])
def login():
    if "username" in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or "").strip()
        password = request.form.get('password') or ""

        user_entry = user_db.get(username)
        if user_entry and verify_password(password, user_entry.get("salt"), user_entry.get("pw_hash")):
            session["username"] = username
            session.permanent = True
            if username != ADMIN_USER and not user_entry.get("lieblingsteam"):
                return redirect(url_for('choose_team'))
            return redirect(url_for('dashboard'))
        else:
            error = "❌ Minecraft-Name oder Passwort falsch."

    error_html = f'<div class="alert alert-fire">{error}</div>' if error else ""

    return BASE_HTML + f"""
    <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;position:relative;z-index:1;">
      <div style="width:100%;max-width:440px;">
        <div class="card fade-in" style="border-color:rgba(0,229,160,0.18);">
          <div style="text-align:center;margin-bottom:22px;">
            <div style="font-size:52px;margin-bottom:12px;">🔐</div>
            <div class="hero-chip" style="display:inline-flex;margin-bottom:14px;">WM 2026 Login</div>
            <h2 style="font-family:'Bebas Neue';font-size:36px;letter-spacing:4px;">ANMELDEN</h2>
          </div>
          {error_html}
          <form method="POST">
            <div class="auth-input-wrap">
              <label class="auth-label">Minecraft-Name</label>
              <input type="text" name="username" class="auth-input" placeholder="z.B. Lattenrost1234" required autofocus autocomplete="username">
            </div>
            <div class="auth-input-wrap">
              <label class="auth-label">Passwort</label>
              <input type="password" name="password" class="auth-input" placeholder="••••••••" required autocomplete="current-password">
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;margin-top:6px;">⚡ Einloggen</button>
          </form>
          <div style="margin-top:18px;text-align:center;font-size:12px;color:var(--muted);font-family:'Rajdhani';font-weight:600;letter-spacing:.5px;line-height:1.8;">
            🔑 Noch keinen Zugang? Wende dich an <strong style="color:var(--text2);">{ADMIN_USER}</strong> — er vergibt dir deinen Minecraft-Namen und ein Passwort.
          </div>
        </div>
      </div>
    </div>
    </body></html>
    """

@app.route('/choose_team', methods=['GET','POST'])
def choose_team():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        return redirect(url_for('home'))
    if request.method == 'POST':
        team_name = request.form.get('team')
        user_db[username]["lieblingsteam"] = team_name
        save_data()
        return redirect(url_for('dashboard'))

    groups_html = ""
    for gruppe_key, gruppe_data in WM_GRUPPEN.items():
        teams_html = ""
        for team in gruppe_data["teams"]:
            code = team['code']
            special_map = {"sco": "gb-sct", "eng": "gb-eng"}
            flag_code = special_map.get(code, code)
            bg_url = f"https://flagcdn.com/h120/{flag_code}.png"

            teams_html += f"""
            <button type="submit" name="team" value="{team['name']}" class="team-btn">
              <div class="team-btn-flag-bg" style="background-image:url('{bg_url}');"></div>
              <div class="team-btn-overlay"></div>
              <span class="team-btn-group-badge">GR. {gruppe_key}</span>
              <span class="team-btn-name">{team['name']}</span>
            </button>"""

        groups_html += f"""
        <div style="margin-bottom:30px;" class="fade-in">
          <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px;">
            <span style="font-family:'Bebas Neue';font-size:44px;line-height:1;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">{gruppe_key}</span>
            <div style="flex:1;height:1px;background:linear-gradient(90deg,rgba(245,200,66,0.3),transparent);"></div>
          </div>
          <div class="team-grid">{teams_html}</div>
        </div>"""

    return BASE_HTML + f"""
    <div class="page">
      <div class="wrap">
        <div style="text-align:center;margin-bottom:52px;" class="fade-in">
          <div class="hero-chip" style="display:inline-flex;margin-bottom:16px;">🌍 Teamauswahl</div>
          <h1 style="font-family:'Bebas Neue';font-size:clamp(48px,8vw,96px);line-height:.88;
               background:linear-gradient(160deg,#fff,var(--gold3),var(--copper));
               -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:18px;letter-spacing:2px;">
            WEM DRÜCKST DU<br>DIE DAUMEN?
          </h1>
          <p style="color:var(--text2);font-size:15px;max-width:400px;margin:0 auto;">
            Wähle dein Lieblingsteam — du kannst es danach jederzeit ändern.
          </p>
        </div>
        <form method="POST">{groups_html}</form>
      </div>
    </div>
    </body></html>"""
# ==========================================
# DASHBOARD / GRUPPE VIEW
# ==========================================
def render_gruppe_page(username, gruppe_id, active_page="dashboard"):
    user_info = user_db[username]
    points = user_info["points"]
    lieblingsteam = user_info.get("lieblingsteam")
    tipps = user_info.get("tipps", {})
    navbar = get_navbar(username, points, lieblingsteam, active_page)
    gruppe_data = WM_GRUPPEN[gruppe_id]
    mein_team = next((t for t in ALLE_TEAMS if t["name"] == lieblingsteam), None)
    total_spiele = sum(len(g["spiele"]) for g in WM_GRUPPEN.values())
    getippt = len(tipps)

    # Tabs
    tabs_html = ""
    for g in WM_GRUPPEN.keys():
        ac = "active" if g == gruppe_id else ""
        tabs_html += f'<a href="/gruppe/{g}" class="tab {ac}">Gr.&nbsp;{g}</a>'

    # Team Pills
    team_pills = ""
    for t in gruppe_data["teams"]:
        is_mine = (t["name"] == lieblingsteam)
        mine_cls = "my-team" if is_mine else ""
        team_pills += f'<span class="gr-pill {mine_cls}">{flag_img(t["code"],18)} {t["name"]}</span>'

    # Live Banner (alle Gruppen, alle aktiven Spiele)
    laufende = []
    for g_data in WM_GRUPPEN.values():
        for sp in g_data["spiele"]:
            st = get_spiel_status(sp)
            if st in ("live", "halbzeit", "nachspielzeit"):
                sc = get_live_score(sp["id"])
                score_txt = f"{sc['heim']}:{sc['gast']}" if sc and sc.get('heim') is not None else "?:?"
                laufende.append((sp['heim'], score_txt, sp['gast'], st))

    live_banner = ""
    if laufende:
        items = ""
        for h, s, g, st in laufende:
            extra = ""
            if st == "halbzeit":
                extra = ' <span style="color:var(--gold);">(HZ)</span>'
            elif st == "nachspielzeit":
                extra = ' <span style="color:#ffab91;">(NSZ)</span>'
            items += f'<span class="lb-item">{h} <span class="lb-score">{s}</span> {g}{extra}</span>'
        live_banner = f"""
        <div class="live-banner fade-in">
          <div class="lb-label"><div class="dot-blink"></div> 🔴 LIVE JETZT</div>
          <div class="lb-items">{items}</div>
        </div>"""

    # Today's games in this group
    heute = datetime.date.today()
    heute_spiele_count = sum(
        1 for sp in gruppe_data["spiele"]
        if datetime.datetime.strptime(sp["datum"], "%d.%m.%Y").date() == heute
    )

    today_banner = ""
    if heute_spiele_count > 0 and not laufende:
        today_banner = f"""
        <div class="today-banner fade-in">
          <span class="today-banner-icon">🗓️</span>
          <span class="today-banner-text">Heute spielen <strong>{heute_spiele_count} Team{'s' if heute_spiele_count > 1 else ''}</strong> in dieser Gruppe!</span>
          <span class="today-banner-count">{heute.strftime('%d.%m.')}</span>
        </div>"""

    # Match Cards
    spiele_html = ""
    for i, spiel in enumerate(gruppe_data["spiele"]):
        sid = spiel["id"]
        tipp = tipps.get(sid)
        status = get_spiel_status(spiel)
        live_score = get_live_score(sid)
        min_bis = minuten_bis_spiel(spiel)
        erlaubt = (status == "upcoming")
        nachspielzeit_min = live_scores_cache.get(sid, {}).get("nachspielzeit", 0)

        heim_code = TEAM_CODE.get(spiel["heim"], "")
        gast_code = TEAM_CODE.get(spiel["gast"], "")

        day_label, day_css = get_day_label(spiel)

        card_extra = ""
        acc_cls = "acc-upcoming"

        if status in ("live", "halbzeit", "nachspielzeit"):
            card_extra = "is-live"
            acc_cls = "acc-live"
        elif status == "final":
            card_extra = "is-final"
            acc_cls = "acc-final"
        elif day_label == "HEUTE":
            card_extra = "is-today"
            acc_cls = "acc-today"
        elif tipp:
            card_extra = "is-tipped"
            acc_cls = "acc-tipped"
        else:
            acc_cls = "acc-upcoming"

        # Center block — Status-Anzeige
        if status in ("live", "halbzeit", "nachspielzeit", "final") and live_score and live_score.get("heim") is not None:
            if status == "live":
                num_cls = "num-live"
                chip = f'<div class="status-badge sb-live"><div class="dot-blink"></div> LIVE</div>'
            elif status == "halbzeit":
                num_cls = "num-live"
                chip = f'<div class="status-badge sb-halbzeit">⏸ HALBZEIT</div>'
            elif status == "nachspielzeit":
                num_cls = "num-live"
                nsz_txt = f" +{nachspielzeit_min}'" if nachspielzeit_min else ""
                chip = f'<div class="status-badge sb-nachspielzeit"><div class="dot-blink"></div> NACHSPIELZEIT{nsz_txt}</div>'
            else:
                num_cls = "num-final"
                chip = f'<div class="status-badge sb-final">ABPFIFF</div>'
            center_html = f"""
            <div class="mc-mid">
              {chip}
              <div class="mc-score-row">
                <span class="mc-num {num_cls}">{live_score["heim"]}</span>
                <span class="mc-colon">:</span>
                <span class="mc-num {num_cls}">{live_score["gast"]}</span>
              </div>
            </div>"""
        elif status in ("live", "halbzeit", "nachspielzeit", "final"):
            if status == "live":
                chip = f'<div class="status-badge sb-live"><div class="dot-blink"></div> LIVE</div>'
            elif status == "halbzeit":
                chip = f'<div class="status-badge sb-halbzeit">⏸ HALBZEIT</div>'
            elif status == "nachspielzeit":
                chip = f'<div class="status-badge sb-nachspielzeit"><div class="dot-blink"></div> NACHSPIELZEIT</div>'
            else:
                chip = f'<div class="status-badge sb-final">ABPFIFF</div>'
            center_html = f'<div class="mc-mid">{chip}<div class="mc-vs">?:?</div></div>'
        elif day_label == "HEUTE":
            center_html = f"""<div class="mc-mid">
              <div class="day-badge day-today">🔥 HEUTE</div>
              <div class="mc-time-today">{spiel['uhrzeit']}</div>
              <div class="mc-vs">VS</div>
            </div>"""
        elif day_label == "MORGEN":
            center_html = f"""<div class="mc-mid">
              <div class="day-badge day-tomorrow">📅 MORGEN</div>
              <div class="mc-time">{spiel['uhrzeit']}</div>
              <div class="mc-vs">VS</div>
            </div>"""
        else:
            center_html = f"""<div class="mc-mid">
              <div class="mc-time">{spiel['uhrzeit']}</div>
              <div class="mc-date">{spiel['datum']}</div>
              <div class="mc-vs">VS</div>
            </div>"""

        # Action block
        if tipp:
            td = tipp if isinstance(tipp, dict) else {"heim": "?", "gast": "?"}
            punkte_key = tipp.get("punkte_result") if isinstance(tipp, dict) else None
            eval_html = ""
            if status == "final" and live_score and live_score.get("heim") is not None:
                if punkte_key == "perfekt":
                    eval_html = '<span class="eval-label ev-perfekt">🎯 Perfekt! +1000 ◈</span>'
                elif punkte_key == "tendenz_tor":
                    eval_html = '<span class="eval-label ev-gut">⚡ Tordiff! +500 ◈</span>'
                elif punkte_key == "tendenz":
                    eval_html = '<span class="eval-label ev-tendenz">✅ Tendenz! +200 ◈</span>'
                elif punkte_key == "falsch":
                    eval_html = '<span class="eval-label ev-falsch">❌ Leider falsch</span>'
                else:
                    eval_html = '<span class="eval-label ev-open">— Ausstehend</span>'
            action_html = f"""
            <div class="mc-action">
              <div class="tipp-saved">
                <div class="saved-score">✅ {td["heim"]} : {td["gast"]}</div>
                {eval_html}
              </div>
            </div>"""
        elif status in ("live", "halbzeit", "nachspielzeit"):
            action_html = '<div class="mc-action"><div class="badge-locked">🔴 Läuft gerade</div></div>'
        elif status == "final":
            action_html = '<div class="mc-action"><div class="badge-missed">— Kein Tipp</div></div>'
        elif not erlaubt:
            action_html = '<div class="mc-action"><div class="badge-locked">🔒 Gesperrt</div></div>'
        else:
            btn_label = "Tippen (−50◈)"
            if day_label == "HEUTE":
                btn_label = "🔥 Heute (−50◈)"
            action_html = f"""
            <div class="mc-action">
              <form action="/submittipp" method="POST">
                <input type="hidden" name="spiel_id" value="{sid}">
                <input type="hidden" name="redirect_gruppe" value="{gruppe_id}">
                <div class="tipp-row">
                  <input type="number" name="tipp_heim" min="0" max="20" class="score-in" placeholder="0" required>
                  <span class="score-sep">:</span>
                  <input type="number" name="tipp_gast" min="0" max="20" class="score-in" placeholder="0" required>
                  <button type="submit" class="tipp-btn">{btn_label}</button>
                </div>
              </form>
            </div>"""

        delay_cls = f"d{min(i+1, 6)}"
        spiele_html += f"""
        <div class="match-card {card_extra} fade-in {delay_cls}" id="spiel-{sid}">
          <div class="mc-accent {acc_cls}"></div>
          <div class="mc-home">
            {flag_img(heim_code, 24)}
            <span class="mc-team-name">{spiel['heim']}</span>
          </div>
          {center_html}
          <div class="mc-away">
            {flag_img(gast_code, 24)}
            <span class="mc-team-name">{spiel['gast']}</span>
          </div>
          {action_html}
        </div>"""

    # Profile sidebar
    fav_team_html = ""
    if mein_team:
        fav_team_html = f"""
        <div class="fav-row">
          {flag_img(mein_team['code'], 30)}
          <div>
            <div class="fav-name">{mein_team['name']}</div>
            <div class="fav-sub">Gruppe {mein_team['gruppe']} · Mein Favorit</div>
          </div>
          <a href="/choose_team" style="margin-left:auto;font-size:11px;color:var(--muted);text-decoration:none;font-family:'Rajdhani';font-weight:700;letter-spacing:1px;">ÄNDERN</a>
        </div>"""

    pct = int(getippt / total_spiele * 100) if total_spiele > 0 else 0

    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap">
        <div style="display:grid;grid-template-columns:280px 1fr;gap:18px;margin-bottom:32px;align-items:start;" class="fade-in">
          <div class="profile-card">
            <img class="profile-head" src="https://mc-heads.net/avatar/{username}/80" alt="{username}" onerror="this.style.opacity='0.3'">
            <div class="profile-name">{username}</div>
            <div class="profile-sub">GrieferGames</div>
            {fav_team_html}
          </div>
          <div>
            <div class="stats-grid">
              <div class="stat-box">
                <div class="stat-num">{points:,}</div>
                <div class="stat-label">◈ Punkte</div>
              </div>
              <div class="stat-box">
                <div class="stat-num">{getippt}</div>
                <div class="stat-label">⚽ Tipps</div>
              </div>
              <div class="stat-box">
                <div class="stat-num">{total_spiele - getippt}</div>
                <div class="stat-label">📋 Offen</div>
              </div>
            </div>
            <div class="card" style="padding:16px 18px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <div style="font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;">Tipp-Fortschritt</div>
                <div style="font-family:'Bebas Neue';font-size:20px;letter-spacing:2px;color:var(--neon);">{pct}%</div>
              </div>
              <div style="font-size:13px;color:var(--text2);margin-bottom:8px;font-weight:600;">{getippt} / {total_spiele} Spiele getippt</div>
              <div class="prog-track"><div class="prog-fill" style="width:{pct}%;"></div></div>
            </div>
          </div>
        </div>

        <div style="margin-bottom:18px;" class="fade-in">
          <div class="sec-eyebrow">⚽ Gruppenphase 2026</div>
          <div class="sec-title">Spielplan & Tipps</div>
          <div class="sec-sub">50 ◈ Einsatz · Gesperrt sobald der Admin ein Spiel startet · <a href="/punkte" style="color:var(--copper);text-decoration:none;font-weight:700;">Punktesystem →</a></div>
        </div>

        {live_banner}
        {today_banner}

        <div class="tabs-wrap fade-in">{tabs_html}</div>

        <div class="card fade-in">
          <div class="gruppe-header">
            <div class="gr-letter">{gruppe_id}</div>
            <div>
              <div style="font-family:'Bebas Neue';font-size:22px;letter-spacing:3px;text-transform:uppercase;">Gruppe {gruppe_id}</div>
              <div class="gr-pills" style="margin-top:8px;">{team_pills}</div>
            </div>
          </div>
          <div class="match-list">{spiele_html}</div>
        </div>
      </div>
    </div>

    <script>
      function checkLive(){{
        fetch('/api/live_scores').then(r=>r.json()).then(scores=>{{
          let needsReload=false;
          for(const[sid,data] of Object.entries(scores)){{
            const el=document.getElementById('spiel-'+sid);
            if(!el) continue;
            const isLiveNow = (data.status==='live'||data.status==='halbzeit'||data.status==='nachspielzeit');
            const wasLive = el.classList.contains('is-live');
            const isFinalNow = data.status==='final';
            const wasFinal = el.classList.contains('is-final');
            if((isLiveNow && !wasLive) || (isFinalNow && !wasFinal) || (!isLiveNow && !isFinalNow && (wasLive||wasFinal))){{
              needsReload=true;
            }}
            if(isLiveNow) needsReload = needsReload || true;
          }}
          if(needsReload) setTimeout(()=>window.location.reload(),500);
        }}).catch(()=>{{}});
      }}
      setInterval(checkLive,15000);
    </script>
    </body></html>"""

@app.route('/dashboard')
def dashboard():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        return redirect(url_for('home'))

    if username == ADMIN_USER:
        # Admin sieht standardmäßig Gruppe A, kann aber überall hin
        return render_gruppe_page(username, "A", "dashboard")

    # Auto-detect best group to show: first group with a game today/tomorrow, else fav team's group
    heute = datetime.date.today()
    morgen = heute + datetime.timedelta(days=1)
    aktive_gruppe = None

    for gk, gd in WM_GRUPPEN.items():
        for sp in gd["spiele"]:
            try:
                sp_date = datetime.datetime.strptime(sp["datum"], "%d.%m.%Y").date()
                if sp_date == heute:
                    aktive_gruppe = gk
                    break
            except:
                pass
        if aktive_gruppe:
            break

    if not aktive_gruppe:
        for gk, gd in WM_GRUPPEN.items():
            for sp in gd["spiele"]:
                try:
                    sp_date = datetime.datetime.strptime(sp["datum"], "%d.%m.%Y").date()
                    if sp_date == morgen:
                        aktive_gruppe = gk
                        break
                except:
                    pass
            if aktive_gruppe:
                break

    if not aktive_gruppe:
        mein_team = next((t for t in ALLE_TEAMS if t["name"] == user_db[username].get("lieblingsteam")), None)
        aktive_gruppe = mein_team["gruppe"] if mein_team else "A"

    return render_gruppe_page(username, aktive_gruppe, "dashboard")

@app.route('/gruppe/<gruppe_id>')
def gruppe_ansicht(gruppe_id):
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        return redirect(url_for('home'))
    gruppe_id = gruppe_id.upper()
    if gruppe_id not in WM_GRUPPEN:
        return redirect(url_for('dashboard'))
    return render_gruppe_page(username, gruppe_id, "dashboard")

@app.route('/api/live_scores')
def api_live_scores():
    result = {}
    for gruppe_data in WM_GRUPPEN.values():
        for spiel in gruppe_data["spiele"]:
            sid = spiel["id"]
            status = get_spiel_status(spiel)
            score = get_live_score(sid)
            result[sid] = {"status": status, "score": score}
    return jsonify(result)
# ==========================================
# LEADERBOARD
# ==========================================
@app.route('/leaderboard')
def leaderboard():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        return redirect(url_for('home'))
    user_info = user_db.get(username, {"points": 1000, "tipps": {}, "lieblingsteam": None})
    navbar = get_navbar(username, user_info["points"], user_info.get("lieblingsteam"), "leaderboard")
    lb = get_leaderboard()
    medals = {1: ("🥇", "r1"), 2: ("🥈", "r2"), 3: ("🥉", "r3")}

    podium_html = ""
    if len(lb) >= 3:
        def podium_card(entry, rank, cls):
            medal, _ = medals.get(rank, ("", ""))
            team = next((t for t in ALLE_TEAMS if t["name"] == entry.get("lieblingsteam")), None)
            team_html = f'{flag_img(team["code"],16)} {team["name"]}' if team else ""
            return f"""
            <div class="{cls}">
              <div class="po-medal">{medal}</div>
              <img class="po-head" src="https://mc-heads.net/avatar/{entry['username']}/56" alt="" onerror="this.style.display='none'">
              <div class="po-name">{entry['username']}</div>
              <div style="font-size:12px;color:var(--muted);font-family:'Rajdhani';font-weight:700;margin-top:3px;">{team_html}</div>
              <div class="po-pts">{entry['points']:,} ◈</div>
            </div>"""
        podium_html = f"""
        <div class="podium-wrap fade-in">
          {podium_card(lb[1], 2, "podium-card po-2")}
          {podium_card(lb[0], 1, "podium-card po-1")}
          {podium_card(lb[2], 3, "podium-card po-3")}
        </div>"""

    rows_html = ""
    for i, entry in enumerate(lb, 1):
        rank_class = f"rk-{i}" if i <= 3 else ""
        is_me = (entry["username"] == username)
        if is_me: rank_class += " rk-me"
        medal, rank_color = medals.get(i, ("", ""))
        rank_display = f'<span class="lb-rank {rank_color}">{medal or str(i)}</span>'
        team = next((t for t in ALLE_TEAMS if t["name"] == entry.get("lieblingsteam")), None)
        team_html = f'{flag_img(team["code"],16)} {team["name"]}' if team else ""
        me_badge = '<span class="lb-me-chip">DU</span>' if is_me else ""
        rows_html += f"""
        <div class="lb-row {rank_class}" data-username="{entry['username'].lower()}">
          {rank_display}
          <div class="lb-user-cell">
            <img class="lb-av" src="https://mc-heads.net/avatar/{entry['username']}/32" alt="" onerror="this.style.display='none'">
            <div>
              <div class="lb-username">{entry['username']} {me_badge}</div>
              <div class="lb-team-sm">{team_html}</div>
            </div>
          </div>
          <div class="lb-tipps-cell">{entry['tipps']} Tipps</div>
          <div class="lb-pts">{entry['points']:,} ◈</div>
        </div>"""

    if not lb:
        rows_html = '<div style="text-align:center;color:var(--muted);padding:60px;font-family:\'Rajdhani\';font-weight:700;font-size:15px;letter-spacing:1px;">NOCH KEINE SPIELER REGISTRIERT</div>'

    my_rank = next((i+1 for i, e in enumerate(lb) if e["username"] == username), None)
    my_rank_txt = f"Platz {my_rank} von {len(lb)}" if my_rank else "–"

    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap" style="max-width:880px;">
        <div style="margin-bottom:32px;" class="fade-in">
          <div class="sec-eyebrow">🏆 Bestenliste</div>
          <div style="font-family:'Bebas Neue';font-size:56px;letter-spacing:4px;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">RANGLISTE</div>
          <div class="sec-sub">Dein Rang: <strong style="color:var(--gold);">{my_rank_txt}</strong></div>
        </div>
        {podium_html}
        <div class="lb-search-wrap fade-in">
          <div class="lb-search-icon">🔍</div>
          <input type="text" class="lb-search" id="lb-search" placeholder="Spieler suchen..." autocomplete="off" spellcheck="false">
        </div>
        <div class="lb-head-row fade-in">
          <div>#</div><div>Spieler</div><div style="text-align:center;">Tipps</div><div style="text-align:right;">Punkte</div>
        </div>
        <div id="lb-list">{rows_html}</div>
        <div id="lb-empty" style="display:none;text-align:center;padding:40px;color:var(--muted);font-family:'Rajdhani';font-weight:700;letter-spacing:1px;font-size:14px;">⚽ KEIN SPIELER GEFUNDEN</div>
      </div>
    </div>
    <script>
      const search=document.getElementById('lb-search');
      const rows=document.querySelectorAll('.lb-row[data-username]');
      const empty=document.getElementById('lb-empty');
      search.addEventListener('input',()=>{{
        const q=search.value.toLowerCase().trim();
        let found=0;
        rows.forEach(row=>{{
          const name=row.getAttribute('data-username');
          if(!q||name.includes(q)){{row.classList.remove('lb-hidden');found++;}}
          else row.classList.add('lb-hidden');
        }});
        empty.style.display=found===0?'block':'none';
      }});
    </script>
    </body></html>"""

# ==========================================
# PUNKTE
# ==========================================
@app.route('/punkte')
def punkte():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        return redirect(url_for('home'))
    user_info = user_db.get(username, {"points": 1000, "tipps": {}, "lieblingsteam": None})
    navbar = get_navbar(username, user_info["points"], user_info.get("lieblingsteam"), "punkte")
    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap" style="max-width:780px;">
        <div style="margin-bottom:36px;" class="fade-in">
          <div class="sec-eyebrow">📋 Spielregeln</div>
          <div style="font-family:'Bebas Neue';font-size:50px;letter-spacing:3px;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">PUNKTESYSTEM</div>
          <div class="sec-sub">So verdienst du Punkte – und so verlierst du sie</div>
        </div>

        <div class="card fade-in d1" style="margin-bottom:14px;border-color:rgba(245,200,66,0.15);">
          <div style="font-family:'Bebas Neue';font-size:24px;letter-spacing:3px;color:var(--gold);margin-bottom:16px;">🎯 TREFFERQUOTEN</div>
          <div class="pts-grid">
            <div class="pts-row top">
              <div><div class="pts-label">🎯 Perfektes Ergebnis</div><div class="pts-sub">z.B. Tipp 2:1 → Ergebnis 2:1</div></div>
              <div class="pts-val">+1.000 ◈</div>
            </div>
            <div class="pts-row">
              <div><div class="pts-label">⚡ Richtige Tordifferenz</div><div class="pts-sub">z.B. Tipp 3:1 → Ergebnis 2:0</div></div>
              <div class="pts-val">+500 ◈</div>
            </div>
            <div class="pts-row">
              <div><div class="pts-label">✅ Richtige Tendenz</div><div class="pts-sub">Sieg / Unentschieden / Niederlage</div></div>
              <div class="pts-val">+200 ◈</div>
            </div>
            <div class="pts-row" style="border-color:rgba(255,87,34,0.25);background:rgba(255,87,34,0.04);">
              <div><div class="pts-label">❌ Falsch getippt</div><div class="pts-sub">Falsche Tendenz</div></div>
              <div class="pts-val neg">0 ◈</div>
            </div>
          </div>
        </div>

        <div class="card fade-in d2" style="margin-bottom:14px;border-color:rgba(224,123,57,0.12);">
          <div style="font-family:'Bebas Neue';font-size:24px;letter-spacing:3px;color:var(--gold);margin-bottom:16px;">💰 STARTKAPITAL & EINSATZ</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="pts-row">
              <div><div class="pts-label">Startkapital</div><div class="pts-sub">Bei der Registrierung</div></div>
              <div class="pts-val">1.000 ◈</div>
            </div>
            <div class="pts-row" style="border-color:rgba(255,87,34,0.25);background:rgba(255,87,34,0.04);">
              <div><div class="pts-label">Einsatz pro Tipp</div><div class="pts-sub">Wird sofort abgezogen</div></div>
              <div class="pts-val neg">−50 ◈</div>
            </div>
          </div>
        </div>

        <div class="card fade-in d3" style="margin-bottom:28px;border-color:rgba(244,67,54,0.18);">
          <div style="font-family:'Bebas Neue';font-size:24px;letter-spacing:3px;color:var(--live);margin-bottom:16px;">🔒 TIPP-SPERRE</div>
          <div class="pts-row" style="border-color:rgba(244,67,54,0.3);background:rgba(244,67,54,0.05);">
            <div>
              <div class="pts-label">Gesperrt sobald der Admin das Spiel startet</div>
              <div class="pts-sub">Der Admin setzt jedes Spiel manuell auf LIVE — danach ist Tippen für dieses Spiel nicht mehr möglich</div>
            </div>
            <div style="font-family:'Bebas Neue';font-size:30px;color:var(--live);letter-spacing:2px;">LIVE</div>
          </div>
          <div style="margin-top:12px;padding:12px 16px;background:var(--g3);border-radius:8px;font-size:13px;color:var(--text2);line-height:1.8;font-weight:500;">
            📡 <strong style="color:var(--text);">Live-Status:</strong> Während Spiele laufen siehst du den aktuellen Spielstand, Halbzeit- und Nachspielzeit-Status direkt im Dashboard. Die Seite aktualisiert sich automatisch.
          </div>
        </div>

        <div style="text-align:center;" class="fade-in d4">
          <a href="/dashboard" class="btn btn-primary" style="font-size:17px;padding:15px 40px;">⚽ Jetzt tippen</a>
        </div>
      </div>
    </div>
    </body></html>"""

# ==========================================
# SUBMIT TIPP
# ==========================================
@app.route('/submittipp', methods=['POST'])
def submit_tipp():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    spiel_id = request.form.get("spiel_id")
    tipp_heim = request.form.get("tipp_heim", "0")
    tipp_gast = request.form.get("tipp_gast", "0")
    redirect_gruppe = request.form.get("redirect_gruppe")

    if username not in user_db:
        return redirect(url_for('home'))

    spiel_gefunden = None
    for gruppe_data in WM_GRUPPEN.values():
        for spiel in gruppe_data["spiele"]:
            if spiel["id"] == spiel_id:
                spiel_gefunden = spiel
                break

    if spiel_gefunden and spiel_id not in user_db[username]["tipps"]:
        status = get_spiel_status(spiel_gefunden)
        # Tippen nur erlaubt, solange der Admin das Spiel nicht gestartet hat (status == upcoming)
        if status == "upcoming":
            if user_db[username]["points"] >= PUNKTE_SYSTEM["einsatz"]:
                user_db[username]["points"] -= PUNKTE_SYSTEM["einsatz"]
                user_db[username]["tipps"][spiel_id] = {
                    "heim": int(tipp_heim),
                    "gast": int(tipp_gast)
                }
                save_data()

    if redirect_gruppe:
        return redirect(url_for('gruppe_ansicht', gruppe_id=redirect_gruppe))
    return redirect(url_for('dashboard'))
# ==========================================
# ADMIN PANEL
# ==========================================
ADMIN_CSS = """
<style>
.ap-wrap{max-width:1100px;margin:0 auto;padding:32px 24px 100px;}
.ap-hero{
  display:flex;align-items:center;gap:16px;margin-bottom:36px;
  padding:20px 28px;
  background:linear-gradient(135deg,rgba(255,87,34,0.12),rgba(245,200,66,0.06));
  border:1px solid rgba(255,87,34,0.35);border-radius:14px;
}
.ap-hero-icon{font-size:42px;line-height:1;}
.ap-hero-title{font-family:'Bebas Neue';font-size:38px;letter-spacing:4px;
  background:linear-gradient(90deg,var(--fire2),var(--gold3));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.ap-hero-sub{font-family:'Rajdhani';font-weight:700;font-size:12px;letter-spacing:2px;
  color:var(--muted);text-transform:uppercase;margin-top:2px;}

/* Group section */
.ap-gruppe-header{
  display:flex;align-items:center;gap:14px;
  margin:28px 0 12px;padding-bottom:10px;
  border-bottom:1px solid rgba(245,200,66,0.12);
}
.ap-gr-letter{
  font-family:'Bebas Neue';font-size:48px;line-height:1;
  background:linear-gradient(135deg,var(--gold3),var(--copper));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  min-width:40px;
}
.ap-gr-label{font-family:'Rajdhani';font-weight:800;font-size:15px;letter-spacing:2px;
  text-transform:uppercase;color:var(--text2);}

/* Match row */
.ap-match{
  display:grid;
  grid-template-columns:200px 140px 1fr;
  align-items:center;gap:16px;
  background:var(--card2);
  border:1px solid var(--border3);
  border-radius:10px;padding:14px 18px;
  margin-bottom:8px;transition:border-color .2s;
}
.ap-match:hover{border-color:rgba(255,255,255,0.1);}
.ap-match.status-live{border-color:rgba(244,67,54,0.4);background:rgba(244,67,54,0.05);}
.ap-match.status-halbzeit{border-color:rgba(245,200,66,0.4);background:rgba(245,200,66,0.05);}
.ap-match.status-nachspielzeit{border-color:rgba(244,67,54,0.55);background:rgba(244,67,54,0.08);}
.ap-match.status-final{border-color:rgba(0,229,160,0.25);background:rgba(0,229,160,0.03);}
.ap-match.status-upcoming{border-color:rgba(41,182,246,0.15);}

.ap-match-teams{
  font-family:'Rajdhani';font-weight:800;font-size:15px;letter-spacing:.5px;
  text-transform:uppercase;line-height:1.5;
}
.ap-match-meta{font-size:11px;color:var(--muted);font-weight:600;font-family:'Rajdhani';
  letter-spacing:1px;margin-top:2px;}
.ap-match-id{
  font-family:'Bebas Neue';font-size:13px;letter-spacing:2px;
  color:var(--muted);background:var(--g3);padding:2px 8px;border-radius:4px;
  display:inline-block;margin-top:3px;
}

/* Status badge in admin */
.ap-status{
  display:flex;flex-direction:column;align-items:center;gap:6px;
  font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:1.5px;
  text-transform:uppercase;
}
.ap-s-pill{display:flex;align-items:center;gap:6px;}
.ap-s-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.ap-s-live .ap-s-dot{background:var(--live);animation:dotBlink .7s step-end infinite;}
.ap-s-live{color:var(--live);}
.ap-s-halbzeit .ap-s-dot{background:var(--gold);}
.ap-s-halbzeit{color:var(--gold);}
.ap-s-nachspielzeit .ap-s-dot{background:var(--live);animation:dotBlink .5s step-end infinite;}
.ap-s-nachspielzeit{color:#ffab91;}
.ap-s-final .ap-s-dot{background:var(--neon);}
.ap-s-final{color:var(--neon);}
.ap-s-upcoming .ap-s-dot{background:var(--sky);}
.ap-s-upcoming{color:var(--sky);}

/* Score control */
.ap-score-control{
  display:flex;align-items:center;justify-content:center;gap:10px;
  background:var(--g3);border-radius:8px;padding:8px 10px;
}
.ap-score-team{display:flex;flex-direction:column;align-items:center;gap:4px;}
.ap-score-num{
  font-family:'Bebas Neue';font-size:32px;line-height:1;color:var(--text);min-width:38px;text-align:center;
}
.ap-score-btns{display:flex;gap:4px;}
.ap-score-btn{
  width:24px;height:24px;border-radius:5px;border:1px solid var(--border2);
  background:var(--g4);color:var(--text2);cursor:pointer;font-family:'Bebas Neue';
  font-size:14px;display:flex;align-items:center;justify-content:center;transition:all .15s;
}
.ap-score-btn:hover{background:rgba(245,200,66,0.15);border-color:rgba(245,200,66,0.4);color:var(--gold);}
.ap-score-sep-admin{font-family:'Bebas Neue';font-size:24px;color:var(--muted);}

/* Action area */
.ap-actions{display:flex;flex-direction:column;gap:8px;align-items:flex-end;}

/* Status toggle buttons */
.ap-btn-row{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;}
.ap-btn{
  font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:1.5px;
  text-transform:uppercase;padding:7px 12px;border-radius:6px;
  border:1.5px solid transparent;cursor:pointer;transition:all .15s;
  background:transparent;
}
.ap-btn-live{color:var(--live);border-color:rgba(244,67,54,0.4);}
.ap-btn-live:hover,.ap-btn-live.active{
  background:rgba(244,67,54,0.18);border-color:rgba(244,67,54,0.8);
  box-shadow:0 0 12px rgba(244,67,54,0.3);
}
.ap-btn-live.active{background:rgba(244,67,54,0.25);}
.ap-btn-halbzeit{color:var(--gold);border-color:rgba(245,200,66,0.4);}
.ap-btn-halbzeit:hover,.ap-btn-halbzeit.active{background:rgba(245,200,66,0.18);border-color:rgba(245,200,66,0.8);}
.ap-btn-halbzeit.active{background:rgba(245,200,66,0.25);}
.ap-btn-nachspielzeit{color:#ffab91;border-color:rgba(244,67,54,0.4);}
.ap-btn-nachspielzeit:hover,.ap-btn-nachspielzeit.active{background:rgba(244,67,54,0.18);border-color:rgba(244,67,54,0.8);}
.ap-btn-nachspielzeit.active{background:rgba(244,67,54,0.25);}
.ap-btn-final{color:var(--neon);border-color:rgba(0,229,160,0.4);}
.ap-btn-final:hover,.ap-btn-final.active{background:rgba(0,229,160,0.18);border-color:rgba(0,229,160,0.8);}
.ap-btn-final.active{background:rgba(0,229,160,0.25);}
.ap-btn-upcoming{color:var(--sky);border-color:rgba(41,182,246,0.35);}
.ap-btn-upcoming:hover,.ap-btn-upcoming.active{background:rgba(41,182,246,0.12);border-color:rgba(41,182,246,0.7);}
.ap-btn-upcoming.active{background:rgba(41,182,246,0.2);}

/* Nachspielzeit input */
.ap-nsz-row{display:flex;align-items:center;gap:6px;justify-content:flex-end;}
.ap-nsz-label{font-family:'Rajdhani';font-weight:700;font-size:11px;color:var(--muted);letter-spacing:1px;text-transform:uppercase;}
.ap-nsz-in{
  width:46px;height:30px;background:var(--g3);border:1px solid var(--border2);
  color:#fff;border-radius:5px;text-align:center;font-family:'Bebas Neue';font-size:15px;
  -moz-appearance:textfield;appearance:none;
}
.ap-nsz-in::-webkit-inner-spin-button,.ap-nsz-in::-webkit-outer-spin-button{-webkit-appearance:none;}
.ap-nsz-btn{
  font-family:'Rajdhani';font-weight:800;font-size:10px;letter-spacing:1px;text-transform:uppercase;
  padding:6px 10px;border-radius:5px;border:1.5px solid rgba(244,67,54,0.4);color:#ffab91;
  background:transparent;cursor:pointer;transition:all .15s;
}
.ap-nsz-btn:hover{background:rgba(244,67,54,0.15);}

/* Abschluss/Auswertung */
.ap-finish-btn{
  background:linear-gradient(135deg,var(--neon2),var(--neon));
  color:#000;border:none;border-radius:6px;
  padding:8px 16px;font-family:'Rajdhani';font-weight:800;font-size:11px;
  letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;
  transition:all .2s;white-space:nowrap;
}
.ap-finish-btn:hover{transform:scale(1.04);box-shadow:0 4px 14px rgba(0,229,160,0.4);}

/* Result tag */
.ap-result-tag{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(0,229,160,0.1);border:1px solid rgba(0,229,160,0.3);
  border-radius:6px;padding:5px 12px;
  font-family:'Bebas Neue';font-size:16px;letter-spacing:1px;color:var(--neon);
}

/* User tipps table */
.ap-tipps-table{
  width:100%;border-collapse:collapse;font-size:12px;
  font-family:'Rajdhani';font-weight:600;
}
.ap-tipps-table th{
  text-align:left;padding:5px 8px;
  color:var(--muted);font-size:10px;letter-spacing:1.5px;text-transform:uppercase;
  border-bottom:1px solid var(--border3);
}
.ap-tipps-table td{padding:5px 8px;border-bottom:1px solid rgba(255,255,255,0.03);}
.ap-tipps-table tr:last-child td{border-bottom:none;}

/* Toast */
#ap-toast{
  position:fixed;bottom:30px;right:30px;z-index:9999;
  background:var(--card);border:1px solid rgba(0,229,160,0.4);
  border-radius:10px;padding:14px 22px;
  font-family:'Rajdhani';font-weight:700;font-size:14px;
  color:var(--neon);letter-spacing:.5px;
  display:none;animation:toastIn .3s ease;
  box-shadow:0 8px 30px rgba(0,0,0,0.5),0 0 20px rgba(0,229,160,0.1);
}
@keyframes toastIn{from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1}}

/* Expand toggle */
.ap-expand-btn{
  background:none;border:none;cursor:pointer;
  color:var(--muted);font-size:11px;font-family:'Rajdhani';font-weight:700;
  letter-spacing:1px;text-transform:uppercase;padding:4px 8px;
  border-radius:4px;transition:all .15s;
}
.ap-expand-btn:hover{color:var(--text2);background:rgba(255,255,255,0.04);}
.ap-tipps-panel{display:none;margin-top:8px;width:100%;}
.ap-tipps-panel.open{display:block;}
.ap-full-row{grid-column:1 / -1;}

/* Auswertung result rows */
.ap-result-row{
  display:flex;align-items:center;justify-content:space-between;
  padding:5px 10px;border-radius:5px;
}
.ap-result-row.perfekt{background:rgba(245,200,66,0.08);}
.ap-result-row.tendenz_tor{background:rgba(0,229,160,0.06);}
.ap-result-row.tendenz{background:rgba(41,182,246,0.06);}
.ap-result-row.falsch{background:rgba(255,87,34,0.05);}

/* Account management */
.ap-acc-form{
  display:grid;grid-template-columns:1fr 1fr auto;gap:10px;align-items:end;
  background:var(--g3);border:1px solid var(--border2);border-radius:10px;padding:16px;margin-bottom:20px;
}
.ap-acc-row{
  display:flex;align-items:center;gap:12px;padding:10px 14px;
  background:var(--g3);border-radius:8px;margin-bottom:6px;
}
.ap-acc-name{font-family:'Rajdhani';font-weight:800;font-size:14px;flex:1;}
.ap-acc-pts{font-family:'Bebas Neue';font-size:18px;color:var(--gold);letter-spacing:1px;}
.ap-acc-meta{font-family:'Rajdhani';font-weight:700;font-size:11px;color:var(--muted);}
.ap-pw-form{display:flex;gap:6px;align-items:center;}
.ap-pw-in{
  width:120px;height:32px;background:var(--g2);border:1px solid var(--border2);
  color:#fff;border-radius:6px;padding:0 10px;font-family:'Rajdhani';font-weight:600;font-size:12px;
}
.ap-pw-btn{
  font-family:'Rajdhani';font-weight:800;font-size:10px;letter-spacing:1px;text-transform:uppercase;
  padding:7px 12px;border-radius:6px;border:1.5px solid rgba(41,182,246,0.4);color:var(--sky);
  background:transparent;cursor:pointer;transition:all .15s;white-space:nowrap;
}
.ap-pw-btn:hover{background:rgba(41,182,246,0.15);}
</style>
"""

def tendenz_calc(h, g):
    if h > g: return "H"
    if h < g: return "G"
    return "U"

def do_auswertung(spiel_id, heim_tore, gast_tore):
    """Führt die Auswertung für ein Spiel durch und gibt Ergebnisliste zurück."""
    echte_tendenz = tendenz_calc(heim_tore, gast_tore)
    echte_diff = heim_tore - gast_tore
    results = []
    for uname, data in user_db.items():
        tipp = data.get("tipps", {}).get(spiel_id)
        if not tipp:
            continue
        if tipp.get("punkte_result"):
            continue
        th, tg = tipp["heim"], tipp["gast"]
        if th == heim_tore and tg == gast_tore:
            pval = PUNKTE_SYSTEM["perfekt"]; erg = "perfekt"
        elif tendenz_calc(th, tg) == echte_tendenz and (th - tg) == echte_diff:
            pval = PUNKTE_SYSTEM["tendenz_tor"]; erg = "tendenz_tor"
        elif tendenz_calc(th, tg) == echte_tendenz:
            pval = PUNKTE_SYSTEM["tendenz"]; erg = "tendenz"
        else:
            pval = PUNKTE_SYSTEM["falsch"]; erg = "falsch"
        user_db[uname]["points"] = user_db[uname].get("points", 0) + pval
        user_db[uname]["tipps"][spiel_id]["punkte_result"] = erg
        results.append({"user": uname, "tipp": f"{th}:{tg}", "erg": erg, "pts": pval})
    save_data()
    return results

def is_admin_session():
    return "username" in session and session["username"] == ADMIN_USER

@app.route('/adminpanel')
def adminpanel():
    if not is_admin_session():
        return redirect(url_for('home'))
    username = session["username"]
    user_info = user_db.get(username, {"points": 1000, "tipps": {}, "lieblingsteam": None})
    navbar = get_navbar(username, user_info["points"], user_info.get("lieblingsteam"), "adminpanel")

    # ---------- Spielverwaltung ----------
    gruppen_html = ""
    for gr_key, gr_data in WM_GRUPPEN.items():
        spiele_html = ""
        for spiel in gr_data["spiele"]:
            sid = spiel["id"]
            cache = get_cache_entry(sid)
            status = cache.get("status", "upcoming")
            heim_score = cache.get("heim") if cache.get("heim") is not None else 0
            gast_score = cache.get("gast") if cache.get("gast") is not None else 0
            nsz = cache.get("nachspielzeit", 0)

            tipps_fuer_spiel = {
                u: d["tipps"][sid]
                for u, d in user_db.items()
                if sid in d.get("tipps", {})
            }
            n_tipps = len(tipps_fuer_spiel)

            status_labels = {
                "live": ("ap-s-live", "🔴 LÄUFT"),
                "halbzeit": ("ap-s-halbzeit", "⏸ HALBZEIT"),
                "nachspielzeit": ("ap-s-nachspielzeit", "🔴 NACHSPIELZEIT"),
                "final": ("ap-s-final", "✅ BEENDET"),
                "upcoming": ("ap-s-upcoming", "⏳ AUSSTEHEND"),
            }
            s_cls, s_label = status_labels.get(status, status_labels["upcoming"])
            status_html = f'<div class="ap-status {s_cls}"><div class="ap-s-pill"><div class="ap-s-dot"></div> {s_label}</div></div>'
            card_cls = f"status-{status}"

            # Tipps detail table
            tipps_rows = ""
            for uname, t in sorted(tipps_fuer_spiel.items()):
                pr = t.get("punkte_result", "—")
                pts_label = {"perfekt": "+1000 ◈ 🎯", "tendenz_tor": "+500 ◈ ⚡", "tendenz": "+200 ◈ ✅", "falsch": "0 ◈ ❌"}.get(pr, "–")
                row_cls = pr if pr in ("perfekt","tendenz_tor","tendenz","falsch") else ""
                tipps_rows += f"""
                <tr class="ap-result-row {row_cls}">
                  <td><strong>{uname}</strong></td>
                  <td style="font-family:'Bebas Neue';font-size:16px;letter-spacing:1px;">{t['heim']}:{t['gast']}</td>
                  <td style="color:var(--text2);">{pts_label}</td>
                </tr>"""

            tipps_panel = ""
            if tipps_fuer_spiel:
                tipps_panel = f"""
                <button class="ap-expand-btn" onclick="toggleTipps('{sid}')">▾ {n_tipps} Tipp{'s' if n_tipps!=1 else ''} anzeigen</button>
                <div class="ap-tipps-panel" id="tipps-{sid}">
                  <table class="ap-tipps-table" style="margin-top:6px;">
                    <tr><th>Spieler</th><th>Tipp</th><th>Ergebnis</th></tr>
                    {tipps_rows}
                  </table>
                </div>"""
            else:
                tipps_panel = f'<span style="font-family:\'Rajdhani\';font-size:11px;color:var(--muted);">Noch keine Tipps</span>'

            # Score control (Tore +/- nur sinnvoll wenn nicht final)
            score_disabled = "disabled" if status == "final" else ""
            score_control = f"""
            <div class="ap-score-control">
              <div class="ap-score-team">
                <div class="ap-score-num" id="h-num-{sid}">{heim_score}</div>
                <div class="ap-score-btns">
                  <button class="ap-score-btn" onclick="adjScore('{sid}','heim',-1)" {score_disabled}>−</button>
                  <button class="ap-score-btn" onclick="adjScore('{sid}','heim',1)" {score_disabled}>+</button>
                </div>
              </div>
              <div class="ap-score-sep-admin">:</div>
              <div class="ap-score-team">
                <div class="ap-score-num" id="g-num-{sid}">{gast_score}</div>
                <div class="ap-score-btns">
                  <button class="ap-score-btn" onclick="adjScore('{sid}','gast',-1)" {score_disabled}>−</button>
                  <button class="ap-score-btn" onclick="adjScore('{sid}','gast',1)" {score_disabled}>+</button>
                </div>
              </div>
            </div>"""

            # Nachspielzeit control
            nsz_control = f"""
            <div class="ap-nsz-row">
              <span class="ap-nsz-label">Nachspielzeit:</span>
              <input type="number" id="nsz-{sid}" class="ap-nsz-in" min="0" max="30" value="{nsz}">
              <button class="ap-nsz-btn" onclick="setNachspielzeit('{sid}')">⏱ Setzen</button>
            </div>"""

            # Status buttons
            status_buttons = f"""
            <div class="ap-btn-row">
              <button class="ap-btn ap-btn-upcoming {'active' if status=='upcoming' else ''}" onclick="setStatus('{sid}','upcoming',this)">⏳ Geplant</button>
              <button class="ap-btn ap-btn-live {'active' if status=='live' else ''}" onclick="setStatus('{sid}','live',this)">🔴 Live</button>
              <button class="ap-btn ap-btn-halbzeit {'active' if status=='halbzeit' else ''}" onclick="setStatus('{sid}','halbzeit',this)">⏸ Halbzeit</button>
              <button class="ap-btn ap-btn-nachspielzeit {'active' if status=='nachspielzeit' else ''}" onclick="setStatus('{sid}','nachspielzeit',this)">🔴 NSZ</button>
              <button class="ap-btn ap-btn-final {'active' if status=='final' else ''}" onclick="finishGame('{sid}')">✅ Beenden</button>
            </div>"""

            result_html = ""
            if status == "final":
                result_html = f'<div class="ap-result-tag">{heim_score} : {gast_score}</div>'

            heim_code = TEAM_CODE.get(spiel["heim"], "")
            gast_code = TEAM_CODE.get(spiel["gast"], "")
            spiele_html += f"""
            <div class="ap-match {card_cls}" id="ap-match-{sid}">
              <div>
                <div class="ap-match-teams">
                  {flag_img(heim_code, 18)} {spiel['heim']}<br>
                  {flag_img(gast_code, 18)} {spiel['gast']}
                </div>
                <div class="ap-match-meta">{spiel['datum']} · {spiel['uhrzeit']} Uhr</div>
                <div class="ap-match-id">{sid}</div>
              </div>
              <div>
                {status_html}
                {result_html}
              </div>
              <div class="ap-actions">
                {score_control}
                {nsz_control}
                {status_buttons}
                <div class="ap-tipps-panel-wrap" style="text-align:right;width:100%;">
                  {tipps_panel}
                </div>
              </div>
            </div>"""

        gruppen_html += f"""
        <div class="ap-gruppe-header">
          <div class="ap-gr-letter">{gr_key}</div>
          <div>
            <div class="ap-gr-label">Gruppe {gr_key}</div>
            <div style="display:flex;gap:6px;margin-top:4px;flex-wrap:wrap;">
              {''.join(f'<span style="font-family:\'Rajdhani\';font-weight:700;font-size:11px;color:var(--muted);background:var(--g3);border-radius:4px;padding:2px 8px;">{flag_img(t["code"],14)} {t["name"]}</span>' for t in gr_data["teams"])}
            </div>
          </div>
        </div>
        {spiele_html}"""

    # ---------- Account-Verwaltung ----------
    acc_rows = ""
    for uname, data in sorted(user_db.items(), key=lambda x: (-(x[1].get("is_admin") and 1 or 0), -x[1].get("points", 0))):
        n = len(data.get("tipps", {}))
        is_admin_acc = data.get("is_admin")
        admin_tag = ' <span style="color:var(--copper);font-size:10px;">★ ADMIN</span>' if is_admin_acc else ""
        has_pw = "✅ Hat Passwort" if data.get("pw_hash") else "⚠️ Kein Passwort"
        acc_rows += f"""
        <div class="ap-acc-row">
          <img src="https://mc-heads.net/avatar/{uname}/28" style="width:28px;height:28px;border-radius:5px;image-rendering:pixelated;" onerror="this.style.display='none'">
          <span class="ap-acc-name">{uname}{admin_tag}</span>
          <span class="ap-acc-meta">{has_pw}</span>
          <span class="ap-acc-pts">{data.get('points',0):,} ◈</span>
          <span class="ap-acc-meta">{n} Tipps</span>
          <form class="ap-pw-form" onsubmit="return setPassword(event,'{uname}')">
            <input type="text" class="ap-pw-in" placeholder="Neues Passwort" required minlength="4">
            <button type="submit" class="ap-pw-btn">🔑 Passwort setzen</button>
          </form>
        </div>"""

    return BASE_HTML + ADMIN_CSS + f"""
    {navbar}
    <div id="ap-toast"></div>
    <div class="ap-wrap">
      <div class="ap-hero fade-in">
        <div class="ap-hero-icon">🛠️</div>
        <div>
          <div class="ap-hero-title">Admin Panel</div>
          <div class="ap-hero-sub">Nur für Lattenrost1234 · Live-Status, Tore & Accounts</div>
        </div>
        <div style="margin-left:auto;text-align:right;">
          <div style="font-family:'Bebas Neue';font-size:36px;letter-spacing:2px;color:var(--gold);">{len([u for u in user_db if not user_db[u].get('is_admin')])}</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;">Registrierte Spieler</div>
        </div>
      </div>

      <!-- Quick stats -->
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:32px;" class="fade-in d1">
        <div class="card" style="text-align:center;padding:20px 14px;">
          <div style="font-family:'Bebas Neue';font-size:44px;line-height:1;color:var(--live);">
            {sum(1 for g in WM_GRUPPEN.values() for s in g['spiele'] if get_spiel_status(s) in ('live','halbzeit','nachspielzeit'))}
          </div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:3px;">🔴 Live jetzt</div>
        </div>
        <div class="card" style="text-align:center;padding:20px 14px;">
          <div style="font-family:'Bebas Neue';font-size:44px;line-height:1;color:var(--neon);">
            {sum(1 for g in WM_GRUPPEN.values() for s in g['spiele'] if get_spiel_status(s)=='final')}
          </div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:3px;">✅ Abgeschlossen</div>
        </div>
        <div class="card" style="text-align:center;padding:20px 14px;">
          <div style="font-family:'Bebas Neue';font-size:44px;line-height:1;color:var(--sky);">
            {sum(len(d.get('tipps',{{}})) for d in user_db.values())}
          </div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:3px;">⚽ Tipps gesamt</div>
        </div>
      </div>

      <!-- Account-Verwaltung -->
      <div style="margin-bottom:10px;" class="fade-in d2">
        <div class="sec-eyebrow">👥 Account-Verwaltung</div>
        <div class="sec-title">Minecraft-Namen & Passwörter</div>
        <div class="sec-sub">Neue Spieler freischalten und Passwörter vergeben/ändern</div>
      </div>

      <div class="ap-acc-form fade-in d2" style="margin-bottom:20px;">
        <div>
          <label class="auth-label">Minecraft-Name</label>
          <input type="text" id="new-acc-name" class="auth-input" placeholder="z.B. 1Unbekannter" required>
        </div>
        <div>
          <label class="auth-label">Passwort</label>
          <input type="text" id="new-acc-pw" class="auth-input" placeholder="z.B. 1234" required minlength="4">
        </div>
        <button class="btn btn-gold btn-sm" onclick="createAccount()" style="height:46px;">➕ Freischalten</button>
      </div>

      <div class="fade-in d3" style="margin-bottom:40px;">
        {acc_rows if acc_rows else '<div style="color:var(--muted);font-family:\'Rajdhani\';padding:20px;">Noch keine Accounts.</div>'}
      </div>

      <!-- Spiele -->
      <div style="margin-bottom:10px;" class="fade-in d2">
        <div class="sec-eyebrow">⚽ Spielverwaltung</div>
        <div class="sec-title">Alle Spiele</div>
        <div class="sec-sub">Status setzen (Live/Halbzeit/Nachspielzeit/Beendet) · Tore +/- · Nachspielzeit · Coins verteilen</div>
      </div>
      <div class="fade-in d3">{gruppen_html}</div>
    </div>

    <script>
    function showToast(msg, ok=true) {{
      const t = document.getElementById('ap-toast');
      t.textContent = msg;
      t.style.borderColor = ok ? 'rgba(0,229,160,0.5)' : 'rgba(244,67,54,0.5)';
      t.style.color = ok ? 'var(--neon)' : 'var(--live)';
      t.style.display = 'block';
      clearTimeout(t._to);
      t._to = setTimeout(() => t.style.display = 'none', 3500);
    }}

    function setStatus(sid, newStatus, btn) {{
      fetch('/api/admin/setstatus', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{spiel_id: sid, status: newStatus}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) {{
          const labels = {{live:'🔴 LIVE',halbzeit:'⏸ Halbzeit',nachspielzeit:'🔴 Nachspielzeit',upcoming:'⏳ Geplant',final:'✅ Beendet'}};
          showToast(sid + ' → ' + (labels[newStatus]||newStatus));
          const card = document.getElementById('ap-match-' + sid);
          card.className = 'ap-match status-' + newStatus;
          card.querySelectorAll('.ap-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
        }} else {{
          showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
        }}
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
    }}

    function adjScore(sid, team, delta) {{
      fetch('/api/admin/adjscore', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{spiel_id: sid, team: team, delta: delta}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) {{
          document.getElementById('h-num-' + sid).textContent = d.heim;
          document.getElementById('g-num-' + sid).textContent = d.gast;
          showToast('⚽ ' + sid + ': ' + d.heim + ':' + d.gast);
        }} else {{
          showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
        }}
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
    }}

    function setNachspielzeit(sid) {{
      const val = parseInt(document.getElementById('nsz-' + sid).value) || 0;
      fetch('/api/admin/nachspielzeit', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{spiel_id: sid, minuten: val}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) showToast('⏱ Nachspielzeit für ' + sid + ': +' + val + ' Min');
        else showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
    }}

    function finishGame(sid) {{
      const h = parseInt(document.getElementById('h-num-' + sid).textContent) || 0;
      const g = parseInt(document.getElementById('g-num-' + sid).textContent) || 0;
      if(!confirm('Spiel ' + sid + ' (' + h + ':' + g + ') beenden und Coins verteilen?')) return;
      fetch('/api/admin/finish', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{spiel_id: sid, heim: h, gast: g}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) {{
          showToast('✅ ' + sid + ' beendet! ' + d.count + ' Tipps ausgewertet.');
          setTimeout(() => location.reload(), 1500);
        }} else {{
          showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
        }}
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
    }}

    function toggleTipps(sid) {{
      const panel = document.getElementById('tipps-' + sid);
      panel.classList.toggle('open');
    }}

    function createAccount() {{
      const name = document.getElementById('new-acc-name').value.trim();
      const pw = document.getElementById('new-acc-pw').value;
      if(!name || pw.length < 4) {{ showToast('❌ Name und Passwort (min. 4 Zeichen) erforderlich', false); return; }}
      fetch('/api/admin/create_account', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{username: name, password: pw}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) {{
          showToast('✅ Account ' + name + ' freigeschaltet!');
          setTimeout(() => location.reload(), 1200);
        }} else {{
          showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
        }}
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
    }}

    function setPassword(ev, uname) {{
      ev.preventDefault();
      const input = ev.target.querySelector('.ap-pw-in');
      const pw = input.value;
      if(pw.length < 4) {{ showToast('❌ Passwort zu kurz (min. 4 Zeichen)', false); return false; }}
      fetch('/api/admin/set_password', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{username: uname, password: pw}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) {{ showToast('🔑 Passwort für ' + uname + ' gesetzt!'); input.value=''; }}
        else showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
      return false;
    }}
    </script>
    </body></html>"""

# ── API: Admin Status setzen (upcoming/live/halbzeit/nachspielzeit/final) ──
@app.route('/api/admin/setstatus', methods=['POST'])
def api_admin_setstatus():
    if not is_admin_session():
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    sid = data.get("spiel_id", "")
    new_status = data.get("status", "upcoming")
    if new_status not in ("live", "halbzeit", "nachspielzeit", "upcoming", "final"):
        return jsonify({"ok": False, "error": "Ungültiger Status"})

    spiel = None
    for gd in WM_GRUPPEN.values():
        for sp in gd["spiele"]:
            if sp["id"] == sid:
                spiel = sp; break

    if not spiel:
        return jsonify({"ok": False, "error": "Spiel nicht gefunden"})

    entry = get_cache_entry(sid)
    entry["status"] = new_status
    if new_status == "upcoming":
        entry["heim"] = None
        entry["gast"] = None
        entry["nachspielzeit"] = 0
    elif entry.get("heim") is None:
        entry["heim"] = 0
        entry["gast"] = 0

    persist_live_cache()
    print(f"[ADMIN] {sid} → {new_status}")
    return jsonify({"ok": True})

# ── API: Admin Tore +/- ────────────────────────────────────────
@app.route('/api/admin/adjscore', methods=['POST'])
def api_admin_adjscore():
    if not is_admin_session():
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    sid = data.get("spiel_id", "")
    team = data.get("team", "")
    delta = int(data.get("delta", 0))

    spiel = None
    for gd in WM_GRUPPEN.values():
        for sp in gd["spiele"]:
            if sp["id"] == sid:
                spiel = sp; break
    if not spiel:
        return jsonify({"ok": False, "error": "Spiel nicht gefunden"})
    if team not in ("heim", "gast"):
        return jsonify({"ok": False, "error": "Ungültiges Team"})

    entry = get_cache_entry(sid)
    current = entry.get(team)
    if current is None:
        current = 0
    new_val = max(0, min(99, current + delta))
    entry[team] = new_val
    persist_live_cache()
    return jsonify({"ok": True, "heim": entry.get("heim", 0), "gast": entry.get("gast", 0)})

# ── API: Admin Nachspielzeit setzen ────────────────────────────
@app.route('/api/admin/nachspielzeit', methods=['POST'])
def api_admin_nachspielzeit():
    if not is_admin_session():
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    sid = data.get("spiel_id", "")
    minuten = int(data.get("minuten", 0))

    spiel = None
    for gd in WM_GRUPPEN.values():
        for sp in gd["spiele"]:
            if sp["id"] == sid:
                spiel = sp; break
    if not spiel:
        return jsonify({"ok": False, "error": "Spiel nicht gefunden"})

    entry = get_cache_entry(sid)
    entry["nachspielzeit"] = max(0, min(30, minuten))
    persist_live_cache()
    return jsonify({"ok": True, "nachspielzeit": entry["nachspielzeit"]})

# ── API: Admin Spiel beenden + Coins verteilen ─────────────────
@app.route('/api/admin/finish', methods=['POST'])
def api_admin_finish():
    if not is_admin_session():
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    sid = data.get("spiel_id", "")
    heim_tore = int(data.get("heim", 0))
    gast_tore = int(data.get("gast", 0))

    entry = get_cache_entry(sid)
    entry["status"] = "final"
    entry["heim"] = heim_tore
    entry["gast"] = gast_tore
    persist_live_cache()

    results = do_auswertung(sid, heim_tore, gast_tore)
    print(f"[ADMIN] Abpfiff {sid} {heim_tore}:{gast_tore} — {len(results)} Tipps ausgewertet")
    for r in results:
        print(f"  → {r['user']}: {r['tipp']} = {r['erg']} (+{r['pts']})")

    return jsonify({"ok": True, "count": len(results), "results": results})

# ── API: Admin Account erstellen ───────────────────────────────
@app.route('/api/admin/create_account', methods=['POST'])
def api_admin_create_account():
    if not is_admin_session():
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or len(password) < 4:
        return jsonify({"ok": False, "error": "Name und Passwort (min. 4 Zeichen) erforderlich"})
    if not re.match(r'^[A-Za-z0-9_]{3,16}$', username):
        return jsonify({"ok": False, "error": "Ungültiger Minecraft-Name (3-16 Zeichen, Buchstaben/Zahlen/_)"})
    if username in user_db:
        return jsonify({"ok": False, "error": "Dieser Name existiert bereits"})

    salt, pw_hash = hash_password(password)
    user_db[username] = {
        "points": 1000,
        "tipps": {},
        "lieblingsteam": None,
        "registered": datetime.datetime.now().strftime("%d.%m.%Y"),
        "salt": salt,
        "pw_hash": pw_hash,
        "is_admin": False
    }
    save_data()
    print(f"[ADMIN] Neuer Account erstellt: {username}")
    return jsonify({"ok": True})

# ── API: Admin Passwort setzen/ändern ──────────────────────────
@app.route('/api/admin/set_password', methods=['POST'])
def api_admin_set_password():
    if not is_admin_session():
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    username = data.get("username") or ""
    password = data.get("password") or ""

    if username not in user_db:
        return jsonify({"ok": False, "error": "Benutzer nicht gefunden"})
    if len(password) < 4:
        return jsonify({"ok": False, "error": "Passwort zu kurz (min. 4 Zeichen)"})

    salt, pw_hash = hash_password(password)
    user_db[username]["salt"] = salt
    user_db[username]["pw_hash"] = pw_hash
    save_data()
    print(f"[ADMIN] Passwort geändert für: {username}")
    return jsonify({"ok": True})

@app.route('/admin')
def admin_old():
    if not is_admin_session():
        return redirect(url_for('home'))
    return redirect(url_for('adminpanel'))

@app.route('/auswertung')
def auswertung():
    if not is_admin_session():
        return redirect(url_for('home'))
    return redirect(url_for('adminpanel'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    print("\n" + "="*60)
    print("   🏆  WM 2026 GRIEFERGAMES TIPP-PORTAL  🏆   ")
    print("="*60)
    print(f"   Daten: {os.path.abspath(DATA_FILE)}")
    print(f"   Live-Scores Cache: {os.path.abspath(LIVESCORES_CACHE_FILE)}")
    print(f"   Geladene Spieler: {len(user_db)}")
    print(f"   Admin-Login: {ADMIN_USER} / {ADMIN_DEFAULT_PASSWORD} (bitte nach erstem Login ändern!)")
    print("   Starte auf: http://127.0.0.1:5005")
    print("="*60 + "\n")
    try:
        port = int(os.environ.get('PORT', 5005))
        host = '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
        app.run(debug=False, host=host, port=port, use_reloader=False)
    except Exception as e:
        print(e)
        input()
