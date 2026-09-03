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

# Diese beiden Werte sind nur noch der STARTWERT für eine frische Installation
# (praktisch, damit zwei Instanzen von Anfang an unterschiedlich starten
# können). Geändert werden Zielgewicht und Kalorienziel danach direkt in der
# App unter "Einstellungen" -- die landen dann in der Datenbank, nicht mehr
# in einer Umgebungsvariable.
ZIELGEWICHT_STANDARD = float(os.environ.get("ZIELGEWICHT_KG", 100.0))
KALORIENZIEL_STANDARD = int(os.environ.get("KALORIENZIEL", 3600))

# Übungen, mit denen die Vorauswahl beim ersten Start gefüllt wird. Jede neu
# eingetragene Übung beim Training-Formular wird danach automatisch mit
# aufgenommen.
STANDARD_UEBUNGEN = [
    "Bankdrücken",
    "Kniebeuge",
    "Kreuzheben",
    "Schulterdrücken",
    "Latzug",
    "Rudern",
    "Beinpresse",
]


def get_db():
    """Öffnet eine Verbindung zur SQLite-Datenbank."""
    conn = sqlite3.connect(DB_PFAD)
    conn.row_factory = sqlite3.Row  # erlaubt Zugriff wie zeile["spalte"]
    return conn


def berechne_e1rm(gewicht, wiederholungen):
    """Schätzt die Maximalleistung (1-Wiederholungs-Maximum) mit der
    Epley-Formel: e1RM = Gewicht * (1 + Wiederholungen / 30).
    Das ist eine Schätzung, kein gemessener Wert -- aber die gängige
    Methode, um Sätze mit unterschiedlichem Gewicht/Wiederholungen
    vergleichbar zu machen."""
    return round(gewicht * (1 + wiederholungen / 30), 1)


