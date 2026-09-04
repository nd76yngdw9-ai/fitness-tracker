"""
Trainings- und Ernährungstracker
--------------------------------
Ein bewusst einfach gehaltenes Flask-Projekt für den Einstieg ins Programmieren.
Alles liegt in EINER Datei (app.py), damit man den kompletten Ablauf einer
Anfrage von oben nach unten lesen kann: Route rein -> Datenbank -> HTML raus.

Grundkonzepte, die hier vorkommen (zum Nachschlagen):
- Flask-Route:      @app.route("/pfad") -> welche Funktion bei welcher URL läuft
- GET vs. POST:      GET = Seite anzeigen, POST = Formular absenden
- SQLite:            eine Datenbank, die einfach eine einzelne Datei ist (tracker.db)
- render_template:   füllt eine HTML-Datei aus templates/ mit Daten
- Session:           ein Cookie im Browser, das (verschlüsselt) merkt, wer
                      eingeloggt ist -- dafür braucht Flask einen "secret_key"

Datenmodell:
- Ein BENUTZER hat einen Benutzernamen + ein gehashtes Passwort. JEDE andere
  Tabelle ist über eine benutzer_id an genau einen Benutzer gebunden --
  so sehen zwei Personen, die dieselbe App nutzen, nur ihre eigenen Daten.
- Ein TRAINING ("trainingseinheit") ist ein Container für einen Tag/Zeitpunkt.
- In einem Training stecken beliebig viele ÜBUNGEN.
- Jede Übung hat beliebig viele SÄTZE ("trainingssatz"), jeder Satz mit
  eigenem Gewicht und eigenen Wiederholungen.
"""

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, get_flashed_messages, Response,
)
import sqlite3
import os
import json
import csv
import io
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Für Sessions (Login-Cookies) zwingend nötig. Für den echten Betrieb per
# Umgebungsvariable SECRET_KEY setzen (siehe WSGI-Anleitung in der README) --
# sonst werden bei jedem Neustart der App alle Logins ungültig.
app.secret_key = os.environ.get("SECRET_KEY", "nur-fuer-lokales-testen-aendere-mich")

# Ohne diese Einstellung wäre der Login-Cookie ein "Session-Cookie", das der
# Browser beim Schließen verwirft -- bei "Zum Home-Bildschirm hinzufügen"
# auf dem iPhone gilt jedes Öffnen der App als komplett neue Sitzung, man
# müsste sich also jedes Mal neu anmelden. permanent_session_lifetime macht
# aus dem Cookie stattdessen ein "dauerhaftes" Cookie mit Ablaufdatum (hier:
# 1 Jahr), das über App-Neustarts hinweg erhalten bleibt.
app.permanent_session_lifetime = timedelta(days=365)

# Standardmäßig lokal "tracker.db", per Umgebungsvariable auf einen anderen
# Pfad umbiegbar (z.B. für Docker-Volumes).
DB_PFAD = os.environ.get("DB_PFAD", "tracker.db")

# Startwerte für neu registrierte Benutzer (danach individuell unter
# "Einstellungen" änderbar).
ZIELGEWICHT_STANDARD = float(os.environ.get("ZIELGEWICHT_KG", 80.0))
KALORIENZIEL_STANDARD = int(os.environ.get("KALORIENZIEL", 2500))

# Übungen, mit denen die Vorauswahl eines NEUEN Benutzers gefüllt wird.
STANDARD_UEBUNGEN = [
    "Bankdrücken",
    "Kniebeuge",
    "Kreuzheben",
    "Schulterdrücken",
    "Latzug",
    "Rudern",
    "Beinpresse",
]

# Optional: wenn gesetzt, muss man bei der Registrierung diesen Code
# eingeben (schützt davor, dass Fremde sich auf deiner öffentlichen App
# einfach so ein Konto anlegen). Wenn nicht gesetzt, ist die Registrierung
# offen für alle mit dem Link.
REGISTRIERUNGS_CODE = os.environ.get("REGISTRIERUNGS_CODE")

# Seiten, die OHNE Login erreichbar sein müssen (sonst gäbe es eine
# Endlos-Weiterleitung: nicht eingeloggt -> zu /login geschickt -> /login
# selbst verlangt auch einen Login -> ...).
OEFFENTLICHE_ENDPUNKTE = {"login", "registrieren", "static"}


def get_db():
    """Öffnet eine Verbindung zur SQLite-Datenbank."""
    conn = sqlite3.connect(DB_PFAD)
    conn.row_factory = sqlite3.Row  # erlaubt Zugriff wie zeile["spalte"]
    return conn


@app.before_request
def login_erforderlich():
    """Läuft vor JEDER Anfrage. Ohne aktive Session (= nicht eingeloggt)
    geht's nur zu den öffentlichen Endpunkten (Login/Registrierung/
    Static-Dateien wie CSS) -- alles andere leitet zum Login um."""
    if request.endpoint in OEFFENTLICHE_ENDPUNKTE or request.endpoint is None:
        return
    if "benutzer_id" not in session:
        return redirect(url_for("login"))


def aktueller_benutzer_id():
    """Kurzform für die ID des gerade eingeloggten Benutzers."""
    return session["benutzer_id"]


def berechne_e1rm(gewicht, wiederholungen):
    """Schätzt die Maximalleistung (1-Wiederholungs-Maximum) mit der
    Epley-Formel: e1RM = Gewicht * (1 + Wiederholungen / 30).
    Das ist eine Schätzung, kein gemessener Wert -- aber die gängige
    Methode, um Sätze mit unterschiedlichem Gewicht/Wiederholungen
    vergleichbar zu machen."""
    return round(gewicht * (1 + wiederholungen / 30), 1)


