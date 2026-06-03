import time
import os
import datetime
import re
import random
import threading
import sys
import json

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
chatlog_ordner = r"C:\Users\zaine\Downloads\mmc-develop-win32\MultiMC\instances\1.8.9\.minecraft\neoessentials\chatlog"

DATA_FILE = "wm2026_data.json"
LIVESCORES_CACHE_FILE = "livescores_cache.json"

app = Flask(__name__)
app.secret_key = "wm2026_griefergames_ultra_secret_1337"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

active_codes = {}
user_db = {}
live_scores_cache = {}
verified_users = set()

# ==========================================
# PERSISTENTER DATENSPEICHER
# ==========================================
def save_data():
    global verified_users
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_db, f, ensure_ascii=False, indent=2)
        verified_users = set(user_db.keys())
    except Exception as e:
        print(f"[FEHLER] Kann Daten nicht speichern: {e}")

def load_data():
    global user_db, verified_users
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                user_db = json.load(f)
            verified_users = set(user_db.keys())
            print(f"[OK] {len(user_db)} Benutzer geladen aus {DATA_FILE}")
        except Exception as e:
            print(f"[WARN] Kann {DATA_FILE} nicht laden: {e}")
            user_db = {}
            verified_users = set()
    else:
        user_db = {}
        verified_users = set()
        print(f"[INFO] Neue Datenbankdatei wird angelegt: {DATA_FILE}")

load_data()

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
# LIVE-SCORES SYSTEM
# ==========================================
FOOTBALL_API_KEY = ""
WM_COMPETITION_ID = "2000"

def fetch_live_scores_thesportsdb():
    global live_scores_cache
    if not REQUESTS_AVAILABLE:
        return
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={today}&s=Soccer"
    try:
        resp = req_lib.get(url, timeout=5)
        if resp.status_code != 200:
            return
        data = resp.json()
        events = data.get("events") or []
        for gruppe_data in WM_GRUPPEN.values():
            for spiel in gruppe_data["spiele"]:
                heim = spiel["heim"].lower()
                gast = spiel["gast"].lower()
                sid = spiel["id"]
                for ev in events:
                    ev_heim = (ev.get("strHomeTeam") or "").lower()
                    ev_gast = (ev.get("strAwayTeam") or "").lower()
                    ev_liga = (ev.get("strLeague") or "").lower()
                    if "world cup" not in ev_liga and "fifa" not in ev_liga:
                        continue
                    if _teams_match(heim, ev_heim) and _teams_match(gast, ev_gast):
                        status = ev.get("strStatus", "").lower()
                        score_home = ev.get("intHomeScore")
                        score_away = ev.get("intAwayScore")
                        cache_entry = {"status": "upcoming", "heim": None, "gast": None, "minuto": None}
                        if status in ["ft", "aet", "pen", "finished", "match finished"]:
                            cache_entry["status"] = "final"
                            cache_entry["heim"] = int(score_home) if score_home is not None else None
                            cache_entry["gast"] = int(score_away) if score_away is not None else None
                        elif status.isdigit() or status in ["ht", "live", "in progress"]:
                            cache_entry["status"] = "live"
                            cache_entry["heim"] = int(score_home) if score_home is not None else 0
                            cache_entry["gast"] = int(score_away) if score_away is not None else 0
                            if status.isdigit():
                                cache_entry["minuto"] = int(status)
                        live_scores_cache[sid] = cache_entry
                        break
    except Exception as e:
        print(f"[LIVE] Fehler beim Score-Abruf: {e}")

def _teams_match(our_name, api_name):
    TEAM_ALIASES = {
        "deutschland": ["germany", "deutschland"],
        "niederlande": ["netherlands", "holland"],
        "österreich": ["austria"],
        "schweiz": ["switzerland"],
        "elfenbeinküste": ["ivory coast", "côte d'ivoire"],
        "tschechien": ["czech republic", "czechia"],
        "südkorea": ["south korea", "korea republic"],
        "südafrika": ["south africa"],
        "saudi-arabien": ["saudi arabia"],
        "kap verde": ["cape verde"],
        "neuseeland": ["new zealand"],
        "schottland": ["scotland"],
        "brasilien": ["brazil"],
        "frankreich": ["france"],
        "spanien": ["spain"],
        "italien": ["italy"],
        "belgien": ["belgium"],
        "kroatien": ["croatia"],
        "ägypten": ["egypt"],
        "norwegen": ["norway"],
        "schweden": ["sweden"],
        "argentinien": ["argentina"],
        "kolumbien": ["colombia"],
        "australien": ["australia"],
        "türkei": ["turkey", "türkiye"],
        "ungarn": ["hungary"],
        "albanien": ["albania"],
        "kamerun": ["cameroon"],
        "nigeria": ["nigeria"],
        "senegal": ["senegal"],
        "marokko": ["morocco"],
        "tunesien": ["tunisia"],
        "portugal": ["portugal"],
        "england": ["england"],
        "serbien": ["serbia"],
        "venezuela": ["venezuela"],
        "mexiko": ["mexico"],
        "bosnien": ["bosnia and herzegovina", "bosnia"],
        "ecuador": ["ecuador"],
        "paraguay": ["paraguay"],
        "chile": ["chile"],
        "haiti": ["haiti"],
        "iran": ["ir iran", "iran"],
        "katar": ["qatar"],
        "usa": ["usa", "united states"],
        "kanada": ["canada"],
        "japan": ["japan"],
        "uruguay": ["uruguay"],
    }
    our_lower = our_name.lower()
    api_lower = api_name.lower()
    if our_lower in api_lower or api_lower in our_lower:
        return True
    aliases = TEAM_ALIASES.get(our_lower, [our_lower])
    for alias in aliases:
        if alias in api_lower or api_lower in alias:
            return True
    return False

def live_score_updater():
    while True:
        try:
            fetch_live_scores_thesportsdb()
            try:
                with open(LIVESCORES_CACHE_FILE, 'w') as f:
                    json.dump(live_scores_cache, f)
            except:
                pass
        except Exception as e:
            print(f"[LIVE-UPDATER] Fehler: {e}")
        time.sleep(60)

if os.path.exists(LIVESCORES_CACHE_FILE):
    try:
        with open(LIVESCORES_CACHE_FILE, 'r') as f:
            live_scores_cache = json.load(f)
        print(f"[OK] Live-Score-Cache geladen ({len(live_scores_cache)} Einträge)")
    except:
        pass

threading.Thread(target=live_score_updater, daemon=True).start()

# ==========================================
# FLAGGEN
# ==========================================
def flag_img(code, size=32):
    code_lower = code.lower()
    special = {"sco": "gb-sct", "eng": "gb-eng", "wal": "gb-wls"}
    if code_lower in special:
        code_lower = special[code_lower]
    return f'<img src="https://flagcdn.com/h{size}/{code_lower}.png" width="{size}" height="{int(size*0.667)}" style="border-radius:3px;vertical-align:middle;object-fit:cover;" alt="" onerror="this.style.display=\'none\'">'

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
# HELPER: Spielzeit-Check
# ==========================================
def parse_spiel_datetime(spiel):
    try:
        dt_str = f"{spiel['datum']} {spiel['uhrzeit']}"
        return datetime.datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
    except:
        return None

def get_spiel_status(spiel):
    sid = spiel["id"]
    if sid in live_scores_cache:
        status = live_scores_cache[sid].get("status", "upcoming")
        if status in ("live", "final"):
            return status
    dt = parse_spiel_datetime(spiel)
    if dt is None:
        return "upcoming"
    jetzt = datetime.datetime.now()
    delta_min = (jetzt - dt).total_seconds() / 60
    if delta_min < -30:
        return "upcoming"
    elif -30 <= delta_min < 0:
        return "soon"
    elif 0 <= delta_min < 105:
        return "live"
    else:
        return "final"

def tipp_erlaubt(spiel):
    status = get_spiel_status(spiel)
    return status in ("upcoming", "soon")

def get_live_score(spiel_id):
    entry = live_scores_cache.get(spiel_id)
    if entry and entry.get("heim") is not None:
        return entry
    return None

def minuten_bis_spiel(spiel):
    dt = parse_spiel_datetime(spiel)
    if dt is None:
        return 9999
    jetzt = datetime.datetime.now()
    return int((dt - jetzt).total_seconds() / 60)

# ==========================================
# LEADERBOARD
# ==========================================
def get_leaderboard():
    lb = []
    for username, data in user_db.items():
        lb.append({
            "username": username,
            "points": data.get("points", 0),
            "tipps": len(data.get("tipps", {})),
            "lieblingsteam": data.get("lieblingsteam")
        })
    lb.sort(key=lambda x: x["points"], reverse=True)
    return lb

# ==========================================
# BACKGROUND LOG-READER (Minecraft Chat)
# ==========================================
def minecraft_log_reader():
    global active_codes, user_db
    heute = datetime.datetime.now().strftime("%d-%m-%Y")
    log_pfad = os.path.join(chatlog_ordner, f"{heute}.txt")
    print(f"[LOG-READER] Überwachung aktiv: {heute}.txt")
    while True:
        if not os.path.exists(log_pfad):
            time.sleep(1)
            heute = datetime.datetime.now().strftime("%d-%m-%Y")
            log_pfad = os.path.join(chatlog_ordner, f"{heute}.txt")
            continue
        letzte_groesse = os.path.getsize(log_pfad)
        while True:
            try:
                aktuelles_datum = datetime.datetime.now().strftime("%d-%m-%Y")
                neuer_pfad = os.path.join(chatlog_ordner, f"{aktuelles_datum}.txt")
                if neuer_pfad != log_pfad and os.path.exists(neuer_pfad):
                    log_pfad = neuer_pfad
                    break
                aktuelle_groesse = os.path.getsize(log_pfad)
                if aktuelle_groesse > letzte_groesse:
                    with open(log_pfad, 'r', encoding='utf-8', errors='ignore') as datei:
                        datei.seek(letzte_groesse)
                        neuer_text = datei.read()
                        for zeile in neuer_text.splitlines():
                            zeile_clean = zeile.strip()
                            if "-> mir]" in zeile_clean and "#verifyWM" in zeile_clean:
                                match_sender = re.search(r'\]\s*\[([^\]]+)->\s*mir\]', zeile_clean)
                                match_zahl = re.search(r'#verifyWM\s+(\d+)', zeile_clean)
                                if match_sender and match_zahl:
                                    ganzer_sender = match_sender.group(1).strip()
                                    spieler_name = ganzer_sender.split()[-1]
                                    code = match_zahl.group(1)
                                    if code in active_codes and active_codes[code]["status"] == "pending":
                                        active_codes[code]["status"] = "verified"
                                        active_codes[code]["username"] = spieler_name
                                        if spieler_name not in user_db:
                                            user_db[spieler_name] = {
                                                "points": 1000,
                                                "tipps": {},
                                                "lieblingsteam": None,
                                                "registered": datetime.datetime.now().strftime("%d.%m.%Y")
                                            }
                                            save_data()
                                        print(f"[✓] Spieler {spieler_name} verifiziert!")
                    letzte_groesse = aktuelle_groesse
            except Exception:
                pass
            time.sleep(0.2)

