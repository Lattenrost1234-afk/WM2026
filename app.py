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

# Persistente Datenspeicherung
DATA_FILE = "wm2026_data.json"
LIVESCORES_CACHE_FILE = "livescores_cache.json"

app = Flask(__name__)
app.secret_key = "wm2026_griefergames_ultra_secret_1337"
# WICHTIG: Permanente Sessions – bleiben nach Browser-Schließen erhalten
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

active_codes = {}
user_db = {}
live_scores_cache = {}  # spiel_id -> {"heim": x, "gast": y, "status": "live"/"final"/"upcoming"}
verified_users = set()  # Spieler die bereits verifiziert wurden (für Cookie-Skip)

# ==========================================
# PERSISTENTER DATENSPEICHER
# ==========================================
def save_data():
    """Speichert user_db in JSON-Datei"""
    global verified_users
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_db, f, ensure_ascii=False, indent=2)
        verified_users = set(user_db.keys())
    except Exception as e:
        print(f"[FEHLER] Kann Daten nicht speichern: {e}")

def load_data():
    """Lädt user_db aus JSON-Datei"""
    global user_db, verified_users
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                user_db = json.load(f)
            verified_users = set(user_db.keys())  # Alle gespeicherten User sind bereits verifiziert
            print(f"[OK] {len(user_db)} Benutzer geladen aus {DATA_FILE}")
        except Exception as e:
            print(f"[WARN] Kann {DATA_FILE} nicht laden: {e}")
            user_db = {}
            verified_users = set()
    else:
        user_db = {}
        verified_users = set()
        print(f"[INFO] Neue Datenbankdatei wird angelegt: {DATA_FILE}")

# Beim Start laden
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
    "deadline_min": 0   # Gesperrt sobald Spiel LIVE ist (0 Min = bei Anpfiff)
}

# ==========================================
# LIVE-SCORES SYSTEM
# ==========================================
# Wir verwenden die kostenlose football-data.org API (WM 2026 Competition ID)
# API Key: kostenlos auf football-data.org registrieren (Free Tier reicht!)
# ODER: Wir nutzen TheSportsDB (keine Key nötig)
FOOTBALL_API_KEY = ""  # Optional: football-data.org API Key hier eintragen
WM_COMPETITION_ID = "2000"  # football-data.org: FIFA World Cup

def fetch_live_scores_thesportsdb():
    """
    Holt Live-Scores von TheSportsDB (kostenlos, kein Key).
    Parst Ergebnisse und matched sie mit unseren Spielen.
    """
    global live_scores_cache
    if not REQUESTS_AVAILABLE:
        return

    # TheSportsDB: Heute's Ereignisse für Soccer
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={today}&s=Soccer"

    try:
        resp = req_lib.get(url, timeout=5)
        if resp.status_code != 200:
            return
        data = resp.json()
        events = data.get("events") or []

        # Alle WM 2026 Spiele aus unserer DB
        for gruppe_data in WM_GRUPPEN.values():
            for spiel in gruppe_data["spiele"]:
                heim = spiel["heim"].lower()
                gast = spiel["gast"].lower()
                sid = spiel["id"]

                for ev in events:
                    ev_heim = (ev.get("strHomeTeam") or "").lower()
                    ev_gast = (ev.get("strAwayTeam") or "").lower()
                    ev_liga = (ev.get("strLeague") or "").lower()

                    # Matching: FIFA WM UND Teams matchen
                    if "world cup" not in ev_liga and "fifa" not in ev_liga:
                        continue

                    if _teams_match(heim, ev_heim) and _teams_match(gast, ev_gast):
                        status = ev.get("strStatus", "").lower()
                        score_home = ev.get("intHomeScore")
                        score_away = ev.get("intAwayScore")

                        cache_entry = {
                            "status": "upcoming",
                            "heim": None,
                            "gast": None,
                            "minuto": None
                        }

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
    """Fuzzy-Matching für Teamnamen (DE <-> EN)"""
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
    """Background-Thread: Aktualisiert Live-Scores alle 60 Sekunden"""
    while True:
        try:
            fetch_live_scores_thesportsdb()
            # Scores auch in Datei cachen
            try:
                with open(LIVESCORES_CACHE_FILE, 'w') as f:
                    json.dump(live_scores_cache, f)
            except:
                pass
        except Exception as e:
            print(f"[LIVE-UPDATER] Fehler: {e}")
        time.sleep(60)

# Live-Score Lookup aus Cache laden
if os.path.exists(LIVESCORES_CACHE_FILE):
    try:
        with open(LIVESCORES_CACHE_FILE, 'r') as f:
            live_scores_cache = json.load(f)
        print(f"[OK] Live-Score-Cache geladen ({len(live_scores_cache)} Einträge)")
    except:
        pass

# Background-Thread starten
threading.Thread(target=live_score_updater, daemon=True).start()

# ==========================================
# FLAGGEN
# ==========================================
def flag_img(code, size=32):
    code_lower = code.lower()
    special = {
        "sco": "gb-sct",
        "eng": "gb-eng",
        "wal": "gb-wls",
    }
    if code_lower in special:
        code_lower = special[code_lower]
    return f'<img src="https://flagcdn.com/h{size}/{code_lower}.png" width="{size}" height="{int(size*0.667)}" style="border-radius:3px; vertical-align:middle; object-fit:cover;" alt="" onerror="this.style.display=\'none\'">'

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
    """
    Gibt Status zurück:
    - 'upcoming': Noch nicht gestartet
    - 'live': Gerade läuft das Spiel (Live-Score aus API ODER Zeitschätzung)
    - 'final': Spiel beendet
    - 'soon': < 30 Min bis Anpfiff
    """
    sid = spiel["id"]

    # Zuerst Live-Cache prüfen
    if sid in live_scores_cache:
        status = live_scores_cache[sid].get("status", "upcoming")
        if status in ("live", "final"):
            return status

    # Zeitbasierte Schätzung als Fallback
    dt = parse_spiel_datetime(spiel)
    if dt is None:
        return "upcoming"
    jetzt = datetime.datetime.now()
    delta_min = (jetzt - dt).total_seconds() / 60

    if delta_min < -30:
        return "upcoming"
    elif -30 <= delta_min < 0:
        return "soon"
    elif 0 <= delta_min < 105:  # 90 Min + Nachspielzeit
        return "live"
    else:
        return "final"

def tipp_erlaubt(spiel):
    """True wenn Tipp noch erlaubt (Spiel noch nicht gestartet / noch nicht live)"""
    status = get_spiel_status(spiel)
    return status in ("upcoming", "soon")

def get_live_score(spiel_id):
    """Gibt Live-Score zurück oder None"""
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
                                            save_data()  # Sofort speichern!
                                        print(f"[✓] Spieler {spieler_name} verifiziert!")
                    letzte_groesse = aktuelle_groesse
            except Exception:
                pass
            time.sleep(0.2)

threading.Thread(target=minecraft_log_reader, daemon=True).start()

