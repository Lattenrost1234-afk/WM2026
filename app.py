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

ADMIN_USER = "Lattenrost1234"

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
    "perfekt":      1000,
    "tendenz_tor":  500,
    "tendenz":      200,
    "falsch":       0,
    "einsatz":      50,
}

# ==========================================
# LIVE-SCORES SYSTEM
# ==========================================
def fetch_live_scores_thesportsdb():
    global live_scores_cache
    if not REQUESTS_AVAILABLE:
        return
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={today}&s=Soccer"
    try:
        resp = req_lib.get(url, timeout=8)
        if resp.status_code != 200:
            return
        data = resp.json()
        events = data.get("events") or []
        matched = 0
        for gruppe_data in WM_GRUPPEN.values():
            for spiel in gruppe_data["spiele"]:
                heim = spiel["heim"].lower()
                gast = spiel["gast"].lower()
                sid = spiel["id"]
                # Skip if admin has manually set this to final
                if live_scores_cache.get(sid, {}).get("admin_locked"):
                    continue
                for ev in events:
                    ev_heim = (ev.get("strHomeTeam") or "").lower()
                    ev_gast = (ev.get("strAwayTeam") or "").lower()
                    ev_liga = (ev.get("strLeague") or "").lower()
                    is_wm = any(kw in ev_liga for kw in [
                        "world cup", "fifa", "wm", "mondial", "copa do mundo", "coupe du monde"
                    ])
                    if not is_wm:
                        continue
                    if _teams_match(heim, ev_heim) and _teams_match(gast, ev_gast):
                        status = ev.get("strStatus", "").lower().strip()
                        score_home = ev.get("intHomeScore")
                        score_away = ev.get("intAwayScore")
                        cache_entry = {"status": "upcoming", "heim": None, "gast": None, "minuto": None}
                        if status in ["ft", "aet", "pen", "finished", "match finished", "after extra time", "penalties"]:
                            cache_entry["status"] = "final"
                            cache_entry["heim"] = int(score_home) if score_home is not None else None
                            cache_entry["gast"] = int(score_away) if score_away is not None else None
                        elif (status.isdigit() or status in ["ht", "live", "in progress", "1h", "2h"]
                              or "'" in status or "+" in status):
                            cache_entry["status"] = "live"
                            cache_entry["heim"] = int(score_home) if score_home is not None else 0
                            cache_entry["gast"] = int(score_away) if score_away is not None else 0
                            if status.isdigit():
                                cache_entry["minuto"] = int(status)
                            elif status == "ht":
                                cache_entry["minuto"] = 45
                        live_scores_cache[sid] = cache_entry
                        matched += 1
                        break
        if matched == 0:
            _apply_time_based_live_fallback()
    except Exception as e:
        print(f"[LIVE] Fehler beim Score-Abruf: {e}")
        _apply_time_based_live_fallback()

def _apply_time_based_live_fallback():
    jetzt = get_now_local()
    for gruppe_data in WM_GRUPPEN.values():
        for spiel in gruppe_data["spiele"]:
            sid = spiel["id"]
            # Never override admin-set status
            if live_scores_cache.get(sid, {}).get("admin_locked"):
                continue
            dt_local = parse_spiel_datetime(spiel)
            if dt_local is None:
                continue
            delta_min = (jetzt - dt_local).total_seconds() / 60
            if 0 <= delta_min < 110:
                existing = live_scores_cache.get(sid, {})
                if existing.get("status") not in ("live", "final"):
                    live_scores_cache[sid] = {
                        "status": "live",
                        "heim": None,
                        "gast": None,
                        "minuto": int(delta_min),
                        "fallback": True
                    }
            elif delta_min >= 110:
                existing = live_scores_cache.get(sid, {})
                if existing.get("status") not in ("final",) and existing.get("fallback"):
                    live_scores_cache[sid] = {
                        "status": "final",
                        "heim": None,
                        "gast": None,
                        "fallback": True
                    }

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

def flag_url(code):
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
# HELPER: Spielzeit-Check
# ==========================================
def parse_spiel_datetime(spiel):
    try:
        dt_str = f"{spiel['datum']} {spiel['uhrzeit']}"
        dt_local = datetime.datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
        return dt_local
    except:
        return None

def get_now_local():
    return datetime.datetime.now()

def get_spiel_status(spiel):
    sid = spiel["id"]
    # Admin-set status always wins
    cached = live_scores_cache.get(sid, {})
    if cached.get("admin_locked") or cached.get("status") in ("live", "final"):
        return cached.get("status", "upcoming")
    # Time-based fallback
    dt_local = parse_spiel_datetime(spiel)
    if dt_local is None:
        return "upcoming"
    jetzt = get_now_local()
    delta_min = (jetzt - dt_local).total_seconds() / 60
    if delta_min < -30:
        return "upcoming"
    elif -30 <= delta_min < 0:
        return "soon"
    elif 0 <= delta_min < 115:
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

def tendenz_calc(h, g):
    if h > g: return "H"
    if h < g: return "G"
    return "U"

def do_auswertung(spiel_id, heim_tore, gast_tore, force=False):
    """
    Wertet alle Tipps für ein Spiel aus.
    force=True: Setzt bisherige Auswertungen zurück und rechnet neu (für Korrekturen).
    Gibt Liste mit Resultaten zurück.
    """
    echte_tendenz = tendenz_calc(heim_tore, gast_tore)
    echte_diff = heim_tore - gast_tore
    results = []
    for uname, data in user_db.items():
        tipp = data.get("tipps", {}).get(spiel_id)
        if not tipp:
            continue
        # Bei force=True: alte Punkte zurückbuchen und neu berechnen
        if force and tipp.get("punkte_result"):
            old_erg = tipp["punkte_result"]
            old_pts = PUNKTE_SYSTEM.get(old_erg, 0)
            user_db[uname]["points"] = user_db[uname].get("points", 0) - old_pts
            user_db[uname]["tipps"][spiel_id].pop("punkte_result", None)
        elif tipp.get("punkte_result") and not force:
            continue  # Already evaluated, skip

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
# DESIGN SYSTEM
# ==========================================

BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Exo+2:ital,wght@0,300;0,400;0,600;0,700;0,800;0,900;1,700&family=Rajdhani:wght@400;500;600;700&display=swap');

:root {
  --g1: #0a0e1a; --g2: #0d1220; --g3: #111828; --g4: #161f35; --g5: #1c2a45;
  --card: #131a2e; --card2: #0f1525;
  --gold: #f5c842; --gold2: #e8b020; --gold3: #ffd966;
  --copper: #e07b39; --fire: #ff5722; --fire2: #ff7043;
  --neon: #00e5a0; --neon2: #00c580; --sky: #29b6f6;
  --live: #f44336; --live2: #ef9a9a;
  --border: rgba(245,200,66,0.15); --border2: rgba(255,255,255,0.07); --border3: rgba(255,255,255,0.04);
  --text: #eaf0ff; --text2: #8fa0c0; --muted: #3d4f6e;
  --r1: #f5c842; --r2: #b8cce0; --r3: #cd8b4a;
}

*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--g1);color:var(--text);font-family:'Exo 2',sans-serif;min-height:100vh;overflow-x:hidden;}

body::before{
  content:'';position:fixed;inset:0;z-index:0;
  background:
    radial-gradient(ellipse 120% 60% at 50% -10%,rgba(0,229,160,0.06) 0%,transparent 55%),
    radial-gradient(ellipse 80% 50% at 5% 70%,rgba(41,182,246,0.04) 0%,transparent 45%),
    radial-gradient(ellipse 60% 50% at 95% 30%,rgba(245,200,66,0.04) 0%,transparent 45%),
    repeating-linear-gradient(0deg,transparent,transparent 44px,rgba(0,229,160,0.018) 44px,rgba(0,229,160,0.018) 45px),
    repeating-linear-gradient(90deg,transparent,transparent 80px,rgba(0,229,160,0.01) 80px,rgba(0,229,160,0.01) 81px);
  pointer-events:none;animation:bgPulse 12s ease-in-out infinite;
}
@keyframes bgPulse{0%,100%{opacity:1}50%{opacity:0.7}}

.navbar{
  position:sticky;top:0;z-index:900;height:62px;
  display:flex;align-items:center;gap:20px;padding:0 28px;
  background:rgba(10,14,26,0.95);border-bottom:1px solid rgba(245,200,66,0.12);
  backdrop-filter:blur(32px) saturate(180%);
}
.navbar::after{content:'';position:absolute;bottom:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(245,200,66,0.4),transparent);
  animation:scanline 6s linear infinite;}
@keyframes scanline{0%{background-position:0% 0%}100%{background-position:200% 0%}}
.nb-logo-wrap{display:flex;align-items:center;gap:12px;flex-shrink:0;}
.nb-icon{width:34px;height:34px;background:linear-gradient(135deg,var(--gold),var(--copper));border-radius:8px;
  display:flex;align-items:center;justify-content:center;font-size:17px;
  box-shadow:0 0 16px rgba(245,200,66,0.35);animation:iconPulse 3s ease-in-out infinite;}