threading.Thread(target=minecraft_log_reader, daemon=True).start()

# ==========================================
# ██████╗ ███████╗███████╗██╗ ██████╗ ███╗   ██╗
# ██╔══██╗██╔════╝██╔════╝██║██╔════╝ ████╗  ██║
# ██║  ██║█████╗  ███████╗██║██║  ███╗██╔██╗ ██║
# ██║  ██║██╔══╝  ╚════██║██║██║   ██║██║╚██╗██║
# ██████╔╝███████╗███████║██║╚██████╔╝██║ ╚████║
# ╚═════╝ ╚══════╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝
# ==========================================

BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@300;400;500;600;700&family=Barlow:ital,wght@0,400;0,500;0,600;0,700;0,800;0,900;1,700&family=Barlow+Condensed:wght@400;500;600;700;800;900&display=swap');

:root {
  /* WM 2026 Palette – Feuer & Stadion-Nacht */
  --pitch:    #0a3d1f;
  --pitch2:   #0d4a26;
  --gold:     #FFD700;
  --gold2:    #FFA500;
  --gold3:    #FFE44D;
  --amber:    #FF8C00;
  --fire1:    #FF4500;
  --fire2:    #FF6B35;
  --neon:     #00FF88;
  --neon2:    #00CC6A;
  --cyan:     #00D4FF;
  --live:     #FF3030;
  --live2:    #FF6060;

  --bg:       #060A0F;
  --bg2:      #080D15;
  --bg3:      #0B1220;
  --card:     #0E1628;
  --card2:    #111C32;
  --card3:    #162240;

  --border:   rgba(255,215,0,0.12);
  --border2:  rgba(255,255,255,0.06);
  --border3:  rgba(255,255,255,0.03);

  --text:     #F0F4FF;
  --text2:    #A8B8D8;
  --muted:    #4A5A7A;

  --r1: #FFD700;
  --r2: #C8D0E0;
  --r3: #CD8C50;
}

*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior:smooth; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Barlow', sans-serif;
  min-height: 100vh;
  overflow-x: hidden;
}

/* ═══════════════════════════════════════
   BACKGROUND – Stadionrasen-Textur + Atmosphäre
═══════════════════════════════════════ */
body::before {
  content: '';
  position: fixed; inset: 0; z-index: 0;
  background:
    radial-gradient(ellipse 80% 50% at 50% -20%, rgba(0,255,136,0.04) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 10% 60%, rgba(255,165,0,0.03) 0%, transparent 50%),
    radial-gradient(ellipse 60% 40% at 90% 80%, rgba(0,212,255,0.03) 0%, transparent 50%),
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 60px,
      rgba(0,255,136,0.012) 60px,
      rgba(0,255,136,0.012) 61px
    );
  pointer-events: none;
}

/* ═══════════════════════════════════════
   PARTICLES / CONFETTI (JS-powered)
═══════════════════════════════════════ */
.particle-canvas {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
}

/* ═══════════════════════════════════════
   NAVBAR
═══════════════════════════════════════ */
.navbar {
  position: sticky; top: 0; z-index: 500;
  height: 64px;
  display: flex; align-items: center;
  padding: 0 32px; gap: 24px;
  background: rgba(6,10,15,0.92);
  border-bottom: 1px solid rgba(255,215,0,0.08);
  backdrop-filter: blur(24px) saturate(2);
}

.nav-logo-wrap {
  display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}
.nav-ball {
  font-size: 22px;
  animation: ball-spin 8s linear infinite;
}
@keyframes ball-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.nav-logo {
  font-family: 'Oswald'; font-weight: 700; font-size: 18px;
  letter-spacing: 5px; text-transform: uppercase;
  background: linear-gradient(90deg, var(--gold3), var(--amber));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.nav-sep { width: 1px; height: 28px; background: rgba(255,255,255,0.06); flex-shrink: 0; }

.nav-links { display: flex; gap: 2px; flex: 1; }
.nav-link {
  padding: 6px 14px; border-radius: 8px; text-decoration: none;
  font-family: 'Barlow Condensed'; font-weight: 700; font-size: 14px; letter-spacing: 1px;
  text-transform: uppercase; color: var(--muted); transition: all 0.15s;
  position: relative;
}
.nav-link::after {
  content: ''; position: absolute; bottom: 2px; left: 14px; right: 14px;
  height: 2px; background: var(--gold); border-radius: 2px;
  transform: scaleX(0); transition: transform 0.2s;
}
.nav-link:hover { color: var(--text2); background: rgba(255,255,255,0.04); }
.nav-link.active { color: var(--gold); }
.nav-link.active::after { transform: scaleX(1); }

.nav-right { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.nav-coins {
  display: flex; align-items: center; gap: 6px;
  background: linear-gradient(135deg, rgba(255,215,0,0.12), rgba(255,140,0,0.08));
  border: 1px solid rgba(255,215,0,0.25); border-radius: 24px;
  padding: 5px 14px 5px 10px; font-weight: 800; font-size: 14px; color: var(--gold);
  font-family: 'Oswald'; letter-spacing: 1px;
}
.coin-icon {
  width: 20px; height: 20px; background: linear-gradient(135deg, var(--gold3), var(--amber));
  border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; color: #000;
}
.nav-head { width: 32px; height: 32px; border-radius: 6px; image-rendering: pixelated; border: 2px solid rgba(255,215,0,0.3); }
.nav-user { font-family: 'Barlow Condensed'; font-weight: 700; font-size: 15px; letter-spacing: 0.5px; }
.nav-logout {
  font-size: 12px; color: var(--muted); text-decoration: none;
  padding: 5px 10px; border-radius: 6px; border: 1px solid transparent;
  transition: all 0.2s; font-family: 'Barlow Condensed'; letter-spacing: 0.5px;
}
.nav-logout:hover { color: var(--fire1); border-color: rgba(255,69,0,0.3); background: rgba(255,69,0,0.06); }

/* ═══════════════════════════════════════
   HERO
═══════════════════════════════════════ */
.hero {
  text-align: center; padding: 100px 20px 80px;
  position: relative; z-index: 1; overflow: hidden;
}
.hero-pitch-lines {
  position: absolute; inset: 0; z-index: 0;
  background:
    repeating-linear-gradient(90deg,
      transparent, transparent 80px,
      rgba(0,255,136,0.025) 80px, rgba(0,255,136,0.025) 81px
    ),
    repeating-linear-gradient(0deg,
      transparent, transparent 80px,
      rgba(0,255,136,0.015) 80px, rgba(0,255,136,0.015) 81px
    );
}
.hero-eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 11px;
  letter-spacing: 4px; text-transform: uppercase; color: var(--neon);
  background: rgba(0,255,136,0.06); border: 1px solid rgba(0,255,136,0.2);
  padding: 7px 20px; border-radius: 100px; margin-bottom: 32px;
}
.hero-title {
  font-family: 'Oswald'; font-weight: 700;
  font-size: clamp(72px, 13vw, 150px); line-height: 0.85;
  letter-spacing: -2px;
  background: linear-gradient(170deg, #ffffff 0%, var(--gold3) 40%, var(--amber) 70%, var(--fire1) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-bottom: 26px; position: relative; z-index: 1;
  text-shadow: none;
}
.hero-title-glow {
  position: absolute; inset: 0; z-index: -1;
  font-family: 'Oswald'; font-weight: 700;
  font-size: clamp(72px, 13vw, 150px); line-height: 0.85;
  letter-spacing: -2px; color: transparent;
  -webkit-text-stroke: 1px rgba(255,215,0,0.1);
  filter: blur(20px);
}
.hero-sub {
  color: var(--text2); font-size: 17px; max-width: 460px;
  margin: 0 auto 50px; line-height: 1.8; font-weight: 500;
}

/* ═══════════════════════════════════════
   BUTTONS
═══════════════════════════════════════ */
.btn {
  display: inline-flex; align-items: center; gap: 10px;
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 16px;
  letter-spacing: 2px; text-transform: uppercase; text-decoration: none;
  padding: 14px 36px; border-radius: 4px; border: none; cursor: pointer;
  transition: all 0.2s; position: relative; overflow: hidden;
}
.btn::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(45deg, transparent 40%, rgba(255,255,255,0.1) 50%, transparent 60%);
  transform: translateX(-100%); transition: transform 0.4s;
}
.btn:hover::after { transform: translateX(100%); }
.btn-fire {
  background: linear-gradient(135deg, var(--fire2), var(--fire1), var(--amber));
  color: #fff; box-shadow: 0 6px 30px rgba(255,69,0,0.4);
  clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 100%, 12px 100%);
}
.btn-fire:hover { transform: translateY(-3px); box-shadow: 0 12px 40px rgba(255,69,0,0.6); }
.btn-neon {
  background: transparent; color: var(--neon);
  border: 2px solid var(--neon); box-shadow: 0 0 20px rgba(0,255,136,0.2);
}
.btn-neon:hover { background: rgba(0,255,136,0.08); box-shadow: 0 0 40px rgba(0,255,136,0.4); }
.btn-gold {
  background: linear-gradient(135deg, var(--gold3), var(--gold2));
  color: #000; font-weight: 900;
}
.btn-gold:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(255,215,0,0.4); }

/* ═══════════════════════════════════════
   CARDS
═══════════════════════════════════════ */
.card {
  background: var(--card); border: 1px solid var(--border2);
  border-radius: 12px; padding: 24px; position: relative; overflow: hidden;
}
.card::before {
  content: ''; position: absolute; inset: 0; border-radius: 12px;
  background: linear-gradient(135deg, rgba(255,215,0,0.03) 0%, transparent 60%);
  pointer-events: none;
}

