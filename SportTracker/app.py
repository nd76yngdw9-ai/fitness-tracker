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
"""

from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
from datetime import date

app = Flask(__name__)
# Standardmäßig lokal "tracker.db", in Docker per Umgebungsvariable auf ein
# persistentes Volume umgebogen (siehe Dockerfile/docker-compose.yml)
DB_PFAD = os.environ.get("DB_PFAD", "tracker.db")

# Per Umgebungsvariable einstellbar, damit zwei Instanzen (z.B. für dich und
# einen Freund) unterschiedliche Ziele haben können, ohne den Code zu ändern.
# Default = deine aktuellen Werte, falls nichts gesetzt ist.
ZIELGEWICHT_KG = float(os.environ.get("ZIELGEWICHT_KG", 100.0))
KALORIENZIEL = int(os.environ.get("KALORIENZIEL", 3600))


def get_db():
    """Öffnet eine Verbindung zur SQLite-Datenbank."""
    conn = sqlite3.connect(DB_PFAD)
    conn.row_factory = sqlite3.Row  # erlaubt Zugriff wie zeile["spalte"]
    return conn


def init_db():
    """Legt die drei Tabellen an, falls sie noch nicht existieren.
    Wird bei jedem Start aufgerufen -- schadet nicht, wenn die Tabellen
    schon da sind (IF NOT EXISTS)."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gewicht (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            wert REAL NOT NULL
        )
    """)
    # Ein Eintrag PRO TAG (datum als Primärschlüssel) statt einzelner
    # Mahlzeiten -- beim erneuten Eintragen für denselben Tag wird der
    # bestehende Eintrag überschrieben (siehe UPSERT in der Route unten).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ernaehrung (
            datum TEXT PRIMARY KEY,
            kalorien INTEGER NOT NULL,
            protein REAL,
            fett REAL,
            kohlenhydrate REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            uebung TEXT NOT NULL,
            gewicht REAL,
            wiederholungen INTEGER,
            saetze INTEGER
        )
    """)

    # Einmalige Migration: falls noch die alte "mahlzeit"-Tabelle (einzelne
    # Mahlzeiten) existiert, werden ihre Kalorien pro Tag aufsummiert und in
    # die neue "ernaehrung"-Tabelle übernommen, damit keine Historie verloren
    # geht. Die Makros (Protein/Fett/Kohlenhydrate) gab es damals noch nicht
    # und bleiben für diese migrierten Tage leer.
    alte_tabelle = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mahlzeit'"
    ).fetchone()
    if alte_tabelle:
        conn.execute("""
            INSERT INTO ernaehrung (datum, kalorien)
            SELECT datum, SUM(kalorien) FROM mahlzeit GROUP BY datum
            ON CONFLICT(datum) DO NOTHING
        """)

    conn.commit()
    conn.close()


@app.route("/")
def index():
    """Dashboard: letztes Gewicht, Fortschritt zum Ziel, Kalorien heute,
    letzte Trainingseinträge."""
    conn = get_db()

    letztes_gewicht = conn.execute(
        "SELECT * FROM gewicht ORDER BY datum DESC, id DESC LIMIT 1"
    ).fetchone()

    heute = date.today().isoformat()
    ernaehrung_heute = conn.execute(
        "SELECT * FROM ernaehrung WHERE datum = ?", (heute,)
    ).fetchone()

    letzte_trainings = conn.execute(
        "SELECT * FROM training ORDER BY datum DESC, id DESC LIMIT 6"
    ).fetchall()

    conn.close()

    fortschritt_prozent = None
    if letztes_gewicht:
        fortschritt_prozent = round(
            min(100, max(0, (letztes_gewicht["wert"] / ZIELGEWICHT_KG) * 100)), 1
        )

    return render_template(
        "index.html",
        letztes_gewicht=letztes_gewicht,
        zielgewicht=ZIELGEWICHT_KG,
        fortschritt_prozent=fortschritt_prozent,
        ernaehrung_heute=ernaehrung_heute,
        kalorienziel=KALORIENZIEL,
        letzte_trainings=letzte_trainings,
    )


@app.route("/gewicht", methods=["GET", "POST"])
def gewicht():
    if request.method == "POST":
        wert = float(request.form["wert"].replace(",", "."))
        conn = get_db()
        conn.execute(
            "INSERT INTO gewicht (datum, wert) VALUES (?, ?)",
            (request.form["datum"], wert),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    return render_template("gewicht.html", heute=date.today().isoformat())


@app.route("/gewicht/verlauf")
def gewicht_verlauf():
    conn = get_db()
    eintraege = conn.execute(
        "SELECT * FROM gewicht ORDER BY datum DESC, id DESC"
    ).fetchall()
    conn.close()
    return render_template("gewicht_verlauf.html", eintraege=eintraege)


def _zahl_oder_none(feldwert):
    """Wandelt einen Formularwert in eine Kommazahl um, oder None wenn leer.
    Erlaubt sowohl Komma als auch Punkt als Dezimaltrennzeichen."""
    if not feldwert:
        return None
    return float(feldwert.replace(",", "."))


@app.route("/ernaehrung", methods=["GET", "POST"])
def ernaehrung():
    if request.method == "POST":
        conn = get_db()
        # UPSERT: existiert für dieses Datum schon ein Eintrag, wird er
        # überschrieben, statt einen zweiten Eintrag für denselben Tag
        # anzulegen (datum ist Primärschlüssel).
        conn.execute(
            """INSERT INTO ernaehrung (datum, kalorien, protein, fett, kohlenhydrate)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(datum) DO UPDATE SET
                   kalorien = excluded.kalorien,
                   protein = excluded.protein,
                   fett = excluded.fett,
                   kohlenhydrate = excluded.kohlenhydrate""",
            (
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

    heute = date.today().isoformat()
    conn = get_db()
    vorhandener_eintrag = conn.execute(
        "SELECT * FROM ernaehrung WHERE datum = ?", (heute,)
    ).fetchone()
    conn.close()

    return render_template(
        "ernaehrung.html", heute=heute, eintrag=vorhandener_eintrag
    )


@app.route("/training", methods=["GET", "POST"])
def training():
    if request.method == "POST":
        conn = get_db()
        conn.execute(
            """INSERT INTO training (datum, uebung, gewicht, wiederholungen, saetze)
               VALUES (?, ?, ?, ?, ?)""",
            (
                request.form["datum"],
                request.form["uebung"],
                float(request.form["gewicht"].replace(",", "."))
                if request.form.get("gewicht")
                else None,
                int(request.form["wiederholungen"])
                if request.form.get("wiederholungen")
                else None,
                int(request.form["saetze"]) if request.form.get("saetze") else None,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    return render_template("training.html", heute=date.today().isoformat())


if __name__ == "__main__":
    init_db()
    # host="0.0.0.0" macht die Seite im ganzen WLAN erreichbar (fürs Handy nötig)
    app.run(host="0.0.0.0", port=5000, debug=True)