@keyframes iconPulse{0%,100%{box-shadow:0 0 16px rgba(245,200,66,0.35)}50%{box-shadow:0 0 28px rgba(245,200,66,0.6)}}
.nb-title{font-family:'Bebas Neue';font-size:22px;letter-spacing:4px;
  background:linear-gradient(90deg,var(--gold3),var(--gold),var(--copper));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.nb-sep{width:1px;height:26px;background:rgba(255,255,255,0.07);flex-shrink:0;}
.nb-links{display:flex;gap:2px;}
.nb-link{padding:6px 14px;border-radius:7px;text-decoration:none;
  font-family:'Rajdhani';font-weight:700;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;
  color:var(--muted);transition:all .15s;position:relative;}
.nb-link:hover{color:var(--text2);background:rgba(255,255,255,0.04);}
.nb-link.active{color:var(--gold);}
.nb-link.active::after{content:'';position:absolute;bottom:4px;left:14px;right:14px;height:2px;
  background:linear-gradient(90deg,var(--gold),var(--copper));border-radius:1px;}
.nb-right{display:flex;align-items:center;gap:10px;margin-left:auto;}
.nb-coins{display:flex;align-items:center;gap:7px;
  background:linear-gradient(135deg,rgba(245,200,66,0.14),rgba(224,123,57,0.08));
  border:1px solid rgba(245,200,66,0.3);border-radius:20px;padding:5px 14px 5px 8px;
  font-family:'Bebas Neue';font-size:17px;letter-spacing:2px;color:var(--gold);}
.coin-dot{width:20px;height:20px;background:linear-gradient(135deg,var(--gold3),var(--copper));
  border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:10px;font-weight:900;color:#000;flex-shrink:0;box-shadow:0 0 8px rgba(245,200,66,0.4);}
.nb-avatar{width:30px;height:30px;border-radius:7px;image-rendering:pixelated;border:2px solid rgba(245,200,66,0.3);}
.nb-user{font-family:'Rajdhani';font-weight:700;font-size:15px;letter-spacing:.5px;}
.nb-logout{font-size:12px;color:var(--muted);text-decoration:none;padding:5px 11px;border-radius:6px;
  border:1px solid transparent;transition:all .2s;font-family:'Rajdhani';font-weight:600;letter-spacing:.5px;}
.nb-logout:hover{color:var(--fire);border-color:rgba(255,87,34,0.35);background:rgba(255,87,34,0.06);}

.hero{padding:90px 20px 80px;text-align:center;position:relative;z-index:1;overflow:hidden;}
.hero-chip{display:inline-flex;align-items:center;gap:8px;
  font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:4px;text-transform:uppercase;
  color:var(--neon);border:1px solid rgba(0,229,160,0.3);background:rgba(0,229,160,0.07);
  padding:7px 20px;border-radius:100px;margin-bottom:28px;animation:chipGlow 3s ease-in-out infinite;}
@keyframes chipGlow{0%,100%{box-shadow:0 0 0 0 rgba(0,229,160,0)}50%{box-shadow:0 0 20px rgba(0,229,160,0.2)}}
.hero-h1{font-family:'Bebas Neue';font-size:clamp(70px,14vw,160px);line-height:.85;letter-spacing:4px;position:relative;z-index:1;margin-bottom:24px;}
.hero-h1-inner{background:linear-gradient(170deg,#ffffff 0%,var(--gold3) 35%,var(--gold2) 60%,var(--copper) 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;display:block;
  animation:titleShimmer 4s ease-in-out infinite;background-size:200% 200%;}
@keyframes titleShimmer{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.hero-sub{color:var(--text2);font-size:16px;font-weight:400;max-width:440px;margin:0 auto 48px;line-height:1.9;}
.hero-ctas{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;}

.btn{display:inline-flex;align-items:center;gap:10px;font-family:'Rajdhani';font-weight:700;font-size:15px;
  letter-spacing:2px;text-transform:uppercase;text-decoration:none;padding:13px 34px;border-radius:5px;
  border:none;cursor:pointer;transition:all .2s;position:relative;overflow:hidden;}
.btn::before{content:'';position:absolute;inset:0;
  background:linear-gradient(45deg,transparent 30%,rgba(255,255,255,0.12) 50%,transparent 70%);
  transform:translateX(-200%);transition:transform .5s;}
.btn:hover::before{transform:translateX(200%);}
.btn-primary{background:linear-gradient(135deg,var(--fire2),var(--fire),var(--copper));color:#fff;
  box-shadow:0 4px 24px rgba(255,87,34,0.4),inset 0 1px 0 rgba(255,255,255,0.1);
  clip-path:polygon(0 0,calc(100% - 10px) 0,100% 100%,10px 100%);}
.btn-primary:hover{transform:translateY(-3px);box-shadow:0 10px 36px rgba(255,87,34,0.55);}
.btn-outline{background:transparent;color:var(--neon);border:1.5px solid rgba(0,229,160,0.4);box-shadow:0 0 16px rgba(0,229,160,0.1);}
.btn-outline:hover{background:rgba(0,229,160,0.07);box-shadow:0 0 30px rgba(0,229,160,0.25);}
.btn-gold{background:linear-gradient(135deg,var(--gold3),var(--gold2));color:#000;font-weight:800;}
.btn-gold:hover{transform:translateY(-2px);box-shadow:0 8px 28px rgba(245,200,66,0.45);}
.btn-sm{padding:8px 16px;font-size:12px;letter-spacing:1.5px;border-radius:5px;}

.card{background:var(--card);border:1px solid var(--border2);border-radius:12px;padding:22px;position:relative;overflow:hidden;}
.wrap{max-width:1280px;margin:0 auto;padding:0 28px;position:relative;z-index:1;}
.page{padding:32px 0 100px;}

.sec-eyebrow{display:inline-flex;align-items:center;gap:6px;
  font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:4px;text-transform:uppercase;
  color:var(--copper);background:rgba(224,123,57,0.09);border:1px solid rgba(224,123,57,0.25);
  padding:4px 12px;border-radius:4px;margin-bottom:8px;}
.sec-title{font-family:'Bebas Neue';font-size:36px;letter-spacing:2px;color:var(--text);}
.sec-sub{color:var(--muted);font-size:13px;margin-top:3px;font-weight:500;}

.tabs-wrap{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:18px;padding:5px;
  background:var(--g3);border-radius:10px;border:1px solid var(--border3);}
.tab{padding:7px 13px;border-radius:7px;cursor:pointer;
  font-family:'Rajdhani';font-weight:700;font-size:12px;letter-spacing:2px;text-transform:uppercase;
  white-space:nowrap;transition:all .15s;text-decoration:none;color:var(--muted);}
.tab:hover{color:var(--text2);background:rgba(255,255,255,0.04);}
.tab.active{background:linear-gradient(135deg,rgba(245,200,66,0.18),rgba(224,123,57,0.1));
  border:1px solid rgba(245,200,66,0.3);color:var(--gold);box-shadow:0 0 12px rgba(245,200,66,0.08);}

.day-badge{display:inline-flex;align-items:center;gap:5px;
  font-family:'Rajdhani';font-weight:800;font-size:9px;letter-spacing:2.5px;text-transform:uppercase;
  padding:3px 10px;border-radius:100px;}
.day-today{background:rgba(255,87,34,0.25);border:1px solid rgba(255,87,34,0.6);color:#ff8a65;
  animation:todayPulse 2s ease-in-out infinite;box-shadow:0 0 10px rgba(255,87,34,0.2);}
@keyframes todayPulse{0%,100%{box-shadow:0 0 8px rgba(255,87,34,0.2)}50%{box-shadow:0 0 20px rgba(255,87,34,0.45)}}
.day-tomorrow{background:rgba(224,123,57,0.18);border:1px solid rgba(224,123,57,0.45);color:var(--copper);}

.match-list{display:flex;flex-direction:column;gap:8px;}
.match-card{
  display:grid;grid-template-columns:1fr 200px 1fr 280px;
  align-items:center;background:var(--card2);border:1px solid var(--border3);
  border-radius:10px;overflow:hidden;transition:all .2s;position:relative;}
.match-card:hover{border-color:rgba(255,255,255,0.09);transform:translateY(-1px);
  box-shadow:0 8px 30px rgba(0,0,0,0.5);}
.match-card.is-final{opacity:0.42;filter:saturate(0.35);}
.match-card.is-final:hover{opacity:0.7;filter:saturate(0.55);transform:none;}
.match-card.is-today{border-color:rgba(255,87,34,0.25);background:linear-gradient(90deg,rgba(255,87,34,0.05),var(--card2) 50%);}
.match-card.is-live{background:linear-gradient(90deg,rgba(244,67,54,0.09),var(--card2) 50%);border-color:rgba(244,67,54,0.3);}
.match-card.is-tipped{border-color:rgba(0,229,160,0.18);}

.mc-accent{position:absolute;left:0;top:0;bottom:0;width:3px;}
.acc-upcoming{background:linear-gradient(180deg,var(--sky),rgba(41,182,246,0.3));}
.acc-soon{background:linear-gradient(180deg,var(--copper),var(--fire));}
.acc-live{background:var(--live);animation:accPulse 1s ease-in-out infinite;}
.acc-final{background:rgba(61,79,110,0.3);}
.acc-tipped{background:linear-gradient(180deg,var(--neon),rgba(0,229,160,0.3));}
.acc-today{background:linear-gradient(180deg,var(--fire2),var(--copper));}
@keyframes accPulse{0%,100%{opacity:1}50%{opacity:0.2}}

.mc-home,.mc-away{padding:14px 18px 14px 22px;display:flex;align-items:center;gap:10px;}
.mc-home{justify-content:flex-end;flex-direction:row-reverse;}
.mc-away{justify-content:flex-start;}
.mc-team-name{font-family:'Rajdhani';font-weight:700;font-size:16px;letter-spacing:.5px;text-transform:uppercase;white-space:nowrap;}

.mc-mid{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:10px 4px;gap:4px;}
.mc-score-row{display:flex;align-items:center;gap:5px;}
.mc-num{font-family:'Bebas Neue';font-size:38px;line-height:1;min-width:28px;text-align:center;letter-spacing:1px;}
.mc-colon{font-family:'Bebas Neue';font-size:30px;color:var(--g5);line-height:1;}
.num-live{color:var(--live2);}
.num-final{color:var(--text);}
.num-up{color:var(--muted);font-size:20px;}

.status-badge{display:inline-flex;align-items:center;gap:4px;
  font-family:'Rajdhani';font-weight:700;font-size:9px;letter-spacing:2px;text-transform:uppercase;
  padding:3px 9px;border-radius:100px;}
.sb-live{background:rgba(244,67,54,0.2);border:1px solid rgba(244,67,54,0.45);color:#ef9a9a;}
.sb-final{background:rgba(61,79,110,0.25);border:1px solid rgba(61,79,110,0.4);color:var(--muted);}
.sb-soon{background:rgba(224,123,57,0.2);border:1px solid rgba(224,123,57,0.4);color:var(--copper);}
.sb-up{background:rgba(41,182,246,0.12);border:1px solid rgba(41,182,246,0.25);color:var(--sky);}
.dot-blink{width:5px;height:5px;border-radius:50%;background:currentColor;animation:dotBlink 1s step-end infinite;}
@keyframes dotBlink{0%,100%{opacity:1}50%{opacity:0}}

.mc-time-today{font-family:'Bebas Neue';font-size:28px;color:#ff8a65;letter-spacing:3px;line-height:1;text-shadow:0 0 16px rgba(255,87,34,0.4);}
.mc-time{font-family:'Bebas Neue';font-size:20px;color:var(--text2);letter-spacing:2px;}
.mc-date{font-family:'Rajdhani';font-size:10px;font-weight:700;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;}
.mc-vs{font-family:'Bebas Neue';font-size:14px;letter-spacing:3px;color:var(--muted);}

/* ─── ACTION BLOCK ─── */
.mc-action{padding:12px 16px;min-width:0;}
.tipp-row{display:flex;align-items:center;gap:5px;justify-content:flex-end;margin-top:4px;}
.score-in{width:42px;height:38px;background:var(--g3);border:1px solid rgba(255,255,255,0.1);
  color:#fff;border-radius:7px;text-align:center;font-family:'Bebas Neue';font-size:22px;
  -moz-appearance:textfield;appearance:none;transition:all .15s;}
.score-in::-webkit-inner-spin-button,.score-in::-webkit-outer-spin-button{-webkit-appearance:none;}
.score-in:focus{outline:none;border-color:var(--gold);background:var(--g2);box-shadow:0 0 0 3px rgba(245,200,66,0.12);}
.score-sep{font-family:'Bebas Neue';font-size:20px;color:var(--muted);}
.tipp-btn{background:linear-gradient(135deg,var(--gold3),var(--gold2));color:#000;border:none;border-radius:6px;
  padding:7px 13px;font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;
  cursor:pointer;transition:all .2s;white-space:nowrap;}
.tipp-btn:hover{transform:scale(1.05);box-shadow:0 4px 14px rgba(245,200,66,0.45);}

/* ─── RESULT AFTER FINAL ─── */
.result-reveal{
  display:flex;flex-direction:column;gap:4px;align-items:flex-end;
}
.result-score-row{
  display:flex;align-items:center;gap:10px;
}
.result-label{
  font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);
}
.result-actual{
  font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;color:var(--text);
}
.result-my-tipp{
  font-family:'Bebas Neue';font-size:18px;letter-spacing:1px;color:var(--text2);
  display:flex;align-items:center;gap:6px;
}
.eval-badge{
  display:inline-flex;align-items:center;gap:5px;
  font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;
  padding:4px 10px;border-radius:6px;
}
.ev-perfekt{background:rgba(245,200,66,0.15);border:1px solid rgba(245,200,66,0.4);color:var(--gold);}
.ev-tendenz_tor{background:rgba(0,229,160,0.1);border:1px solid rgba(0,229,160,0.35);color:var(--neon);}
.ev-tendenz{background:rgba(41,182,246,0.1);border:1px solid rgba(41,182,246,0.35);color:var(--sky);}
.ev-falsch{background:rgba(255,87,34,0.1);border:1px solid rgba(255,87,34,0.35);color:var(--fire2);}
.ev-open{background:rgba(61,79,110,0.2);border:1px solid rgba(61,79,110,0.35);color:var(--muted);}

.tipp-saved{display:flex;flex-direction:column;align-items:flex-end;gap:3px;}
.saved-score{font-family:'Bebas Neue';font-size:18px;color:var(--neon);letter-spacing:1px;display:flex;align-items:center;gap:7px;}
.badge-locked{font-family:'Rajdhani';font-size:12px;font-weight:700;color:var(--live);display:flex;align-items:center;gap:5px;}
.badge-missed{font-family:'Rajdhani';font-size:12px;font-weight:700;color:var(--muted);}
.badge-warn{font-family:'Rajdhani';font-size:11px;font-weight:700;color:var(--copper);letter-spacing:.5px;}

.live-banner{background:linear-gradient(90deg,rgba(244,67,54,0.14),rgba(244,67,54,0.04));
  border:1px solid rgba(244,67,54,0.35);border-radius:10px;padding:11px 18px;margin-bottom:14px;
  display:flex;align-items:center;gap:14px;overflow:hidden;position:relative;}
.live-banner::before{content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,rgba(244,67,54,0.05),transparent 40%,transparent 60%,rgba(244,67,54,0.05));
  animation:bannerScan 3s linear infinite;}
@keyframes bannerScan{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.lb-label{font-family:'Bebas Neue';font-size:14px;letter-spacing:3px;color:var(--live);display:flex;align-items:center;gap:8px;flex-shrink:0;}
.lb-items{display:flex;gap:24px;overflow:hidden;flex:1;}
.lb-item{font-family:'Rajdhani';font-weight:700;font-size:14px;white-space:nowrap;color:var(--text2);}
.lb-score{color:var(--live2);font-family:'Bebas Neue';font-size:17px;letter-spacing:1px;}

.today-banner{background:linear-gradient(90deg,rgba(255,87,34,0.1),rgba(255,87,34,0.02));
  border:1px solid rgba(255,87,34,0.3);border-radius:10px;padding:10px 18px;margin-bottom:14px;
  display:flex;align-items:center;gap:12px;}
.today-banner-icon{font-size:20px;}
.today-banner-text{font-family:'Rajdhani';font-weight:700;font-size:14px;color:#ff8a65;letter-spacing:.5px;}
.today-banner-count{margin-left:auto;font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;color:var(--copper);}

.gruppe-header{display:flex;align-items:center;gap:18px;padding-bottom:18px;margin-bottom:18px;border-bottom:1px solid var(--border3);}
.gr-letter{font-family:'Bebas Neue';font-size:72px;line-height:1;background:linear-gradient(160deg,var(--gold3),var(--copper));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;min-width:52px;filter:drop-shadow(0 0 20px rgba(245,200,66,0.2));}
.gr-pills{display:flex;gap:7px;flex-wrap:wrap;}
.gr-pill{display:flex;align-items:center;gap:6px;background:var(--g3);border:1px solid var(--border2);
  border-radius:6px;padding:5px 12px 5px 8px;font-family:'Rajdhani';font-weight:700;font-size:12px;letter-spacing:.5px;transition:all .15s;}
.gr-pill.my-team{background:rgba(245,200,66,0.09);border-color:rgba(245,200,66,0.35);color:var(--gold);box-shadow:0 0 10px rgba(245,200,66,0.06);}

.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px;}
.stat-box{background:var(--card);border:1px solid var(--border3);border-radius:12px;padding:18px 14px;text-align:center;position:relative;overflow:hidden;}
.stat-box::after{content:'';position:absolute;bottom:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--gold),transparent);opacity:.25;}
.stat-num{font-family:'Bebas Neue';font-size:52px;line-height:1;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:2px;}
.stat-label{font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-top:3px;}

.prog-track{height:5px;background:var(--g3);border-radius:3px;overflow:hidden;}
.prog-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--neon2),var(--neon));
  transition:width 1.2s cubic-bezier(.34,1.56,.64,1);box-shadow:0 0 8px rgba(0,229,160,0.4);}

.profile-card{background:var(--card);border:1px solid var(--border2);border-radius:12px;padding:22px;text-align:center;}
.profile-head{width:80px;height:80px;border-radius:10px;image-rendering:pixelated;border:2px solid transparent;
  background:linear-gradient(var(--card),var(--card)) padding-box,linear-gradient(135deg,var(--gold3),var(--copper)) border-box;}
.profile-name{font-family:'Bebas Neue';font-size:26px;letter-spacing:3px;margin-top:10px;}
.profile-sub{font-family:'Rajdhani';font-weight:700;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--neon2);margin-top:2px;}
.fav-row{display:flex;align-items:center;gap:9px;background:rgba(245,200,66,0.06);border:1px solid rgba(245,200,66,0.18);
  border-radius:8px;padding:9px 13px;margin-top:14px;text-align:left;}