/* ═══════════════════════════════════════
   LAYOUT
═══════════════════════════════════════ */
.wrap { max-width: 1260px; margin: 0 auto; padding: 0 28px; position: relative; z-index: 1; }
.wrap-sm { max-width: 560px; margin: 0 auto; padding: 0 24px; position: relative; z-index: 1; }
.page { padding: 36px 0 120px; }

/* ═══════════════════════════════════════
   SECTION HEADERS
═══════════════════════════════════════ */
.sec-header { margin-bottom: 20px; }
.sec-tag {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 10px;
  letter-spacing: 4px; text-transform: uppercase; color: var(--amber);
  background: rgba(255,165,0,0.08); border: 1px solid rgba(255,165,0,0.2);
  padding: 4px 12px; border-radius: 4px; margin-bottom: 8px;
}
.sec-title {
  font-family: 'Oswald'; font-weight: 700; font-size: 32px;
  letter-spacing: 1px; color: var(--text);
}
.sec-sub { color: var(--muted); font-size: 13px; margin-top: 4px; font-weight: 500; }

/* ═══════════════════════════════════════
   TABS
═══════════════════════════════════════ */
.tabs-wrap {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 20px;
  padding: 6px; background: var(--bg3); border-radius: 10px;
  border: 1px solid var(--border3);
}
.tab {
  padding: 7px 14px; border-radius: 7px; cursor: pointer;
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 13px;
  letter-spacing: 1.5px; text-transform: uppercase;
  white-space: nowrap; transition: all 0.15s; text-decoration: none;
  color: var(--muted);
}
.tab:hover { color: var(--text2); background: rgba(255,255,255,0.04); }
.tab.active {
  background: linear-gradient(135deg, rgba(255,215,0,0.15), rgba(255,140,0,0.1));
  border: 1px solid rgba(255,215,0,0.25); color: var(--gold);
}

/* ═══════════════════════════════════════
   MATCH CARDS – WM STYLE
═══════════════════════════════════════ */
.match-list { display: flex; flex-direction: column; gap: 8px; }

.match-card {
  display: grid;
  grid-template-columns: 1fr 160px 1fr 240px;
  align-items: center;
  background: var(--card2);
  border: 1px solid var(--border3);
  border-radius: 10px;
  overflow: hidden;
  transition: all 0.2s;
  position: relative;
}
.match-card:hover {
  border-color: rgba(255,255,255,0.08);
  transform: translateY(-1px);
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}

/* Color stripe */
.match-card .mc-stripe {
  position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
}
.mc-stripe-upcoming { background: rgba(0,212,255,0.5); }
.mc-stripe-soon { background: var(--amber); }
.mc-stripe-live { background: var(--live); animation: stripe-pulse 1.2s ease-in-out infinite; }
.mc-stripe-final { background: rgba(74,90,122,0.4); }
.mc-stripe-tipped { background: var(--neon); opacity: 0.7; }

@keyframes stripe-pulse { 0%,100%{opacity:1} 50%{opacity:0.2} }

.match-card.is-live {
  background: linear-gradient(90deg, rgba(255,48,48,0.06) 0%, var(--card2) 40%);
  border-color: rgba(255,48,48,0.2);
}
.match-card.is-final { opacity: 0.7; }
.match-card.is-final:hover { opacity: 1; }
.match-card.is-tipped { border-color: rgba(0,255,136,0.15); }

/* Team cells */
.mc-team-home, .mc-team-away {
  padding: 16px 20px 16px 24px;
  display: flex; align-items: center; gap: 10px;
}
.mc-team-home { justify-content: flex-end; flex-direction: row-reverse; }
.mc-team-away { justify-content: flex-start; }

.mc-team-name {
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 16px;
  letter-spacing: 0.5px; text-transform: uppercase; white-space: nowrap;
}

/* Center score */
.mc-center {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 10px 4px; gap: 5px;
}
.mc-score-row {
  display: flex; align-items: center; gap: 6px;
}
.mc-score-num {
  font-family: 'Oswald'; font-weight: 700; font-size: 34px; line-height: 1;
  min-width: 28px; text-align: center;
}
.mc-score-sep {
  font-family: 'Oswald'; font-weight: 300; font-size: 28px; color: var(--bg3);
  line-height: 1;
}
.live-num { color: var(--live2); }
.final-num { color: var(--text); }
.upcoming-num { color: var(--muted); font-size: 18px; }

.mc-vs {
  font-family: 'Barlow Condensed'; font-weight: 900; font-size: 13px;
  letter-spacing: 3px; color: var(--muted); text-transform: uppercase;
}

.status-chip {
  display: inline-flex; align-items: center; gap: 4px;
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 9px;
  letter-spacing: 2px; text-transform: uppercase;
  padding: 3px 9px; border-radius: 100px;
}
.chip-live {
  background: rgba(255,48,48,0.2); border: 1px solid rgba(255,48,48,0.4); color: var(--live2);
}
.chip-final {
  background: rgba(74,90,122,0.2); border: 1px solid rgba(74,90,122,0.3); color: var(--muted);
}
.chip-soon {
  background: rgba(255,165,0,0.15); border: 1px solid rgba(255,165,0,0.3); color: var(--amber);
}
.chip-upcoming {
  background: rgba(0,212,255,0.1); border: 1px solid rgba(0,212,255,0.2); color: var(--cyan);
}
.blink-dot {
  width: 5px; height: 5px; border-radius: 50%; background: currentColor;
  animation: blink 1s step-end infinite;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }

/* Kickoff time */
.mc-kickoff {
  font-family: 'Oswald'; font-weight: 600; font-size: 18px; color: var(--text2);
  letter-spacing: 1px;
}
.mc-date-text {
  font-family: 'Barlow Condensed'; font-size: 10px; font-weight: 700;
  color: var(--muted); letter-spacing: 1.5px; text-transform: uppercase;
}

/* Action area */
.mc-action { padding: 14px 18px; }
.tipp-form-row { display: flex; align-items: center; gap: 5px; justify-content: flex-end; margin-top: 4px; }

.score-in {
  width: 40px; height: 36px; background: var(--bg3);
  border: 1px solid rgba(255,255,255,0.1); color: #fff;
  border-radius: 6px; text-align: center;
  font-family: 'Oswald'; font-size: 20px; font-weight: 600;
  -moz-appearance: textfield; appearance: none; transition: all 0.15s;
}
.score-in::-webkit-inner-spin-button, .score-in::-webkit-outer-spin-button { -webkit-appearance: none; }
.score-in:focus {
  outline: none; border-color: var(--gold); background: var(--bg2);
  box-shadow: 0 0 0 3px rgba(255,215,0,0.1);
}
.score-in-sep { font-family: 'Oswald'; font-size: 18px; color: var(--muted); }

.tipp-submit {
  background: linear-gradient(135deg, var(--gold3), var(--amber));
  color: #000; border: none; border-radius: 6px;
  padding: 6px 12px; font-family: 'Barlow Condensed'; font-weight: 900;
  font-size: 12px; letter-spacing: 1px; text-transform: uppercase;
  cursor: pointer; transition: all 0.2s; white-space: nowrap;
}
.tipp-submit:hover { transform: scale(1.04); box-shadow: 0 4px 16px rgba(255,215,0,0.4); }

