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

# ==========================================
# KONFIGURATION
# ==========================================
chatlog_ordner = r"C:\Users\zaine\Downloads\mmc-develop-win32\MultiMC\instances\1.8.9\.minecraft\neoessentials\chatlog"

app = Flask(__name__)
app.secret_key = "wm2026_griefergames_ultra_secret_1337"

active_codes = {}
user_db = {}

# ==========================================
# PUNKTE-SYSTEM
# ==========================================
PUNKTE_SYSTEM = {
    "perfekt":     1000,   # Exaktes Ergebnis
    "tendenz_tor": 500,    # Richtige Tordifferenz
    "tendenz":     200,    # Richtige Tendenz (Sieg/Unentschieden/Niederlage)
    "falsch":      0,
    "einsatz":     50,     # Kosten pro Tipp
    "deadline_min": 10     # Minuten vor Spielbeginn = kein Tipp mehr möglich
}

# ==========================================
# FLAGGEN (als Image-URLs via flagcdn.com)
# ==========================================
def flag_img(code, size=32):
    """Gibt ein <img>-Tag mit der Länderflagge zurück"""
    code_lower = code.lower()
    # Spezialfälle
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

# Alle Teams als flache Liste mit code
ALLE_TEAMS = []
for gruppe_key, gruppe_data in WM_GRUPPEN.items():
    for team in gruppe_data["teams"]:
        ALLE_TEAMS.append({**team, "gruppe": gruppe_key})

# Mapping Name -> Code
TEAM_CODE = {t["name"]: t["code"] for t in ALLE_TEAMS}

# ==========================================
# HELPER: Spielzeit-Check (10 Min Deadline)
# ==========================================
def parse_spiel_datetime(spiel):
    """Gibt das datetime-Objekt des Spielbeginns zurück"""
    try:
        dt_str = f"{spiel['datum']} {spiel['uhrzeit']}"
        return datetime.datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
    except:
        return None

def tipp_erlaubt(spiel):
    """True wenn man noch tippen darf (mehr als 10 Min vor Anpfiff)"""
    dt = parse_spiel_datetime(spiel)
    if dt is None:
        return True
    jetzt = datetime.datetime.now()
    delta = dt - jetzt
    return delta.total_seconds() > PUNKTE_SYSTEM["deadline_min"] * 60

def minuten_bis_spiel(spiel):
    """Gibt Minuten bis Spielbeginn zurück (negativ = läuft/vorbei)"""
    dt = parse_spiel_datetime(spiel)
    if dt is None:
        return 9999
    jetzt = datetime.datetime.now()
    return int((dt - jetzt).total_seconds() / 60)

# ==========================================
# LEADERBOARD
# ==========================================
def get_leaderboard():
    """Gibt sortierte Liste aller User mit Punkten"""
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
# BACKGROUND LOG-READER
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
                                        print(f"[✓] Spieler {spieler_name} verifiziert!")
                    letzte_groesse = aktuelle_groesse
            except Exception:
                pass
            time.sleep(0.2)

threading.Thread(target=minecraft_log_reader, daemon=True).start()