.fav-name{font-family:'Rajdhani';font-weight:800;font-size:15px;color:var(--gold);letter-spacing:.5px;}
.fav-sub{font-size:11px;color:var(--muted);font-weight:600;}

.lb-search-wrap{position:relative;margin-bottom:14px;}
.lb-search{width:100%;padding:11px 16px 11px 44px;background:var(--g3);border:1px solid var(--border2);
  border-radius:10px;color:var(--text);font-family:'Exo 2';font-size:14px;font-weight:500;outline:none;transition:all .2s;}
.lb-search:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(245,200,66,0.08);}
.lb-search::placeholder{color:var(--muted);}
.lb-search-icon{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:17px;pointer-events:none;}
.lb-head-row{display:grid;grid-template-columns:56px 1fr 80px 110px;gap:12px;padding:6px 16px;
  font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:8px;}
.lb-row{display:grid;grid-template-columns:56px 1fr 80px 110px;align-items:center;gap:12px;
  padding:12px 16px;border-radius:10px;border:1px solid transparent;margin-bottom:6px;transition:all .2s;cursor:default;}
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
.lb-me-chip{font-family:'Rajdhani';font-weight:800;font-size:9px;letter-spacing:2px;
  background:rgba(41,182,246,0.15);color:var(--sky);border:1px solid rgba(41,182,246,0.3);
  padding:2px 8px;border-radius:4px;text-transform:uppercase;}
.lb-tipps-cell{font-family:'Rajdhani';font-weight:700;font-size:14px;color:var(--muted);text-align:center;}
.lb-pts{font-family:'Bebas Neue';font-size:26px;text-align:right;letter-spacing:1px;
  background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}

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

.pts-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px;}
.pts-row{display:flex;align-items:center;justify-content:space-between;background:var(--g3);border:1px solid var(--border2);border-radius:8px;padding:15px 18px;gap:12px;}
.pts-row.top{border-color:rgba(0,229,160,0.3);background:rgba(0,229,160,0.04);}
.pts-label{font-weight:700;font-size:14px;}
.pts-sub{font-size:12px;color:var(--muted);margin-top:2px;font-weight:500;}
.pts-val{font-family:'Bebas Neue';font-size:28px;letter-spacing:1px;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;white-space:nowrap;}
.pts-val.neg{background:linear-gradient(135deg,var(--fire2),var(--fire));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}

.code-display{font-family:'Bebas Neue';font-size:80px;letter-spacing:24px;color:var(--neon);text-align:center;
  padding:26px 20px;background:rgba(0,229,160,0.05);border:2px solid rgba(0,229,160,0.28);border-radius:12px;
  margin:22px 0;animation:codeGlow 2s ease-in-out infinite;}
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