.tipp-saved-wrap { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; }
.tipp-saved-score {
  font-family: 'Oswald'; font-weight: 700; font-size: 16px; color: var(--neon);
  display: flex; align-items: center; gap: 6px;
}
.tipp-eval { font-family: 'Barlow Condensed'; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
.eval-perfekt { color: var(--gold); }
.eval-gut { color: var(--neon2); }
.eval-tendenz { color: var(--cyan); }
.eval-falsch { color: var(--fire1); }
.eval-open { color: var(--muted); }

.badge-locked {
  font-family: 'Barlow Condensed'; font-size: 12px; font-weight: 700; letter-spacing: 0.5px;
  color: var(--live); display: flex; align-items: center; gap: 5px;
}
.badge-missed { font-family: 'Barlow Condensed'; font-size: 12px; font-weight: 700; color: var(--muted); }
.badge-soon-warn {
  font-family: 'Barlow Condensed'; font-size: 11px; font-weight: 700;
  color: var(--amber); letter-spacing: 0.5px;
}

/* ═══════════════════════════════════════
   LIVE BANNER
═══════════════════════════════════════ */
.live-banner {
  background: linear-gradient(90deg, rgba(255,48,48,0.12) 0%, rgba(255,48,48,0.04) 100%);
  border: 1px solid rgba(255,48,48,0.3); border-radius: 10px;
  padding: 12px 20px; margin-bottom: 16px;
  display: flex; align-items: center; gap: 16px; overflow: hidden;
}
.live-banner-label {
  font-family: 'Barlow Condensed'; font-weight: 900; font-size: 12px;
  letter-spacing: 3px; text-transform: uppercase; color: var(--live);
  display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.live-ticker-items {
  display: flex; gap: 24px; overflow: hidden; flex: 1;
}
.live-ticker-item {
  font-family: 'Barlow Condensed'; font-weight: 700; font-size: 14px;
  white-space: nowrap; color: var(--text2);
}
.live-ticker-score { color: var(--live2); font-weight: 900; font-size: 16px; font-family: 'Oswald'; }

/* ═══════════════════════════════════════
   GRUPPE HEADER
═══════════════════════════════════════ */
.gruppe-header {
  display: flex; align-items: center; gap: 20px;
  padding: 0 0 20px; margin-bottom: 20px;
  border-bottom: 1px solid var(--border3);
}
.gruppe-letter {
  font-family: 'Oswald'; font-weight: 700; font-size: 64px; line-height: 1;
  background: linear-gradient(160deg, var(--gold3), var(--amber));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  min-width: 48px;
}
.gruppe-team-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.gruppe-pill {
  display: flex; align-items: center; gap: 6px;
  background: var(--bg3); border: 1px solid var(--border2);
  border-radius: 6px; padding: 5px 12px 5px 8px;
  font-family: 'Barlow Condensed'; font-weight: 700; font-size: 13px;
  letter-spacing: 0.5px; transition: all 0.15s;
}
.gruppe-pill.my-team {
  background: rgba(255,215,0,0.07); border-color: rgba(255,215,0,0.3); color: var(--gold);
}

/* ═══════════════════════════════════════
   STATS CARDS
═══════════════════════════════════════ */
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 16px; }
.stat-box {
  background: var(--card); border: 1px solid var(--border3); border-radius: 12px;
  padding: 20px 16px; text-align: center; position: relative; overflow: hidden;
}
.stat-box::after {
  content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
  opacity: 0.3;
}
.stat-num {
  font-family: 'Oswald'; font-weight: 700; font-size: 48px; line-height: 1;
  background: linear-gradient(135deg, var(--gold3), var(--amber));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.stat-label {
  font-family: 'Barlow Condensed'; font-weight: 700; font-size: 10px;
  letter-spacing: 2px; text-transform: uppercase; color: var(--muted); margin-top: 4px;
}

/* ═══════════════════════════════════════
   PROGRESS BAR
═══════════════════════════════════════ */
.prog-track {
  height: 6px; background: var(--bg3); border-radius: 3px; overflow: hidden;
}
.prog-fill {
  height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, var(--neon2), var(--neon));
  transition: width 1s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 0 10px rgba(0,255,136,0.4);
}

/* ═══════════════════════════════════════
   PROFILE CARD
═══════════════════════════════════════ */
.profile-card {
  background: var(--card); border: 1px solid var(--border2);
  border-radius: 12px; padding: 24px; text-align: center;
}
.profile-head {
  width: 80px; height: 80px; border-radius: 10px;
  image-rendering: pixelated;
  border: 3px solid transparent;
  background: linear-gradient(var(--card), var(--card)) padding-box,
              linear-gradient(135deg, var(--gold3), var(--amber)) border-box;
}
.profile-name { font-family: 'Oswald'; font-weight: 700; font-size: 24px; letter-spacing: 2px; margin-top: 10px; }
.profile-sub { font-family: 'Barlow Condensed'; font-weight: 600; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: var(--neon2); margin-top: 2px; }
.fav-team-row {
  display: flex; align-items: center; gap: 10px;
  background: rgba(255,215,0,0.05); border: 1px solid rgba(255,215,0,0.15);
  border-radius: 8px; padding: 10px 14px; margin-top: 14px; text-align: left;
}
.fav-team-name { font-family: 'Barlow Condensed'; font-weight: 800; font-size: 15px; color: var(--gold); letter-spacing: 0.5px; }
.fav-team-sub { font-size: 11px; color: var(--muted); font-weight: 600; }

/* ═══════════════════════════════════════
   LEADERBOARD
═══════════════════════════════════════ */
.lb-search-wrap {
  position: relative; margin-bottom: 16px;
}
.lb-search {
  width: 100%; padding: 12px 16px 12px 44px;
  background: var(--bg3); border: 1px solid var(--border2);
  border-radius: 10px; color: var(--text); font-family: 'Barlow', sans-serif;
  font-size: 15px; font-weight: 500; outline: none; transition: all 0.2s;
}
.lb-search:focus { border-color: var(--gold); box-shadow: 0 0 0 3px rgba(255,215,0,0.08); }
.lb-search::placeholder { color: var(--muted); }
.lb-search-icon {
  position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
  color: var(--muted); font-size: 18px; pointer-events: none;
}

.lb-header-row {
  display: grid; grid-template-columns: 56px 1fr 80px 100px;
  gap: 12px; padding: 8px 18px;
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 10px;
  letter-spacing: 2px; text-transform: uppercase; color: var(--muted);
  margin-bottom: 8px;
}

.lb-row {
  display: grid; grid-template-columns: 56px 1fr 80px 100px;
  align-items: center; gap: 12px;
  padding: 13px 18px; border-radius: 10px;
  border: 1px solid transparent; margin-bottom: 6px;
  transition: all 0.2s; cursor: default;
}
.lb-row:hover { background: rgba(255,255,255,0.03); border-color: var(--border2); }
.lb-row.rank-1 {
  background: linear-gradient(90deg, rgba(255,215,0,0.1), rgba(255,165,0,0.04));
  border-color: rgba(255,215,0,0.25);
}
.lb-row.rank-2 {
  background: rgba(192,208,224,0.04); border-color: rgba(192,208,224,0.15);
}
.lb-row.rank-3 {
  background: rgba(205,140,80,0.06); border-color: rgba(205,140,80,0.2);
}
.lb-row.rank-me {
  border-color: rgba(0,212,255,0.35); background: rgba(0,212,255,0.04);
}
.lb-row.lb-hidden { display: none; }

.lb-rank {
  font-family: 'Oswald'; font-weight: 700; font-size: 28px; text-align: center;
  line-height: 1; color: var(--muted);
}
.lb-rank.r1 { color: var(--r1); text-shadow: 0 0 16px rgba(255,215,0,0.5); }
.lb-rank.r2 { color: var(--r2); }
.lb-rank.r3 { color: var(--r3); }

.lb-user-cell { display: flex; align-items: center; gap: 12px; }
.lb-head { width: 32px; height: 32px; border-radius: 6px; image-rendering: pixelated; }
.lb-name { font-family: 'Barlow Condensed'; font-weight: 800; font-size: 16px; letter-spacing: 0.5px; }
.lb-team-small { font-size: 12px; color: var(--muted); font-weight: 600; display: flex; align-items: center; gap: 4px; }
.lb-me-badge {
  font-family: 'Barlow Condensed'; font-weight: 800; font-size: 9px;
  letter-spacing: 2px; background: rgba(0,212,255,0.15); color: var(--cyan);
  border: 1px solid rgba(0,212,255,0.3); padding: 2px 8px; border-radius: 4px;
  text-transform: uppercase;
}
.lb-tipps-cell {
  font-family: 'Barlow Condensed'; font-weight: 700; font-size: 15px;
  color: var(--muted); text-align: center;
}
.lb-pts {
  font-family: 'Oswald'; font-weight: 700; font-size: 24px; text-align: right;
  background: linear-gradient(135deg, var(--gold3), var(--amber));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}

/* Podium */
.podium-wrap {
  display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 36px;
}
.podium-card {
  border-radius: 12px; padding: 24px 16px; text-align: center;
  position: relative; overflow: hidden; border: 1px solid;
}
.podium-1 {
  background: linear-gradient(160deg, rgba(255,215,0,0.12), rgba(255,165,0,0.06));
  border-color: rgba(255,215,0,0.35); order: 1;
}
.podium-2 {
  background: rgba(192,208,224,0.05); border-color: rgba(192,208,224,0.2);
  order: 0; margin-top: 24px;
}
.podium-3 {
  background: rgba(205,140,80,0.06); border-color: rgba(205,140,80,0.2);
  order: 2; margin-top: 36px;
}
.podium-medal { font-size: 36px; margin-bottom: 10px; }
.podium-head {
  width: 56px; height: 56px; border-radius: 8px; image-rendering: pixelated;
  border: 2px solid rgba(255,215,0,0.3); margin: 0 auto 10px;
}
.podium-name { font-family: 'Oswald'; font-weight: 700; font-size: 18px; letter-spacing: 1px; }
.podium-pts {
  font-family: 'Oswald'; font-weight: 700; font-size: 28px;
  background: linear-gradient(135deg, var(--gold3), var(--amber));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-top: 6px;
}

/* ═══════════════════════════════════════
   PUNKTE SYSTEM PAGE
═══════════════════════════════════════ */
.pts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
.pts-row {
  display: flex; align-items: center; justify-content: space-between;
  background: var(--bg3); border: 1px solid var(--border2);
  border-radius: 8px; padding: 16px 20px; gap: 12px;
}
.pts-row.top { border-color: rgba(0,255,136,0.3); background: rgba(0,255,136,0.04); }
.pts-label { font-weight: 600; font-size: 15px; }
.pts-sub { font-size: 12px; color: var(--muted); margin-top: 2px; font-weight: 500; }
.pts-val {
  font-family: 'Oswald'; font-weight: 700; font-size: 26px;
  background: linear-gradient(135deg, var(--gold3), var(--amber));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  white-space: nowrap;
}
.pts-val.neg { background: linear-gradient(135deg, var(--fire2), var(--fire1)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

/* ═══════════════════════════════════════
   REGISTER PAGE
═══════════════════════════════════════ */
.code-display {
  font-family: 'Oswald'; font-weight: 700; font-size: 72px; letter-spacing: 20px;
  color: var(--neon); text-align: center; padding: 28px 20px;
  background: rgba(0,255,136,0.04); border: 2px solid rgba(0,255,136,0.25);
  border-radius: 12px; margin: 24px 0;
  text-shadow: 0 0 30px rgba(0,255,136,0.4);
  animation: code-glow 2s ease-in-out infinite;
}
@keyframes code-glow {
  0%,100% { text-shadow: 0 0 20px rgba(0,255,136,0.4); }
  50% { text-shadow: 0 0 40px rgba(0,255,136,0.8); }
}
.step-card {
  background: var(--bg3); border: 1px solid var(--border2); border-radius: 10px;
  padding: 20px; line-height: 2.4; font-size: 14px;
}
.step-card code {
  background: rgba(0,212,255,0.1); color: var(--cyan);
  border: 1px solid rgba(0,212,255,0.2);
  border-radius: 5px; padding: 2px 10px; font-size: 13px; font-family: 'Courier New', monospace;
}

/* Spinner */
.spinner {
  width: 36px; height: 36px; margin: 16px auto;
  border: 3px solid rgba(255,255,255,0.08); border-top-color: var(--neon);
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Alerts */
.alert { padding: 14px 20px; border-radius: 8px; margin-bottom: 14px; font-size: 14px; font-weight: 600; }
.alert-neon { background: rgba(0,255,136,0.07); border: 1px solid rgba(0,255,136,0.25); color: var(--neon); }
.alert-gold { background: rgba(255,215,0,0.07); border: 1px solid rgba(255,215,0,0.2); color: var(--gold); text-align: center; }

.prog-anim { height: 3px; background: var(--bg3); border-radius: 2px; margin-top: 16px; overflow: hidden; }
.prog-anim-fill {
  height: 100%; width: 0%;
  background: linear-gradient(90deg, var(--neon2), var(--neon));
  animation: prog 60s linear forwards; border-radius: 2px;
}
@keyframes prog { to { width: 100%; } }

/* ═══════════════════════════════════════
   CHOOSE TEAM PAGE
═══════════════════════════════════════ */
.team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(155px,1fr)); gap: 10px; }
.team-btn {
  position: relative; overflow: hidden;
  background: linear-gradient(160deg, var(--c1), var(--c2));
  border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
  padding: 0; cursor: pointer; min-height: 126px;
  display: flex; flex-direction: column; align-items: center; justify-content: flex-end;
  font-family: inherit; transition: transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}
.team-btn:hover {
  transform: translateY(-5px) scale(1.03);
  box-shadow: 0 12px 32px rgba(0,0,0,0.7), 0 0 0 2px rgba(255,215,0,0.5);
}
.team-btn-overlay { position: absolute; inset: 0; background: linear-gradient(180deg, transparent 35%, rgba(0,0,0,0.65) 100%); z-index: 1; }
.team-btn-flag {
  position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
  width: 66px; height: 44px; object-fit: cover; border-radius: 4px;
  box-shadow: 0 3px 14px rgba(0,0,0,0.6); z-index: 2;
}
.team-btn-name {
  position: relative; z-index: 3; color: #fff;
  font-family: 'Barlow Condensed'; font-weight: 900; font-size: 14px;
  letter-spacing: 0.5px; text-transform: uppercase;
  text-shadow: 0 1px 8px rgba(0,0,0,0.9); padding: 0 10px; text-align: center;
  line-height: 1.2; margin-top: 68px;
}
.team-btn-group {
  position: relative; z-index: 3; color: rgba(255,255,255,0.6);
  font-size: 10px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase;
  padding-bottom: 10px; margin-top: 3px;
}

/* ═══════════════════════════════════════
   SCROLL ANIMATIONS
═══════════════════════════════════════ */
.fade-up {
  opacity: 0; transform: translateY(20px);
  animation: fadeUp 0.5s ease forwards;
}
@keyframes fadeUp { to { opacity: 1; transform: translateY(0); } }

.stagger-1 { animation-delay: 0.05s; }
.stagger-2 { animation-delay: 0.10s; }
.stagger-3 { animation-delay: 0.15s; }
.stagger-4 { animation-delay: 0.20s; }
.stagger-5 { animation-delay: 0.25s; }
.stagger-6 { animation-delay: 0.30s; }

/* ═══════════════════════════════════════
   MISC
═══════════════════════════════════════ */
.divider { height: 1px; background: var(--border2); margin: 24px 0; }
.mc-head-avatar { width: 80px; height: 80px; border-radius: 10px; image-rendering: pixelated; }
.text-gold { color: var(--gold); }
.text-neon { color: var(--neon); }
.text-muted { color: var(--muted); }
.fw900 { font-weight: 900; }
.font-cond { font-family: 'Barlow Condensed'; }
.font-oswald { font-family: 'Oswald'; }

/* SCROLLBAR */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: rgba(255,215,0,0.2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,215,0,0.4); }

/* RESPONSIVE */
@media(max-width:1000px){
  .match-card { grid-template-columns: 1fr 130px 1fr; }
  .match-card .mc-action { display: none; }
}
@media(max-width:700px){
  .navbar { padding: 0 16px; }
  .nav-links { display: none; }
  .stats-grid { grid-template-columns: 1fr 1fr 1fr; }
  .match-card { grid-template-columns: 1fr 100px 1fr; }
  .mc-team-name { font-size: 13px; }
  .mc-score-num { font-size: 26px; }
  .pts-grid { grid-template-columns: 1fr; }
  .podium-wrap { gap: 8px; }
  .podium-2, .podium-3 { margin-top: 0; }
  .lb-row { grid-template-columns: 44px 1fr 90px; }
  .lb-tipps-cell { display: none; }
}
</style>
"""

BASE_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>WM 2026 – GrieferGames Tipp-Portal</title>
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
    links = ""
    for pid, url, label in pages:
        ac = "active" if active_page == pid else ""
        links += f'<a href="{url}" class="nav-link {ac}">{label}</a>'
    return f"""
    <nav class="navbar">
      <div class="nav-logo-wrap">
        <span class="nav-ball">⚽</span>
        <span class="nav-logo">WM 2026</span>
      </div>
      <div class="nav-sep"></div>
      <div class="nav-links">{links}</div>
      <div class="nav-right">
        {team_flag}
        <img class="nav-head" src="https://mc-heads.net/avatar/{username}/32" alt="" onerror="this.style.display='none'">
        <span class="nav-user">{username}</span>
        <div class="nav-coins"><div class="coin-icon">◈</div>{points:,}</div>
        <a href="/logout" class="nav-logout">Abmelden</a>
      </div>
    </nav>
    """

# ==========================================
# HOME
# ==========================================
HOME_HTML = BASE_HTML + """
<canvas class="particle-canvas" id="particles"></canvas>
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;position:relative;z-index:1;">
  <div class="hero">
    <div class="hero-pitch-lines"></div>
    <div class="hero-eyebrow fade-up">⚽ GrieferGames × FIFA World Cup 2026</div>
    <div style="position:relative;display:inline-block;">
      <div class="hero-title fade-up stagger-1">WM 2026<br>TIPP<br>PORTAL</div>
    </div>
    <p class="hero-sub fade-up stagger-2">Tippe alle 72 Gruppenspiele der Weltmeisterschaft und beweise, dass du der beste Fußball-Prophet auf GrieferGames bist.</p>
    <div style="display:flex;gap:14px;justify-content:center;flex-wrap:wrap;" class="fade-up stagger-3">
      <a href="/register" class="btn btn-fire">⚡ Jetzt mitmachen</a>
      <a href="#features" class="btn btn-neon">Mehr erfahren</a>
    </div>
  </div>

  <div id="features" class="wrap" style="padding-bottom:100px;max-width:900px;">
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;text-align:center;">
      <div class="card fade-up stagger-1" style="border-color:rgba(0,255,136,0.12);">
        <div style="font-size:40px;margin-bottom:12px;">🌍</div>
        <div style="font-family:'Oswald';font-size:28px;font-weight:700;color:var(--gold);letter-spacing:1px;">48 TEAMS</div>
        <div style="font-size:13px;color:var(--muted);margin-top:4px;font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;">12 GRUPPEN</div>
      </div>
      <div class="card fade-up stagger-2" style="border-color:rgba(255,165,0,0.12);">
        <div style="font-size:40px;margin-bottom:12px;">⚽</div>
        <div style="font-family:'Oswald';font-size:28px;font-weight:700;color:var(--gold);letter-spacing:1px;">72 SPIELE</div>
        <div style="font-size:13px;color:var(--muted);margin-top:4px;font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;">GRUPPENPHASE</div>
      </div>
      <div class="card fade-up stagger-3" style="border-color:rgba(255,69,0,0.12);">
        <div style="font-size:40px;margin-bottom:12px;">🏆</div>
        <div style="font-family:'Oswald';font-size:28px;font-weight:700;color:var(--gold);letter-spacing:1px;">BIS 1.000</div>
        <div style="font-size:13px;color:var(--muted);margin-top:4px;font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;">PUNKTE PRO TIPP</div>
      </div>
    </div>

    <!-- Punkte-Vorschau -->
    <div class="card fade-up stagger-4" style="margin-top:24px;border-color:rgba(255,215,0,0.12);">
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;text-align:center;">
        <div>
          <div style="font-family:'Oswald';font-size:32px;font-weight:700;color:var(--neon);">1.000</div>
          <div style="font-size:11px;color:var(--muted);font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;margin-top:3px;">🎯 PERFEKT</div>
        </div>
        <div>
          <div style="font-family:'Oswald';font-size:32px;font-weight:700;color:var(--gold);">500</div>
          <div style="font-size:11px;color:var(--muted);font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;margin-top:3px;">⚡ TORDIFFERENZ</div>
        </div>
        <div>
          <div style="font-family:'Oswald';font-size:32px;font-weight:700;color:var(--cyan);">200</div>
          <div style="font-size:11px;color:var(--muted);font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;margin-top:3px;">✅ TENDENZ</div>
        </div>
        <div>
          <div style="font-family:'Oswald';font-size:32px;font-weight:700;color:var(--fire1);">–50</div>
          <div style="font-size:11px;color:var(--muted);font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;margin-top:3px;">💸 EINSATZ</div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
// Particle System – floating footballs & confetti
const canvas = document.getElementById('particles');
const ctx = canvas.getContext('2d');
canvas.width = window.innerWidth;
canvas.height = window.innerHeight;
window.addEventListener('resize', () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight; });