# ==========================================
# CSS / BASE HTML
# ==========================================
BASE_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap');

  :root {
    --gold:    #FFD700;
    --gold2:   #FFA500;
    --green:   #00E676;
    --red:     #FF1744;
    --dark:    #07090F;
    --dark2:   #0B0E18;
    --dark3:   #101422;
    --card:    #0D1120;
    --card2:   #121829;
    --border:  rgba(255,215,0,0.12);
    --border2: rgba(255,255,255,0.06);
    --text:    #DDE5F5;
    --muted:   #6B7A99;
    --accent:  #3B82F6;
    --rank1:   #FFD700;
    --rank2:   #C0C0C0;
    --rank3:   #CD7F32;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  html { scroll-behavior: smooth; }
  body {
    background: var(--dark);
    color: var(--text);
    font-family: 'Barlow', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* BG PATTERN */
  body::before {
    content:'';
    position: fixed; inset: 0;
    background:
      radial-gradient(ellipse 80% 50% at 10% 0%, rgba(255,215,0,0.035) 0%, transparent 70%),
      radial-gradient(ellipse 60% 40% at 90% 100%, rgba(59,130,246,0.04) 0%, transparent 70%);
    pointer-events: none; z-index:0;
  }

  /* NAVBAR */
  .navbar {
    position: sticky; top:0; z-index:200;
    background: rgba(7,9,15,0.92);
    border-bottom: 1px solid var(--border);
    backdrop-filter: blur(16px);
    height: 64px;
    display: flex; align-items: center;
    padding: 0 32px; gap: 24px;
  }
  .nav-logo {
    font-family: 'Bebas Neue'; font-size: 22px; letter-spacing: 3px;
    background: linear-gradient(90deg, var(--gold), var(--gold2));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    white-space: nowrap;
  }
  .nav-sep { width:1px; height:28px; background: var(--border2); }
  .nav-links { display:flex; gap:4px; flex:1; }
  .nav-link {
    padding: 6px 14px; border-radius: 6px; text-decoration: none;
    font-family: 'Barlow Condensed'; font-weight: 700; font-size: 15px;
    letter-spacing: 0.5px; color: var(--muted); transition: all 0.15s;
  }
  .nav-link:hover { color: var(--text); background: var(--dark3); }
  .nav-link.active { color: var(--gold); background: rgba(255,215,0,0.08); }
  .nav-right { display:flex; align-items:center; gap:12px; margin-left:auto; }
  .nav-points {
    font-family: 'Barlow Condensed'; font-weight: 700; font-size: 16px;
    color: var(--gold); background: rgba(255,215,0,0.1);
    border: 1px solid rgba(255,215,0,0.25); border-radius: 6px; padding: 4px 12px;
  }
  .nav-user { font-weight:600; font-size:14px; color: var(--text); }
  .nav-head { width:32px; height:32px; border-radius:5px; image-rendering:pixelated; border:1px solid var(--border); }
  .nav-logout { font-size:12px; color:var(--muted); text-decoration:none; transition:color 0.2s; }
  .nav-logout:hover { color: var(--red); }

  /* HERO */
  .hero { text-align:center; padding: 80px 20px 60px; position:relative; z-index:1; }
  .hero-eyebrow {
    display:inline-flex; align-items:center; gap:8px;
    background: rgba(255,215,0,0.08); border:1px solid rgba(255,215,0,0.2);
    color: var(--gold); font-family:'Barlow Condensed'; font-weight:700;
    font-size:12px; letter-spacing:3px; text-transform:uppercase;
    padding: 6px 18px; border-radius:4px; margin-bottom:24px;
  }
  .hero-title {
    font-family: 'Bebas Neue'; font-size: clamp(56px,10vw,120px);
    letter-spacing: 4px; line-height: 0.9;
    background: linear-gradient(180deg, #fff 0%, var(--gold) 60%, var(--gold2) 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    margin-bottom: 20px;
  }
  .hero-sub { color:var(--muted); font-size:16px; max-width:440px; margin:0 auto 40px; line-height:1.7; }

  /* BUTTONS */
  .btn {
    display:inline-flex; align-items:center; gap:8px;
    font-family:'Barlow Condensed'; font-weight:700; font-size:16px;
    letter-spacing:1px; text-transform:uppercase; text-decoration:none;
    padding:12px 28px; border-radius:6px; border:none; cursor:pointer;
    transition: all 0.2s;
  }
  .btn-gold {
    background: linear-gradient(135deg, var(--gold), var(--gold2));
    color:#000; box-shadow: 0 4px 20px rgba(255,215,0,0.2);
  }
  .btn-gold:hover { transform:translateY(-2px); box-shadow:0 8px 28px rgba(255,215,0,0.35); }
  .btn-outline {
    background:transparent; color:var(--text);
    border:1px solid var(--border2);
  }
  .btn-outline:hover { border-color:var(--border); background:var(--dark3); }

  /* CARDS */
  .card {
    background: var(--card); border:1px solid var(--border);
    border-radius:12px; padding:24px; position:relative; overflow:hidden;
  }
  .card-inner {
    background: var(--card2); border:1px solid var(--border2);
    border-radius:10px; padding:20px;
  }

  /* LAYOUT */
  .wrap { max-width:1280px; margin:0 auto; padding:0 24px; position:relative; z-index:1; }
  .wrap-sm { max-width:560px; margin:0 auto; padding:0 24px; position:relative; z-index:1; }
  .page { padding: 40px 0 100px; }

  /* SECTION */
  .sec-title {
    font-family:'Bebas Neue'; font-size:28px; letter-spacing:2px;
    color:var(--text); margin-bottom:4px;
  }
  .sec-sub { color:var(--muted); font-size:13px; margin-bottom:20px; }

  /* TABS */
  .tabs { display:flex; gap:3px; flex-wrap:wrap; margin-bottom:20px; }
  .tab {
    padding:7px 14px; border-radius:6px; cursor:pointer;
    font-family:'Barlow Condensed'; font-weight:700; font-size:14px;
    letter-spacing:0.5px; border:1px solid transparent;
    white-space:nowrap; transition:all 0.15s; text-decoration:none; color:var(--muted);
  }
  .tab:hover { color:var(--text); background:var(--dark3); }
  .tab.active { background:rgba(255,215,0,0.1); border-color:rgba(255,215,0,0.25); color:var(--gold); }

  /* MATCH CARD */
  .match-card {
    display:grid; grid-template-columns: 1fr 60px 1fr 280px;
    align-items:center; gap:12px;
    background: var(--card2); border:1px solid var(--border2);
    border-radius:10px; padding:14px 18px; margin-bottom:8px;
    transition: border-color 0.2s;
  }
  .match-card:hover { border-color: rgba(255,215,0,0.2); }
  .match-card.tipped { border-color: rgba(0,230,118,0.25); background: rgba(0,230,118,0.02); }
  .match-card.gesperrt { opacity:0.65; }
  .match-team-home { text-align:right; }
  .match-team-away { text-align:left; }
  .team-name-row {
    display:flex; align-items:center; gap:8px;
    font-family:'Barlow Condensed'; font-weight:700; font-size:17px;
  }
  .team-name-row.home { justify-content:flex-end; }
  .match-vs {
    font-family:'Bebas Neue'; font-size:22px; color:var(--muted);
    text-align:center;
  }
  .match-info { text-align:right; }
  .match-date { font-size:11px; color:var(--muted); font-weight:600; letter-spacing:0.5px; }

  /* TIPP INPUT */
  .tipp-row { display:flex; align-items:center; gap:6px; justify-content:flex-end; margin-top:6px; }
  .score-input {
    width:42px; height:34px; background:var(--dark3);
    border:1px solid var(--border2); color:#fff;
    border-radius:5px; text-align:center;
    font-family:'Bebas Neue'; font-size:20px;
    -moz-appearance:textfield; appearance:none;
    transition: border-color 0.15s;
  }
  .score-input::-webkit-inner-spin-button,
  .score-input::-webkit-outer-spin-button { -webkit-appearance:none; }
  .score-input:focus { outline:none; border-color: rgba(255,215,0,0.5); background:var(--dark2); }
  .score-sep { font-family:'Bebas Neue'; font-size:18px; color:var(--muted); }
  .tipp-btn {
    background:linear-gradient(135deg,var(--gold),var(--gold2));
    color:#000; border:none; border-radius:5px;
    padding:5px 12px; font-family:'Barlow Condensed';
    font-weight:700; font-size:13px; cursor:pointer;
    letter-spacing:0.5px; transition:opacity 0.2s; white-space:nowrap;
  }
  .tipp-btn:hover { opacity:0.85; }
  .tipp-saved {
    color:var(--green); font-size:13px;
    font-family:'Barlow Condensed'; font-weight:700;
    display:flex; align-items:center; gap:4px;
  }
  .locked-badge {
    font-size:12px; color:var(--red);
    font-family:'Barlow Condensed'; font-weight:700;
    background: rgba(255,23,68,0.1); border:1px solid rgba(255,23,68,0.2);
    padding:3px 10px; border-radius:4px; display:inline-flex; align-items:center; gap:4px;
  }
  .soon-badge {
    font-size:12px; color:var(--gold2);
    font-family:'Barlow Condensed'; font-weight:700;
    background: rgba(255,165,0,0.1); border:1px solid rgba(255,165,0,0.2);
    padding:3px 10px; border-radius:4px; display:inline-flex; align-items:center; gap:4px;
  }

  /* STATS ROW */
  .stats-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:24px; }
  .stat-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:18px; text-align:center; }
  .stat-num {
    font-family:'Bebas Neue'; font-size:42px; line-height:1;
    background:linear-gradient(135deg,var(--gold),var(--gold2));
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  }
  .stat-label { color:var(--muted); font-size:11px; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; margin-top:4px; }

  /* PROGRESS */
  .progress-track { height:6px; background:var(--dark3); border-radius:3px; overflow:hidden; }
  .progress-fill { height:100%; background:linear-gradient(90deg,var(--gold),var(--gold2)); border-radius:3px; transition:width 0.5s; }

  /* GRUPPE HEADER */
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

  /* TEAM GRID */
  .team-select-grid {
    display:grid; grid-template-columns:repeat(auto-fill, minmax(150px,1fr)); gap:10px; margin-top:16px;
  }
  .team-select-btn {
    background:var(--dark3); border:2px solid var(--border2);
    border-radius:10px; padding:14px 10px; text-align:center;
    cursor:pointer; transition:all 0.2s; display:flex; flex-direction:column;
    align-items:center; gap:8px; font-family:'Barlow Condensed'; font-weight:700; font-size:14px;
  }
  .team-select-btn:hover {
    border-color:var(--gold); background:rgba(255,215,0,0.06);
    transform:translateY(-2px);
  }
  .team-flag-img { width:48px; height:32px; border-radius:4px; object-fit:cover; }
  .team-gruppe-tag { font-size:11px; color:var(--muted); font-weight:600; letter-spacing:1px; }

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

  /* PROGRESS BAR ANIMATED */
  .prog-anim { height:3px; background:var(--dark3); border-radius:2px; margin-top:16px; overflow:hidden; }
  .prog-anim-fill {
    height:100%; width:0%;
    background:linear-gradient(90deg,var(--gold),var(--gold2));
    animation:prog 60s linear forwards;
    border-radius:2px;
  }
  @keyframes prog { to { width:100%; } }

  /* ALERT */
  .alert { padding:12px 18px; border-radius:7px; margin-bottom:14px; font-size:14px; font-weight:500; }
  .alert-green { background:rgba(0,230,118,0.08); border:1px solid rgba(0,230,118,0.25); color:var(--green); }
  .alert-gold  { background:rgba(255,215,0,0.06); border:1px solid rgba(255,215,0,0.2);  color:var(--gold); text-align:center; }

  /* MC HEAD in profile */
  .mc-head-lg { width:72px; height:72px; border-radius:10px; image-rendering:pixelated; border:2px solid var(--border); }

  /* BADGE / MEDAL */
  .medal { font-size:22px; }

  /* FADE */
  .fade-in { animation: fadeIn 0.4s ease forwards; }
  @keyframes fadeIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }

  /* DIVIDER */
  .divider { height:1px; background:var(--border2); margin:24px 0; }

  @media(max-width:900px){
    .match-card { grid-template-columns:1fr; }
    .stats-grid { grid-template-columns:repeat(3,1fr); }
    .punkte-grid { grid-template-columns:1fr; }
  }
  @media(max-width:640px){
    .navbar { padding:0 16px; }
    .nav-links { display:none; }
    .stats-grid { grid-template-columns:1fr; }
    .team-select-grid { grid-template-columns:repeat(auto-fill,minmax(120px,1fr)); }
    .lb-row { grid-template-columns:40px 1fr 80px; }
    .lb-tipps { display:none; }
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

# Wird vom lokalen watcher.py aufgerufen wenn jemand #verifyWM schreibt
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
        print(f"[OK] {username} via API verifiziert!")
        return jsonify({"success": True})

    return jsonify({"error": "Code nicht gefunden"}), 404

@app.route('/login_success/<code>')
def login_success(code):
    if code in active_codes and active_codes[code]["status"] == "verified":
        username = active_codes[code]["username"]
        session["username"] = username
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
        return redirect(url_for('dashboard'))

    # Landesfarben-Verläufe pro Nation (c1 = Hauptfarbe, c2 = Sekundärfarbe, text = Textfarbe)
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
      .team-nation-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
        gap: 12px;
      }}
      .team-nation-btn {{
        position: relative; overflow: hidden;
        background: linear-gradient(135deg, var(--c1), var(--c2));
        border: none; border-radius: 12px;
        padding: 0; cursor: pointer;
        display: flex; flex-direction: column; align-items: center;
        gap: 0; font-family: inherit;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        box-shadow: 0 4px 16px rgba(0,0,0,0.4);
        min-height: 130px; justify-content: flex-end;
      }}
      .team-nation-btn:hover {{
        box-shadow: 0 8px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,215,0,0.5);
      }}
      .team-nation-glow {{
        position: absolute; inset: 0;
        background: linear-gradient(180deg, transparent 40%, rgba(0,0,0,0.55) 100%);
        z-index: 1;
      }}
      .team-nation-flag {{
        position: absolute; top: 14px; left: 50%; transform: translateX(-50%);
        width: 64px; height: 43px; object-fit: cover;
        border-radius: 5px;
        box-shadow: 0 3px 12px rgba(0,0,0,0.5);
        z-index: 2;
      }}
      .team-nation-name {{
        position: relative; z-index: 3;
        color: #fff; font-family: 'Barlow Condensed'; font-weight: 800;
        font-size: 15px; letter-spacing: 0.5px;
        text-shadow: 0 1px 6px rgba(0,0,0,0.8);
        padding: 0 10px; margin-top: 72px;
        text-align: center; line-height: 1.2;
      }}
      .team-nation-group {{
        position: relative; z-index: 3;
        color: rgba(255,255,255,0.65); font-size: 11px;
        font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
        padding-bottom: 12px; margin-top: 3px;
      }}
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
        tabs_html += f'<a href="/gruppe/{g}" class="tab {ac}">GR. {g}</a>'

    # Team-Pills der Gruppe
    team_pills = ""
    for t in gruppe_data["teams"]:
        is_mine = (t["name"] == lieblingsteam)
        mine_class = "mein-team" if is_mine else ""
        team_pills += f'<span class="gruppe-team-pill {mine_class}">{flag_img(t["code"],20)} {t["name"]}</span>'

    # Spiele
    spiele_html = ""
    for spiel in gruppe_data["spiele"]:
        sid = spiel["id"]
        tipp = tipps.get(sid)
        erlaubt = tipp_erlaubt(spiel)
        min_bis = minuten_bis_spiel(spiel)

        heim_code = TEAM_CODE.get(spiel["heim"], "")
        gast_code = TEAM_CODE.get(spiel["gast"], "")

        tipped_class = "tipped" if tipp else ("gesperrt" if not erlaubt else "")

        if tipp:
            td = tipp if isinstance(tipp, dict) else {"heim": "?", "gast": "?"}
            tipp_html = f'<div class="tipp-row"><span class="tipp-saved">✅ {td["heim"]} : {td["gast"]}</span></div>'
        elif not erlaubt:
            tipp_html = f'<div class="tipp-row"><span class="locked-badge">🔒 Gesperrt</span></div>'
        elif min_bis <= 60:
            tipp_html = f"""<form action="/submittipp" method="POST" style="display:inline;">
              <input type="hidden" name="spiel_id" value="{sid}">
              <input type="hidden" name="redirect_gruppe" value="{gruppe_id}">
              <div class="tipp-row">
                <input type="number" name="tipp_heim" min="0" max="20" class="score-input" placeholder="0" required>
                <span class="score-sep">:</span>
                <input type="number" name="tipp_gast" min="0" max="20" class="score-input" placeholder="0" required>
                <button type="submit" class="tipp-btn">⏰ Jetzt! (-50🪙)</button>
              </div>
            </form>"""
        else:
            tipp_html = f"""<form action="/submittipp" method="POST" style="display:inline;">
              <input type="hidden" name="spiel_id" value="{sid}">
              <input type="hidden" name="redirect_gruppe" value="{gruppe_id}">
              <div class="tipp-row">
                <input type="number" name="tipp_heim" min="0" max="20" class="score-input" placeholder="0" required>
                <span class="score-sep">:</span>
                <input type="number" name="tipp_gast" min="0" max="20" class="score-input" placeholder="0" required>
                <button type="submit" class="tipp-btn">Tippen (-50🪙)</button>
              </div>
            </form>"""

        deadline_notice = ""
        if not tipp and not erlaubt:
            deadline_notice = ""
        elif not tipp and 0 < min_bis <= PUNKTE_SYSTEM["deadline_min"]:
            deadline_notice = f'<span class="soon-badge">⚠️ Noch {min_bis} Min!</span>'

        spiele_html += f"""
        <div class="match-card {tipped_class}">
          <div class="match-team-home">
            <div class="team-name-row home">{spiel['heim']} {flag_img(heim_code, 24)}</div>
          </div>
          <div class="match-vs">VS</div>
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
          <!-- SIDEBAR -->
          <div class="card">
            <div style="text-align:center;">
              <img class="mc-head-lg" src="https://mc-heads.net/avatar/{username}/72" alt="{username}">
              <div style="font-family:'Bebas Neue';font-size:26px;letter-spacing:2px;margin-top:10px;">{username}</div>
              <div style="font-size:12px;color:var(--muted);">GrieferGames</div>
            </div>
            {my_team_html}
          </div>
          <!-- STATS -->
          <div>
            <div class="stats-grid">
              <div class="stat-card">
                <div class="stat-num">{points:,}</div>
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

        <!-- TIPPS BEREICH -->
        <div class="sec-title">⚽ Gruppenphase</div>
        <div class="sec-sub">50 Punkte Einsatz pro Tipp · Sperre 10 Min vor Anpfiff · <a href="/punkte" style="color:var(--gold);text-decoration:none;">Punktesystem ansehen →</a></div>
        
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
    </body></html>"""