def berechne_gewichtstrend(eintraege_aufsteigend):
    """Lineare Regression (Methode der kleinsten Quadrate) über Datum (als
    Tageszahl) und Gewicht. Gibt (Steigung pro Tag, Achsenabschnitt) zurück,
    oder None, wenn es nicht mindestens 2 Einträge an unterschiedlichen
    Tagen gibt (dann lässt sich kein Trend berechnen)."""
    punkte = [
        (date.fromisoformat(e["datum"]).toordinal(), e["wert"])
        for e in eintraege_aufsteigend
    ]
    x_werte = [x for x, _ in punkte]
    if len(set(x_werte)) < 2:
        return None

    n = len(punkte)
    summe_x = sum(x for x, _ in punkte)
    summe_y = sum(y for _, y in punkte)
    summe_xy = sum(x * y for x, y in punkte)
    summe_xx = sum(x * x for x, _ in punkte)

    nenner = n * summe_xx - summe_x ** 2
    if nenner == 0:
        return None

    steigung = (n * summe_xy - summe_x * summe_y) / nenner
    achsenabschnitt = (summe_y - steigung * summe_x) / n
    return steigung, achsenabschnitt


def init_db():
    """Legt alle Tabellen an, falls sie noch nicht existieren, und migriert
    Daten aus älteren (Einzelbenutzer-)Versionen dieser App. Wird beim
    Start des Moduls aufgerufen -- schadet nicht, wenn schon alles
    vorhanden ist.

    Migrations-Prinzip für bestehende Installationen: alle Zeilen aus der
    alten, benutzerlosen Version werden dem Benutzer mit id=1 zugeordnet.
    Da SQLite AUTOINCREMENT beim allerersten angelegten Benutzer automatisch
    die id 1 vergibt, landet die alte Historie automatisch beim ersten
    Benutzer, der sich neu registriert."""
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS benutzer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benutzername TEXT NOT NULL UNIQUE,
            passwort_hash TEXT NOT NULL
        )
    """)

    # --- gewicht: einfache Spalte ergänzen, falls noch nicht vorhanden ---
    _tabelle_um_benutzer_id_ergaenzen(
        conn, "gewicht",
        "CREATE TABLE gewicht (id INTEGER PRIMARY KEY AUTOINCREMENT, benutzer_id INTEGER NOT NULL, datum TEXT NOT NULL, wert REAL NOT NULL)"
    )

    # --- trainingseinheit: einfache Spalte ergänzen ---
    _tabelle_um_benutzer_id_ergaenzen(
        conn, "trainingseinheit",
        "CREATE TABLE trainingseinheit (id INTEGER PRIMARY KEY AUTOINCREMENT, benutzer_id INTEGER NOT NULL, datum TEXT NOT NULL, erstellt_um TEXT NOT NULL)"
    )

    # --- ernaehrung: braucht einen zusammengesetzten Primärschlüssel
    #     (benutzer_id, datum) statt nur datum -> komplett neu aufbauen ---
    ernaehrung_existiert = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ernaehrung'"
    ).fetchone()
    if ernaehrung_existiert:
        spalten = [r["name"] for r in conn.execute("PRAGMA table_info(ernaehrung)")]
        if "benutzer_id" not in spalten:
            conn.execute("ALTER TABLE ernaehrung RENAME TO ernaehrung_alt")
            conn.execute("""
                CREATE TABLE ernaehrung (
                    benutzer_id INTEGER NOT NULL,
                    datum TEXT NOT NULL,
                    kalorien INTEGER NOT NULL,
                    protein REAL, fett REAL, kohlenhydrate REAL,
                    PRIMARY KEY (benutzer_id, datum)
                )
            """)
            conn.execute("""
                INSERT INTO ernaehrung (benutzer_id, datum, kalorien, protein, fett, kohlenhydrate)
                SELECT 1, datum, kalorien, protein, fett, kohlenhydrate FROM ernaehrung_alt
            """)
            conn.execute("DROP TABLE ernaehrung_alt")
    else:
        conn.execute("""
            CREATE TABLE ernaehrung (
                benutzer_id INTEGER NOT NULL,
                datum TEXT NOT NULL,
                kalorien INTEGER NOT NULL,
                protein REAL, fett REAL, kohlenhydrate REAL,
                PRIMARY KEY (benutzer_id, datum)
            )
        """)

    # --- einstellungen: benutzer_id als Primärschlüssel statt fixer id=1,
    #     PLUS neue Spalte "startgewicht" -> komplett neu aufbauen ---
    einstellungen_existiert = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='einstellungen'"
    ).fetchone()
    if einstellungen_existiert:
        spalten = [r["name"] for r in conn.execute("PRAGMA table_info(einstellungen)")]
        if "benutzer_id" not in spalten:
            conn.execute("ALTER TABLE einstellungen RENAME TO einstellungen_alt")
            conn.execute("""
                CREATE TABLE einstellungen (
                    benutzer_id INTEGER PRIMARY KEY,
                    startgewicht REAL,
                    zielgewicht REAL NOT NULL,
                    kalorienziel INTEGER NOT NULL,
                    proteinziel REAL
                )
            """)
            alte_zeile = conn.execute("SELECT * FROM einstellungen_alt WHERE id = 1").fetchone()
            if alte_zeile:
                conn.execute(
                    "INSERT INTO einstellungen (benutzer_id, startgewicht, zielgewicht, kalorienziel, proteinziel) VALUES (1, NULL, ?, ?, NULL)",
                    (alte_zeile["zielgewicht"], alte_zeile["kalorienziel"]),
                )
            conn.execute("DROP TABLE einstellungen_alt")
        elif "proteinziel" not in spalten:
            # Zwischen-Version: hatte schon benutzer_id, aber noch kein
            # Protein-Ziel -- einfache Spalte ergänzen reicht hier.
            conn.execute("ALTER TABLE einstellungen ADD COLUMN proteinziel REAL")
    else:
        conn.execute("""
            CREATE TABLE einstellungen (
                benutzer_id INTEGER PRIMARY KEY,
                startgewicht REAL,
                zielgewicht REAL NOT NULL,
                kalorienziel INTEGER NOT NULL,
                proteinziel REAL
            )
        """)

    # --- uebungen: UNIQUE muss (benutzer_id, name) statt nur name sein ---
    uebungen_existiert = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='uebungen'"
    ).fetchone()
    if uebungen_existiert:
        spalten = [r["name"] for r in conn.execute("PRAGMA table_info(uebungen)")]
        if "benutzer_id" not in spalten:
            conn.execute("ALTER TABLE uebungen RENAME TO uebungen_alt")
            conn.execute("""
                CREATE TABLE uebungen (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    benutzer_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    UNIQUE(benutzer_id, name)
                )
            """)
            conn.execute("INSERT INTO uebungen (benutzer_id, name) SELECT 1, name FROM uebungen_alt")
            conn.execute("DROP TABLE uebungen_alt")
    else:
        conn.execute("""
            CREATE TABLE uebungen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benutzer_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                UNIQUE(benutzer_id, name)
            )
        """)

    # --- trainingssatz: unverändert (hängt über trainingseinheit_id am
    #     Training, das seinerseits schon eine benutzer_id hat) ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trainingssatz (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trainingseinheit_id INTEGER NOT NULL REFERENCES trainingseinheit(id),
            uebung TEXT NOT NULL,
            gewicht REAL NOT NULL,
            wiederholungen INTEGER NOT NULL,
            satznummer INTEGER NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def _tabelle_um_benutzer_id_ergaenzen(conn, tabellenname, erstellungs_sql):
    """Hilfsfunktion für die Migration: legt die Tabelle frisch mit der
    finalen Struktur an, falls sie noch nicht existiert -- oder ergänzt bei
    einer bestehenden alten Tabelle die Spalte benutzer_id (Standardwert 1,
    damit alte Zeilen automatisch dem ersten Benutzer zugeordnet werden)."""
    vorhanden = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabellenname,)
    ).fetchone()
    if not vorhanden:
        conn.execute(erstellungs_sql)
        return
    spalten = [r["name"] for r in conn.execute(f"PRAGMA table_info({tabellenname})")]
    if "benutzer_id" not in spalten:
        conn.execute(f"ALTER TABLE {tabellenname} ADD COLUMN benutzer_id INTEGER NOT NULL DEFAULT 1")


def get_einstellungen(conn, benutzer_id):
    """Liest Startgewicht/Zielgewicht/Kalorienziel des angegebenen Benutzers."""
    return conn.execute(
        "SELECT * FROM einstellungen WHERE benutzer_id = ?", (benutzer_id,)
    ).fetchone()


def hole_letzte_leistung(conn, benutzer_id):
    """Baut ein Dictionary {Übungsname: {datum, saetze}} mit der jeweils
    letzten (jüngsten) Trainingseinheit DIESES Benutzers, in der die Übung
    vorkam. Wird als JSON in die Seite eingebettet, damit JavaScript beim
    Tippen sofort die letzte Leistung anzeigen kann."""
    uebungsnamen = conn.execute("""
        SELECT DISTINCT ts.uebung
        FROM trainingssatz ts
        JOIN trainingseinheit te ON te.id = ts.trainingseinheit_id
        WHERE te.benutzer_id = ?
    """, (benutzer_id,)).fetchall()

    ergebnis = {}
    for zeile in uebungsnamen:
        name = zeile["uebung"]
        letzte_einheit = conn.execute("""
            SELECT te.id, te.datum
            FROM trainingseinheit te
            JOIN trainingssatz ts ON ts.trainingseinheit_id = te.id
            WHERE ts.uebung = ? AND te.benutzer_id = ?
            ORDER BY te.erstellt_um DESC
            LIMIT 1
        """, (name, benutzer_id)).fetchone()

        if letzte_einheit:
            saetze = conn.execute(
                """SELECT gewicht, wiederholungen FROM trainingssatz
                   WHERE trainingseinheit_id = ? AND uebung = ?
                   ORDER BY satznummer""",
                (letzte_einheit["id"], name),
            ).fetchall()
            ergebnis[name] = {
                "datum": letzte_einheit["datum"],
                "saetze": [
                    {"gewicht": s["gewicht"], "wiederholungen": s["wiederholungen"]}
                    for s in saetze
                ],
            }
    return ergebnis


# ---------------------------------------------------------------------
# Login / Registrierung / Logout
# ---------------------------------------------------------------------

@app.route("/registrieren", methods=["GET", "POST"])
def registrieren():
    if request.method == "POST":
        benutzername = request.form["benutzername"].strip()
        passwort = request.form["passwort"]
        passwort_wiederholung = request.form["passwort_wiederholung"]
        eingegebener_code = request.form.get("registrierungs_code", "")

        fehler = None
        if REGISTRIERUNGS_CODE and eingegebener_code != REGISTRIERUNGS_CODE:
            fehler = "Registrierungscode ist falsch."
        elif not benutzername or not passwort:
            fehler = "Benutzername und Passwort dürfen nicht leer sein."
        elif passwort != passwort_wiederholung:
            fehler = "Die Passwörter stimmen nicht überein."

        conn = get_db()
        if fehler is None:
            existiert_schon = conn.execute(
                "SELECT id FROM benutzer WHERE benutzername = ?", (benutzername,)
            ).fetchone()
            if existiert_schon:
                fehler = "Dieser Benutzername ist schon vergeben."

        if fehler:
            conn.close()
            return render_template(
                "registrieren.html", fehler=fehler, braucht_code=bool(REGISTRIERUNGS_CODE)
            )

        cursor = conn.execute(
            "INSERT INTO benutzer (benutzername, passwort_hash) VALUES (?, ?)",
            (benutzername, generate_password_hash(passwort)),
        )
        neue_benutzer_id = cursor.lastrowid

        conn.execute(
            "INSERT OR IGNORE INTO einstellungen (benutzer_id, startgewicht, zielgewicht, kalorienziel, proteinziel) VALUES (?, NULL, ?, ?, NULL)",
            (neue_benutzer_id, ZIELGEWICHT_STANDARD, KALORIENZIEL_STANDARD),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO uebungen (benutzer_id, name) VALUES (?, ?)",
            [(neue_benutzer_id, name) for name in STANDARD_UEBUNGEN],
        )
        conn.commit()
        conn.close()

        session.permanent = True
        session["benutzer_id"] = neue_benutzer_id
        session["benutzername"] = benutzername
        return redirect(url_for("index"))

    return render_template("registrieren.html", fehler=None, braucht_code=bool(REGISTRIERUNGS_CODE))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        benutzername = request.form["benutzername"].strip()
        passwort = request.form["passwort"]

        conn = get_db()
        zeile = conn.execute(
            "SELECT * FROM benutzer WHERE benutzername = ?", (benutzername,)
        ).fetchone()
        conn.close()

        if zeile and check_password_hash(zeile["passwort_hash"], passwort):
            session.permanent = True
            session["benutzer_id"] = zeile["id"]
            session["benutzername"] = zeile["benutzername"]
            return redirect(url_for("index"))

        return render_template("login.html", fehler="Benutzername oder Passwort ist falsch.")

    return render_template("login.html", fehler=None)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------

@app.route("/")
def index():
    """Dashboard: letztes Gewicht, Fortschritt zum Ziel, Ernährung heute,
    letzte Trainings -- alles nur für den eingeloggten Benutzer."""
    benutzer_id = aktueller_benutzer_id()
    conn = get_db()

    einstellungen = get_einstellungen(conn, benutzer_id)

    letztes_gewicht = conn.execute(
        "SELECT * FROM gewicht WHERE benutzer_id = ? ORDER BY datum DESC, id DESC LIMIT 1",
        (benutzer_id,),
    ).fetchone()

    heute = date.today().isoformat()
    ernaehrung_heute = conn.execute(
        "SELECT * FROM ernaehrung WHERE benutzer_id = ? AND datum = ?", (benutzer_id, heute)
    ).fetchone()

    letzte_einheiten = conn.execute(
        "SELECT * FROM trainingseinheit WHERE benutzer_id = ? ORDER BY erstellt_um DESC LIMIT 4",
        (benutzer_id,),
    ).fetchall()
    letzte_trainings = []
    for einheit in letzte_einheiten:
        uebungen_namen = conn.execute(
            "SELECT DISTINCT uebung FROM trainingssatz WHERE trainingseinheit_id = ?",
            (einheit["id"],),
        ).fetchall()
        letzte_trainings.append({
            "id": einheit["id"],
            "datum": einheit["datum"],
            "uebungen": [u["uebung"] for u in uebungen_namen],
        })

    # --- Wochenrückblick: Durchschnittswerte der letzten 7 Tage ---
    sieben_tage_start = (date.today() - timedelta(days=6)).isoformat()
    gewicht_schnitt = conn.execute(
        "SELECT AVG(wert) AS schnitt FROM gewicht WHERE benutzer_id = ? AND datum >= ?",
        (benutzer_id, sieben_tage_start),
    ).fetchone()["schnitt"]
    kalorien_schnitt = conn.execute(
        "SELECT AVG(kalorien) AS schnitt FROM ernaehrung WHERE benutzer_id = ? AND datum >= ?",
        (benutzer_id, sieben_tage_start),
    ).fetchone()["schnitt"]
    trainings_diese_woche = conn.execute(
        "SELECT COUNT(*) AS anzahl FROM trainingseinheit WHERE benutzer_id = ? AND datum >= ?",
        (benutzer_id, sieben_tage_start),
    ).fetchone()["anzahl"]

    wochenrueckblick = {
        "gewicht_schnitt": round(gewicht_schnitt, 1) if gewicht_schnitt is not None else None,
        "kalorien_schnitt": round(kalorien_schnitt) if kalorien_schnitt is not None else None,
        "trainings_anzahl": trainings_diese_woche,
    }

    # --- Trainings-Kalender: letzte 84 Tage (12 Wochen) als Heatmap-Raster ---
    heatmap_start = date.today() - timedelta(days=83)
    trainingstage_rohdaten = conn.execute(
        "SELECT DISTINCT datum FROM trainingseinheit WHERE benutzer_id = ? AND datum >= ?",
        (benutzer_id, heatmap_start.isoformat()),
    ).fetchall()
    trainingstage_menge = {r["datum"] for r in trainingstage_rohdaten}
    heatmap_tage = []
    for i in range(84):
        tag = heatmap_start + timedelta(days=i)
        heatmap_tage.append({
            "datum": tag.isoformat(),
            "trainiert": tag.isoformat() in trainingstage_menge,
        })

    # Startgewicht für die Fortschrittsanzeige: entweder das explizit in den
    # Einstellungen gesetzte, oder ersatzweise der allererste Gewichtseintrag.
    effektives_startgewicht = einstellungen["startgewicht"]
    if effektives_startgewicht is None:
        erster_eintrag = conn.execute(
            "SELECT wert FROM gewicht WHERE benutzer_id = ? ORDER BY datum ASC, id ASC LIMIT 1",
            (benutzer_id,),
        ).fetchone()
        if erster_eintrag:
            effektives_startgewicht = erster_eintrag["wert"]

    conn.close()

    # Fortschritt = Anteil der Strecke vom Start- zum Zielgewicht, die schon
    # zurückgelegt ist. Funktioniert für Zunehmen UND Abnehmen: bei einem
    # Ziel UNTER dem Start ist (ziel - start) negativ, und ein sinkendes
    # aktuelles Gewicht ergibt trotzdem einen positiven, wachsenden Anteil.
    fortschritt_prozent = None
    if letztes_gewicht and effektives_startgewicht is not None and effektives_startgewicht != einstellungen["zielgewicht"]:
        anteil = (letztes_gewicht["wert"] - effektives_startgewicht) / (
            einstellungen["zielgewicht"] - effektives_startgewicht
        )
        fortschritt_prozent = round(min(100, max(0, anteil * 100)), 1)

    return render_template(
        "index.html",
        benutzername=session.get("benutzername"),
        letztes_gewicht=letztes_gewicht,
        zielgewicht=einstellungen["zielgewicht"],
        fortschritt_prozent=fortschritt_prozent,
        ernaehrung_heute=ernaehrung_heute,
        kalorienziel=einstellungen["kalorienziel"],
        proteinziel=einstellungen["proteinziel"],
        letzte_trainings=letzte_trainings,
        wochenrueckblick=wochenrueckblick,
        heatmap_tage=heatmap_tage,
    )


@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen():
    benutzer_id = aktueller_benutzer_id()
    conn = get_db()

    if request.method == "POST":
        startgewicht_roh = request.form.get("startgewicht", "").strip()
        proteinziel_roh = request.form.get("proteinziel", "").strip()
        conn.execute(
            """UPDATE einstellungen
               SET startgewicht = ?, zielgewicht = ?, kalorienziel = ?, proteinziel = ?
               WHERE benutzer_id = ?""",
            (
                float(startgewicht_roh.replace(",", ".")) if startgewicht_roh else None,
                float(request.form["zielgewicht"].replace(",", ".")),
                int(request.form["kalorienziel"]),
                float(proteinziel_roh.replace(",", ".")) if proteinziel_roh else None,
                benutzer_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    aktuelle_werte = get_einstellungen(conn, benutzer_id)
    conn.close()
    return render_template(
        "einstellungen.html", werte=aktuelle_werte, benutzername=session.get("benutzername")
    )


# ---------------------------------------------------------------------
# Gewicht
# ---------------------------------------------------------------------

@app.route("/gewicht", methods=["GET", "POST"])
def gewicht():
    if request.method == "POST":
        wert = float(request.form["wert"].replace(",", "."))
        conn = get_db()
        conn.execute(
            "INSERT INTO gewicht (benutzer_id, datum, wert) VALUES (?, ?, ?)",
            (aktueller_benutzer_id(), request.form["datum"], wert),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    return render_template("gewicht.html", heute=date.today().isoformat())


@app.route("/gewicht/verlauf")
def gewicht_verlauf():
    benutzer_id = aktueller_benutzer_id()
    conn = get_db()
    eintraege = conn.execute(
        "SELECT * FROM gewicht WHERE benutzer_id = ? ORDER BY datum DESC, id DESC", (benutzer_id,)
    ).fetchall()
    eintraege_aufsteigend = conn.execute(
        "SELECT * FROM gewicht WHERE benutzer_id = ? ORDER BY datum ASC, id ASC", (benutzer_id,)
    ).fetchall()
    einstellungen_zeile = get_einstellungen(conn, benutzer_id)
    conn.close()

    labels_menge = {e["datum"] for e in eintraege_aufsteigend}
    projektion_je_datum = {}
    projektions_text = None

    trend = berechne_gewichtstrend(eintraege_aufsteigend) if eintraege_aufsteigend else None
    if trend:
        steigung, achsenabschnitt = trend
        letzter_eintrag = eintraege_aufsteigend[-1]
        letztes_datum = date.fromisoformat(letzter_eintrag["datum"])
        letzter_ordinal = letztes_datum.toordinal()

        projektion_je_datum[letzter_eintrag["datum"]] = letzter_eintrag["wert"]
        for tage in range(7, 91, 7):
            zukunfts_datum = (letztes_datum + timedelta(days=tage)).isoformat()
            projektion_je_datum[zukunfts_datum] = round(
                achsenabschnitt + steigung * (letzter_ordinal + tage), 1
            )

        labels_menge.update(projektion_je_datum.keys())

        zielgewicht = einstellungen_zeile["zielgewicht"]

        # Zieldatum: an welchem Tag schneidet die Trendlinie das Zielgewicht?
        # Nur sinnvoll, wenn das rechnerisch in der ZUKUNFT liegt (nicht
        # bereits in der Vergangenheit) -- sonst wird kein Datum angezeigt.
        ziel_datum = None
        if steigung != 0:
            ziel_ordinal = round((zielgewicht - achsenabschnitt) / steigung)
            if ziel_ordinal > letzter_ordinal:
                ziel_datum = date.fromordinal(ziel_ordinal).isoformat()

        projektions_text = {
            "kg_pro_woche": round(steigung * 7, 2),
            "wert_in_3_monaten": round(achsenabschnitt + steigung * (letzter_ordinal + 90), 1),
            "datum_in_3_monaten": (letztes_datum + timedelta(days=90)).isoformat(),
            "ziel_datum": ziel_datum,
        }

    alle_labels = sorted(labels_menge)
    gewicht_je_datum = {e["datum"]: e["wert"] for e in eintraege_aufsteigend}

    # 7-Tage-gleitender Durchschnitt: für jeden Eintrag der Schnitt aller
    # Werte der letzten 7 Kalendertage (inkl. diesem Tag). Glättet
    # Tagesschwankungen (Wasser, Salz, Verdauung) stärker als der Rohwert.
    durchschnitt_je_datum = {}
    for eintrag in eintraege_aufsteigend:
        fenster_start = (date.fromisoformat(eintrag["datum"]) - timedelta(days=6)).isoformat()
        werte_im_fenster = [
            e["wert"] for e in eintraege_aufsteigend
            if fenster_start <= e["datum"] <= eintrag["datum"]
        ]
        durchschnitt_je_datum[eintrag["datum"]] = round(sum(werte_im_fenster) / len(werte_im_fenster), 1)

    gewicht_werte = [gewicht_je_datum.get(d) for d in alle_labels]
    durchschnitt_werte = [durchschnitt_je_datum.get(d) for d in alle_labels]
    projektion_werte = [projektion_je_datum.get(d) for d in alle_labels]

    return render_template(
        "gewicht_verlauf.html",
        eintraege=eintraege,
        labels_json=json.dumps(alle_labels),
        gewicht_werte_json=json.dumps(gewicht_werte),
        durchschnitt_werte_json=json.dumps(durchschnitt_werte),
        projektion_werte_json=json.dumps(projektion_werte),
        zielgewicht=einstellungen_zeile["zielgewicht"],
        projektions_text=projektions_text,
    )


@app.route("/gewicht/<int:eintrag_id>/loeschen", methods=["POST"])
def gewicht_loeschen(eintrag_id):
    conn = get_db()
    # "AND benutzer_id = ?" ist hier entscheidend: verhindert, dass jemand
    # durch Erraten einer fremden ID die Daten eines ANDEREN Benutzers löscht.
    conn.execute(
        "DELETE FROM gewicht WHERE id = ? AND benutzer_id = ?",
        (eintrag_id, aktueller_benutzer_id()),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("gewicht_verlauf"))


# ---------------------------------------------------------------------
# Ernährung
# ---------------------------------------------------------------------

def _zahl_oder_none(feldwert):
    """Wandelt einen Formularwert in eine Kommazahl um, oder None wenn leer.
    Erlaubt sowohl Komma als auch Punkt als Dezimaltrennzeichen."""
    if not feldwert:
        return None
    return float(feldwert.replace(",", "."))


@app.route("/ernaehrung", methods=["GET", "POST"])
def ernaehrung():
    benutzer_id = aktueller_benutzer_id()

    if request.method == "POST":
        conn = get_db()
        conn.execute(
            """INSERT INTO ernaehrung (benutzer_id, datum, kalorien, protein, fett, kohlenhydrate)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(benutzer_id, datum) DO UPDATE SET
                   kalorien = excluded.kalorien,
                   protein = excluded.protein,
                   fett = excluded.fett,
                   kohlenhydrate = excluded.kohlenhydrate""",
            (
                benutzer_id,
                request.form["datum"],
                int(request.form["kalorien"]),
                _zahl_oder_none(request.form.get("protein")),
                _zahl_oder_none(request.form.get("fett")),
                _zahl_oder_none(request.form.get("kohlenhydrate")),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    datum = request.args.get("datum", date.today().isoformat())
    conn = get_db()
    vorhandener_eintrag = conn.execute(
        "SELECT * FROM ernaehrung WHERE benutzer_id = ? AND datum = ?", (benutzer_id, datum)
    ).fetchone()
    conn.close()

    return render_template(
        "ernaehrung.html", heute=datum, eintrag=vorhandener_eintrag
    )


@app.route("/ernaehrung/verlauf")
def ernaehrung_verlauf():
    benutzer_id = aktueller_benutzer_id()
    conn = get_db()
    eintraege = conn.execute(
        "SELECT * FROM ernaehrung WHERE benutzer_id = ? ORDER BY datum DESC", (benutzer_id,)
    ).fetchall()

    sieben_tage_start = (date.today() - timedelta(days=6)).isoformat()
    wochenschnitt_zeile = conn.execute(
        """SELECT AVG(kalorien) AS kalorien, AVG(protein) AS protein,
                  AVG(fett) AS fett, AVG(kohlenhydrate) AS kohlenhydrate,
                  COUNT(*) AS anzahl
           FROM ernaehrung WHERE benutzer_id = ? AND datum >= ?""",
        (benutzer_id, sieben_tage_start),
    ).fetchone()
    conn.close()

    wochenschnitt = None
    if wochenschnitt_zeile["anzahl"] > 0:
        wochenschnitt = {
            "kalorien": round(wochenschnitt_zeile["kalorien"]),
            "protein": round(wochenschnitt_zeile["protein"], 1) if wochenschnitt_zeile["protein"] is not None else None,
            "fett": round(wochenschnitt_zeile["fett"], 1) if wochenschnitt_zeile["fett"] is not None else None,
            "kohlenhydrate": round(wochenschnitt_zeile["kohlenhydrate"], 1) if wochenschnitt_zeile["kohlenhydrate"] is not None else None,
            "anzahl_tage": wochenschnitt_zeile["anzahl"],
        }

    return render_template("ernaehrung_verlauf.html", eintraege=eintraege, wochenschnitt=wochenschnitt)


@app.route("/ernaehrung/<datum>/loeschen", methods=["POST"])
def ernaehrung_loeschen(datum):
    conn = get_db()
    conn.execute(
        "DELETE FROM ernaehrung WHERE benutzer_id = ? AND datum = ?",
        (aktueller_benutzer_id(), datum),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("ernaehrung_verlauf"))


# ---------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------

@app.route("/training/neu", methods=["GET", "POST"])
def training_neu():
    """Startet ein neues Training (den 'Container' für die Übungen von
    heute) und leitet direkt in die Trainingsansicht weiter."""
    if request.method == "POST":
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO trainingseinheit (benutzer_id, datum, erstellt_um) VALUES (?, ?, ?)",
            (aktueller_benutzer_id(), request.form["datum"], datetime.now().isoformat()),
        )
        neue_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return redirect(url_for("training_session", einheit_id=neue_id))

    return render_template("training_neu.html", heute=date.today().isoformat())


@app.route("/training/<int:einheit_id>")
def training_session(einheit_id):
    """Übersicht EINES Trainings: alle bisher hinzugefügten Übungen mit
    ihren Sätzen. "AND benutzer_id = ?" stellt sicher, dass niemand ein
    fremdes Training über die ID aufrufen kann."""
    benutzer_id = aktueller_benutzer_id()
    conn = get_db()
    einheit = conn.execute(
        "SELECT * FROM trainingseinheit WHERE id = ? AND benutzer_id = ?",
        (einheit_id, benutzer_id),
    ).fetchone()
    if einheit is None:
        conn.close()
        return redirect(url_for("index"))

    saetze = conn.execute(
        """SELECT * FROM trainingssatz WHERE trainingseinheit_id = ?
           ORDER BY id, satznummer""",
        (einheit_id,),
    ).fetchall()

    uebungen_gruppiert = {}
    gesamtvolumen = 0
    for satz in saetze:
        uebungen_gruppiert.setdefault(satz["uebung"], []).append(satz)
        gesamtvolumen += satz["gewicht"] * satz["wiederholungen"]

    # Volumen (Gewicht x Wiederholungen, aufsummiert) pro Übung -- eine
    # gängige Kennzahl fürs Trainingsvolumen, unabhängig vom Maximalgewicht.
    volumen_je_uebung = {
        name: round(sum(s["gewicht"] * s["wiederholungen"] for s in saetze_liste))
        for name, saetze_liste in uebungen_gruppiert.items()
    }

    # Falls noch keine Übung eingetragen ist: Vorlage vom letzten Training
    # dieses Benutzers anbieten (nur die Übungsnamen, keine Gewichte).
    vorlage_uebungen = []
    if not uebungen_gruppiert:
        letztes_anderes_training = conn.execute(
            """SELECT id FROM trainingseinheit
               WHERE benutzer_id = ? AND id != ?
               ORDER BY erstellt_um DESC LIMIT 1""",
            (benutzer_id, einheit_id),
        ).fetchone()
        if letztes_anderes_training:
            namen = conn.execute(
                """SELECT DISTINCT uebung, MIN(id) AS erste_id FROM trainingssatz
                   WHERE trainingseinheit_id = ? GROUP BY uebung ORDER BY erste_id""",
                (letztes_anderes_training["id"],),
            ).fetchall()
            vorlage_uebungen = [n["uebung"] for n in namen]

    conn.close()

    return render_template(
        "training_session.html",
        einheit=einheit,
        uebungen_gruppiert=uebungen_gruppiert,
        volumen_je_uebung=volumen_je_uebung,
        gesamtvolumen=round(gesamtvolumen),
        vorlage_uebungen=vorlage_uebungen,
    )


@app.route("/training/<int:einheit_id>/loeschen", methods=["POST"])
def training_loeschen(einheit_id):
    conn = get_db()
    # Zugehörigkeit prüfen, bevor irgendwas gelöscht wird.
    gehoert_mir = conn.execute(
        "SELECT id FROM trainingseinheit WHERE id = ? AND benutzer_id = ?",
        (einheit_id, aktueller_benutzer_id()),
    ).fetchone()
    if gehoert_mir:
        conn.execute("DELETE FROM trainingssatz WHERE trainingseinheit_id = ?", (einheit_id,))
        conn.execute("DELETE FROM trainingseinheit WHERE id = ?", (einheit_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("verlauf"))


@app.route("/training/<int:einheit_id>/uebung/neu", methods=["GET", "POST"])
def training_uebung_neu(einheit_id):
    """Formular, um EINE Übung (mit beliebig vielen Sätzen) zu einem
    bestehenden Training hinzuzufügen."""
    benutzer_id = aktueller_benutzer_id()
    conn = get_db()
    einheit = conn.execute(
        "SELECT * FROM trainingseinheit WHERE id = ? AND benutzer_id = ?",
        (einheit_id, benutzer_id),
    ).fetchone()
    if einheit is None:
        conn.close()
        return redirect(url_for("index"))

    if request.method == "POST":
        uebung = request.form["uebung"].strip()
        gewichte = request.form.getlist("gewicht[]")
        wiederholungen_liste = request.form.getlist("wiederholungen[]")

        # Bisherige Bestleistung VOR dem Speichern merken, um danach zu
        # erkennen, ob einer der neuen Sätze einen neuen Rekord bedeutet.
        bisherige_saetze = conn.execute("""
            SELECT ts.gewicht, ts.wiederholungen FROM trainingssatz ts
            JOIN trainingseinheit te ON te.id = ts.trainingseinheit_id
            WHERE ts.uebung = ? AND te.benutzer_id = ?
        """, (uebung, benutzer_id)).fetchall()
        bisherige_bestleistung = max(
            (berechne_e1rm(s["gewicht"], s["wiederholungen"]) for s in bisherige_saetze),
            default=0,
        )

        conn.execute(
            "INSERT OR IGNORE INTO uebungen (benutzer_id, name) VALUES (?, ?)",
            (benutzer_id, uebung),
        )

        satznummer = 0
        neue_bestleistung = 0
        for gewicht_roh, wdh_roh in zip(gewichte, wiederholungen_liste):
            if not gewicht_roh or not wdh_roh:
                continue
            satznummer += 1
            gewicht_wert = float(gewicht_roh.replace(",", "."))
            wdh_wert = int(wdh_roh)
            neue_bestleistung = max(neue_bestleistung, berechne_e1rm(gewicht_wert, wdh_wert))
            conn.execute(
                """INSERT INTO trainingssatz
                   (trainingseinheit_id, uebung, gewicht, wiederholungen, satznummer)
                   VALUES (?, ?, ?, ?, ?)""",
                (einheit_id, uebung, gewicht_wert, wdh_wert, satznummer),
            )
        conn.commit()
        conn.close()

        # Nur als Rekord feiern, wenn es schon eine Vergleichsgrundlage gab
        # (sonst wäre JEDE erste Übung automatisch ein "Rekord").
        if satznummer > 0 and bisherige_bestleistung > 0 and neue_bestleistung > bisherige_bestleistung:
            flash(f"Neue Bestleistung bei {uebung}: {neue_bestleistung} kg berechnetes Max! 🎉")

        return redirect(url_for("training_session", einheit_id=einheit_id))

    uebungen_liste = conn.execute(
        "SELECT name FROM uebungen WHERE benutzer_id = ? ORDER BY name", (benutzer_id,)
    ).fetchall()
    letzte_leistung = hole_letzte_leistung(conn, benutzer_id)
    conn.close()

    return render_template(
        "training_uebung_neu.html",
        einheit=einheit,
        uebungen=uebungen_liste,
        vorausgefuellte_uebung=request.args.get("uebung", ""),
        letzte_leistung_json=json.dumps(letzte_leistung, ensure_ascii=False),
    )


@app.route("/training/<int:einheit_id>/uebung/<uebung>/loeschen", methods=["POST"])
def training_uebung_loeschen(einheit_id, uebung):
    conn = get_db()
    gehoert_mir = conn.execute(
        "SELECT id FROM trainingseinheit WHERE id = ? AND benutzer_id = ?",
        (einheit_id, aktueller_benutzer_id()),
    ).fetchone()
    if gehoert_mir:
        conn.execute(
            "DELETE FROM trainingssatz WHERE trainingseinheit_id = ? AND uebung = ?",
            (einheit_id, uebung),
        )
        conn.commit()
    conn.close()
    return redirect(url_for("training_session", einheit_id=einheit_id))


@app.route("/verlauf")
def verlauf():
    """Eigener Menüpunkt: Liste vergangener Trainings sowie, für
    ausgewählte Übungen, grafischer UND tabellarischer Verlauf."""
    benutzer_id = aktueller_benutzer_id()
    conn = get_db()

    einheiten_rohdaten = conn.execute(
        "SELECT * FROM trainingseinheit WHERE benutzer_id = ? ORDER BY erstellt_um DESC",
        (benutzer_id,),
    ).fetchall()
    einheiten = []
    for einheit in einheiten_rohdaten:
        uebungen_namen = conn.execute(
            "SELECT DISTINCT uebung FROM trainingssatz WHERE trainingseinheit_id = ?",
            (einheit["id"],),
        ).fetchall()
        einheiten.append({
            "id": einheit["id"],
            "datum": einheit["datum"],
            "uebungen": [u["uebung"] for u in uebungen_namen],
        })

    alle_uebungen = conn.execute(
        "SELECT name FROM uebungen WHERE benutzer_id = ? ORDER BY name", (benutzer_id,)
    ).fetchall()
    ausgewaehlte_uebung = request.args.get("uebung") or None

    uebungs_daten = None
    alle_chart_labels = []

    if ausgewaehlte_uebung:
        saetze = conn.execute("""
            SELECT te.datum AS datum, ts.gewicht, ts.wiederholungen, ts.satznummer
            FROM trainingssatz ts
            JOIN trainingseinheit te ON te.id = ts.trainingseinheit_id
            WHERE ts.uebung = ? AND te.benutzer_id = ?
            ORDER BY te.datum, ts.satznummer
        """, (ausgewaehlte_uebung, benutzer_id)).fetchall()

        tabellen_zeilen = []
        rohdaten_punkte = []
        beste_je_tag = {}
        chart_labels_menge = set()

        for satz in saetze:
            e1rm = berechne_e1rm(satz["gewicht"], satz["wiederholungen"])
            tabellen_zeilen.append({
                "datum": satz["datum"],
                "satznummer": satz["satznummer"],
                "gewicht": satz["gewicht"],
                "wiederholungen": satz["wiederholungen"],
                "e1rm": e1rm,
            })
            rohdaten_punkte.append({"datum": satz["datum"], "wert": satz["gewicht"]})
            chart_labels_menge.add(satz["datum"])
            if satz["datum"] not in beste_je_tag or e1rm > beste_je_tag[satz["datum"]]:
                beste_je_tag[satz["datum"]] = e1rm

        e1rm_punkte = [{"datum": tag, "wert": beste_je_tag[tag]} for tag in sorted(beste_je_tag)]

        uebungs_daten = {
            "name": ausgewaehlte_uebung,
            "bestleistung": max(beste_je_tag.values()) if beste_je_tag else 0,
            "tabellen_zeilen": list(reversed(tabellen_zeilen)),
            "e1rm_punkte": e1rm_punkte,
            "rohdaten_punkte": rohdaten_punkte,
        }
        alle_chart_labels = sorted(chart_labels_menge)

    conn.close()

    chart_daten = {}
    if uebungs_daten:
        chart_daten[uebungs_daten["name"]] = {
            "e1rm": uebungs_daten["e1rm_punkte"],
            "rohdaten": uebungs_daten["rohdaten_punkte"],
        }

    return render_template(
        "verlauf.html",
        einheiten=einheiten,
        alle_uebungen=alle_uebungen,
        ausgewaehlte_uebung=ausgewaehlte_uebung,
        uebungs_daten=uebungs_daten,
        chart_daten_json=json.dumps(chart_daten, ensure_ascii=False),
        chart_labels_json=json.dumps(alle_chart_labels),
    )


@app.route("/export")
def export_csv():
    """Exportiert alle Daten des eingeloggten Benutzers als ein ZIP mit
    drei CSV-Dateien (Gewicht, Ernährung, Trainingssätze) -- z.B. für ein
    eigenes Backup oder um die Daten in einer anderen App weiterzuverwenden."""
    import zipfile

    benutzer_id = aktueller_benutzer_id()
    conn = get_db()

    gewicht_zeilen = conn.execute(
        "SELECT datum, wert FROM gewicht WHERE benutzer_id = ? ORDER BY datum", (benutzer_id,)
    ).fetchall()
    ernaehrung_zeilen = conn.execute(
        "SELECT datum, kalorien, protein, fett, kohlenhydrate FROM ernaehrung WHERE benutzer_id = ? ORDER BY datum",
        (benutzer_id,),
    ).fetchall()
    training_zeilen = conn.execute("""
        SELECT te.datum, ts.uebung, ts.satznummer, ts.gewicht, ts.wiederholungen
        FROM trainingssatz ts
        JOIN trainingseinheit te ON te.id = ts.trainingseinheit_id
        WHERE te.benutzer_id = ?
        ORDER BY te.datum, ts.uebung, ts.satznummer
    """, (benutzer_id,)).fetchall()
    conn.close()

    def csv_text(kopfzeile, zeilen):
        puffer = io.StringIO()
        schreiber = csv.writer(puffer)
        schreiber.writerow(kopfzeile)
        for zeile in zeilen:
            schreiber.writerow(list(zeile))
        return puffer.getvalue()

    zip_puffer = io.BytesIO()
    with zipfile.ZipFile(zip_puffer, "w", zipfile.ZIP_DEFLATED) as zip_datei:
        zip_datei.writestr("gewicht.csv", csv_text(["datum", "wert_kg"], gewicht_zeilen))
        zip_datei.writestr(
            "ernaehrung.csv",
            csv_text(["datum", "kalorien", "protein_g", "fett_g", "kohlenhydrate_g"], ernaehrung_zeilen),
        )
        zip_datei.writestr(
            "training.csv",
            csv_text(["datum", "uebung", "satznummer", "gewicht_kg", "wiederholungen"], training_zeilen),
        )
    zip_puffer.seek(0)

    dateiname = f"tracker-export-{date.today().isoformat()}.zip"
    return Response(
        zip_puffer.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f"attachment; filename={dateiname}"},
    )


# WICHTIG: init_db() läuft hier auf Modul-Ebene (nicht nur im
# if __name__ == "__main__"-Block), damit die Datenbank auch dann
# eingerichtet wird, wenn die App nicht direkt gestartet, sondern von einem
# WSGI-Server importiert wird (so funktioniert Hosting z.B. auf
# PythonAnywhere -- dort wird "app" importiert, nicht "python app.py" ausgeführt).
init_db()

if __name__ == "__main__":
    # host="0.0.0.0" macht die Seite im ganzen WLAN erreichbar (fürs Handy nötig)
    # Nur für lokales Testen -- auf PythonAnywhere übernimmt deren WSGI-Server das.
    app.run(host="0.0.0.0", port=5000, debug=True)