# ==========================================
# CSS
# ==========================================
BASE_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700;800;900&display=swap');

  :root {
    --gold:    #F5C842;
    --gold2:   #E8A020;
    --gold3:   #FFE066;
    --green:   #22C55E;
    --green2:  #16A34A;
    --red:     #EF4444;
    --live:    #FF3B3B;
    --live2:   #FF6B6B;
    --live-bg: rgba(255,59,59,0.06);
    --upcoming:#3B82F6;
    --soon:    #F59E0B;
    --dark:    #080B12;
    --dark2:   #0C1018;
    --dark3:   #111520;
    --dark4:   #161C2D;
    --card:    #0F1320;
    --card2:   #141929;
    --card3:   #192035;
    --border:  rgba(245,200,66,0.14);
    --border2: rgba(255,255,255,0.07);
    --border3: rgba(255,255,255,0.04);
    --text:    #E8EEFF;
    --text2:   #B8C4E0;
    --muted:   #5A6A8A;
    --accent:  #3B82F6;
    --rank1:   #F5C842;
    --rank2:   #C0C8D8;
    --rank3:   #CD8C50;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  html { scroll-behavior: smooth; }
  body {
    background: var(--dark);
    color: var(--text);
    font-family: 'Inter', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
  }
  body::before {
    content:'';
    position: fixed; inset: 0;
    background:
      radial-gradient(ellipse 70% 60% at 15% -10%, rgba(245,200,66,0.04) 0%, transparent 60%),
      radial-gradient(ellipse 50% 50% at 85% 110%, rgba(59,130,246,0.05) 0%, transparent 60%);
    pointer-events: none; z-index:0;
  }

  /* ====== NAVBAR ====== */
  .navbar {
    position: sticky; top:0; z-index:300;
    background: rgba(8,11,18,0.95);
    border-bottom: 1px solid var(--border3);
    backdrop-filter: blur(20px) saturate(1.5);
    height: 60px;
    display: flex; align-items: center;
    padding: 0 28px; gap: 20px;
  }
  .nav-logo {
    font-family: 'Bebas Neue'; font-size: 20px; letter-spacing: 4px;
    background: linear-gradient(90deg, var(--gold3), var(--gold2));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    white-space: nowrap; flex-shrink:0;
  }
  .nav-sep { width:1px; height:24px; background: var(--border3); flex-shrink:0; }
  .nav-links { display:flex; gap:2px; flex:1; }
  .nav-link {
    padding: 5px 12px; border-radius: 6px; text-decoration: none;
    font-weight: 600; font-size: 13px; letter-spacing: 0.2px;
    color: var(--muted); transition: all 0.15s;
  }
  .nav-link:hover { color: var(--text2); background: var(--dark4); }
  .nav-link.active { color: var(--gold); background: rgba(245,200,66,0.1); }
  .nav-right { display:flex; align-items:center; gap:10px; margin-left:auto; }
  .nav-points {
    font-weight: 700; font-size: 14px;
    color: var(--gold); background: rgba(245,200,66,0.08);
    border: 1px solid rgba(245,200,66,0.2); border-radius: 20px; padding: 4px 12px;
  }
  .nav-user { font-weight:600; font-size:13px; color: var(--text2); }
  .nav-head { width:30px; height:30px; border-radius:50%; image-rendering:pixelated; border:2px solid var(--border); }
  .nav-logout { font-size:12px; color:var(--muted); text-decoration:none; transition:color 0.2s; }
  .nav-logout:hover { color: var(--red); }

  /* ====== HERO ====== */
  .hero { text-align:center; padding: 90px 20px 70px; position:relative; z-index:1; }
  .hero-eyebrow {
    display:inline-flex; align-items:center; gap:8px;
    background: rgba(245,200,66,0.07); border:1px solid rgba(245,200,66,0.18);
    color: var(--gold); font-weight:700;
    font-size:11px; letter-spacing:3px; text-transform:uppercase;
    padding: 6px 18px; border-radius:100px; margin-bottom:28px;
  }
  .hero-title {
    font-family: 'Bebas Neue'; font-size: clamp(64px,11vw,130px);
    letter-spacing: 5px; line-height: 0.88;
    background: linear-gradient(170deg, #ffffff 0%, var(--gold3) 45%, var(--gold2) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    margin-bottom: 22px;
  }
  .hero-sub { color:var(--muted); font-size:16px; max-width:420px; margin:0 auto 44px; line-height:1.75; }

  /* ====== BUTTONS ====== */
  .btn {
    display:inline-flex; align-items:center; gap:8px;
    font-weight:700; font-size:14px;
    letter-spacing:0.5px; text-decoration:none;
    padding:12px 28px; border-radius:100px; border:none; cursor:pointer;
    transition: all 0.2s;
  }
  .btn-gold {
    background: linear-gradient(135deg, var(--gold3), var(--gold2));
    color:#000; box-shadow: 0 4px 24px rgba(245,200,66,0.25);
  }
  .btn-gold:hover { transform:translateY(-2px); box-shadow:0 8px 32px rgba(245,200,66,0.4); }
  .btn-outline {
    background:transparent; color:var(--text2);
    border:1px solid var(--border2);
  }
  .btn-outline:hover { border-color:var(--border); background:var(--dark4); }

  /* ====== CARDS ====== */
  .card {
    background: var(--card); border:1px solid var(--border2);
    border-radius:16px; padding:24px; position:relative; overflow:hidden;
  }
  .card-inner {
    background: var(--card2); border:1px solid var(--border3);
    border-radius:12px; padding:20px;
  }

  /* ====== LAYOUT ====== */
  .wrap { max-width:1240px; margin:0 auto; padding:0 24px; position:relative; z-index:1; }
  .wrap-sm { max-width:540px; margin:0 auto; padding:0 24px; position:relative; z-index:1; }
  .page { padding: 32px 0 100px; }

  /* ====== SECTION ====== */
  .sec-title {
    font-family:'Bebas Neue'; font-size:26px; letter-spacing:2px;
    color:var(--text); margin-bottom:4px;
  }
  .sec-sub { color:var(--muted); font-size:12px; margin-bottom:20px; }

  /* ====== TABS ====== */
  .tabs {
    display:flex; gap:4px; flex-wrap:wrap; margin-bottom:16px;
    background: var(--dark3); padding:4px; border-radius:12px;
    border:1px solid var(--border3);
  }
  .tab {
    padding:6px 13px; border-radius:8px; cursor:pointer;
    font-weight:700; font-size:13px;
    white-space:nowrap; transition:all 0.15s; text-decoration:none;
    color:var(--muted); letter-spacing:0.3px;
  }
  .tab:hover { color:var(--text2); background:var(--dark4); }
  .tab.active { background:var(--card2); border:1px solid var(--border2); color:var(--gold); }

  /* ====== MATCH CARD – GOOGLE-STYLE ====== */
  .match-card {
    display:grid;
    grid-template-columns: 1fr 140px 1fr 260px;
    align-items:center; gap:0;
    background: var(--card2); border:1px solid var(--border3);
    border-radius:14px; margin-bottom:6px;
    transition: all 0.2s; overflow:hidden; position:relative;
  }
  .match-card:hover { border-color: rgba(255,255,255,0.1); background:var(--card3); }

  /* Status-Streifen links */
  .match-card::before {
    content:''; position:absolute; left:0; top:0; bottom:0; width:3px;
    border-radius:3px 0 0 3px;
  }
  .match-card.upcoming-card::before { background: var(--upcoming); opacity:0.5; }
  .match-card.soon-card::before { background: var(--soon); }
  .match-card.live-card::before {
    background: var(--live);
    animation: stripe-pulse 1.5s ease-in-out infinite;
  }
  .match-card.final-card::before { background: var(--muted); opacity:0.3; }
  .match-card.tipped-card::before { background: var(--green); opacity:0.6; }

  @keyframes stripe-pulse {
    0%,100% { opacity:1; }
    50% { opacity:0.3; }
  }

  .match-card.live-card {
    border-color: rgba(255,59,59,0.25) !important;
    background: rgba(255,59,59,0.04) !important;
  }
  .match-card.final-card {
    opacity: 0.75;
  }
  .match-card.final-card:hover { opacity:1; }
  .match-card.tipped-card { border-color: rgba(34,197,94,0.2); }

  .match-cell { padding:14px 18px 14px 22px; }
  .match-cell-center { padding:14px 8px; }
  .match-cell-right { padding:14px 18px; }

  .match-team-home { text-align:right; }
  .match-team-away { text-align:left; }
  .team-name-row {
    display:flex; align-items:center; gap:8px;
    font-weight:700; font-size:15px; letter-spacing:-0.2px;
  }
  .team-name-row.home { justify-content:flex-end; }

  /* ====== LIVE SCORE CENTER (Google-Style) ====== */
  .score-center {
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    gap:4px; padding:10px 4px;
  }
  .score-nums {
    display:flex; align-items:center; gap:4px;
  }
  .score-num {
    font-family:'Bebas Neue'; font-size:30px; line-height:1;
    min-width:28px; text-align:center; transition:all 0.3s;
  }
  .score-num.live-color { color: var(--live2); }
  .score-num.final-color { color: var(--text); opacity:0.9; }
  .score-num.upcoming-color { color: var(--muted); font-size:18px; }

  /* Tor-Flash Animation */
  @keyframes goal-flash {
    0%   { transform:scale(1); }
    20%  { transform:scale(1.4); color: var(--gold3); }
    50%  { transform:scale(1.2); color: var(--gold); }
    100% { transform:scale(1); }
  }
  .goal-scored { animation: goal-flash 0.8s ease-out forwards; }

  .score-sep { font-family:'Bebas Neue'; font-size:22px; color:var(--dark4); }
  .score-sep-upcoming { font-weight:800; font-size:13px; color:var(--muted); letter-spacing:1px; }

  .status-badge {
    display:inline-flex; align-items:center; gap:4px;
    font-weight:800; font-size:9px; letter-spacing:2px; text-transform:uppercase;
    padding:2px 8px; border-radius:100px;
  }
  .badge-live {
    background: rgba(255,59,59,0.18); border:1px solid rgba(255,59,59,0.4);
    color: var(--live2);
  }
  .badge-final {
    background: rgba(90,106,138,0.15); border:1px solid rgba(90,106,138,0.3);
    color: var(--muted);
  }
  .badge-upcoming {
    background: rgba(59,130,246,0.12); border:1px solid rgba(59,130,246,0.25);
    color: #60A5FA;
  }
  .badge-soon {
    background: rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.3);
    color: var(--soon);
  }
  .live-dot {
    width:5px; height:5px; border-radius:50%; background:currentColor;
    animation: blink 1s step-end infinite;
  }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }

  /* Minuten-Anzeige */
  .live-minute {
    font-weight:700; font-size:10px; color: var(--live2);
    background: rgba(255,59,59,0.1); padding:1px 6px; border-radius:4px;
  }

  /* Anpfiff-Zeit */
  .kickoff-time {
    font-weight:700; font-size:16px; color:var(--text2); letter-spacing:0.5px;
  }
  .kickoff-date {
    font-size:10px; color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:1px;
  }

  /* ====== TIPP INPUT ====== */
  .match-action { text-align:right; }
  .tipp-row { display:flex; align-items:center; gap:5px; justify-content:flex-end; margin-top:4px; }
  .score-input {
    width:38px; height:32px; background:var(--dark3);
    border:1px solid var(--border2); color:#fff;
    border-radius:8px; text-align:center;
    font-family:'Bebas Neue'; font-size:18px;
    -moz-appearance:textfield; appearance:none;
    transition: all 0.15s;
  }
  .score-input::-webkit-inner-spin-button,
  .score-input::-webkit-outer-spin-button { -webkit-appearance:none; }
  .score-input:focus { outline:none; border-color: rgba(245,200,66,0.5); background:var(--dark2); box-shadow:0 0 0 3px rgba(245,200,66,0.08); }
  .score-sep-in { font-family:'Bebas Neue'; font-size:16px; color:var(--muted); }
  .tipp-btn {
    background:linear-gradient(135deg,var(--gold3),var(--gold2));
    color:#000; border:none; border-radius:8px;
    padding:5px 11px; font-weight:800;
    font-size:11px; cursor:pointer;
    letter-spacing:0.3px; transition:opacity 0.2s; white-space:nowrap;
  }
  .tipp-btn:hover { opacity:0.85; transform:scale(1.02); }
  .tipp-saved {
    color:var(--green); font-size:12px; font-weight:700;
    display:flex; align-items:center; gap:4px;
  }
  .tipp-saved-with-result { display:flex; flex-direction:column; align-items:flex-end; gap:3px; }
  .tipp-result-line {
    font-size:10px; color:var(--muted); font-weight:600; letter-spacing:0.5px;
  }
  .tipp-result-line.gewonnen { color: var(--green); }
  .tipp-result-line.verloren { color: var(--red); }
  .action-badge {
    display:inline-flex; align-items:center; gap:4px;
    font-size:11px; font-weight:700; letter-spacing:0.5px;
    padding:3px 10px; border-radius:6px;
  }
  .badge-locked { color:var(--live); background:rgba(255,59,59,0.08); border:1px solid rgba(255,59,59,0.2); }
  .badge-warn { color:var(--soon); background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.2); }
  .badge-missed { color:var(--muted); font-size:11px; font-weight:600; }

  /* ====== LIVE BANNER ====== */
  .live-games-banner {
    background: linear-gradient(90deg, rgba(255,59,59,0.08), rgba(255,59,59,0.03));
    border: 1px solid rgba(255,59,59,0.25);
    border-radius:12px; padding:12px 18px; margin-bottom:14px;
    display:flex; align-items:center; gap:14px; flex-wrap:wrap;
    overflow:hidden; position:relative;
  }
  .live-banner-scroll {
    display:flex; gap:20px; overflow:hidden; flex:1;
    -webkit-mask-image:linear-gradient(90deg,transparent 0,#000 5%,#000 90%,transparent 100%);
  }
  .live-banner-item {
    display:flex; align-items:center; gap:8px;
    font-size:13px; font-weight:700; white-space:nowrap;
    color:var(--text);
  }
  .live-banner-score { font-family:'Bebas Neue'; font-size:18px; color:var(--live2); }

  /* ====== STATS ====== */
  .stats-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:20px; }
  .stat-card {
    background:var(--card); border:1px solid var(--border3);
    border-radius:14px; padding:18px; text-align:center;
  }
  .stat-num {
    font-family:'Bebas Neue'; font-size:44px; line-height:1;
    background:linear-gradient(135deg,var(--gold3),var(--gold2));
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }
  .stat-label { color:var(--muted); font-size:10px; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; margin-top:4px; }

  /* ====== PROGRESS ====== */
  .progress-track { height:5px; background:var(--dark3); border-radius:3px; overflow:hidden; }
  .progress-fill { height:100%; background:linear-gradient(90deg,var(--gold3),var(--gold2)); border-radius:3px; transition:width 0.8s cubic-bezier(0.34,1.56,0.64,1); }

  /* ====== GRUPPE HEADER ====== */
  .gruppe-header { display:flex; align-items:center; gap:16px; margin-bottom:16px; }
  .gruppe-letter {
    font-family:'Bebas Neue'; font-size:52px; line-height:1;
    background:linear-gradient(180deg,var(--gold),var(--gold2));
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; min-width:36px;
  }
  .gruppe-teams { display:flex; gap:6px; flex-wrap:wrap; }
  .gruppe-team-pill {
    display:flex; align-items:center; gap:6px;
    background:var(--dark3); border:1px solid var(--border2);
    border-radius:20px; padding:4px 10px 4px 6px;
    font-family:'Barlow Condensed'; font-weight:700; font-size:13px;
  }
  .gruppe-team-pill.mein-team { border-color:rgba(255,215,0,0.4); background:rgba(255,215,0,0.06); color:var(--gold); }

  /* LEADERBOARD */
  .lb-row {
    display:grid; grid-template-columns: 48px 1fr 80px 80px;
    align-items:center; gap:12px;
    padding:12px 16px; border-radius:8px;
    border:1px solid transparent; margin-bottom:6px;
    transition: all 0.2s;
  }
  .lb-row:hover { background:var(--dark3); }
  .lb-row.rank-1 { background:rgba(255,215,0,0.07); border-color:rgba(255,215,0,0.3); }
  .lb-row.rank-2 { background:rgba(192,192,192,0.05); border-color:rgba(192,192,192,0.2); }
  .lb-row.rank-3 { background:rgba(205,127,50,0.07); border-color:rgba(205,127,50,0.25); }
  .lb-row.rank-me { border-color:rgba(59,130,246,0.4); background:rgba(59,130,246,0.05); }
  .lb-rank {
    font-family:'Bebas Neue'; font-size:26px; text-align:center;
    color: var(--muted);
  }
  .lb-rank.r1 { color: var(--rank1); text-shadow: 0 0 12px rgba(255,215,0,0.4); }
  .lb-rank.r2 { color: var(--rank2); }
  .lb-rank.r3 { color: var(--rank3); }
  .lb-user { display:flex; align-items:center; gap:10px; }
  .lb-head { width:28px; height:28px; border-radius:4px; image-rendering:pixelated; }
  .lb-name { font-weight:600; font-size:15px; }
  .lb-team { font-size:12px; color:var(--muted); }
  .lb-tipps { font-family:'Barlow Condensed'; font-weight:700; font-size:15px; color:var(--muted); text-align:center; }
  .lb-pts {
    font-family:'Bebas Neue'; font-size:22px; text-align:right;
    background:linear-gradient(135deg,var(--gold),var(--gold2));
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }

  /* PUNKTE INFO */
  .punkte-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-top:16px; }
  .punkte-row {
    display:flex; align-items:center; justify-content:space-between;
    background:var(--dark3); border:1px solid var(--border2);
    border-radius:8px; padding:10px 16px;
  }
  .punkte-label { font-size:14px; font-weight:500; }
  .punkte-val {
    font-family:'Bebas Neue'; font-size:20px;
    background:linear-gradient(135deg,var(--gold),var(--gold2));
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }
  .punkte-row.perfekt { border-color:rgba(0,230,118,0.3); background:rgba(0,230,118,0.04); }

  /* CODE BOX */
  .code-box {
    font-family:'Bebas Neue'; font-size:60px; letter-spacing:16px;
    color:var(--green); text-align:center;
    padding:24px; border-radius:10px;
    background:rgba(0,230,118,0.04); border:2px dashed rgba(0,230,118,0.3);
    margin:20px 0;
    text-shadow: 0 0 20px rgba(0,230,118,0.3);
  }
  .step-box {
    background:var(--dark3); border:1px solid var(--border2); border-radius:8px;
    padding:18px; font-size:14px; line-height:2.2;
  }
  .step-box code {
    background:rgba(255,23,68,0.12); color:#FF8099;
    border-radius:4px; padding:2px 8px; font-size:13px;
    font-family:'Courier New',monospace;
  }

  /* SPINNER */
  .spinner {
    width:36px; height:36px; margin:20px auto;
    border:3px solid var(--border2); border-top-color:var(--gold);
    border-radius:50%; animation:spin 0.7s linear infinite;
  }
  @keyframes spin { to { transform:rotate(360deg); } }

  .prog-anim { height:3px; background:var(--dark3); border-radius:2px; margin-top:16px; overflow:hidden; }
  .prog-anim-fill {
    height:100%; width:0%;
    background:linear-gradient(90deg,var(--gold),var(--gold2));
    animation:prog 60s linear forwards;
    border-radius:2px;
  }
  @keyframes prog { to { width:100%; } }

  .alert { padding:12px 18px; border-radius:7px; margin-bottom:14px; font-size:14px; font-weight:500; }
  .alert-green { background:rgba(0,230,118,0.08); border:1px solid rgba(0,230,118,0.25); color:var(--green); }
  .alert-gold  { background:rgba(255,215,0,0.06); border:1px solid rgba(255,215,0,0.2);  color:var(--gold); text-align:center; }

  .mc-head-lg { width:72px; height:72px; border-radius:10px; image-rendering:pixelated; border:2px solid var(--border); }

  .fade-in { animation: fadeIn 0.4s ease forwards; }
  @keyframes fadeIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }

  .divider { height:1px; background:var(--border2); margin:24px 0; }

  /* LIVE SCORES HEADER BANNER */
  .live-games-banner {
    background: linear-gradient(90deg, rgba(255,68,68,0.1), rgba(255,68,68,0.05));
    border: 1px solid rgba(255,68,68,0.3);
    border-radius:10px; padding:14px 18px; margin-bottom:16px;
    display:flex; align-items:center; gap:12px; flex-wrap:wrap;
  }
  .live-games-title {
    font-family:'Barlow Condensed'; font-weight:800; font-size:13px;
    letter-spacing:2px; text-transform:uppercase; color:var(--live);
    display:flex; align-items:center; gap:6px;
  }

  @media(max-width:900px){
    .match-card { grid-template-columns:1fr 100px 1fr; }
    .match-card .match-info { display:none; }
    .stats-grid { grid-template-columns:repeat(3,1fr); }
    .punkte-grid { grid-template-columns:1fr; }
  }
  @media(max-width:640px){
    .navbar { padding:0 16px; }
    .nav-links { display:none; }
    .stats-grid { grid-template-columns:1fr; }
    .lb-row { grid-template-columns:40px 1fr 80px; }
    .lb-tipps { display:none; }
    .match-card { grid-template-columns:1fr 80px 1fr; }
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
# NAVBAR HELPER
# ==========================================
def get_navbar(username, points, lieblingsteam, active_page="dashboard"):
    team_code = TEAM_CODE.get(lieblingsteam, "")
    team_flag_html = flag_img(team_code, 20) if team_code else ""
    pages = [
        ("dashboard", "/dashboard", "⚽ Tipps"),
        ("leaderboard", "/leaderboard", "🏆 Rangliste"),
        ("punkte", "/punkte", "📋 Punktesystem"),
    ]
    links = ""
    for page_id, url, label in pages:
        active_class = "active" if active_page == page_id else ""
        links += f'<a href="{url}" class="nav-link {active_class}">{label}</a>'
    return f"""
    <nav class="navbar">
      <span class="nav-logo">WM 2026</span>
      <div class="nav-sep"></div>
      <div class="nav-links">{links}</div>
      <div class="nav-right">
        {team_flag_html}
        <img class="nav-head" src="https://mc-heads.net/avatar/{username}/32" alt="" onerror="this.style.display='none'">
        <span class="nav-user">{username}</span>
        <span class="nav-points">🪙 {points:,}</span>
        <a href="/logout" class="nav-logout">Abmelden</a>
      </div>
    </nav>
    """

# ==========================================
# HOME
# ==========================================
HOME_HTML = BASE_HTML + """
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;">
  <div class="hero">
    <div class="hero-eyebrow">⚽ GrieferGames × FIFA World Cup 2026</div>
    <div class="hero-title">WM 2026<br>TIPP-PORTAL</div>
    <p class="hero-sub">Tippe alle 72 Gruppenspiele der Weltmeisterschaft und zeig wer der beste Fußball-Prophet auf GrieferGames ist.</p>
    <a href="/register" class="btn btn-gold" style="font-size:18px; padding:14px 36px;">⚡ Jetzt mitmachen</a>
  </div>
  <div class="wrap" style="padding-bottom:80px; max-width:800px;">
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;text-align:center;">
      <div class="card">
        <div style="font-size:32px;margin-bottom:8px;">🌍</div>
        <div style="font-family:'Bebas Neue';font-size:24px;color:var(--gold);">48 TEAMS</div>
        <div style="font-size:13px;color:var(--muted);">12 Gruppen</div>
      </div>
      <div class="card">
        <div style="font-size:32px;margin-bottom:8px;">⚽</div>
        <div style="font-family:'Bebas Neue';font-size:24px;color:var(--gold);">72 SPIELE</div>
        <div style="font-size:13px;color:var(--muted);">Gruppenphase</div>
      </div>
      <div class="card">
        <div style="font-size:32px;margin-bottom:8px;">🪙</div>
        <div style="font-family:'Bebas Neue';font-size:24px;color:var(--gold);">BIS 1.000 PTS</div>
        <div style="font-size:13px;color:var(--muted);">Pro Tipp</div>
      </div>
    </div>
  </div>
</div>
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
    <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;">
      <div class="wrap-sm fade-in" style="width:100%;">
        <div class="card" style="max-width:500px;margin:0 auto;">
          <div style="text-align:center;margin-bottom:20px;">
            <div style="font-size:40px;margin-bottom:10px;">🔐</div>
            <div class="hero-eyebrow" style="display:inline-flex;margin-bottom:12px;">Minecraft Verifizierung</div>
            <h2 style="font-family:'Bebas Neue';font-size:32px;letter-spacing:2px;">Dein Code</h2>
          </div>
          <div class="code-box">{code}</div>
          <div class="step-box" style="margin-bottom:18px;">
            <div style="font-family:'Barlow Condensed';font-weight:700;font-size:15px;letter-spacing:1px;color:var(--gold);margin-bottom:10px;">SO GEHT'S:</div>
            <div>1. Logge dich auf <strong>GrieferGames</strong> ein</div>
            <div>2. Schreibe diese Nachricht im Chat:</div>
            <div style="margin:8px 0 0 12px;">
              <code>/msg Lattenrost1234 #verifyWM {code}</code>
            </div>
            <div style="margin-top:12px;color:var(--muted);font-size:13px;">
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
            document.getElementById('status').innerHTML='✅ Verifiziert! Weiterleitung...';
            document.getElementById('status').className='alert alert-green';
            setTimeout(()=>window.location.href='/login_success/{code}',800);
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
                "points": 1000,
                "tipps": {},
                "lieblingsteam": None,
                "registered": datetime.datetime.now().strftime("%d.%m.%Y")
            }
            save_data()
        return jsonify({"success": True})
    return jsonify({"error": "Code nicht gefunden"}), 404

# NEU: Live-Score API endpoint für Frontend-Polling
@app.route('/api/live_scores')
def api_live_scores():
    """Gibt alle aktuellen Live-Scores zurück"""
    result = {}
    for gruppe_data in WM_GRUPPEN.values():
        for spiel in gruppe_data["spiele"]:
            sid = spiel["id"]
            status = get_spiel_status(spiel)
            score = get_live_score(sid)
            result[sid] = {
                "status": status,
                "score": score
            }
    return jsonify(result)

@app.route('/login_success/<code>')
def login_success(code):
    if code in active_codes and active_codes[code]["status"] == "verified":
        username = active_codes[code]["username"]
        session["username"] = username
        session.permanent = True  # WICHTIG: Permanente Session
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
            save_data()  # Speichern!
        return redirect(url_for('dashboard'))

    TEAM_COLORS = {
        "Mexiko":          ("1a7c3e", "d52b1e", "ffffff"),
        "Südkorea":        ("cd2e3a", "003478", "ffffff"),
        "Südafrika":       ("007749", "ffb612", "ffffff"),
        "Tschechien":      ("d7141a", "11457e", "ffffff"),
        "Schweiz":         ("ff0000", "a00000", "ffffff"),
        "Kanada":          ("ff0000", "8b0000", "ffffff"),
        "Katar":           ("8d1b3d", "ffffff", "ffffff"),
        "Bosnien":         ("002395", "fcd116", "ffffff"),
        "Brasilien":       ("009c3b", "fedf00", "ffffff"),
        "Marokko":         ("c1272d", "006233", "ffffff"),
        "Schottland":      ("003580", "ffffff", "ffffff"),
        "Haiti":           ("00209f", "d21034", "ffffff"),
        "USA":             ("b22234", "3c3b6e", "ffffff"),
        "Paraguay":        ("d52b1e", "009ada", "ffffff"),
        "Australien":      ("00843d", "ffcd00", "ffffff"),
        "Türkei":          ("e30a17", "c00d0d", "ffffff"),
        "Deutschland":     ("000000", "dd0000", "ffffff"),
        "Elfenbeinküste":  ("f77f00", "009a44", "ffffff"),
        "Ecuador":         ("ffd100", "0072ce", "ffffff"),
        "Ungarn":          ("ce2939", "477050", "ffffff"),
        "Niederlande":     ("ff6600", "ae1c28", "ffffff"),
        "Japan":           ("bc002d", "ffffff", "ffffff"),
        "Tunesien":        ("e70013", "ffffff", "ffffff"),
        "Schweden":        ("006aa7", "fecc02", "ffffff"),
        "Belgien":         ("000000", "ef3340", "ffffff"),
        "Ägypten":         ("ce1126", "c09300", "ffffff"),
        "Iran":            ("239f40", "da0000", "ffffff"),
        "Neuseeland":      ("00247d", "cc142b", "ffffff"),
        "Spanien":         ("aa151b", "f1bf00", "ffffff"),
        "Uruguay":         ("5aaee3", "ffffff", "ffffff"),
        "Saudi-Arabien":   ("006c35", "ffffff", "ffffff"),
        "Kap Verde":       ("003893", "cf2027", "ffffff"),
        "Frankreich":      ("002395", "ed2939", "ffffff"),
        "Senegal":         ("00853f", "fdef42", "ffffff"),
        "Norwegen":        ("ef2b2d", "002868", "ffffff"),
        "Kroatien":        ("ff0000", "171796", "ffffff"),
        "England":         ("cf142b", "00247d", "ffffff"),
        "Kolumbien":       ("fcd116", "003087", "ffffff"),
        "Serbien":         ("c6363c", "0c4076", "ffffff"),
        "Venezuela":       ("cf142b", "003087", "ffffff"),
        "Portugal":        ("006600", "ff0000", "ffffff"),
        "Argentinien":     ("74acdf", "ffffff", "ffffff"),
        "Chile":           ("d52b1e", "003087", "ffffff"),
        "Albanien":        ("e41e20", "000000", "ffffff"),
        "Italien":         ("009246", "ce2b37", "ffffff"),
        "Kamerun":         ("007a5e", "ce1126", "ffffff"),
        "Nigeria":         ("008751", "ffffff", "ffffff"),
        "Österreich":      ("ed2939", "ffffff", "ffffff"),
    }

    groups_html = ""
    for gruppe_key, gruppe_data in WM_GRUPPEN.items():
        teams_html = ""
        for team in gruppe_data["teams"]:
            code = team['code']
            special_map = {"sco": "gb-sct", "eng": "gb-eng"}
            flag_code = special_map.get(code, code)
            flag_src = f"https://flagcdn.com/h56/{flag_code}.png"
            c1, c2, txt = TEAM_COLORS.get(team['name'], ("1a2a4a", "2d4a8a", "ffffff"))
            teams_html += f"""
            <button type="submit" name="team" value="{team['name']}"
              class="team-nation-btn"
              style="--c1:#{c1};--c2:#{c2};--txt:#{txt};"
              onmouseover="this.style.transform='translateY(-4px) scale(1.03)'"
              onmouseout="this.style.transform=''"
            >
              <div class="team-nation-glow"></div>
              <img class="team-nation-flag" src="{flag_src}" alt="{team['name']}" onerror="this.style.opacity='0'">
              <span class="team-nation-name">{team['name']}</span>
              <span class="team-nation-group">Gruppe {gruppe_key}</span>
            </button>"""
        groups_html += f"""
        <div style="margin-bottom:28px;">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
            <span style="font-family:'Bebas Neue';font-size:36px;line-height:1;
                  background:linear-gradient(135deg,var(--gold),var(--gold2));
                  -webkit-background-clip:text;-webkit-text-fill-color:transparent;">{gruppe_key}</span>
            <div style="flex:1;height:1px;background:var(--border2);"></div>
          </div>
          <div class="team-nation-grid">{teams_html}</div>
        </div>"""

    return BASE_HTML + f"""
    <style>
      .team-nation-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }}
      .team-nation-btn {{
        position: relative; overflow: hidden;
        background: linear-gradient(135deg, var(--c1), var(--c2));
        border: none; border-radius: 12px; padding: 0; cursor: pointer;
        display: flex; flex-direction: column; align-items: center;
        gap: 0; font-family: inherit; transition: transform 0.2s ease, box-shadow 0.2s ease;
        box-shadow: 0 4px 16px rgba(0,0,0,0.4); min-height: 130px; justify-content: flex-end;
      }}
      .team-nation-btn:hover {{ box-shadow: 0 8px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,215,0,0.5); }}
      .team-nation-glow {{ position: absolute; inset: 0; background: linear-gradient(180deg, transparent 40%, rgba(0,0,0,0.55) 100%); z-index: 1; }}
      .team-nation-flag {{ position: absolute; top: 14px; left: 50%; transform: translateX(-50%); width: 64px; height: 43px; object-fit: cover; border-radius: 5px; box-shadow: 0 3px 12px rgba(0,0,0,0.5); z-index: 2; }}
      .team-nation-name {{ position: relative; z-index: 3; color: #fff; font-family: 'Barlow Condensed'; font-weight: 800; font-size: 15px; letter-spacing: 0.5px; text-shadow: 0 1px 6px rgba(0,0,0,0.8); padding: 0 10px; margin-top: 72px; text-align: center; line-height: 1.2; }}
      .team-nation-group {{ position: relative; z-index: 3; color: rgba(255,255,255,0.65); font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; padding-bottom: 12px; margin-top: 3px; }}
    </style>
    <div class="page">
      <div class="wrap">
        <div style="text-align:center;margin-bottom:52px;">
          <div class="hero-eyebrow" style="display:inline-flex;margin-bottom:16px;">🌍 Teamauswahl</div>
          <h1 class="hero-title" style="font-size:clamp(40px,7vw,80px);">Wen drückst du<br>die Daumen?</h1>
          <p class="hero-sub">Wähle dein Lieblingsteam für die WM 2026 – du kannst es später jederzeit ändern.</p>
        </div>
        <form method="POST">{groups_html}</form>
      </div>
    </div>
    </body></html>"""

# ==========================================
# DASHBOARD / GRUPPE VIEW (mit Live-Scores!)
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
        tabs_html += f'<a href="/gruppe/{g}" class="tab {ac}">GR. {g}</a>'

    # Team-Pills
    team_pills = ""
    for t in gruppe_data["teams"]:
        is_mine = (t["name"] == lieblingsteam)
        mine_class = "mein-team" if is_mine else ""
        team_pills += f'<span class="gruppe-team-pill {mine_class}">{flag_img(t["code"],20)} {t["name"]}</span>'

    # Laufende Spiele Banner
    laufende_spiele = []
    for g_data in WM_GRUPPEN.values():
        for sp in g_data["spiele"]:
            st = get_spiel_status(sp)
            if st == "live":
                sc = get_live_score(sp["id"])
                score_txt = f"{sc['heim']}:{sc['gast']}" if sc and sc.get('heim') is not None else "?:?"
                laufende_spiele.append(f"{sp['heim']} {score_txt} {sp['gast']}")

    live_banner = ""
    if laufende_spiele:
        spiele_items = " &nbsp;|&nbsp; ".join(laufende_spiele)
        live_banner = f"""
        <div class="live-games-banner">
          <div class="live-games-title"><div class="live-dot"></div> LIVE JETZT</div>
          <div style="font-family:'Barlow Condensed';font-size:14px;font-weight:600;">{spiele_items}</div>
        </div>"""

    # Spiele rendern
    spiele_html = ""
    for spiel in gruppe_data["spiele"]:
        sid = spiel["id"]
        tipp = tipps.get(sid)
        status = get_spiel_status(spiel)
        live_score = get_live_score(sid)
        min_bis = minuten_bis_spiel(spiel)
        erlaubt = status in ("upcoming", "soon")

        heim_code = TEAM_CODE.get(spiel["heim"], "")
        gast_code = TEAM_CODE.get(spiel["gast"], "")

        # Kartenstatus
        if status == "live":
            card_class = "match-card live-card"
        elif status == "final":
            card_class = "match-card final-card"
        elif tipp:
            card_class = "match-card tipped"
        elif not erlaubt:
            card_class = "match-card gesperrt"
        else:
            card_class = "match-card"

        # Mittelteil: Live-Score oder VS
        if status in ("live", "final") and live_score and live_score.get("heim") is not None:
            score_color = "live-color" if status == "live" else "final-color"
            status_badge = f'<div class="live-badge"><div class="live-dot"></div> LIVE</div>' if status == "live" else f'<div class="final-badge">ABPFIFF</div>'
            vs_html = f"""
            <div class="live-score-box">
              {status_badge}
              <div class="live-score-nums">
                <span class="live-score-num {score_color}">{live_score["heim"]}</span>
                <span class="live-score-sep">:</span>
                <span class="live-score-num {score_color}">{live_score["gast"]}</span>
              </div>
            </div>"""
        elif status in ("live", "final"):
            # Spiel ist live/final aber Score noch nicht im Cache
            badge = f'<div class="live-badge"><div class="live-dot"></div> LIVE</div>' if status == "live" else f'<div class="final-badge">ABPFIFF</div>'
            vs_html = f'<div class="live-score-box">{badge}<div class="match-vs">?:?</div></div>'
        else:
            vs_html = f'<div class="match-vs-block"><div class="match-vs">VS</div></div>'

        # Tipp-Bereich
        if tipp:
            td = tipp if isinstance(tipp, dict) else {"heim": "?", "gast": "?"}
            # Ergebnis-Auswertung anzeigen wenn Spiel vorbei
            punkte_info = ""
            if status == "final" and live_score and live_score.get("heim") is not None:
                punkte_key = tipp.get("punkte_result")
                if punkte_key == "perfekt":
                    punkte_info = f'<div class="tipp-result-line gewonnen">🎯 Perfekt! +1000 🪙</div>'
                elif punkte_key == "tendenz_tor":
                    punkte_info = f'<div class="tipp-result-line gewonnen">⚡ Tordifferenz! +500 🪙</div>'
                elif punkte_key == "tendenz":
                    punkte_info = f'<div class="tipp-result-line gewonnen">✅ Tendenz! +200 🪙</div>'
                elif punkte_key == "falsch":
                    punkte_info = f'<div class="tipp-result-line verloren">❌ Leider falsch</div>'
            tipp_html = f'<div class="tipp-row"><div class="tipp-saved-with-result"><div class="tipp-saved">✅ {td["heim"]} : {td["gast"]}</div>{punkte_info}</div></div>'
        elif status == "live":
            tipp_html = f'<div class="tipp-row"><span class="locked-badge">🔴 Läuft gerade</span></div>'
        elif status == "final":
            tipp_html = f'<div class="tipp-row"><span style="font-size:12px;color:var(--muted);font-family:\'Barlow Condensed\';font-weight:700;">— Kein Tipp</span></div>'
        elif not erlaubt:
            tipp_html = f'<div class="tipp-row"><span class="locked-badge">🔒 Gesperrt</span></div>'
        else:
            btn_label = "⏰ Jetzt! (-50🪙)" if min_bis <= 60 else "Tippen (-50🪙)"
            tipp_html = f"""<form action="/submittipp" method="POST" style="display:inline;">
              <input type="hidden" name="spiel_id" value="{sid}">
              <input type="hidden" name="redirect_gruppe" value="{gruppe_id}">
              <div class="tipp-row">
                <input type="number" name="tipp_heim" min="0" max="20" class="score-input" placeholder="0" required>
                <span class="score-sep">:</span>
                <input type="number" name="tipp_gast" min="0" max="20" class="score-input" placeholder="0" required>
                <button type="submit" class="tipp-btn">{btn_label}</button>
              </div>
            </form>"""

        deadline_notice = ""
        if not tipp and status == "soon":
            deadline_notice = f'<span class="soon-badge">⚠️ Noch {max(0, min_bis)} Min!</span>'

        spiele_html += f"""
        <div class="match-card {card_class.replace('match-card ', '')}" id="spiel-{sid}">
          <div class="match-team-home">
            <div class="team-name-row home">{spiel['heim']} {flag_img(heim_code, 24)}</div>
          </div>
          {vs_html}
          <div class="match-team-away">
            <div class="team-name-row">{flag_img(gast_code, 24)} {spiel['gast']}</div>
          </div>
          <div class="match-info">
            <div class="match-date">📅 {spiel['datum']} · {spiel['uhrzeit']} Uhr</div>
            {deadline_notice}
            {tipp_html}
          </div>
        </div>"""

    # Profile sidebar
    my_team_html = ""
    if mein_team:
        my_team_html = f"""
        <div style="display:flex;align-items:center;gap:10px;background:rgba(255,215,0,0.05);
             border:1px solid rgba(255,215,0,0.15);border-radius:8px;padding:10px 14px;margin-top:14px;">
          {flag_img(mein_team['code'], 32)}
          <div>
            <div style="font-family:'Barlow Condensed';font-weight:700;font-size:15px;color:var(--gold);">{mein_team['name']}</div>
            <div style="font-size:11px;color:var(--muted);">Gruppe {mein_team['gruppe']} · Mein Team</div>
          </div>
          <a href="/choose_team" style="margin-left:auto;font-size:11px;color:var(--muted);text-decoration:none;">ändern</a>
        </div>"""

    pct = int(getippt/total_spiele*100) if total_spiele > 0 else 0

    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap">
        <div style="display:grid;grid-template-columns:260px 1fr;gap:20px;margin-bottom:32px;align-items:start;">
          <div class="card">
            <div style="text-align:center;">
              <img class="mc-head-lg" src="https://mc-heads.net/avatar/{username}/72" alt="{username}">
              <div style="font-family:'Bebas Neue';font-size:26px;letter-spacing:2px;margin-top:10px;">{username}</div>
              <div style="font-size:12px;color:var(--muted);">GrieferGames</div>
            </div>
            {my_team_html}
          </div>
          <div>
            <div class="stats-grid">
              <div class="stat-card">
                <div class="stat-num" id="my-points">{points:,}</div>
                <div class="stat-label">🪙 Punkte</div>
              </div>
              <div class="stat-card">
                <div class="stat-num">{getippt}</div>
                <div class="stat-label">⚽ Tipps</div>
              </div>
              <div class="stat-card">
                <div class="stat-num">{total_spiele - getippt}</div>
                <div class="stat-label">📋 Ausstehend</div>
              </div>
            </div>
            <div class="card">
              <div style="font-family:'Barlow Condensed';font-weight:700;font-size:12px;color:var(--muted);letter-spacing:1.5px;margin-bottom:6px;">TIPP-FORTSCHRITT</div>
              <div style="font-size:13px;margin-bottom:8px;">{getippt} / {total_spiele} Spiele · {pct}%</div>
              <div class="progress-track">
                <div class="progress-fill" style="width:{pct}%;"></div>
              </div>
            </div>
          </div>
        </div>

        <div class="sec-title">⚽ Gruppenphase</div>
        <div class="sec-sub">50 Punkte Einsatz · Sperre bei Anpfiff · Live-Scores aktualisieren automatisch · <a href="/punkte" style="color:var(--gold);text-decoration:none;">Punktesystem →</a></div>

        {live_banner}
        <div class="tabs">{tabs_html}</div>

        <div class="card fade-in">
          <div class="gruppe-header">
            <div class="gruppe-letter">{gruppe_id}</div>
            <div>
              <div style="font-family:'Bebas Neue';font-size:18px;letter-spacing:2px;">GRUPPE {gruppe_id}</div>
              <div class="gruppe-teams">{team_pills}</div>
            </div>
          </div>
          {spiele_html}
        </div>
      </div>
    </div>

    <!-- Live-Score Polling: alle 30 Sek aktualisieren wenn Live-Spiele laufen -->
    <script>
      function checkLiveGames() {{
        fetch('/api/live_scores').then(r=>r.json()).then(scores => {{
          let hasLive = false;
          for (const [sid, data] of Object.entries(scores)) {{
            if (data.status === 'live' || data.status === 'final') {{
              hasLive = true;
              // Seite neu laden wenn Spielstatus sich geändert hat
              const el = document.getElementById('spiel-' + sid);
              if (el) {{
                const isLiveCard = el.classList.contains('live-card');
                const isFinalCard = el.classList.contains('final-card');
                if ((data.status === 'live' && !isLiveCard) ||
                    (data.status === 'final' && !isFinalCard)) {{
                  window.location.reload();
                  return;
                }}
              }}
            }}
          }}
          // Wenn Live-Spiele laufen, alle 30s neu laden für Score-Updates
          if (hasLive) {{
            setTimeout(() => window.location.reload(), 30000);
          }}
        }}).catch(()=>{{}});
      }}
      // Initial check nach 10 Sek, dann alle 60 Sek
      setTimeout(checkLiveGames, 10000);
      setInterval(checkLiveGames, 60000);
    </script>
    </body></html>"""

@app.route('/dashboard')
def dashboard():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    # WICHTIG: User aus DB laden falls nicht da (sollte durch persistente Speicherung nicht passieren)
    if username not in user_db:
        # Prüfen ob User in DB-Datei existiert
        load_data()
        if username not in user_db:
            # User wirklich nicht da – neu registrieren
            return redirect(url_for('home'))
    # Lieblingsteam-Gruppe oder A als Default
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
    medals = {1: ("🥇", "r1"), 2: ("🥈", "r2"), 3: ("🥉", "r3")}
    rows_html = ""
    for i, entry in enumerate(lb, 1):
        rank_class = f"rank-{i}" if i <= 3 else ""
        is_me = (entry["username"] == username)
        if is_me: rank_class += " rank-me"
        medal, rank_color = medals.get(i, ("", ""))
        rank_display = f'<span class="lb-rank {rank_color}">{medal or str(i)}</span>'
        team = next((t for t in ALLE_TEAMS if t["name"] == entry.get("lieblingsteam")), None)
        team_html = f'{flag_img(team["code"], 16)} {team["name"]}' if team else ""
        me_indicator = " 👈 Du" if is_me else ""
        rows_html += f"""
        <div class="lb-row {rank_class}">
          {rank_display}
          <div class="lb-user">
            <img class="lb-head" src="https://mc-heads.net/avatar/{entry['username']}/28" alt="" onerror="this.style.display='none'">
            <div>
              <div class="lb-name">{entry['username']}{me_indicator}</div>
              <div class="lb-team">{team_html}</div>
            </div>
          </div>
          <div class="lb-tipps">{entry['tipps']} Tipps</div>
          <div class="lb-pts">{entry['points']:,}</div>
        </div>"""
    if not lb:
        rows_html = '<div style="text-align:center;color:var(--muted);padding:40px;">Noch keine Spieler registriert.</div>'
    my_rank = next((i+1 for i, e in enumerate(lb) if e["username"] == username), None)
    my_rank_txt = f"Platz {my_rank} von {len(lb)}" if my_rank else "–"

    return BASE_HTML + f"""
    {navbar}
    <div class="page">
      <div class="wrap" style="max-width:800px;">
        <div style="margin-bottom:32px;">
          <div class="hero-eyebrow" style="display:inline-flex;margin-bottom:12px;">🏆 Rangliste</div>
          <div class="sec-title" style="font-size:40px;">Leaderboard</div>
          <div class="sec-sub">Dein Rang: <strong style="color:var(--gold);">{my_rank_txt}</strong></div>
        </div>
        {"" if len(lb) < 3 else f'''
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:32px;text-align:center;">
          <div class="card" style="order:1;margin-top:20px;border-color:rgba(192,192,192,0.3);">
            <div style="font-size:32px;margin-bottom:8px;">🥈</div>
            <img style="width:48px;height:48px;border-radius:7px;image-rendering:pixelated;" src="https://mc-heads.net/avatar/{lb[1]["username"]}/48" onerror="this.style.display=\'none\'">
            <div style="font-family:\'Bebas Neue\';font-size:18px;margin-top:8px;">{lb[1]["username"]}</div>
            <div style="font-family:\'Bebas Neue\';font-size:26px;color:var(--rank2);">{lb[1]["points"]:,}</div>
          </div>
          <div class="card" style="order:0;border-color:rgba(255,215,0,0.4);background:rgba(255,215,0,0.04);">
            <div style="font-size:40px;margin-bottom:8px;">🥇</div>
            <img style="width:56px;height:56px;border-radius:8px;image-rendering:pixelated;" src="https://mc-heads.net/avatar/{lb[0]["username"]}/56" onerror="this.style.display=\'none\'">
            <div style="font-family:\'Bebas Neue\';font-size:22px;margin-top:8px;color:var(--gold);">{lb[0]["username"]}</div>
            <div style="font-family:\'Bebas Neue\';font-size:32px;color:var(--gold);">{lb[0]["points"]:,}</div>
          </div>
          <div class="card" style="order:2;margin-top:30px;border-color:rgba(205,127,50,0.3);">
            <div style="font-size:28px;margin-bottom:8px;">🥉</div>
            <img style="width:44px;height:44px;border-radius:6px;image-rendering:pixelated;" src="https://mc-heads.net/avatar/{lb[2]["username"]}/44" onerror="this.style.display=\'none\'">
            <div style="font-family:\'Bebas Neue\';font-size:17px;margin-top:8px;">{lb[2]["username"]}</div>
            <div style="font-family:\'Bebas Neue\';font-size:24px;color:var(--rank3);">{lb[2]["points"]:,}</div>
          </div>
        </div>
        ''' if len(lb) >= 3 else ""}
        <div class="card">
          <div style="display:grid;grid-template-columns:48px 1fr 80px 80px;gap:12px;
               padding:8px 16px;margin-bottom:8px;
               font-family:'Barlow Condensed';font-weight:700;font-size:11px;
               letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;">
            <div>Rang</div><div>Spieler</div><div style="text-align:center;">Tipps</div><div style="text-align:right;">Punkte</div>
          </div>
          {rows_html}
        </div>
      </div>
    </div>
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
      <div class="wrap" style="max-width:720px;">
        <div style="margin-bottom:32px;">
          <div class="hero-eyebrow" style="display:inline-flex;margin-bottom:12px;">📋 Punktesystem</div>
          <div class="sec-title" style="font-size:40px;">Wie werden Punkte vergeben?</div>
          <div class="sec-sub">Jeder Tipp kostet 50 Punkte. Bei richtiger Vorhersage bekommst du Punkte zurück – und mehr!</div>
        </div>
        <div class="card" style="margin-bottom:20px;">
          <div style="font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;margin-bottom:4px;color:var(--gold);">🎯 TREFFERQUOTEN</div>
          <div style="font-size:13px;color:var(--muted);margin-bottom:16px;">Punkte werden nach Spielschluss automatisch gutgeschrieben</div>
          <div class="punkte-grid">
            <div class="punkte-row perfekt">
              <div><div style="font-weight:700;font-size:15px;">🎯 Perfektes Ergebnis</div><div style="font-size:12px;color:var(--muted);margin-top:2px;">z.B. Tipp 2:1 → Ergebnis 2:1</div></div>
              <div class="punkte-val">+1.000</div>
            </div>
            <div class="punkte-row">
              <div><div style="font-weight:700;font-size:15px;">⚡ Richtige Tordifferenz</div><div style="font-size:12px;color:var(--muted);margin-top:2px;">z.B. Tipp 3:1 → Ergebnis 2:0</div></div>
              <div class="punkte-val">+500</div>
            </div>
            <div class="punkte-row">
              <div><div style="font-weight:700;font-size:15px;">✅ Richtige Tendenz</div><div style="font-size:12px;color:var(--muted);margin-top:2px;">Sieg / Unentschieden / Niederlage</div></div>
              <div class="punkte-val">+200</div>
            </div>
            <div class="punkte-row" style="border-color:rgba(255,23,68,0.2);background:rgba(255,23,68,0.03);">
              <div><div style="font-weight:700;font-size:15px;">❌ Falsch getippt</div><div style="font-size:12px;color:var(--muted);margin-top:2px;">Falsche Tendenz</div></div>
              <div class="punkte-val" style="background:linear-gradient(135deg,var(--red),#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">0</div>
            </div>
          </div>
        </div>
        <div class="card" style="margin-bottom:20px;">
          <div style="font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;margin-bottom:4px;color:var(--gold);">💰 EINSATZ & STARTKAPITAL</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px;">
            <div class="punkte-row"><div style="font-weight:700;">Startpunkte (neu)</div><div class="punkte-val">1.000</div></div>
            <div class="punkte-row" style="border-color:rgba(255,23,68,0.2);"><div style="font-weight:700;">Einsatz pro Tipp</div><div class="punkte-val" style="background:linear-gradient(135deg,var(--red),#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">-50</div></div>
          </div>
        </div>
        <div class="card">
          <div style="font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;margin-bottom:4px;color:var(--gold);">🔴 TIPP-SPERRE</div>
          <div style="font-size:13px;color:var(--muted);margin-bottom:16px;">Wann ist Schluss mit Tippen?</div>
          <div class="punkte-row" style="border-color:rgba(255,68,68,0.3);background:rgba(255,68,68,0.04);">
            <div><div style="font-weight:700;font-size:15px;">🔒 Sperre bei Spielbeginn</div><div style="font-size:12px;color:var(--muted);margin-top:2px;">Sobald das Spiel als LIVE erkannt wird, ist Tippen gesperrt</div></div>
            <div style="font-family:'Bebas Neue';font-size:24px;color:var(--live);">LIVE</div>
          </div>
          <div style="margin-top:14px;padding:12px 16px;background:var(--dark3);border-radius:8px;font-size:13px;color:var(--muted);line-height:1.7;">
            💡 <strong style="color:var(--text);">Live-Scores:</strong> Während Spiele laufen, siehst du den Echtzeit-Spielstand direkt in der Übersicht. Die Seite aktualisiert sich automatisch alle 30 Sekunden bei laufenden Spielen.
          </div>
        </div>
        <div style="margin-top:20px;text-align:center;">
          <a href="/dashboard" class="btn btn-gold">⚽ Jetzt tippen</a>
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
        if status not in ("upcoming", "soon"):
            pass  # Zu spät
        elif user_db[username]["points"] >= PUNKTE_SYSTEM["einsatz"]:
            user_db[username]["points"] -= PUNKTE_SYSTEM["einsatz"]
            user_db[username]["tipps"][spiel_id] = {
                "heim": int(tipp_heim),
                "gast": int(tipp_gast)
            }
            save_data()  # Sofort speichern!

    if redirect_gruppe:
        return redirect(url_for('gruppe_ansicht', gruppe_id=redirect_gruppe))
    return redirect(url_for('dashboard'))

# ==========================================
# AUSWERTUNG (Admin-Route)
# /auswertung?key=ADMIN1337&spiel_id=A1&heim=2&gast=1
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
            punkte_val = PUNKTE_SYSTEM["perfekt"]
            ergebnis = "perfekt"
        elif tendenz(th, tg) == echte_tendenz and (th - tg) == echte_diff:
            punkte_val = PUNKTE_SYSTEM["tendenz_tor"]
            ergebnis = "tendenz_tor"
        elif tendenz(th, tg) == echte_tendenz:
            punkte_val = PUNKTE_SYSTEM["tendenz"]
            ergebnis = "tendenz"
        else:
            punkte_val = PUNKTE_SYSTEM["falsch"]
            ergebnis = "falsch"

        user_db[uname]["points"] = user_db[uname].get("points", 0) + punkte_val
        # Ergebnis im Tipp speichern
        user_db[uname]["tipps"][spiel_id]["punkte_result"] = ergebnis
        auswertungen.append(f"{uname}: {th}:{tg} → {ergebnis} (+{punkte_val})")

    save_data()  # Nach Auswertung speichern!

    return f"<pre>Auswertung {spiel_id} ({heim_tore}:{gast_tore}):\n" + "\n".join(auswertungen) + "\n\nGespeichert!</pre>"

# NEU: Admin-Übersicht aller User
@app.route('/admin')
def admin():
    key = request.args.get("key","")
    if key != "ADMIN1337":
        return "Kein Zugriff", 403
    output = f"<h2>WM 2026 Admin – {len(user_db)} Spieler</h2><pre>"
    for uname, data in sorted(user_db.items(), key=lambda x: -x[1].get("points",0)):
        output += f"{uname}: {data.get('points',0)} Punkte, {len(data.get('tipps',{}))} Tipps\n"
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
    print(f"   Daten werden gespeichert in: {os.path.abspath(DATA_FILE)}")
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