const particles = [];
const EMOJIS = ['⚽','🏆','⭐','🔥'];

for (let i = 0; i < 18; i++) {
  particles.push({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vy: -(0.2 + Math.random() * 0.5),
    vx: (Math.random() - 0.5) * 0.3,
    size: 14 + Math.random() * 18,
    opacity: 0.04 + Math.random() * 0.07,
    emoji: EMOJIS[Math.floor(Math.random() * EMOJIS.length)],
    rot: Math.random() * Math.PI * 2,
    rotSpeed: (Math.random() - 0.5) * 0.015
  });
}

function animParticles() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (const p of particles) {
    p.y += p.vy; p.x += p.vx; p.rot += p.rotSpeed;
    if (p.y < -40) { p.y = canvas.height + 40; p.x = Math.random() * canvas.width; }
    ctx.save();
    ctx.globalAlpha = p.opacity;
    ctx.font = p.size + 'px serif';
    ctx.translate(p.x, p.y);
    ctx.rotate(p.rot);
    ctx.fillText(p.emoji, -p.size/2, p.size/2);
    ctx.restore();
  }
  requestAnimationFrame(animParticles);
}
animParticles();
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

@app.route('/register')
def register():
    code = str(random.randint(1000, 9999))
    active_codes[code] = {"status": "pending", "username": None}
    return BASE_HTML + f"""
    <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;position:relative;z-index:1;">
      <div style="width:100%;max-width:520px;">
        <div class="card fade-up" style="border-color:rgba(0,255,136,0.15);">
          <div style="text-align:center;margin-bottom:24px;">
            <div style="font-size:48px;margin-bottom:12px;">🔐</div>
            <div class="hero-eyebrow" style="display:inline-flex;margin-bottom:14px;font-family:'Barlow Condensed';">Minecraft Verifizierung</div>
            <h2 style="font-family:'Oswald';font-size:36px;font-weight:700;letter-spacing:2px;">DEIN CODE</h2>
          </div>
          <div class="code-display">{code}</div>
          <div class="step-card" style="margin-bottom:20px;">
            <div style="font-family:'Barlow Condensed';font-weight:900;font-size:14px;letter-spacing:2px;color:var(--amber);margin-bottom:12px;text-transform:uppercase;">📋 So geht's:</div>
            <div>1. Logge dich auf <strong style="color:var(--text);">GrieferGames</strong> ein</div>
            <div>2. Schreibe diese Nachricht im Chat:</div>
            <div style="margin:10px 0 0 14px;">
              <code>/msg Lattenrost1234 #verifyWM {code}</code>
            </div>
            <div style="margin-top:14px;color:var(--muted);font-size:13px;font-family:'Barlow Condensed';font-weight:600;">
              ⚡ Lass dieses Fenster offen – das System erkennt die Nachricht automatisch.
            </div>
          </div>
          <div id="status" class="alert alert-gold">
            <div class="spinner"></div>
            Warte auf Chat-Nachricht...
          </div>
          <div class="prog-anim"><div class="prog-anim-fill"></div></div>
        </div>
      </div>
    </div>
    <script>
      const iv = setInterval(() => {{
        fetch('/api/check_status/{code}').then(r=>r.json()).then(d=>{{
          if(d.status==='verified'){{
            clearInterval(iv);
            const el = document.getElementById('status');
            el.innerHTML='✅ Verifiziert! Weiterleitung...';
            el.className='alert alert-neon';
            setTimeout(()=>window.location.href='/login_success/{code}',900);
          }}
        }});
      }},1000);
    </script>
    </body></html>
    """