@app.route('/dashboard')
def dashboard():
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        user_db[username] = {"points": 1000, "tipps": {}, "lieblingsteam": None}
    mein_team = next((t for t in ALLE_TEAMS if t["name"] == user_db[username].get("lieblingsteam")), None)
    aktive_gruppe = mein_team["gruppe"] if mein_team else "A"
    return render_gruppe_page(username, aktive_gruppe, "dashboard")

@app.route('/gruppe/<gruppe_id>')
def gruppe_ansicht(gruppe_id):
    if "username" not in session:
        return redirect(url_for('home'))
    username = session["username"]
    if username not in user_db:
        user_db[username] = {"points": 1000, "tipps": {}, "lieblingsteam": None}
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
        if is_me:
            rank_class += " rank-me"
        
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
    
    # Mein Rang
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
        
        <!-- TOP 3 PODEST -->
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
        
        <!-- FULL TABLE -->
        <div class="card">
          <div style="display:grid;grid-template-columns:48px 1fr 80px 80px;gap:12px;
               padding:8px 16px;margin-bottom:8px;
               font-family:\'Barlow Condensed\';font-weight:700;font-size:11px;
               letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;">
            <div>Rang</div>
            <div>Spieler</div>
            <div style="text-align:center;">Tipps</div>
            <div style="text-align:right;">Punkte</div>
          </div>
          {rows_html}
        </div>
      </div>
    </div>
    </body></html>"""

# ==========================================
# PUNKTE-SYSTEM SEITE
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
              <div>
                <div style="font-weight:700;font-size:15px;">🎯 Perfektes Ergebnis</div>
                <div style="font-size:12px;color:var(--muted);margin-top:2px;">z.B. Tipp 2:1 → Ergebnis 2:1</div>
              </div>
              <div class="punkte-val">+1.000</div>
            </div>
            <div class="punkte-row">
              <div>
                <div style="font-weight:700;font-size:15px;">⚡ Richtige Tordifferenz</div>
                <div style="font-size:12px;color:var(--muted);margin-top:2px;">z.B. Tipp 3:1 → Ergebnis 2:0 (beide +2)</div>
              </div>
              <div class="punkte-val">+500</div>
            </div>
            <div class="punkte-row">
              <div>
                <div style="font-weight:700;font-size:15px;">✅ Richtige Tendenz</div>
                <div style="font-size:12px;color:var(--muted);margin-top:2px;">Sieg / Unentschieden / Niederlage korrekt</div>
              </div>
              <div class="punkte-val">+200</div>
            </div>
            <div class="punkte-row" style="border-color:rgba(255,23,68,0.2);background:rgba(255,23,68,0.03);">
              <div>
                <div style="font-weight:700;font-size:15px;">❌ Falsch getippt</div>
                <div style="font-size:12px;color:var(--muted);margin-top:2px;">Falsche Tendenz</div>
              </div>
              <div class="punkte-val" style="background:linear-gradient(135deg,var(--red),#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">0</div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-bottom:20px;">
          <div style="font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;margin-bottom:4px;color:var(--gold);">💰 EINSATZ & STARTKAPITAL</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px;">
            <div class="punkte-row">
              <div style="font-weight:700;">Startpunkte (neu)</div>
              <div class="punkte-val">1.000</div>
            </div>
            <div class="punkte-row" style="border-color:rgba(255,23,68,0.2);">
              <div style="font-weight:700;">Einsatz pro Tipp</div>
              <div class="punkte-val" style="background:linear-gradient(135deg,var(--red),#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">-50</div>
            </div>
          </div>
        </div>
        
        <div class="card">
          <div style="font-family:'Bebas Neue';font-size:22px;letter-spacing:2px;margin-bottom:4px;color:var(--gold);">⏰ TIPP-DEADLINE</div>
          <div style="font-size:13px;color:var(--muted);margin-bottom:16px;">Wann ist Schluss mit Tippen?</div>
          <div class="punkte-row" style="border-color:rgba(255,165,0,0.3);background:rgba(255,165,0,0.04);">
            <div>
              <div style="font-weight:700;font-size:15px;">🔒 Sperre vor Spielbeginn</div>
              <div style="font-size:12px;color:var(--muted);margin-top:2px;">10 Minuten vor Anpfiff wird das Tippen gesperrt</div>
            </div>
            <div style="font-family:'Bebas Neue';font-size:24px;color:var(--gold2);">10 MIN</div>
          </div>
          <div style="margin-top:14px;padding:12px 16px;background:var(--dark3);border-radius:8px;font-size:13px;color:var(--muted);line-height:1.7;">
            💡 <strong style="color:var(--text);">Tipp:</strong> Tippe früh – bei Spielen kurz vor der Deadline wird ein Warnsymbol angezeigt.<br>
            Bereits gesetzte Tipps können nicht mehr geändert werden.
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
        if not tipp_erlaubt(spiel_gefunden):
            # Zu spät – Tipp wird abgelehnt
            pass
        elif user_db[username]["points"] >= PUNKTE_SYSTEM["einsatz"]:
            user_db[username]["points"] -= PUNKTE_SYSTEM["einsatz"]
            user_db[username]["tipps"][spiel_id] = {
                "heim": int(tipp_heim),
                "gast": int(tipp_gast)
            }
    
    if redirect_gruppe:
        return redirect(url_for('gruppe_ansicht', gruppe_id=redirect_gruppe))
    return redirect(url_for('dashboard'))

# ==========================================
# AUSWERTUNG (Admin-Route)
# Aufruf: /auswertung?key=ADMIN1337&spiel_id=A1&heim=2&gast=1
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
    
    # Tendenz bestimmen
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
            punkte = PUNKTE_SYSTEM["perfekt"]
            ergebnis = "perfekt"
        elif tendenz(th, tg) == echte_tendenz and (th - tg) == echte_diff:
            punkte = PUNKTE_SYSTEM["tendenz_tor"]
            ergebnis = "tordifferenz"
        elif tendenz(th, tg) == echte_tendenz:
            punkte = PUNKTE_SYSTEM["tendenz"]
            ergebnis = "tendenz"
        else:
            punkte = PUNKTE_SYSTEM["falsch"]
            ergebnis = "falsch"
        
        user_db[uname]["points"] = user_db[uname].get("points", 0) + punkte
        auswertungen.append(f"{uname}: {th}:{tg} → {ergebnis} (+{punkte})")
    
    return f"Auswertung {spiel_id} ({heim_tore}:{gast_tore}):<br>" + "<br>".join(auswertungen)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    print("\n" + "="*55)
    print("   🏆  WM 2026 GRIEFERGAMES TIPP-PORTAL  🏆   ")
    print("="*55)
    print("   Starte auf: http://127.0.0.1:5005")
    print("="*55 + "\n")
    try:
        port = int(os.environ.get('PORT', 5005))
        host = '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
        app.run(debug=False, host=host, port=port, use_reloader=False)
    except Exception as e:
        print(e)
        input()