.team-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(152px,1fr));gap:12px;}
.team-btn{position:relative;overflow:hidden;border:1px solid rgba(255,255,255,0.1);border-radius:11px;
  padding:0;cursor:pointer;min-height:140px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
  font-family:inherit;transition:transform .2s ease,box-shadow .2s ease,border-color .2s;
  box-shadow:0 4px 20px rgba(0,0,0,0.6);background:#0a0e1a;}
.team-btn-flag-bg{position:absolute;inset:0;background-size:cover;background-position:center;background-repeat:no-repeat;
  transition:transform .3s ease,filter .3s ease;filter:brightness(0.55) saturate(1.1);}
.team-btn:hover .team-btn-flag-bg{transform:scale(1.08);filter:brightness(0.75) saturate(1.3);}
.team-btn-overlay{position:absolute;inset:0;background:linear-gradient(180deg,transparent 0%,transparent 40%,rgba(0,0,0,0.45) 70%,rgba(0,0,0,0.88) 100%);z-index:1;}
.team-btn:hover{transform:translateY(-6px) scale(1.04);box-shadow:0 16px 40px rgba(0,0,0,0.8),0 0 0 2px rgba(245,200,66,0.5);border-color:rgba(245,200,66,0.4);}
.team-btn-group-badge{position:absolute;top:10px;right:10px;z-index:3;font-family:'Bebas Neue';font-size:13px;letter-spacing:2px;
  background:rgba(0,0,0,0.6);color:rgba(255,255,255,0.7);border:1px solid rgba(255,255,255,0.15);border-radius:5px;padding:2px 8px;backdrop-filter:blur(4px);}
.team-btn-name{position:relative;z-index:3;color:#fff;font-family:'Rajdhani';font-weight:800;font-size:14px;
  letter-spacing:.5px;text-transform:uppercase;text-shadow:0 1px 10px rgba(0,0,0,1),0 0 20px rgba(0,0,0,0.8);
  padding:0 10px;text-align:center;line-height:1.2;margin-bottom:12px;}

.fade-in{opacity:0;transform:translateY(16px);animation:fadeIn .45s ease forwards;}
.d1{animation-delay:.05s}.d2{animation-delay:.1s}.d3{animation-delay:.15s}
.d4{animation-delay:.2s}.d5{animation-delay:.25s}.d6{animation-delay:.3s}
@keyframes fadeIn{to{opacity:1;transform:translateY(0)}}

::-webkit-scrollbar{width:6px;}
::-webkit-scrollbar-track{background:var(--g1);}
::-webkit-scrollbar-thumb{background:rgba(245,200,66,0.2);border-radius:3px;}
::-webkit-scrollbar-thumb:hover{background:rgba(245,200,66,0.4);}
.divider{height:1px;background:var(--border2);margin:22px 0;}

@media(max-width:1000px){.match-card{grid-template-columns:1fr 160px 1fr;}.match-card .mc-action{display:none;}}
@media(max-width:700px){
  .navbar{padding:0 14px;}.nb-links{display:none;}
  .stats-grid{grid-template-columns:repeat(3,1fr);}
  .match-card{grid-template-columns:1fr 110px 1fr;}
  .mc-team-name{font-size:13px;}.mc-num{font-size:28px;}
  .pts-grid{grid-template-columns:1fr;}
  .podium-wrap{gap:7px;}.po-2,.po-3{margin-top:0;}
  .lb-row{grid-template-columns:44px 1fr 100px;}.lb-tipps-cell{display:none;}
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
    <div class="hero-chip fade-in">⚡ GrieferGames × FIFA World Cup 2026</div>
    <div class="hero-h1 fade-in d1">
      <span class="hero-h1-inner">WM 2026<br>TIPP<br>PORTAL</span>
    </div>
    <p class="hero-sub fade-in d2">Tippe alle 72 Gruppenspiele der Weltmeisterschaft und beweise, dass du der beste Fußball-Prophet auf GrieferGames bist.</p>
    <div class="hero-ctas fade-in d3">
      <a href="/register" class="btn btn-primary">⚡ Jetzt mitmachen</a>
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
const cv=document.getElementById('pcanvas');
const cx=cv.getContext('2d');
cv.width=window.innerWidth;cv.height=window.innerHeight;
window.addEventListener('resize',()=>{cv.width=window.innerWidth;cv.height=window.innerHeight;});
const EMOJIS=['⚽','🏆','⭐','🔥','🌍'];
const pts=Array.from({length:22},()=>({
  x:Math.random()*cv.width,y:Math.random()*cv.height,
  vx:(Math.random()-.5)*.35,vy:-(0.18+Math.random()*.5),
  size:12+Math.random()*20,op:0.03+Math.random()*.06,
  e:EMOJIS[Math.floor(Math.random()*EMOJIS.length)],
  r:Math.random()*Math.PI*2,rs:(Math.random()-.5)*.012
}));
(function anim(){
  cx.clearRect(0,0,cv.width,cv.height);
  pts.forEach(p=>{p.y+=p.vy;p.x+=p.vx;p.r+=p.rs;
    if(p.y<-50){p.y=cv.height+50;p.x=Math.random()*cv.width;}
    cx.save();cx.globalAlpha=p.op;cx.font=p.size+'px serif';
    cx.translate(p.x,p.y);cx.rotate(p.r);cx.fillText(p.e,-p.size/2,p.size/2);cx.restore();
  });requestAnimationFrame(anim);
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

@app.route('/register')
def register():
    code = str(random.randint(1000, 9999))
    active_codes[code] = {"status": "pending", "username": None}
    return BASE_HTML + f"""
    <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;position:relative;z-index:1;">
      <div style="width:100%;max-width:520px;">
        <div class="card fade-in" style="border-color:rgba(0,229,160,0.18);">
          <div style="text-align:center;margin-bottom:22px;">
            <div style="font-size:52px;margin-bottom:12px;">🔐</div>
            <div class="hero-chip" style="display:inline-flex;margin-bottom:14px;">Minecraft Verifizierung</div>
            <h2 style="font-family:'Bebas Neue';font-size:40px;letter-spacing:4px;">DEIN CODE</h2>
          </div>
          <div class="code-display">{code}</div>
          <div class="step-card" style="margin-bottom:18px;">
            <div style="font-family:'Rajdhani';font-weight:800;font-size:13px;letter-spacing:2px;color:var(--copper);margin-bottom:12px;text-transform:uppercase;">📋 So geht's:</div>
            <div>1. Logge dich auf <strong style="color:var(--text);">GrieferGames</strong> ein</div>
            <div>2. Schreibe diese Nachricht im Chat:</div>
            <div style="margin:10px 0 0 14px;"><code>/msg HostCasino #verifyWM {code}</code></div>
            <div style="margin-top:14px;color:var(--muted);font-size:12px;font-family:'Rajdhani';font-weight:600;">
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
      const iv=setInterval(()=>{{
        fetch('/api/check_status/{code}').then(r=>r.json()).then(d=>{{
          if(d.status==='verified'){{
            clearInterval(iv);
            const el=document.getElementById('status');
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
            user_db[username] = {"points": 1000, "tipps": {}, "lieblingsteam": None,
                                 "registered": datetime.datetime.now().strftime("%d.%m.%Y")}
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

@app.route('/choose_team', methods=['GET', 'POST'])
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
    <div class="page"><div class="wrap">
      <div style="text-align:center;margin-bottom:52px;" class="fade-in">
        <div class="hero-chip" style="display:inline-flex;margin-bottom:16px;">🌍 Teamauswahl</div>
        <h1 style="font-family:'Bebas Neue';font-size:clamp(48px,8vw,96px);line-height:.88;
             background:linear-gradient(160deg,#fff,var(--gold3),var(--copper));
             -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:18px;letter-spacing:2px;">
          WEM DRÜCKST DU<br>DIE DAUMEN?
        </h1>
        <p style="color:var(--text2);font-size:15px;max-width:400px;margin:0 auto;">Wähle dein Lieblingsteam — du kannst es danach jederzeit ändern.</p>
      </div>
      <form method="POST">{groups_html}</form>
    </div></div>
    </body></html>"""

# ==========================================
# DASHBOARD
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

    tabs_html = ""
    for g in WM_GRUPPEN.keys():
        ac = "active" if g == gruppe_id else ""
        tabs_html += f'<a href="/gruppe/{g}" class="tab {ac}">Gr.&nbsp;{g}</a>'

    team_pills = ""
    for t in gruppe_data["teams"]:
        is_mine = (t["name"] == lieblingsteam)
        mine_cls = "my-team" if is_mine else ""
        team_pills += f'<span class="gr-pill {mine_cls}">{flag_img(t["code"],18)} {t["name"]}</span>'

    laufende = []
    for g_data in WM_GRUPPEN.values():
        for sp in g_data["spiele"]:
            if get_spiel_status(sp) == "live":
                sc = get_live_score(sp["id"])
                score_txt = f"{sc['heim']}:{sc['gast']}" if sc and sc.get('heim') is not None else "?:?"
                laufende.append((sp['heim'], score_txt, sp['gast']))

    live_banner = ""
    if laufende:
        items = "".join(f'<span class="lb-item">{h} <span class="lb-score">{s}</span> {g}</span>' for h,s,g in laufende)
        live_banner = f"""
        <div class="live-banner fade-in">
          <div class="lb-label"><div class="dot-blink"></div> 🔴 LIVE JETZT</div>
          <div class="lb-items">{items}</div>
        </div>"""

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
          <span class="today-banner-text">Heute spielen <strong>{heute_spiele_count} Team{'s' if heute_spiele_count>1 else ''}</strong> in dieser Gruppe!</span>
          <span class="today-banner-count">{heute.strftime('%d.%m.')}</span>
        </div>"""

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
        day_label, day_css = get_day_label(spiel)

        card_extra = ""
        acc_cls = "acc-upcoming"

        if status == "live":
            card_extra = "is-live"; acc_cls = "acc-live"
        elif status == "final":
            card_extra = "is-final"; acc_cls = "acc-final"
        elif status == "soon":
            card_extra = "is-today"; acc_cls = "acc-soon"
        elif day_label == "HEUTE":
            card_extra = "is-today"; acc_cls = "acc-today"
        elif tipp:
            card_extra = "is-tipped"; acc_cls = "acc-tipped"

        # Center block
        if status in ("live", "final") and live_score and live_score.get("heim") is not None:
            num_cls = "num-live" if status == "live" else "num-final"
            chip = (f'<div class="status-badge sb-live"><div class="dot-blink"></div> LIVE</div>'
                    if status == "live" else
                    f'<div class="status-badge sb-final">ABPFIFF</div>')
            center_html = f"""<div class="mc-mid">{chip}
              <div class="mc-score-row">
                <span class="mc-num {num_cls}">{live_score["heim"]}</span>
                <span class="mc-colon">:</span>
                <span class="mc-num {num_cls}">{live_score["gast"]}</span>
              </div></div>"""
        elif status in ("live", "final"):
            chip = (f'<div class="status-badge sb-live"><div class="dot-blink"></div> LIVE</div>'
                    if status == "live" else
                    f'<div class="status-badge sb-final">ABPFIFF</div>')
            center_html = f'<div class="mc-mid">{chip}<div class="mc-vs">?:?</div></div>'
        elif status == "soon":
            center_html = f"""<div class="mc-mid">
              <div class="status-badge sb-soon">⚡ BALD</div>
              <div class="mc-time-today">{spiel['uhrzeit']}</div>
              <div class="day-badge day-today"><div class="dot-blink"></div> HEUTE</div>
            </div>"""
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

        # Action block — IMPROVED result display after final
        if status == "final" and tipp:
            td = tipp if isinstance(tipp, dict) else {"heim": "?", "gast": "?"}
            punkte_key = tipp.get("punkte_result") if isinstance(tipp, dict) else None
            eval_map = {
                "perfekt":     ("🎯 Perfekt!", "ev-perfekt", "+1.000 ◈"),
                "tendenz_tor": ("⚡ Tordifferenz!", "ev-tendenz_tor", "+500 ◈"),
                "tendenz":     ("✅ Tendenz!", "ev-tendenz", "+200 ◈"),
                "falsch":      ("❌ Falsch", "ev-falsch", "0 ◈"),
            }
            if punkte_key and punkte_key in eval_map and live_score and live_score.get("heim") is not None:
                label_txt, badge_cls, pts_txt = eval_map[punkte_key]
                action_html = f"""
                <div class="mc-action">
                  <div class="result-reveal">
                    <div class="result-label">ENDERGEBNIS</div>
                    <div class="result-actual">{live_score['heim']} : {live_score['gast']}</div>
                    <div class="result-my-tipp">
                      <span style="font-size:10px;color:var(--muted);font-family:'Rajdhani';font-weight:700;letter-spacing:1px;text-transform:uppercase;">Dein Tipp:</span>
                      {td['heim']} : {td['gast']}
                    </div>
                    <div class="eval-badge {badge_cls}">{label_txt} {pts_txt}</div>
                  </div>
                </div>"""
            elif live_score and live_score.get("heim") is not None:
                # Auswertung noch ausstehend
                action_html = f"""
                <div class="mc-action">
                  <div class="result-reveal">
                    <div class="result-label">ENDERGEBNIS</div>
                    <div class="result-actual">{live_score['heim']} : {live_score['gast']}</div>
                    <div class="result-my-tipp">
                      <span style="font-size:10px;color:var(--muted);font-family:'Rajdhani';font-weight:700;letter-spacing:1px;text-transform:uppercase;">Dein Tipp:</span>
                      {td['heim']} : {td['gast']}
                    </div>
                    <div class="eval-badge ev-open">⏳ Ausstehend</div>
                  </div>
                </div>"""
            else:
                # Kein Score vorhanden, nur Tipp anzeigen
                action_html = f"""
                <div class="mc-action">
                  <div class="tipp-saved">
                    <div class="saved-score">✅ {td['heim']} : {td['gast']}</div>
                    <div class="eval-badge ev-open" style="margin-top:4px;">⏳ Ergebnis ausstehend</div>
                  </div>
                </div>"""
        elif status == "final" and not tipp:
            score_txt = f"{live_score['heim']}:{live_score['gast']}" if live_score and live_score.get("heim") is not None else "?:?"
            action_html = f"""
            <div class="mc-action">
              <div class="result-reveal">
                <div class="result-label">ENDERGEBNIS</div>
                <div class="result-actual">{score_txt}</div>
                <div class="badge-missed" style="margin-top:4px;">— Kein Tipp abgegeben</div>
              </div>
            </div>"""
        elif status == "live":
            if tipp:
                td = tipp if isinstance(tipp, dict) else {"heim": "?", "gast": "?"}
                action_html = f"""
                <div class="mc-action">
                  <div class="tipp-saved">
                    <div class="result-label">DEIN TIPP</div>
                    <div class="saved-score">{td['heim']} : {td['gast']}</div>
                    <div class="badge-locked">🔴 Läuft gerade</div>
                  </div>
                </div>"""
            else:
                action_html = '<div class="mc-action"><div class="badge-locked">🔴 Läuft — kein Tipp</div></div>'
        elif not erlaubt:
            action_html = '<div class="mc-action"><div class="badge-locked">🔒 Gesperrt</div></div>'
        elif tipp:
            td = tipp if isinstance(tipp, dict) else {"heim": "?", "gast": "?"}
            action_html = f"""
            <div class="mc-action">
              <div class="tipp-saved">
                <div class="result-label">DEIN TIPP</div>
                <div class="saved-score">✅ {td['heim']} : {td['gast']}</div>
              </div>
            </div>"""
        else:
            btn_label = "Tippen (−50◈)"
            if status == "soon":
                btn_label = "⚡ Jetzt! (−50◈)"
            elif day_label == "HEUTE":
                btn_label = "🔥 Heute (−50◈)"
            warn_html = f'<div class="badge-warn">⚠️ Noch {max(0,min_bis)} Min!</div>' if status == "soon" else ""
            action_html = f"""
            <div class="mc-action">
              {warn_html}
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

        delay_cls = f"d{min(i+1,6)}"
        spiele_html += f"""
        <div class="match-card {card_extra} fade-in {delay_cls}" id="spiel-{sid}">
          <div class="mc-accent {acc_cls}"></div>
          <div class="mc-home">{flag_img(heim_code,24)}<span class="mc-team-name">{spiel['heim']}</span></div>
          {center_html}
          <div class="mc-away">{flag_img(gast_code,24)}<span class="mc-team-name">{spiel['gast']}</span></div>
          {action_html}
        </div>"""

    fav_team_html = ""
    if mein_team:
        fav_team_html = f"""
        <div class="fav-row">
          {flag_img(mein_team['code'],30)}
          <div>
            <div class="fav-name">{mein_team['name']}</div>
            <div class="fav-sub">Gruppe {mein_team['gruppe']} · Mein Favorit</div>
          </div>
          <a href="/choose_team" style="margin-left:auto;font-size:11px;color:var(--muted);text-decoration:none;font-family:'Rajdhani';font-weight:700;letter-spacing:1px;">ÄNDERN</a>
        </div>"""

    pct = int(getippt / total_spiele * 100) if total_spiele > 0 else 0

    return BASE_HTML + f"""
    {navbar}
    <div class="page"><div class="wrap">
      <div style="display:grid;grid-template-columns:280px 1fr;gap:18px;margin-bottom:32px;align-items:start;" class="fade-in">
        <div class="profile-card">
          <img class="profile-head" src="https://mc-heads.net/avatar/{username}/80" alt="{username}" onerror="this.style.opacity='0.3'">
          <div class="profile-name">{username}</div>
          <div class="profile-sub">GrieferGames</div>
          {fav_team_html}
        </div>
        <div>
          <div class="stats-grid">
            <div class="stat-box"><div class="stat-num">{points:,}</div><div class="stat-label">◈ Punkte</div></div>
            <div class="stat-box"><div class="stat-num">{getippt}</div><div class="stat-label">⚽ Tipps</div></div>
            <div class="stat-box"><div class="stat-num">{total_spiele-getippt}</div><div class="stat-label">📋 Offen</div></div>
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
        <div class="sec-sub">50 ◈ Einsatz · Gesperrt bei Anpfiff · Live-Scores in Echtzeit · <a href="/punkte" style="color:var(--copper);text-decoration:none;font-weight:700;">Punktesystem →</a></div>
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
    </div></div>

    <script>
      function checkLive(){{
        fetch('/api/live_scores').then(r=>r.json()).then(scores=>{{
          for(const[sid,data] of Object.entries(scores)){{
            if(data.status==='live'||data.status==='final'){{
              const el=document.getElementById('spiel-'+sid);
              if(el){{
                if((data.status==='live'&&!el.classList.contains('is-live'))||
                   (data.status==='final'&&!el.classList.contains('is-final'))){{
                  window.location.reload();return;
                }}
              }}
            }}
          }}
        }}).catch(()=>{{}});
      }}
      setTimeout(checkLive,10000);setInterval(checkLive,60000);
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
    heute = datetime.date.today()
    morgen = heute + datetime.timedelta(days=1)
    aktive_gruppe = None
    for gk, gd in WM_GRUPPEN.items():
        for sp in gd["spiele"]:
            try:
                if datetime.datetime.strptime(sp["datum"], "%d.%m.%Y").date() == heute:
                    aktive_gruppe = gk; break
            except: pass
        if aktive_gruppe: break
    if not aktive_gruppe:
        for gk, gd in WM_GRUPPEN.items():
            for sp in gd["spiele"]:
                try:
                    if datetime.datetime.strptime(sp["datum"], "%d.%m.%Y").date() == morgen:
                        aktive_gruppe = gk; break
                except: pass
            if aktive_gruppe: break
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
        load_data()
        if username not in user_db:
            return redirect(url_for('home'))
    gruppe_id = gruppe_id.upper()
    if gruppe_id not in WM_GRUPPEN:
        return redirect(url_for('dashboard'))
    return render_gruppe_page(username, gruppe_id, "dashboard")

# ==========================================
# LEADERBOARD
# ==========================================
@app.route('/leaderboard')
def leaderboard():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    user_info = user_db.get(username, {"points": 1000, "tipps": {}, "lieblingsteam": None})
    navbar = get_navbar(username, user_info["points"], user_info.get("lieblingsteam"), "leaderboard")
    lb = get_leaderboard()
    medals = {1: ("🥇","r1"), 2: ("🥈","r2"), 3: ("🥉","r3")}

    podium_html = ""
    if len(lb) >= 3:
        def podium_card(entry, rank, cls):
            medal, _ = medals.get(rank, ("",""))
            team = next((t for t in ALLE_TEAMS if t["name"] == entry.get("lieblingsteam")), None)
            team_html = f'{flag_img(team["code"],16)} {team["name"]}' if team else ""
            return f"""<div class="{cls}">
              <div class="po-medal">{medal}</div>
              <img class="po-head" src="https://mc-heads.net/avatar/{entry['username']}/56" alt="" onerror="this.style.display='none'">
              <div class="po-name">{entry['username']}</div>
              <div style="font-size:12px;color:var(--muted);font-family:'Rajdhani';font-weight:700;margin-top:3px;">{team_html}</div>
              <div class="po-pts">{entry['points']:,} ◈</div>
            </div>"""
        podium_html = f"""<div class="podium-wrap fade-in">
          {podium_card(lb[1],2,"podium-card po-2")}
          {podium_card(lb[0],1,"podium-card po-1")}
          {podium_card(lb[2],3,"podium-card po-3")}
        </div>"""

    rows_html = ""
    for i, entry in enumerate(lb, 1):
        rank_class = f"rk-{i}" if i <= 3 else ""
        is_me = (entry["username"] == username)
        if is_me: rank_class += " rk-me"
        medal, rank_color = medals.get(i, ("",""))
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

    my_rank = next((i+1 for i,e in enumerate(lb) if e["username"] == username), None)
    my_rank_txt = f"Platz {my_rank} von {len(lb)}" if my_rank else "–"

    return BASE_HTML + f"""
    {navbar}
    <div class="page"><div class="wrap" style="max-width:880px;">
      <div style="margin-bottom:32px;" class="fade-in">
        <div class="sec-eyebrow">🏆 Bestenliste</div>
        <div style="font-family:'Bebas Neue';font-size:56px;letter-spacing:4px;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">RANGLISTE</div>
        <div class="sec-sub">Dein Rang: <strong style="color:var(--gold);">{my_rank_txt}</strong></div>
      </div>
      {podium_html}
      <div class="lb-search-wrap fade-in">
        <div class="lb-search-icon">🔍</div>
        <input type="text" class="lb-search" id="lb-search" placeholder="Spieler suchen..." autocomplete="off">
      </div>
      <div class="lb-head-row fade-in">
        <div>#</div><div>Spieler</div><div style="text-align:center;">Tipps</div><div style="text-align:right;">Punkte</div>
      </div>
      <div id="lb-list">{rows_html}</div>
      <div id="lb-empty" style="display:none;text-align:center;padding:40px;color:var(--muted);font-family:'Rajdhani';font-weight:700;letter-spacing:1px;font-size:14px;">⚽ KEIN SPIELER GEFUNDEN</div>
    </div></div>
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
# PUNKTE PAGE
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
    <div class="page"><div class="wrap" style="max-width:780px;">
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
          <div class="pts-row"><div><div class="pts-label">Startkapital</div><div class="pts-sub">Bei der Registrierung</div></div><div class="pts-val">1.000 ◈</div></div>
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
            <div class="pts-label">Gesperrt sobald LIVE</div>
            <div class="pts-sub">Sobald das Spiel als LIVE markiert wird – kein Tippen mehr möglich</div>
          </div>
          <div style="font-family:'Bebas Neue';font-size:30px;color:var(--live);letter-spacing:2px;">LIVE</div>
        </div>
      </div>
      <div style="text-align:center;" class="fade-in d4">
        <a href="/dashboard" class="btn btn-primary" style="font-size:17px;padding:15px 40px;">⚽ Jetzt tippen</a>
      </div>
    </div></div>
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
                spiel_gefunden = spiel; break

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
# ADMIN PANEL CSS
# ==========================================
ADMIN_CSS = """
<style>
.ap-wrap{max-width:1140px;margin:0 auto;padding:32px 24px 100px;}

.ap-hero{
  display:flex;align-items:center;gap:16px;margin-bottom:36px;
  padding:20px 28px;
  background:linear-gradient(135deg,rgba(255,87,34,0.12),rgba(245,200,66,0.06));
  border:1px solid rgba(255,87,34,0.35);border-radius:14px;
}
.ap-hero-title{font-family:'Bebas Neue';font-size:38px;letter-spacing:4px;
  background:linear-gradient(90deg,var(--fire2),var(--gold3));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.ap-hero-sub{font-family:'Rajdhani';font-weight:700;font-size:12px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:2px;}

.ap-gruppe-header{display:flex;align-items:center;gap:14px;margin:28px 0 12px;padding-bottom:10px;border-bottom:1px solid rgba(245,200,66,0.12);}
.ap-gr-letter{font-family:'Bebas Neue';font-size:48px;line-height:1;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;min-width:40px;}
.ap-gr-label{font-family:'Rajdhani';font-weight:800;font-size:15px;letter-spacing:2px;text-transform:uppercase;color:var(--text2);}

/* ─── MATCH ROW ─── */
.ap-match{
  display:grid;
  grid-template-columns:220px 120px 1fr;
  align-items:start;gap:18px;
  background:var(--card2);
  border:1px solid var(--border3);
  border-radius:10px;padding:16px 20px;
  margin-bottom:8px;transition:border-color .2s;
  position:relative;
}
.ap-match::before{
  content:'';position:absolute;left:0;top:0;bottom:0;width:3px;border-radius:3px 0 0 3px;
  background:var(--muted);
}
.ap-match.status-live::before{background:var(--live);animation:accPulse 1s ease-in-out infinite;}
.ap-match.status-final::before{background:var(--neon);}
.ap-match.status-upcoming::before{background:var(--sky);}

.ap-match:hover{border-color:rgba(255,255,255,0.1);}
.ap-match.status-live{border-color:rgba(244,67,54,0.4);background:rgba(244,67,54,0.04);}
.ap-match.status-final{border-color:rgba(0,229,160,0.2);background:rgba(0,229,160,0.02);}

.ap-match-teams{font-family:'Rajdhani';font-weight:800;font-size:15px;letter-spacing:.5px;text-transform:uppercase;line-height:1.6;}
.ap-match-meta{font-size:11px;color:var(--muted);font-weight:600;font-family:'Rajdhani';letter-spacing:1px;margin-top:3px;}
.ap-match-id{font-family:'Bebas Neue';font-size:13px;letter-spacing:2px;color:var(--muted);background:var(--g3);padding:2px 8px;border-radius:4px;display:inline-block;margin-top:4px;}

/* Status center */
.ap-status-col{display:flex;flex-direction:column;align-items:center;gap:8px;padding-top:4px;}
.ap-status-badge{
  display:inline-flex;align-items:center;gap:6px;
  font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:2px;text-transform:uppercase;
  padding:5px 12px;border-radius:6px;
}
.ap-s-live{background:rgba(244,67,54,0.2);border:1px solid rgba(244,67,54,0.5);color:var(--live);}
.ap-s-final{background:rgba(0,229,160,0.12);border:1px solid rgba(0,229,160,0.35);color:var(--neon);}
.ap-s-upcoming{background:rgba(41,182,246,0.1);border:1px solid rgba(41,182,246,0.3);color:var(--sky);}
.ap-s-dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex-shrink:0;}
.ap-s-live .ap-s-dot{animation:dotBlink .7s step-end infinite;}

.ap-result-display{
  display:flex;align-items:center;gap:6px;
  font-family:'Bebas Neue';font-size:28px;letter-spacing:3px;color:var(--neon);
  background:rgba(0,229,160,0.07);border:1px solid rgba(0,229,160,0.25);
  border-radius:8px;padding:5px 14px;
}
.ap-result-vs{font-size:18px;color:var(--muted);}

.ap-tipps-count{
  display:flex;align-items:center;gap:6px;cursor:pointer;
  font-family:'Rajdhani';font-weight:700;font-size:12px;color:var(--muted);
  padding:4px 8px;border-radius:5px;border:1px solid transparent;transition:all .15s;
}
.ap-tipps-count:hover{color:var(--text2);background:rgba(255,255,255,0.04);border-color:var(--border2);}
.ap-tipps-num{font-family:'Bebas Neue';font-size:22px;color:var(--gold);letter-spacing:1px;}

/* ─── ACTIONS ─── */
.ap-actions{display:flex;flex-direction:column;gap:10px;}

.ap-status-btns{display:flex;gap:6px;flex-wrap:wrap;}
.ap-btn{
  font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;
  padding:8px 14px;border-radius:7px;border:1.5px solid transparent;
  cursor:pointer;transition:all .15s;background:transparent;
}
.ap-btn-live{color:var(--live);border-color:rgba(244,67,54,0.4);}
.ap-btn-live:hover{background:rgba(244,67,54,0.15);border-color:rgba(244,67,54,0.7);}
.ap-btn-live.active{background:rgba(244,67,54,0.2);border-color:var(--live);box-shadow:0 0 12px rgba(244,67,54,0.25);}
.ap-btn-upcoming{color:var(--sky);border-color:rgba(41,182,246,0.3);}
.ap-btn-upcoming:hover{background:rgba(41,182,246,0.1);border-color:rgba(41,182,246,0.6);}
.ap-btn-upcoming.active{background:rgba(41,182,246,0.15);border-color:var(--sky);}

/* SCORE ENTRY */
.ap-score-form{
  background:var(--g3);border:1px solid rgba(0,229,160,0.2);
  border-radius:9px;padding:12px 16px;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
}
.ap-score-form.hidden{display:none;}
.ap-score-in{
  width:48px;height:40px;background:var(--g2);
  border:1px solid rgba(255,255,255,0.12);color:#fff;
  border-radius:7px;text-align:center;font-family:'Bebas Neue';font-size:22px;
  -moz-appearance:textfield;appearance:none;transition:all .15s;
}
.ap-score-in::-webkit-inner-spin-button,.ap-score-in::-webkit-outer-spin-button{-webkit-appearance:none;}
.ap-score-in:focus{outline:none;border-color:var(--neon);box-shadow:0 0 0 3px rgba(0,229,160,0.12);}
.ap-score-sep{font-family:'Bebas Neue';font-size:20px;color:var(--muted);}
.ap-score-label{font-family:'Rajdhani';font-weight:800;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--neon2);}

.ap-finish-btn{
  background:linear-gradient(135deg,var(--neon2),var(--neon));color:#000;border:none;border-radius:7px;
  padding:9px 18px;font-family:'Rajdhani';font-weight:800;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;
  cursor:pointer;transition:all .2s;white-space:nowrap;
}
.ap-finish-btn:hover{transform:scale(1.04);box-shadow:0 4px 16px rgba(0,229,160,0.4);}

/* CORRECTION button (when already final) */
.ap-correct-btn{
  background:linear-gradient(135deg,rgba(245,200,66,0.18),rgba(224,123,57,0.12));
  color:var(--gold);border:1.5px solid rgba(245,200,66,0.4);border-radius:7px;
  padding:9px 18px;font-family:'Rajdhani';font-weight:800;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;
  cursor:pointer;transition:all .2s;white-space:nowrap;
}
.ap-correct-btn:hover{box-shadow:0 4px 16px rgba(245,200,66,0.25);transform:scale(1.03);}

/* TIPPS TABLE */
.ap-tipps-panel{
  display:none;
  background:var(--g3);border:1px solid var(--border2);border-radius:8px;padding:12px;
  margin-top:4px;
}
.ap-tipps-panel.open{display:block;}
.ap-tipps-table{width:100%;border-collapse:collapse;font-size:13px;font-family:'Rajdhani';font-weight:600;}
.ap-tipps-table th{text-align:left;padding:5px 10px;color:var(--muted);font-size:10px;letter-spacing:1.5px;text-transform:uppercase;border-bottom:1px solid var(--border3);}
.ap-tipps-table td{padding:6px 10px;border-bottom:1px solid rgba(255,255,255,0.025);}
.ap-tipps-table tr:last-child td{border-bottom:none;}
.ap-tipps-table tr:hover td{background:rgba(255,255,255,0.02);}
.trow-perfekt td:first-child{border-left:3px solid var(--gold);}
.trow-tendenz_tor td:first-child{border-left:3px solid var(--neon);}
.trow-tendenz td:first-child{border-left:3px solid var(--sky);}
.trow-falsch td:first-child{border-left:3px solid var(--fire);}
.trow-none td:first-child{border-left:3px solid var(--muted);}

/* Result badges in table */
.rb{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:800;letter-spacing:1px;text-transform:uppercase;}
.rb-perfekt{background:rgba(245,200,66,0.15);color:var(--gold);}
.rb-tendenz_tor{background:rgba(0,229,160,0.12);color:var(--neon);}
.rb-tendenz{background:rgba(41,182,246,0.12);color:var(--sky);}
.rb-falsch{background:rgba(255,87,34,0.12);color:var(--fire2);}
.rb-none{background:rgba(61,79,110,0.2);color:var(--muted);}

/* PLAYER TABLE */
.ap-players-table{width:100%;border-collapse:separate;border-spacing:0 5px;}
.ap-players-table th{text-align:left;padding:6px 14px;font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);}
.ap-players-table td{padding:10px 14px;background:var(--g3);font-family:'Rajdhani';font-weight:700;font-size:14px;}
.ap-players-table td:first-child{border-radius:8px 0 0 8px;}
.ap-players-table td:last-child{border-radius:0 8px 8px 0;text-align:right;}
.ap-players-table tr:hover td{background:rgba(255,255,255,0.04);}

/* TOAST */
#ap-toast{
  position:fixed;bottom:30px;right:30px;z-index:9999;
  background:var(--card);border:1px solid rgba(0,229,160,0.4);
  border-radius:10px;padding:14px 22px;
  font-family:'Rajdhani';font-weight:700;font-size:14px;color:var(--neon);letter-spacing:.5px;
  display:none;box-shadow:0 8px 30px rgba(0,0,0,0.5),0 0 20px rgba(0,229,160,0.1);
  animation:toastIn .3s ease;
}
@keyframes toastIn{from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1}}

/* MANUAL POINTS EDITOR */
.ap-pts-editor{
  display:none;flex-direction:column;gap:8px;
  background:var(--g3);border:1px solid rgba(245,200,66,0.2);border-radius:9px;padding:12px 16px;margin-top:8px;
}
.ap-pts-editor.open{display:flex;}
</style>
"""

def render_admin_panel():
    username = session["username"]
    user_info = user_db.get(username, {"points": 1000, "tipps": {}, "lieblingsteam": None})
    navbar = get_navbar(username, user_info["points"], user_info.get("lieblingsteam"), "adminpanel")

    gruppen_html = ""
    for gr_key, gr_data in WM_GRUPPEN.items():
        spiele_html = ""
        for spiel in gr_data["spiele"]:
            sid = spiel["id"]
            cache = live_scores_cache.get(sid, {})
            status = cache.get("status", "upcoming")
            heim_score = cache.get("heim")
            gast_score = cache.get("gast")

            # Count tipps
            tipps_fuer_spiel = {
                u: d["tipps"][sid]
                for u, d in user_db.items()
                if sid in d.get("tipps", {})
            }
            n_tipps = len(tipps_fuer_spiel)

            # Status badge
            if status == "live":
                status_badge = f'<div class="ap-status-badge ap-s-live"><div class="ap-s-dot"></div> LIVE</div>'
                card_cls = "status-live"
            elif status == "final":
                status_badge = f'<div class="ap-status-badge ap-s-final"><div class="ap-s-dot"></div> BEENDET</div>'
                card_cls = "status-final"
            else:
                status_badge = f'<div class="ap-status-badge ap-s-upcoming"><div class="ap-s-dot"></div> AUSSTEHEND</div>'
                card_cls = "status-upcoming"

            # Result display if final
            result_html = ""
            if status == "final" and heim_score is not None:
                result_html = f'<div class="ap-result-display"><span>{heim_score}</span><span class="ap-result-vs">:</span><span>{gast_score}</span></div>'

            # Tipps table
            tipps_rows = ""
            for uname, t in sorted(tipps_fuer_spiel.items()):
                pr = t.get("punkte_result", "")
                pts_map = {"perfekt": "+1000 ◈", "tendenz_tor": "+500 ◈", "tendenz": "+200 ◈", "falsch": "0 ◈"}
                pts_label = pts_map.get(pr, "–")
                rb_cls = f"rb-{pr}" if pr else "rb-none"
                label_txt = {"perfekt":"🎯 Perfekt","tendenz_tor":"⚡ Tordiff","tendenz":"✅ Tendenz","falsch":"❌ Falsch"}.get(pr,"⏳ Offen")
                row_cls = f"trow-{pr}" if pr else "trow-none"
                tipps_rows += f"""
                <tr class="{row_cls}">
                  <td>{uname}</td>
                  <td style="font-family:'Bebas Neue';font-size:18px;letter-spacing:2px;">{t['heim']} : {t['gast']}</td>
                  <td><span class="rb {rb_cls}">{label_txt}</span></td>
                  <td style="font-family:'Bebas Neue';font-size:16px;color:var(--gold);">{pts_label}</td>
                </tr>"""

            tipps_panel_html = ""
            if tipps_fuer_spiel:
                tipps_panel_html = f"""
                <div class="ap-tipps-panel" id="tipps-{sid}">
                  <table class="ap-tipps-table">
                    <tr><th>Spieler</th><th>Tipp</th><th>Ergebnis</th><th>Punkte</th></tr>
                    {tipps_rows}
                  </table>
                </div>"""

            # Show/hide finish form based on current status
            finish_hidden = "" if status == "live" else "hidden"
            correct_hidden = "" if status == "final" else "hidden"
            curr_h = heim_score if heim_score is not None else 0
            curr_g = gast_score if gast_score is not None else 0

            heim_code = TEAM_CODE.get(spiel["heim"], "")
            gast_code = TEAM_CODE.get(spiel["gast"], "")

            spiele_html += f"""
            <div class="ap-match {card_cls}" id="ap-match-{sid}">
              <!-- LEFT: match info -->
              <div>
                <div class="ap-match-teams">
                  {flag_img(heim_code,18)} {spiel['heim']}<br>
                  {flag_img(gast_code,18)} {spiel['gast']}
                </div>
                <div class="ap-match-meta">{spiel['datum']} · {spiel['uhrzeit']} Uhr</div>
                <div class="ap-match-id">{sid}</div>
              </div>
              <!-- CENTER: status + result -->
              <div class="ap-status-col">
                {status_badge}
                <div id="result-{sid}">{result_html}</div>
                <div onclick="toggleTipps('{sid}')" class="ap-tipps-count">
                  <span class="ap-tipps-num">{n_tipps}</span>
                  <span>Tipp{'s' if n_tipps!=1 else ''}</span>
                </div>
              </div>
              <!-- RIGHT: actions -->
              <div class="ap-actions">
                <!-- Status buttons -->
                <div class="ap-status-btns">
                  <button class="ap-btn ap-btn-live {'active' if status=='live' else ''}"
                    id="btn-live-{sid}"
                    onclick="setStatus('{sid}','live')">
                    🔴 LIVE setzen
                  </button>
                  <button class="ap-btn ap-btn-upcoming {'active' if status=='upcoming' else ''}"
                    id="btn-up-{sid}"
                    onclick="setStatus('{sid}','upcoming')">
                    ⏸ Zurücksetzen
                  </button>
                </div>

                <!-- Abpfiff form (shown when LIVE) -->
                <div id="finish-form-{sid}" class="ap-score-form {finish_hidden}">
                  <span class="ap-score-label">Abpfiff:</span>
                  <input type="number" id="fh-{sid}" min="0" max="30" value="{curr_h}" class="ap-score-in">
                  <span class="ap-score-sep">:</span>
                  <input type="number" id="fg-{sid}" min="0" max="30" value="{curr_g}" class="ap-score-in">
                  <button class="ap-finish-btn" onclick="finishGame('{sid}')">
                    ✅ Abpfiff + Punkte verteilen
                  </button>
                </div>

                <!-- Korrektur form (shown when FINAL) -->
                <div id="correct-form-{sid}" class="ap-score-form {correct_hidden}" style="border-color:rgba(245,200,66,0.3);">
                  <span class="ap-score-label" style="color:var(--gold);">🔧 Korrektur:</span>
                  <input type="number" id="ch-{sid}" min="0" max="30" value="{curr_h}" class="ap-score-in">
                  <span class="ap-score-sep">:</span>
                  <input type="number" id="cg-{sid}" min="0" max="30" value="{curr_g}" class="ap-score-in">
                  <button class="ap-correct-btn" onclick="correctGame('{sid}')">
                    🔧 Korrigieren & neu berechnen
                  </button>
                </div>

                <!-- Tipps panel -->
                {tipps_panel_html}
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

    # Stats
    n_live = sum(1 for g in WM_GRUPPEN.values() for s in g['spiele'] if live_scores_cache.get(s['id'],{}).get('status')=='live')
    n_final = sum(1 for g in WM_GRUPPEN.values() for s in g['spiele'] if live_scores_cache.get(s['id'],{}).get('status')=='final')
    n_tipps_total = sum(len(d.get('tipps',{})) for d in user_db.values())

    # Player table
    player_rows = ""
    for rank, (uname, data) in enumerate(
        sorted(user_db.items(), key=lambda x: -x[1].get("points", 0)), 1
    ):
        n = len(data.get("tipps", {}))
        team = next((t for t in ALLE_TEAMS if t["name"] == data.get("lieblingsteam")), None)
        team_flag = flag_img(team["code"], 14) + " " + team["name"] if team else "–"
        medals_map = {1:"🥇", 2:"🥈", 3:"🥉"}
        medal = medals_map.get(rank, str(rank))
        player_rows += f"""
        <tr>
          <td style="font-family:'Bebas Neue';font-size:22px;color:var(--muted);">{medal}</td>
          <td>
            <div style="display:flex;align-items:center;gap:9px;">
              <img src="https://mc-heads.net/avatar/{uname}/28" style="width:28px;height:28px;border-radius:5px;image-rendering:pixelated;" onerror="this.style.display='none'">
              <span style="font-family:'Rajdhani';font-weight:800;font-size:15px;">{uname}</span>
            </div>
          </td>
          <td style="font-size:12px;color:var(--muted);">{team_flag}</td>
          <td style="font-family:'Rajdhani';font-weight:700;font-size:13px;color:var(--muted);text-align:center;">{n} Tipps</td>
          <td style="font-family:'Bebas Neue';font-size:24px;letter-spacing:1px;background:linear-gradient(135deg,var(--gold3),var(--copper));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">{data.get('points',0):,} ◈</td>
        </tr>"""

    return BASE_HTML + ADMIN_CSS + f"""
    {navbar}
    <div id="ap-toast"></div>
    <div class="ap-wrap">

      <!-- HERO -->
      <div class="ap-hero fade-in">
        <div style="font-size:40px;line-height:1;">🛠️</div>
        <div>
          <div class="ap-hero-title">Admin Panel</div>
          <div class="ap-hero-sub">Nur für {ADMIN_USER} · Spielverwaltung & Punkteverteilung</div>
        </div>
        <div style="margin-left:auto;text-align:right;">
          <div style="font-family:'Bebas Neue';font-size:36px;letter-spacing:2px;color:var(--gold);">{len(user_db)}</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;">Registrierte Spieler</div>
        </div>
      </div>

      <!-- QUICK STATS -->
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:36px;" class="fade-in d1">
        <div class="card" style="text-align:center;padding:18px 12px;">
          <div style="font-family:'Bebas Neue';font-size:44px;line-height:1;color:var(--live);">{n_live}</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:3px;">🔴 Live jetzt</div>
        </div>
        <div class="card" style="text-align:center;padding:18px 12px;">
          <div style="font-family:'Bebas Neue';font-size:44px;line-height:1;color:var(--neon);">{n_final}</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:3px;">✅ Abgeschlossen</div>
        </div>
        <div class="card" style="text-align:center;padding:18px 12px;">
          <div style="font-family:'Bebas Neue';font-size:44px;line-height:1;color:var(--sky);">{n_tipps_total}</div>
          <div style="font-family:'Rajdhani';font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);text-transform:uppercase;margin-top:3px;">⚽ Tipps gesamt</div>
        </div>
      </div>

      <!-- HOW-TO BOX -->
      <div class="card fade-in d2" style="margin-bottom:28px;border-color:rgba(245,200,66,0.12);padding:18px 22px;">
        <div style="font-family:'Bebas Neue';font-size:18px;letter-spacing:3px;color:var(--gold);margin-bottom:10px;">📋 WORKFLOW</div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;font-family:'Rajdhani';font-weight:700;font-size:13px;color:var(--text2);">
          <div style="display:flex;align-items:flex-start;gap:10px;">
            <span style="font-family:'Bebas Neue';font-size:28px;color:var(--live);line-height:1;">1</span>
            <div><div style="color:var(--text);">🔴 LIVE setzen</div><div style="font-size:11px;color:var(--muted);margin-top:2px;">Sperrt Tipps sofort für alle Spieler</div></div>
          </div>
          <div style="display:flex;align-items:flex-start;gap:10px;">
            <span style="font-family:'Bebas Neue';font-size:28px;color:var(--neon);line-height:1;">2</span>
            <div><div style="color:var(--text);">✅ Abpfiff + Punkte</div><div style="font-size:11px;color:var(--muted);margin-top:2px;">Score eintragen → alle Tipps werden ausgewertet</div></div>
          </div>
          <div style="display:flex;align-items:flex-start;gap:10px;">
            <span style="font-family:'Bebas Neue';font-size:28px;color:var(--gold);line-height:1;">3</span>
            <div><div style="color:var(--text);">🔧 Korrigieren</div><div style="font-size:11px;color:var(--muted);margin-top:2px;">Fehler? Ergebnis ändern → Punkte werden neu berechnet</div></div>
          </div>
        </div>
      </div>

      <!-- SPIELE -->
      <div style="margin-bottom:12px;" class="fade-in d3">
        <div class="sec-eyebrow">⚽ Spielverwaltung</div>
        <div class="sec-title">Alle 72 Gruppenspiele</div>
        <div class="sec-sub">Klick auf Tipp-Zahl um alle Tipps eines Spiels zu sehen</div>
      </div>
      <div class="fade-in d4">{gruppen_html}</div>

      <!-- SPIELERLISTE -->
      <div style="margin:44px 0 12px;" class="fade-in">
        <div class="sec-eyebrow">👥 Spieler</div>
        <div class="sec-title">Rangliste</div>
      </div>
      <div class="card fade-in">
        {'<table class="ap-players-table"><tr><th>#</th><th>Spieler</th><th>Team</th><th style="text-align:center;">Tipps</th><th style="text-align:right;">Punkte</th></tr>' + player_rows + '</table>'
          if player_rows else
          '<div style="color:var(--muted);font-family:\'Rajdhani\';padding:20px;text-align:center;">Noch keine Spieler registriert.</div>'}
      </div>
    </div>

    <script>
    function showToast(msg, ok=true) {{
      const t = document.getElementById('ap-toast');
      t.textContent = msg;
      t.style.borderColor = ok ? 'rgba(0,229,160,0.5)' : 'rgba(244,67,54,0.5)';
      t.style.color = ok ? 'var(--neon)' : 'var(--live)';
      t.style.display = 'block';
      clearTimeout(t._to);
      t._to = setTimeout(() => {{ t.style.display = 'none'; }}, 3500);
    }}

    function setStatus(sid, newStatus) {{
      fetch('/api/admin/setstatus', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{spiel_id: sid, status: newStatus}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) {{
          const card = document.getElementById('ap-match-' + sid);
          card.className = 'ap-match status-' + (newStatus === 'upcoming' ? 'upcoming' : 'live');

          // Update status badge
          const statusCol = card.querySelector('.ap-status-col');
          if(newStatus === 'live') {{
            statusCol.querySelector('.ap-status-badge').className = 'ap-status-badge ap-s-live';
            statusCol.querySelector('.ap-status-badge').innerHTML = '<div class="ap-s-dot"></div> LIVE';
          }} else {{
            statusCol.querySelector('.ap-status-badge').className = 'ap-status-badge ap-s-upcoming';
            statusCol.querySelector('.ap-status-badge').innerHTML = '<div class="ap-s-dot"></div> AUSSTEHEND';
          }}

          // Toggle forms
          const ff = document.getElementById('finish-form-' + sid);
          const cf = document.getElementById('correct-form-' + sid);
          if(ff) ff.classList.toggle('hidden', newStatus !== 'live');
          if(cf) cf.classList.add('hidden'); // hide correction when resetting

          // Update button states
          document.getElementById('btn-live-' + sid).classList.toggle('active', newStatus === 'live');
          document.getElementById('btn-up-' + sid).classList.toggle('active', newStatus === 'upcoming');

          showToast(newStatus === 'live'
            ? '🔴 ' + sid + ' ist jetzt LIVE — Tipps gesperrt!'
            : '⏸ ' + sid + ' wurde zurückgesetzt');
        }} else {{
          showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
        }}
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
    }}

    function finishGame(sid) {{
      const h = parseInt(document.getElementById('fh-' + sid).value) || 0;
      const g = parseInt(document.getElementById('fg-' + sid).value) || 0;
      if(!confirm('Spiel ' + sid + ' mit Ergebnis ' + h + ':' + g + ' abschließen und Punkte verteilen?')) return;
      _sendFinish(sid, h, g, false);
    }}

    function correctGame(sid) {{
      const h = parseInt(document.getElementById('ch-' + sid).value) || 0;
      const g = parseInt(document.getElementById('cg-' + sid).value) || 0;
      if(!confirm('Ergebnis von ' + sid + ' auf ' + h + ':' + g + ' KORRIGIEREN?\\n\\nAlle alten Punkte werden zurückgebucht und neu berechnet.')) return;
      _sendFinish(sid, h, g, true);
    }}

    function _sendFinish(sid, h, g, isCorrection) {{
      fetch('/api/admin/finish', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{spiel_id: sid, heim: h, gast: g, correction: isCorrection}})
      }}).then(r => r.json()).then(d => {{
        if(d.ok) {{
          const card = document.getElementById('ap-match-' + sid);
          card.className = 'ap-match status-final';

          // Update status badge
          const statusBadge = card.querySelector('.ap-status-badge');
          if(statusBadge) {{ statusBadge.className = 'ap-status-badge ap-s-final'; statusBadge.innerHTML = '<div class="ap-s-dot"></div> BEENDET'; }}

          // Update result display
          const resultEl = document.getElementById('result-' + sid);
          if(resultEl) resultEl.innerHTML = '<div class="ap-result-display"><span>' + h + '</span><span class="ap-result-vs">:</span><span>' + g + '</span></div>';

          // Show correction form, hide finish form
          const ff = document.getElementById('finish-form-' + sid);
          const cf = document.getElementById('correct-form-' + sid);
          if(ff) ff.classList.add('hidden');
          if(cf) {{
            cf.classList.remove('hidden');
            // Update input values
            document.getElementById('ch-' + sid).value = h;
            document.getElementById('cg-' + sid).value = g;
          }}

          // Update button states
          const btnLive = document.getElementById('btn-live-' + sid);
          const btnUp = document.getElementById('btn-up-' + sid);
          if(btnLive) btnLive.classList.remove('active');
          if(btnUp) btnUp.classList.remove('active');

          const msg = isCorrection
            ? '🔧 ' + sid + ' korrigiert zu ' + h + ':' + g + ' · ' + d.count + ' Tipps neu bewertet'
            : '✅ ' + sid + ' abgeschlossen! ' + d.count + ' Tipps ausgewertet';
          showToast(msg);

          // Reload tipps panel
          setTimeout(() => location.reload(), 2500);
        }} else {{
          showToast('❌ Fehler: ' + (d.error || 'Unbekannt'), false);
        }}
      }}).catch(() => showToast('❌ Netzwerkfehler', false));
    }}

    function toggleTipps(sid) {{
      const panel = document.getElementById('tipps-' + sid);
      if(panel) panel.classList.toggle('open');
    }}
    </script>
    </body></html>"""

@app.route('/adminpanel')
def adminpanel():
    if "username" not in session or session["username"] != ADMIN_USER:
        return redirect(url_for('home'))
    return render_admin_panel()

# ==========================================
# ADMIN API ENDPOINTS
# ==========================================
@app.route('/api/admin/setstatus', methods=['POST'])
def api_admin_setstatus():
    if "username" not in session or session["username"] != ADMIN_USER:
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    sid = data.get("spiel_id", "")
    new_status = data.get("status", "upcoming")
    if new_status not in ("live", "upcoming", "final"):
        return jsonify({"ok": False, "error": "Ungültiger Status"})

    spiel = None
    for gd in WM_GRUPPEN.values():
        for sp in gd["spiele"]:
            if sp["id"] == sid:
                spiel = sp; break

    if not spiel:
        return jsonify({"ok": False, "error": "Spiel nicht gefunden"})

    if sid not in live_scores_cache:
        live_scores_cache[sid] = {"status": "upcoming", "heim": None, "gast": None, "minuto": None}

    live_scores_cache[sid]["status"] = new_status
    live_scores_cache[sid]["admin_locked"] = (new_status != "upcoming")

    if new_status == "upcoming":
        live_scores_cache[sid]["heim"] = None
        live_scores_cache[sid]["gast"] = None
        live_scores_cache[sid]["admin_locked"] = False

    try:
        with open(LIVESCORES_CACHE_FILE, 'w') as f:
            json.dump(live_scores_cache, f)
    except Exception as e:
        print(f"[WARN] Cache nicht gespeichert: {e}")

    print(f"[ADMIN] {sid} → {new_status}")
    return jsonify({"ok": True})

@app.route('/api/admin/finish', methods=['POST'])
def api_admin_finish():
    if "username" not in session or session["username"] != ADMIN_USER:
        return jsonify({"ok": False, "error": "Kein Zugriff"}), 403
    data = request.get_json()
    sid = data.get("spiel_id", "")
    heim_tore = int(data.get("heim", 0))
    gast_tore = int(data.get("gast", 0))
    is_correction = bool(data.get("correction", False))

    if sid not in live_scores_cache:
        live_scores_cache[sid] = {}
    live_scores_cache[sid]["status"] = "final"
    live_scores_cache[sid]["heim"] = heim_tore
    live_scores_cache[sid]["gast"] = gast_tore
    live_scores_cache[sid]["admin_locked"] = True

    try:
        with open(LIVESCORES_CACHE_FILE, 'w') as f:
            json.dump(live_scores_cache, f)
    except Exception as e:
        print(f"[WARN] Cache nicht gespeichert: {e}")

    # Auswertung (force=True für Korrektur)
    results = do_auswertung(sid, heim_tore, gast_tore, force=is_correction)

    action = "KORREKTUR" if is_correction else "Abpfiff"
    print(f"[ADMIN] {action} {sid} {heim_tore}:{gast_tore} — {len(results)} Tipps ausgewertet")
    for r in results:
        print(f"  → {r['user']}: {r['tipp']} = {r['erg']} (+{r['pts']})")

    return jsonify({"ok": True, "count": len(results), "results": results})

# Legacy redirects
@app.route('/auswertung')
@app.route('/admin')
def admin_redirect():
    if "username" not in session or session["username"] != ADMIN_USER:
        return redirect(url_for('home'))
    return redirect(url_for('adminpanel'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ==========================================
# START
# ==========================================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("   🏆  WM 2026 GRIEFERGAMES TIPP-PORTAL  🏆   ")
    print("="*60)
    print(f"   Daten: {os.path.abspath(DATA_FILE)}")
    print(f"   Live-Score-Cache: {os.path.abspath(LIVESCORES_CACHE_FILE)}")
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
PYEOF
echo "Done, line count: $(wc -l < /home/claude/wm_tipp_portal.py)"