@app.route('/api/check_status/<code>')
def check_status(code):
    if code in active_codes:
        return jsonify({"status": active_codes[code]["status"]})
    return jsonify({"status": "not_found"})

@app.route('/api/verify', methods=['POST'])
def api_verify():
    data = request.get_json()
    secret = data.get("secret", "")
    code = data.get("code", "")
    username = data.get("username", "")
    if secret != "GG_VERIFY_SECRET_2026":
        return jsonify({"error": "Unauthorized"}), 403
    if code in active_codes and active_codes[code]["status"] == "pending":
        active_codes[code]["status"] = "verified"
        active_codes[code]["username"] = username
        if username not in user_db:
            user_db[username] = {
                "points": 1000, "tipps": {}, "lieblingsteam": None,
                "registered": datetime.datetime.now().strftime("%d.%m.%Y")
            }
            save_data()
        return jsonify({"success": True})
    return jsonify({"error": "Code nicht gefunden"}), 404

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

@app.route('/login_success/<code>')
def login_success(code):
    if code in active_codes and active_codes[code]["status"] == "verified":
        username = active_codes[code]["username"]
        session["username"] = username
        session.permanent = True
        del active_codes[code]
        if username in user_db and user_db[username].get("lieblingsteam"):
            return redirect(url_for('dashboard'))
        return redirect(url_for('choose_team'))
    return "Fehler", 403

@app.route('/choose_team', methods=['GET','POST'])
def choose_team():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if request.method == 'POST':
        team_name = request.form.get('team')
        if username in user_db:
            user_db[username]["lieblingsteam"] = team_name
            save_data()
        return redirect(url_for('dashboard'))

    TEAM_COLORS = {
        "Mexiko":("1a7c3e","d52b1e"),"Südkorea":("cd2e3a","003478"),"Südafrika":("007749","ffb612"),
        "Tschechien":("d7141a","11457e"),"Schweiz":("cc0000","880000"),"Kanada":("cc0000","8b0000"),
        "Katar":("8d1b3d","4a0e22"),"Bosnien":("002395","fcd116"),"Brasilien":("009c3b","fedf00"),
        "Marokko":("c1272d","006233"),"Schottland":("003580","1a5fa8"),"Haiti":("00209f","d21034"),
        "USA":("b22234","3c3b6e"),"Paraguay":("d52b1e","009ada"),"Australien":("00843d","ffcd00"),
        "Türkei":("e30a17","a00808"),"Deutschland":("111111","dd0000"),"Elfenbeinküste":("f77f00","009a44"),
        "Ecuador":("ffd100","0072ce"),"Ungarn":("ce2939","477050"),"Niederlande":("ff5500","cc3300"),
        "Japan":("bc002d","7a001d"),"Tunesien":("cc0000","880000"),"Schweden":("006aa7","004f80"),
        "Belgien":("111111","ef3340"),"Ägypten":("ce1126","8a0a1a"),"Iran":("239f40","157a2e"),
        "Neuseeland":("00247d","8b0000"),"Spanien":("aa151b","780f12"),"Uruguay":("5aaee3","2a7ab5"),
        "Saudi-Arabien":("006c35","004a24"),"Kap Verde":("003893","8b1a1a"),"Frankreich":("002395","00175e"),
        "Senegal":("00853f","005529"),"Norwegen":("ef2b2d","002868"),"Kroatien":("cc0000","001a99"),
        "England":("cf142b","8b0d1c"),"Kolumbien":("fcd116","b8960f"),"Serbien":("c6363c","0c4076"),
        "Venezuela":("cf142b","003087"),"Portugal":("006600","cc0000"),"Argentinien":("74acdf","4a8cca"),
        "Chile":("d52b1e","003087"),"Albanien":("c80000","800000"),"Italien":("009246","ce2b37"),
        "Kamerun":("007a5e","ce1126"),"Nigeria":("008751","005535"),"Österreich":("cc0000","880000"),
    }

    groups_html = ""
    for gruppe_key, gruppe_data in WM_GRUPPEN.items():
        teams_html = ""
        for team in gruppe_data["teams"]:
            code = team['code']
            special_map = {"sco": "gb-sct", "eng": "gb-eng"}
            flag_code = special_map.get(code, code)
            flag_src = f"https://flagcdn.com/h56/{flag_code}.png"
            c1, c2 = TEAM_COLORS.get(team['name'], ("1a2a4a", "2d4a8a"))
            teams_html += f"""
            <button type="submit" name="team" value="{team['name']}" class="team-btn" style="--c1:#{c1};--c2:#{c2};">
              <div class="team-btn-overlay"></div>
              <img class="team-btn-flag" src="{flag_src}" alt="{team['name']}" onerror="this.style.opacity='0'">
              <span class="team-btn-name">{team['name']}</span>
              <span class="team-btn-group">GR. {gruppe_key}</span>
            </button>"""

        groups_html += f"""
        <div style="margin-bottom:32px;" class="fade-up">
          <div style="display:flex;align-items:center;gap:16px;margin-bottom:14px;">
            <span style="font-family:'Oswald';font-weight:700;font-size:40px;line-height:1;
                  background:linear-gradient(135deg,var(--gold3),var(--amber));
                  -webkit-background-clip:text;-webkit-text-fill-color:transparent;">{gruppe_key}</span>
            <div style="flex:1;height:1px;background:linear-gradient(90deg,rgba(255,215,0,0.3),transparent);"></div>
          </div>
          <div class="team-grid">{teams_html}</div>
        </div>"""

    return BASE_HTML + f"""
    <div class="page">
      <div class="wrap">
        <div style="text-align:center;margin-bottom:56px;" class="fade-up">
          <div class="hero-eyebrow" style="display:inline-flex;margin-bottom:16px;">🌍 Teamauswahl</div>
          <h1 style="font-family:'Oswald';font-weight:700;font-size:clamp(48px,8vw,90px);line-height:0.9;
               background:linear-gradient(160deg,#fff,var(--gold3),var(--amber));
               -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:20px;letter-spacing:-1px;">
            WEM DRÜCKST DU<br>DIE DAUMEN?
          </h1>
          <p style="color:var(--text2);font-size:16px;max-width:400px;margin:0 auto;">
            Wähle dein Lieblingsteam für die WM 2026. Du kannst es später jederzeit ändern.
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
        tabs_html += f'<a href="/gruppe/{g}" class="tab {ac}">GR.&nbsp;{g}</a>'

    # Team Pills
    team_pills = ""
    for t in gruppe_data["teams"]:
        is_mine = (t["name"] == lieblingsteam)
        mine_cls = "my-team" if is_mine else ""
        team_pills += f'<span class="gruppe-pill {mine_cls}">{flag_img(t["code"],18)} {t["name"]}</span>'

    # Live Banner
    laufende = []
    for g_data in WM_GRUPPEN.values():
        for sp in g_data["spiele"]:
            if get_spiel_status(sp) == "live":
                sc = get_live_score(sp["id"])
                score_txt = f"{sc['heim']}:{sc['gast']}" if sc and sc.get('heim') is not None else "?:?"
                laufende.append((sp['heim'], score_txt, sp['gast']))

    live_banner = ""
    if laufende:
        items = "".join(f'<span class="live-ticker-item">{h} <span class="live-ticker-score">{s}</span> {g}</span>' for h,s,g in laufende)
        live_banner = f"""
        <div class="live-banner fade-up">
          <div class="live-banner-label"><div class="blink-dot"></div> 🔴 LIVE JETZT</div>
          <div class="live-ticker-items">{items}</div>
        </div>"""

    # Match Cards
    spiele_html = ""
    for i, spiel in enumerate(gruppe_data["spiele"]):
        sid = spiel["id"]
        tipp = tipps.get(sid)
        status = get_spiel_status(spiel)
        live_score = get_live_score(sid)
        min_bis = minuten_bis_spiel(spiel)
        erlaubt = status in ("upcoming", "soon")

        heim_code = TEAM_CODE.get(spiel["heim"], "")
        gast_code = TEAM_CODE.get(spiel["gast"], "")

        # Card classes
        card_extra = ""
        if status == "live": card_extra = "is-live"
        elif status == "final": card_extra = "is-final"
        elif tipp: card_extra = "is-tipped"

        stripe_cls = f"mc-stripe-{status}" if status in ("live","final","upcoming","soon") else ("mc-stripe-tipped" if tipp else "mc-stripe-upcoming")

        # Center block
        if status in ("live","final") and live_score and live_score.get("heim") is not None:
            num_cls = "live-num" if status == "live" else "final-num"
            chip = f'<div class="status-chip chip-live"><div class="blink-dot"></div> LIVE</div>' if status=="live" else f'<div class="status-chip chip-final">ABPFIFF</div>'
            center_html = f"""
            <div class="mc-center">
              {chip}
              <div class="mc-score-row">
                <span class="mc-score-num {num_cls}">{live_score["heim"]}</span>
                <span class="mc-score-sep">:</span>
                <span class="mc-score-num {num_cls}">{live_score["gast"]}</span>
              </div>
            </div>"""
        elif status in ("live","final"):
            chip = f'<div class="status-chip chip-live"><div class="blink-dot"></div> LIVE</div>' if status=="live" else f'<div class="status-chip chip-final">ABPFIFF</div>'
            center_html = f'<div class="mc-center">{chip}<div class="mc-vs">?:?</div></div>'
        elif status == "soon":
            center_html = f"""<div class="mc-center">
              <div class="status-chip chip-soon">⚡ BALD</div>
              <div class="mc-kickoff">{spiel['uhrzeit']}</div>
              <div class="mc-date-text">{spiel['datum']}</div>
            </div>"""
        else:
            center_html = f"""<div class="mc-center">
              <div class="mc-kickoff">{spiel['uhrzeit']}</div>
              <div class="mc-date-text">{spiel['datum']}</div>
              <div class="mc-vs">VS</div>
            </div>"""

        # Action block
        if tipp:
            td = tipp if isinstance(tipp, dict) else {"heim":"?","gast":"?"}
            punkte_key = tipp.get("punkte_result") if isinstance(tipp, dict) else None
            eval_html = ""
            if status == "final" and live_score and live_score.get("heim") is not None:
                if punkte_key == "perfekt":
                    eval_html = '<span class="tipp-eval eval-perfekt">🎯 Perfekt! +1000 ◈</span>'
                elif punkte_key == "tendenz_tor":
                    eval_html = '<span class="tipp-eval eval-gut">⚡ Tordiff! +500 ◈</span>'
                elif punkte_key == "tendenz":
                    eval_html = '<span class="tipp-eval eval-tendenz">✅ Tendenz! +200 ◈</span>'
                elif punkte_key == "falsch":
                    eval_html = '<span class="tipp-eval eval-falsch">❌ Leider falsch</span>'
                else:
                    eval_html = '<span class="tipp-eval eval-open">— Ausstehend</span>'
            action_html = f"""
            <div class="mc-action">
              <div class="tipp-saved-wrap">
                <div class="tipp-saved-score">✅ {td["heim"]} : {td["gast"]}</div>
                {eval_html}
              </div>
            </div>"""
        elif status == "live":
            action_html = '<div class="mc-action"><div class="badge-locked">🔴 Läuft gerade</div></div>'
        elif status == "final":
            action_html = '<div class="mc-action"><div class="badge-missed">— Kein Tipp abgegeben</div></div>'
        elif not erlaubt:
            action_html = '<div class="mc-action"><div class="badge-locked">🔒 Gesperrt</div></div>'
        else:
            btn_label = f"⏰ Jetzt! (−50◈)" if min_bis <= 60 else "Tippen (−50◈)"
            warn_html = f'<div class="badge-soon-warn">⚠️ Noch {max(0,min_bis)} Min!</div>' if status == "soon" else ""
            action_html = f"""
            <div class="mc-action">
              {warn_html}
              <form action="/submittipp" method="POST">
                <input type="hidden" name="spiel_id" value="{sid}">
                <input type="hidden" name="redirect_gruppe" value="{gruppe_id}">
                <div class="tipp-form-row">
                  <input type="number" name="tipp_heim" min="0" max="20" class="score-in" placeholder="0" required>
                  <span class="score-in-sep">:</span>
                  <input type="number" name="tipp_gast" min="0" max="20" class="score-in" placeholder="0" required>
                  <button type="submit" class="tipp-submit">{btn_label}</button>
                </div>
              </form>
            </div>"""

        delay_cls = f"stagger-{min(i+1,6)}"
        spiele_html += f"""
        <div class="match-card {card_extra} fade-up {delay_cls}" id="spiel-{sid}">
          <div class="mc-stripe {stripe_cls}"></div>
          <div class="mc-team-home">
            {flag_img(heim_code, 24)}
            <span class="mc-team-name">{spiel['heim']}</span>
          </div>
          {center_html}
          <div class="mc-team-away">
            {flag_img(gast_code, 24)}
            <span class="mc-team-name">{spiel['gast']}</span>
          </div>
          {action_html}
        </div>"""

    # Profile sidebar
    fav_team_html = ""
    if mein_team:
        fav_team_html = f"""
        <div class="fav-team-row">
          {flag_img(mein_team['code'], 30)}
          <div>
            <div class="fav-team-name">{mein_team['name']}</div>
            <div class="fav-team-sub">Gruppe {mein_team['gruppe']} · Mein Favorit</div>
          </div>
          <a href="/choose_team" style="margin-left:auto;font-size:11px;color:var(--muted);text-decoration:none;font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;">ÄNDERN</a>
        </div>"""

    pct = int(getippt / total_spiele * 100) if total_spiele > 0 else 0

    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap">
        <!-- Profile + Stats -->
        <div style="display:grid;grid-template-columns:280px 1fr;gap:20px;margin-bottom:36px;align-items:start;" class="fade-up">
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
            <div class="card" style="padding:18px 20px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <div style="font-family:'Barlow Condensed';font-weight:800;font-size:12px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;">Tipp-Fortschritt</div>
                <div style="font-family:'Oswald';font-weight:700;font-size:18px;color:var(--neon);">{pct}%</div>
              </div>
              <div style="font-size:13px;color:var(--text2);margin-bottom:10px;font-weight:600;">{getippt} / {total_spiele} Spiele getippt</div>
              <div class="prog-track"><div class="prog-fill" style="width:{pct}%;"></div></div>
            </div>
          </div>
        </div>

        <!-- Section Header -->
        <div class="sec-header fade-up">
          <div class="sec-tag">⚽ Gruppenphase 2026</div>
          <div class="sec-title">Spielplan & Tipps</div>
          <div class="sec-sub">50 ◈ Einsatz · Gesperrt bei Anpfiff · Live-Scores in Echtzeit · <a href="/punkte" style="color:var(--amber);text-decoration:none;font-weight:700;">Punktesystem →</a></div>
        </div>

        {live_banner}

        <!-- Tabs -->
        <div class="tabs-wrap fade-up">{tabs_html}</div>

        <!-- Gruppe Header -->
        <div class="card fade-up" style="margin-bottom:0;">
          <div class="gruppe-header">
            <div class="gruppe-letter">{gruppe_id}</div>
            <div>
              <div style="font-family:'Oswald';font-weight:700;font-size:20px;letter-spacing:2px;text-transform:uppercase;">Gruppe {gruppe_id}</div>
              <div class="gruppe-team-pills" style="margin-top:8px;">{team_pills}</div>
            </div>
          </div>
          <div class="match-list">
            {spiele_html}
          </div>
        </div>
      </div>
    </div>

    <script>
      function checkLive() {{
        fetch('/api/live_scores').then(r=>r.json()).then(scores => {{
          let hasLive = false;
          for (const [sid, data] of Object.entries(scores)) {{
            if (data.status === 'live' || data.status === 'final') {{
              hasLive = true;
              const el = document.getElementById('spiel-' + sid);
              if (el) {{
                if ((data.status==='live' && !el.classList.contains('is-live')) ||
                    (data.status==='final' && !el.classList.contains('is-final'))) {{
                  window.location.reload(); return;
                }}
              }}
            }}
          }}
          if (hasLive) setTimeout(()=>window.location.reload(), 30000);
        }}).catch(()=>{{}});
      }}
      setTimeout(checkLive, 10000);
      setInterval(checkLive, 60000);
    </script>
    </body></html>"""