def init_db():
    """Legt alle Tabellen an, falls sie noch nicht existieren, und migriert
    Daten aus älteren Versionen dieser App. Wird bei jedem Start aufgerufen
    -- schadet nicht, wenn schon alles vorhanden ist (IF NOT EXISTS)."""
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

    # Zielgewicht/Kalorienziel: genau EINE Zeile (id=1), die über die
    # "Einstellungen"-Seite in der App verändert wird.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS einstellungen (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            zielgewicht REAL NOT NULL,
            kalorienziel INTEGER NOT NULL
        )
    """)
    vorhandene_einstellungen = conn.execute(
        "SELECT COUNT(*) AS anzahl FROM einstellungen"
    ).fetchone()["anzahl"]
    if vorhandene_einstellungen == 0:
        conn.execute(
            "INSERT INTO einstellungen (id, zielgewicht, kalorienziel) VALUES (1, ?, ?)",
            (ZIELGEWICHT_STANDARD, KALORIENZIEL_STANDARD),
        )

    # Übungs-Vorauswahl: Katalog von Übungsnamen, die im Trainings-Formular
    # zum Auswählen vorgeschlagen werden. Neue, frei eingetippte Übungen
    # werden beim Speichern eines Trainings automatisch ergänzt.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uebungen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    vorhandene_uebungen = conn.execute(
        "SELECT COUNT(*) AS anzahl FROM uebungen"
    ).fetchone()["anzahl"]
    if vorhandene_uebungen == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO uebungen (name) VALUES (?)",
            [(name,) for name in STANDARD_UEBUNGEN],
        )

    # Trainingssätze: JEDE Zeile ist EIN Satz (nicht mehr eine ganze
    # Trainingseinheit), damit sich Gewicht und Wiederholungen von Satz zu
    # Satz unterscheiden können -- z.B. Satz 1: 120kg x5, Satz 2: 125kg x3.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trainingssatz (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            uebung TEXT NOT NULL,
            gewicht REAL NOT NULL,
            wiederholungen INTEGER NOT NULL,
            satznummer INTEGER NOT NULL
        )
    """)

    # Einmalige Migration: falls noch die alte "mahlzeit"-Tabelle (einzelne
    # Mahlzeiten) existiert, werden ihre Kalorien pro Tag aufsummiert und in
    # die "ernaehrung"-Tabelle übernommen.
    alte_mahlzeit_tabelle = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mahlzeit'"
    ).fetchone()
    if alte_mahlzeit_tabelle:
        conn.execute("""
            INSERT INTO ernaehrung (datum, kalorien)
            SELECT datum, SUM(kalorien) FROM mahlzeit GROUP BY datum
            ON CONFLICT(datum) DO NOTHING
        """)

    # Einmalige Migration: falls noch die alte "training"-Tabelle (eine Zeile
    # pro Trainingseinheit mit EINEM Gewicht + Satzanzahl) existiert, wird
    # jede Zeile in mehrere einzelne Sätze in "trainingssatz" aufgeteilt.
    # Die alte Tabelle wird danach gelöscht, damit das nicht bei jedem
    # weiteren Start erneut passiert (sonst gäbe es Dubletten).
    alte_training_tabelle = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='training'"
    ).fetchone()
    if alte_training_tabelle:
        alte_zeilen = conn.execute("SELECT * FROM training").fetchall()
        for zeile in alte_zeilen:
            if zeile["gewicht"] is None or zeile["wiederholungen"] is None:
                continue
            anzahl_saetze = zeile["saetze"] or 1
            for satznummer in range(1, anzahl_saetze + 1):
                conn.execute(
                    """INSERT INTO trainingssatz
                       (datum, uebung, gewicht, wiederholungen, satznummer)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        zeile["datum"],
                        zeile["uebung"],
                        zeile["gewicht"],
                        zeile["wiederholungen"],
                        satznummer,
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO uebungen (name) VALUES (?)",
                    (zeile["uebung"],),
                )
        conn.execute("DROP TABLE training")

    conn.commit()
    conn.close()


def get_einstellungen(conn):
    """Liest die aktuelle Zielgewicht/Kalorienziel-Zeile aus der Datenbank."""
    return conn.execute("SELECT * FROM einstellungen WHERE id = 1").fetchone()


@app.route("/")
def index():
    """Dashboard: letztes Gewicht, Fortschritt zum Ziel, Ernährung heute,
    letzte Trainingseinheiten."""
    conn = get_db()

    einstellungen = get_einstellungen(conn)

    letztes_gewicht = conn.execute(
        "SELECT * FROM gewicht ORDER BY datum DESC, id DESC LIMIT 1"
    ).fetchone()

    heute = date.today().isoformat()
    ernaehrung_heute = conn.execute(
        "SELECT * FROM ernaehrung WHERE datum = ?", (heute,)
    ).fetchone()

    # Die letzten 4 Trainingseinheiten (= Kombination aus Datum + Übung),
    # jeweils mit allen dazugehörigen Sätzen.
    letzte_einheiten = conn.execute("""
        SELECT datum, uebung, MAX(id) AS letzte_id
        FROM trainingssatz
        GROUP BY datum, uebung
        ORDER BY letzte_id DESC
        LIMIT 4
    """).fetchall()

    letzte_trainings = []
    for einheit in letzte_einheiten:
        saetze = conn.execute(
            """SELECT gewicht, wiederholungen FROM trainingssatz
               WHERE datum = ? AND uebung = ? ORDER BY satznummer""",
            (einheit["datum"], einheit["uebung"]),
        ).fetchall()
        letzte_trainings.append({
            "datum": einheit["datum"],
            "uebung": einheit["uebung"],
            "saetze": saetze,
        })

    conn.close()

    fortschritt_prozent = None
    if letztes_gewicht:
        fortschritt_prozent = round(
            min(100, max(0, (letztes_gewicht["wert"] / einstellungen["zielgewicht"]) * 100)), 1
        )

    return render_template(
        "index.html",
        letztes_gewicht=letztes_gewicht,
        zielgewicht=einstellungen["zielgewicht"],
        fortschritt_prozent=fortschritt_prozent,
        ernaehrung_heute=ernaehrung_heute,
        kalorienziel=einstellungen["kalorienziel"],
        letzte_trainings=letzte_trainings,
    )


@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen():
    conn = get_db()

    if request.method == "POST":
        conn.execute(
            "UPDATE einstellungen SET zielgewicht = ?, kalorienziel = ? WHERE id = 1",
            (
                float(request.form["zielgewicht"].replace(",", ".")),
                int(request.form["kalorienziel"]),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    aktuelle_werte = get_einstellungen(conn)
    conn.close()
    return render_template("einstellungen.html", werte=aktuelle_werte)


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
        datum = request.form["datum"]
        uebung = request.form["uebung"].strip()
        # Mehrere Sätze kommen als gleichnamige Formularfelder rein
        # (gewicht[] / wiederholungen[]) -- getlist gibt sie in der
        # Reihenfolge zurück, in der sie im Formular standen.
        gewichte = request.form.getlist("gewicht[]")
        wiederholungen_liste = request.form.getlist("wiederholungen[]")

        conn = get_db()
        # Neue, frei eingetippte Übung direkt zur Vorauswahl hinzufügen.
        conn.execute("INSERT OR IGNORE INTO uebungen (name) VALUES (?)", (uebung,))

        satznummer = 0
        for gewicht_roh, wdh_roh in zip(gewichte, wiederholungen_liste):
            if not gewicht_roh or not wdh_roh:
                continue  # leer gelassene Zeile überspringen
            satznummer += 1
            conn.execute(
                """INSERT INTO trainingssatz
                   (datum, uebung, gewicht, wiederholungen, satznummer)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    datum,
                    uebung,
                    float(gewicht_roh.replace(",", ".")),
                    int(wdh_roh),
                    satznummer,
                ),
            )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    conn = get_db()
    uebungen = conn.execute("SELECT name FROM uebungen ORDER BY name").fetchall()
    conn.close()
    return render_template(
        "training.html", heute=date.today().isoformat(), uebungen=uebungen
    )


@app.route("/training/verlauf")
def training_verlauf():
    conn = get_db()
    uebungsnamen = conn.execute(
        "SELECT DISTINCT uebung FROM trainingssatz ORDER BY uebung"
    ).fetchall()

    uebungen_mit_verlauf = []
    for zeile in uebungsnamen:
        name = zeile["uebung"]
        saetze = conn.execute(
            """SELECT * FROM trainingssatz WHERE uebung = ?
               ORDER BY datum DESC, satznummer""",
            (name,),
        ).fetchall()
        saetze_mit_e1rm = [
            {
                "datum": s["datum"],
                "satznummer": s["satznummer"],
                "gewicht": s["gewicht"],
                "wiederholungen": s["wiederholungen"],
                "e1rm": berechne_e1rm(s["gewicht"], s["wiederholungen"]),
            }
            for s in saetze
        ]
        bestleistung = max((s["e1rm"] for s in saetze_mit_e1rm), default=0)
        uebungen_mit_verlauf.append({
            "name": name,
            "saetze": saetze_mit_e1rm,
            "bestleistung": bestleistung,
        })

    conn.close()
    return render_template("training_verlauf.html", uebungen=uebungen_mit_verlauf)


if __name__ == "__main__":
    init_db()
    # host="0.0.0.0" macht die Seite im ganzen WLAN erreichbar (fürs Handy nötig)
    app.run(host="0.0.0.0", port=5000, debug=True)