@app.route('/dashboard')
def dashboard():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        load_data()
        if username not in user_db:
            return redirect(url_for('home'))
    mein_team = next((t for t in ALLE_TEAMS if t["name"] == user_db[username].get("lieblingsteam")), None)
    aktive_gruppe = mein_team["gruppe"] if mein_team else "A"
    return render_gruppe_page(username, aktive_gruppe, "dashboard")

@app.route('/gruppe/<gruppe_id>')
def gruppe_ansicht(gruppe_id):
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        load_data()
        if username not in user_db:
            return redirect(url_for('home'))
    gruppe_id = gruppe_id.upper()
    if gruppe_id not in WM_GRUPPEN:
        return redirect(url_for('dashboard'))
    return render_gruppe_page(username, gruppe_id, "dashboard")

# ==========================================
# LEADERBOARD mit Suche
# ==========================================
@app.route('/leaderboard')
def leaderboard():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    user_info = user_db.get(username, {"points": 1000, "tipps": {}, "lieblingsteam": None})
    navbar = get_navbar(username, user_info["points"], user_info.get("lieblingsteam"), "leaderboard")
    lb = get_leaderboard()
    medals = {1:("🥇","r1"), 2:("🥈","r2"), 3:("🥉","r3")}

    # Podium (top 3)
    podium_html = ""
    if len(lb) >= 3:
        def podium_card(entry, rank, cls):
            medal, _ = medals.get(rank, ("",""))
            team = next((t for t in ALLE_TEAMS if t["name"] == entry.get("lieblingsteam")), None)
            team_html = f'{flag_img(team["code"],16)} {team["name"]}' if team else ""
            return f"""
            <div class="podium-card {cls}">
              <div class="podium-medal">{medal}</div>
              <img class="podium-head" src="https://mc-heads.net/avatar/{entry['username']}/56" alt="" onerror="this.style.display='none'">
              <div class="podium-name">{entry['username']}</div>
              <div style="font-size:12px;color:var(--muted);font-family:'Barlow Condensed';font-weight:700;margin-top:3px;">{team_html}</div>
              <div class="podium-pts">{entry['points']:,} ◈</div>
            </div>"""

        podium_html = f"""
        <div class="podium-wrap fade-up">
          {podium_card(lb[1], 2, "podium-card podium-2")}
          {podium_card(lb[0], 1, "podium-card podium-1")}
          {podium_card(lb[2], 3, "podium-card podium-3")}
        </div>"""

    # Rows
    rows_html = ""
    for i, entry in enumerate(lb, 1):
        rank_class = f"rank-{i}" if i <= 3 else ""
        is_me = (entry["username"] == username)
        if is_me: rank_class += " rank-me"
        medal, rank_color = medals.get(i, ("",""))
        rank_display = f'<span class="lb-rank {rank_color}">{medal or str(i)}</span>'
        team = next((t for t in ALLE_TEAMS if t["name"] == entry.get("lieblingsteam")), None)
        team_html = f'{flag_img(team["code"],16)} {team["name"]}' if team else ""
        me_badge = '<span class="lb-me-badge">DU</span>' if is_me else ""
        rows_html += f"""
        <div class="lb-row {rank_class}" data-username="{entry['username'].lower()}">
          {rank_display}
          <div class="lb-user-cell">
            <img class="lb-head" src="https://mc-heads.net/avatar/{entry['username']}/32" alt="" onerror="this.style.display='none'">
            <div>
              <div class="lb-name">{entry['username']} {me_badge}</div>
              <div class="lb-team-small">{team_html}</div>
            </div>
          </div>
          <div class="lb-tipps-cell">{entry['tipps']} Tipps</div>
          <div class="lb-pts">{entry['points']:,} ◈</div>
        </div>"""

    if not lb:
        rows_html = '<div style="text-align:center;color:var(--muted);padding:60px;font-family:\'Barlow Condensed\';font-weight:700;font-size:16px;letter-spacing:1px;">NOCH KEINE SPIELER REGISTRIERT</div>'

    my_rank = next((i+1 for i,e in enumerate(lb) if e["username"] == username), None)
    my_rank_txt = f"Platz {my_rank} von {len(lb)}" if my_rank else "–"

    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap" style="max-width:860px;">
        <div style="margin-bottom:36px;" class="fade-up">
          <div class="sec-tag">🏆 Bestenliste</div>
          <div class="sec-title" style="font-size:48px;letter-spacing:2px;">RANGLISTE</div>
          <div class="sec-sub">Dein Rang: <strong style="color:var(--gold);">{my_rank_txt}</strong></div>
        </div>

        {podium_html}

        <!-- Suche -->
        <div class="lb-search-wrap fade-up">
          <div class="lb-search-icon">🔍</div>
          <input type="text" class="lb-search" id="lb-search" placeholder="Spieler suchen..." autocomplete="off" spellcheck="false">
        </div>

        <!-- Header -->
        <div class="lb-header-row fade-up">
          <div>#</div>
          <div>Spieler</div>
          <div style="text-align:center;">Tipps</div>
          <div style="text-align:right;">Punkte</div>
        </div>

        <!-- Rows -->
        <div id="lb-list">
          {rows_html}
        </div>
        <div id="lb-empty" style="display:none;text-align:center;padding:40px;color:var(--muted);font-family:'Barlow Condensed';font-weight:700;letter-spacing:1px;font-size:14px;">
          ⚽ KEIN SPIELER GEFUNDEN
        </div>
      </div>
    </div>

    <script>
      const search = document.getElementById('lb-search');
      const rows = document.querySelectorAll('.lb-row[data-username]');
      const empty = document.getElementById('lb-empty');

      search.addEventListener('input', () => {{
        const q = search.value.toLowerCase().trim();
        let found = 0;
        rows.forEach(row => {{
          const name = row.getAttribute('data-username');
          if (!q || name.includes(q)) {{
            row.classList.remove('lb-hidden');
            found++;
          }} else {{
            row.classList.add('lb-hidden');
          }}
        }});
        empty.style.display = found === 0 ? 'block' : 'none';
      }});
    </script>
    </body></html>"""

# ==========================================
# PUNKTE-SYSTEM
# ==========================================
@app.route('/punkte')
def punkte():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    user_info = user_db.get(username, {"points": 1000, "tipps": {}, "lieblingsteam": None})
    navbar = get_navbar(username, user_info["points"], user_info.get("lieblingsteam"), "punkte")
    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap" style="max-width:760px;">
        <div style="margin-bottom:40px;" class="fade-up">
          <div class="sec-tag">📋 Spielregeln</div>
          <div class="sec-title" style="font-size:44px;">PUNKTESYSTEM</div>
          <div class="sec-sub">So verdienst du Punkte – und so verlierst du sie</div>
        </div>

        <!-- Punktekategorien -->
        <div class="card fade-up stagger-1" style="margin-bottom:16px;border-color:rgba(255,215,0,0.12);">
          <div style="font-family:'Oswald';font-weight:700;font-size:22px;letter-spacing:2px;color:var(--gold);margin-bottom:16px;">🎯 TREFFERQUOTEN</div>
          <div class="pts-grid">
            <div class="pts-row top">
              <div>
                <div class="pts-label">🎯 Perfektes Ergebnis</div>
                <div class="pts-sub">z.B. Tipp 2:1 → Ergebnis 2:1</div>
              </div>
              <div class="pts-val">+1.000 ◈</div>
            </div>
            <div class="pts-row">
              <div>
                <div class="pts-label">⚡ Richtige Tordifferenz</div>
                <div class="pts-sub">z.B. Tipp 3:1 → Ergebnis 2:0</div>
              </div>
              <div class="pts-val">+500 ◈</div>
            </div>
            <div class="pts-row">
              <div>
                <div class="pts-label">✅ Richtige Tendenz</div>
                <div class="pts-sub">Sieg / Unentschieden / Niederlage</div>
              </div>
              <div class="pts-val">+200 ◈</div>
            </div>
            <div class="pts-row" style="border-color:rgba(255,69,0,0.25);background:rgba(255,69,0,0.04);">
              <div>
                <div class="pts-label">❌ Falsch getippt</div>
                <div class="pts-sub">Falsche Tendenz</div>
              </div>
              <div class="pts-val neg">0 ◈</div>
            </div>
          </div>
        </div>

        <div class="card fade-up stagger-2" style="margin-bottom:16px;border-color:rgba(255,165,0,0.1);">
          <div style="font-family:'Oswald';font-weight:700;font-size:22px;letter-spacing:2px;color:var(--gold);margin-bottom:16px;">💰 STARTKAPITAL & EINSATZ</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="pts-row">
              <div>
                <div class="pts-label">Startkapital</div>
                <div class="pts-sub">Bei der Registrierung</div>
              </div>
              <div class="pts-val">1.000 ◈</div>
            </div>
            <div class="pts-row" style="border-color:rgba(255,69,0,0.25);background:rgba(255,69,0,0.04);">
              <div>
                <div class="pts-label">Einsatz pro Tipp</div>
                <div class="pts-sub">Wird sofort abgezogen</div>
              </div>
              <div class="pts-val neg">−50 ◈</div>
            </div>
          </div>
        </div>

        <div class="card fade-up stagger-3" style="margin-bottom:24px;border-color:rgba(255,48,48,0.15);">
          <div style="font-family:'Oswald';font-weight:700;font-size:22px;letter-spacing:2px;color:var(--live);margin-bottom:16px;">🔒 TIPP-SPERRE</div>
          <div class="pts-row" style="border-color:rgba(255,48,48,0.3);background:rgba(255,48,48,0.05);">
            <div>
              <div class="pts-label">Gesperrt bei Spielbeginn</div>
              <div class="pts-sub">Sobald das Spiel als LIVE erkannt wird – kein Tippen mehr möglich</div>
            </div>
            <div style="font-family:'Oswald';font-weight:700;font-size:28px;color:var(--live);">LIVE</div>
          </div>
          <div style="margin-top:14px;padding:14px 18px;background:var(--bg3);border-radius:8px;font-size:13px;color:var(--text2);line-height:1.7;font-weight:500;">
            📡 <strong style="color:var(--text);">Live-Scores:</strong> Während Spiele laufen siehst du den Echtzeit-Spielstand direkt im Dashboard. Die Seite aktualisiert sich automatisch alle 30 Sekunden wenn Live-Spiele laufen.
          </div>
        </div>

        <div style="text-align:center;" class="fade-up stagger-4">
          <a href="/dashboard" class="btn btn-fire" style="font-size:18px;padding:16px 40px;">⚽ Jetzt tippen</a>
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
        user_db[username] = {"points": 1000, "tipps": {}, "lieblingsteam": None}

    spiel_gefunden = None
    for gruppe_data in WM_GRUPPEN.values():
        for spiel in gruppe_data["spiele"]:
            if spiel["id"] == spiel_id:
                spiel_gefunden = spiel
                break

    if spiel_gefunden and spiel_id not in user_db[username]["tipps"]:
        status = get_spiel_status(spiel_gefunden)
        if status in ("upcoming", "soon"):
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
# AUSWERTUNG (Admin)
# ==========================================
@app.route('/auswertung')
def auswertung():
    key = request.args.get("key","")
    if key != "ADMIN1337":
        return "Kein Zugriff", 403
    spiel_id = request.args.get("spiel_id")
    heim_tore = int(request.args.get("heim", 0))
    gast_tore = int(request.args.get("gast", 0))
    if not spiel_id:
        return "spiel_id fehlt", 400

    def tendenz(h, g):
        if h > g: return "H"
        if h < g: return "G"
        return "U"

    echte_tendenz = tendenz(heim_tore, gast_tore)
    echte_diff = heim_tore - gast_tore
    auswertungen = []

    for uname, data in user_db.items():
        tipp = data.get("tipps", {}).get(spiel_id)
        if not tipp:
            continue
        th, tg = tipp["heim"], tipp["gast"]
        if th == heim_tore and tg == gast_tore:
            punkte_val = PUNKTE_SYSTEM["perfekt"]; ergebnis = "perfekt"
        elif tendenz(th, tg) == echte_tendenz and (th - tg) == echte_diff:
            punkte_val = PUNKTE_SYSTEM["tendenz_tor"]; ergebnis = "tendenz_tor"
        elif tendenz(th, tg) == echte_tendenz:
            punkte_val = PUNKTE_SYSTEM["tendenz"]; ergebnis = "tendenz"
        else:
            punkte_val = PUNKTE_SYSTEM["falsch"]; ergebnis = "falsch"

        user_db[uname]["points"] = user_db[uname].get("points", 0) + punkte_val
        user_db[uname]["tipps"][spiel_id]["punkte_result"] = ergebnis
        auswertungen.append(f"{uname}: {th}:{tg} → {ergebnis} (+{punkte_val})")

    save_data()
    return f"<pre style='background:#111;color:#0f0;padding:20px;font-size:14px;'>Auswertung {spiel_id} ({heim_tore}:{gast_tore}):\n" + "\n".join(auswertungen) + "\n\n✅ Gespeichert!</pre>"

@app.route('/admin')
def admin():
    key = request.args.get("key","")
    if key != "ADMIN1337":
        return "Kein Zugriff", 403
    output = f"<pre style='background:#111;color:#0f0;padding:20px;'>WM 2026 Admin – {len(user_db)} Spieler\n\n"
    for uname, data in sorted(user_db.items(), key=lambda x: -x[1].get("points",0)):
        output += f"{uname}: {data.get('points',0)} ◈  {len(data.get('tipps',{}))} Tipps\n"
    output += "</pre>"
    return output

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
    print("   Starte auf: http://127.0.0.1:5005")
    print("="*60 + "\n")
    try:
        port = int(os.environ.get('PORT', 5005))
        host = '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
        app.run(debug=False, host=host, port=port, use_reloader=False)
    except Exception as e:
        print(e)
        input()
