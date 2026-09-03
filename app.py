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

Datenmodell (seit dieser Version):
- Ein TRAINING ("trainingseinheit") ist ein Container für einen Tag/Zeitpunkt.
- In einem Training stecken beliebig viele ÜBUNGEN.
- Jede Übung hat beliebig viele SÄTZE ("trainingssatz"), jeder Satz mit
  eigenem Gewicht und eigenen Wiederholungen.
"""

from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
import json
from datetime import date, datetime, timedelta

app = Flask(__name__)
# Standardmäßig lokal "tracker.db", in Docker per Umgebungsvariable auf ein
# persistentes Volume umgebogen (siehe Dockerfile/docker-compose.yml)
DB_PFAD = os.environ.get("DB_PFAD", "tracker.db")

# Nur noch der STARTWERT für eine frische Installation. Geändert werden
# Zielgewicht und Kalorienziel danach direkt in der App unter "Einstellungen".
ZIELGEWICHT_STANDARD = float(os.environ.get("ZIELGEWICHT_KG", 100.0))
KALORIENZIEL_STANDARD = int(os.environ.get("KALORIENZIEL", 3600))

# Übungen, mit denen die Vorauswahl beim ersten Start gefüllt wird. Jede neu
# eingetragene Übung wird danach automatisch mit aufgenommen.
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

    # Ein Training ist der Container für einen Trainingstermin (man kann
    # theoretisch mehrere pro Tag haben -- erstellt_um unterscheidet sie).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trainingseinheit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            erstellt_um TEXT NOT NULL
        )
    """)

    # Migration: falls "trainingssatz" noch die ALTE Struktur hat (mit einer
    # "datum"-Spalte direkt am Satz, ohne Training-Container), wird sie
    # umbenannt, und wir bauen unten die neue Struktur + Migration.
    alte_struktur = False
    tabelle_vorhanden = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trainingssatz'"
    ).fetchone()
    if tabelle_vorhanden:
        spalten = [row["name"] for row in conn.execute("PRAGMA table_info(trainingssatz)")]
        if "datum" in spalten:
            alte_struktur = True
            conn.execute("ALTER TABLE trainingssatz RENAME TO trainingssatz_alt")

    # Jede Zeile ist EIN Satz einer Übung, verknüpft mit seinem Training.
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

    if alte_struktur:
        # Annahme für die Migration: alle Sätze desselben alten Datums
        # gehören zu EINEM Training (die alte Version kannte noch keine
        # mehreren Trainings pro Tag).
        alte_saetze = conn.execute(
            "SELECT * FROM trainingssatz_alt ORDER BY datum, id"
        ).fetchall()
        einheit_je_datum = {}
        for satz in alte_saetze:
            datum = satz["datum"]
            if datum not in einheit_je_datum:
                cursor = conn.execute(
                    "INSERT INTO trainingseinheit (datum, erstellt_um) VALUES (?, ?)",
                    (datum, datum + "T00:00:00"),
                )
                einheit_je_datum[datum] = cursor.lastrowid
            conn.execute(
                """INSERT INTO trainingssatz
                   (trainingseinheit_id, uebung, gewicht, wiederholungen, satznummer)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    einheit_je_datum[datum],
                    satz["uebung"],
                    satz["gewicht"],
                    satz["wiederholungen"],
                    satz["satznummer"],
                ),
            )
        conn.execute("DROP TABLE trainingssatz_alt")

    conn.commit()
    conn.close()


def get_einstellungen(conn):
    """Liest die aktuelle Zielgewicht/Kalorienziel-Zeile aus der Datenbank."""
    return conn.execute("SELECT * FROM einstellungen WHERE id = 1").fetchone()


def hole_letzte_leistung(conn):
    """Baut ein Dictionary {Übungsname: {datum, saetze}} mit der jeweils
    letzten (jüngsten) Trainingseinheit, in der diese Übung vorkam. Wird als
    JSON in die Seite eingebettet, damit JavaScript beim Tippen sofort die
    letzte Leistung anzeigen kann, ohne extra beim Server nachzufragen."""
    uebungsnamen = conn.execute(
        "SELECT DISTINCT uebung FROM trainingssatz"
    ).fetchall()

    ergebnis = {}
    for zeile in uebungsnamen:
        name = zeile["uebung"]
        letzte_einheit = conn.execute("""
            SELECT te.id, te.datum
            FROM trainingseinheit te
            JOIN trainingssatz ts ON ts.trainingseinheit_id = te.id
            WHERE ts.uebung = ?
            ORDER BY te.erstellt_um DESC
            LIMIT 1
        """, (name,)).fetchone()

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


@app.route("/")
def index():
    """Dashboard: letztes Gewicht, Fortschritt zum Ziel, Ernährung heute,
    letzte Trainings."""
    conn = get_db()

    einstellungen = get_einstellungen(conn)

    letztes_gewicht = conn.execute(
        "SELECT * FROM gewicht ORDER BY datum DESC, id DESC LIMIT 1"
    ).fetchone()

    heute = date.today().isoformat()
    ernaehrung_heute = conn.execute(
        "SELECT * FROM ernaehrung WHERE datum = ?", (heute,)
    ).fetchone()

    letzte_einheiten = conn.execute(
        "SELECT * FROM trainingseinheit ORDER BY erstellt_um DESC LIMIT 4"
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
    eintraege_aufsteigend = conn.execute(
        "SELECT * FROM gewicht ORDER BY datum ASC, id ASC"
    ).fetchall()
    einstellungen_zeile = get_einstellungen(conn)
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

        # Beim letzten ECHTEN Wert anfangen, damit die gestrichelte
        # Projektionslinie im Diagramm nahtlos an die durchgezogene Linie
        # anschließt. Danach alle 7 Tage einen Punkt, 3 Monate (~90 Tage) voraus.
        projektion_je_datum[letzter_eintrag["datum"]] = letzter_eintrag["wert"]
        for tage in range(7, 91, 7):
            zukunfts_datum = (letztes_datum + timedelta(days=tage)).isoformat()
            projektion_je_datum[zukunfts_datum] = round(
                achsenabschnitt + steigung * (letzter_ordinal + tage), 1
            )

        labels_menge.update(projektion_je_datum.keys())

        projektions_text = {
            "kg_pro_woche": round(steigung * 7, 2),
            "wert_in_3_monaten": round(achsenabschnitt + steigung * (letzter_ordinal + 90), 1),
            "datum_in_3_monaten": (letztes_datum + timedelta(days=90)).isoformat(),
        }

    alle_labels = sorted(labels_menge)
    gewicht_je_datum = {e["datum"]: e["wert"] for e in eintraege_aufsteigend}

    # Für Chart.js: pro Label (Datum) entweder der Wert oder null (= keine
    # Linie an der Stelle). Beide Listen haben dieselbe Länge wie alle_labels.
    gewicht_werte = [gewicht_je_datum.get(d) for d in alle_labels]
    projektion_werte = [projektion_je_datum.get(d) for d in alle_labels]

    return render_template(
        "gewicht_verlauf.html",
        eintraege=eintraege,
        labels_json=json.dumps(alle_labels),
        gewicht_werte_json=json.dumps(gewicht_werte),
        projektion_werte_json=json.dumps(projektion_werte),
        zielgewicht=einstellungen_zeile["zielgewicht"],
        projektions_text=projektions_text,
    )


@app.route("/gewicht/<int:eintrag_id>/loeschen", methods=["POST"])
def gewicht_loeschen(eintrag_id):
    conn = get_db()
    conn.execute("DELETE FROM gewicht WHERE id = ?", (eintrag_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("gewicht_verlauf"))


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

    # ?datum=... erlaubt, auch einen ANDEREN Tag als heute zu bearbeiten
    # (z.B. um einen Tippfehler von vorgestern zu korrigieren).
    datum = request.args.get("datum", date.today().isoformat())
    conn = get_db()
    vorhandener_eintrag = conn.execute(
        "SELECT * FROM ernaehrung WHERE datum = ?", (datum,)
    ).fetchone()
    conn.close()

    return render_template(
        "ernaehrung.html", heute=datum, eintrag=vorhandener_eintrag
    )


@app.route("/ernaehrung/verlauf")
def ernaehrung_verlauf():
    conn = get_db()
    eintraege = conn.execute(
        "SELECT * FROM ernaehrung ORDER BY datum DESC"
    ).fetchall()
    conn.close()
    return render_template("ernaehrung_verlauf.html", eintraege=eintraege)


@app.route("/ernaehrung/<datum>/loeschen", methods=["POST"])
def ernaehrung_loeschen(datum):
    conn = get_db()
    conn.execute("DELETE FROM ernaehrung WHERE datum = ?", (datum,))
    conn.commit()
    conn.close()
    return redirect(url_for("ernaehrung_verlauf"))


@app.route("/training/neu", methods=["GET", "POST"])
def training_neu():
    """Startet ein neues Training (den 'Container' für die Übungen von
    heute) und leitet direkt in die Trainingsansicht weiter, wo Übungen
    hinzugefügt werden können."""
    if request.method == "POST":
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO trainingseinheit (datum, erstellt_um) VALUES (?, ?)",
            (request.form["datum"], datetime.now().isoformat()),
        )
        neue_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return redirect(url_for("training_session", einheit_id=neue_id))

    return render_template("training_neu.html", heute=date.today().isoformat())


@app.route("/training/<int:einheit_id>")
def training_session(einheit_id):
    """Übersicht EINES Trainings: alle bisher hinzugefügten Übungen mit
    ihren Sätzen, plus Möglichkeit weitere Übungen hinzuzufügen."""
    conn = get_db()
    einheit = conn.execute(
        "SELECT * FROM trainingseinheit WHERE id = ?", (einheit_id,)
    ).fetchone()
    if einheit is None:
        conn.close()
        return redirect(url_for("index"))

    saetze = conn.execute(
        """SELECT * FROM trainingssatz WHERE trainingseinheit_id = ?
           ORDER BY id, satznummer""",
        (einheit_id,),
    ).fetchall()
    conn.close()

    # Nach Übung gruppieren, aber Reihenfolge des Hinzufügens beibehalten
    uebungen_gruppiert = {}
    for satz in saetze:
        uebungen_gruppiert.setdefault(satz["uebung"], []).append(satz)

    return render_template(
        "training_session.html", einheit=einheit, uebungen_gruppiert=uebungen_gruppiert
    )


@app.route("/training/<int:einheit_id>/loeschen", methods=["POST"])
def training_loeschen(einheit_id):
    conn = get_db()
    conn.execute("DELETE FROM trainingssatz WHERE trainingseinheit_id = ?", (einheit_id,))
    conn.execute("DELETE FROM trainingseinheit WHERE id = ?", (einheit_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("verlauf"))


@app.route("/training/<int:einheit_id>/uebung/neu", methods=["GET", "POST"])
def training_uebung_neu(einheit_id):
    """Formular, um EINE Übung (mit beliebig vielen Sätzen) zu einem
    bestehenden Training hinzuzufügen. Nach dem Speichern geht's zurück zur
    Trainingsübersicht, wo die nächste Übung hinzugefügt werden kann."""
    conn = get_db()
    einheit = conn.execute(
        "SELECT * FROM trainingseinheit WHERE id = ?", (einheit_id,)
    ).fetchone()
    if einheit is None:
        conn.close()
        return redirect(url_for("index"))

    if request.method == "POST":
        uebung = request.form["uebung"].strip()
        gewichte = request.form.getlist("gewicht[]")
        wiederholungen_liste = request.form.getlist("wiederholungen[]")

        conn.execute("INSERT OR IGNORE INTO uebungen (name) VALUES (?)", (uebung,))

        satznummer = 0
        for gewicht_roh, wdh_roh in zip(gewichte, wiederholungen_liste):
            if not gewicht_roh or not wdh_roh:
                continue
            satznummer += 1
            conn.execute(
                """INSERT INTO trainingssatz
                   (trainingseinheit_id, uebung, gewicht, wiederholungen, satznummer)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    einheit_id,
                    uebung,
                    float(gewicht_roh.replace(",", ".")),
                    int(wdh_roh),
                    satznummer,
                ),
            )
        conn.commit()
        conn.close()
        return redirect(url_for("training_session", einheit_id=einheit_id))

    uebungen_liste = conn.execute("SELECT name FROM uebungen ORDER BY name").fetchall()
    letzte_leistung = hole_letzte_leistung(conn)
    conn.close()

    return render_template(
        "training_uebung_neu.html",
        einheit=einheit,
        uebungen=uebungen_liste,
        letzte_leistung_json=json.dumps(letzte_leistung, ensure_ascii=False),
    )


@app.route("/training/<int:einheit_id>/uebung/<uebung>/loeschen", methods=["POST"])
def training_uebung_loeschen(einheit_id, uebung):
    conn = get_db()
    conn.execute(
        "DELETE FROM trainingssatz WHERE trainingseinheit_id = ? AND uebung = ?",
        (einheit_id, uebung),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("training_session", einheit_id=einheit_id))


@app.route("/verlauf")
def verlauf():
    """Eigener Menüpunkt: zeigt sowohl die Liste vergangener Trainings als
    auch, für ausgewählte Übungen, den grafischen Verlauf der berechneten
    Maximalleistung über die Zeit."""
    conn = get_db()

    einheiten_rohdaten = conn.execute(
        "SELECT * FROM trainingseinheit ORDER BY erstellt_um DESC"
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

    alle_uebungen = conn.execute("SELECT name FROM uebungen ORDER BY name").fetchall()
    ausgewaehlte_uebungen = request.args.getlist("uebung")

    chart_daten = {}
    for name in ausgewaehlte_uebungen:
        saetze = conn.execute("""
            SELECT te.datum AS datum, ts.gewicht, ts.wiederholungen
            FROM trainingssatz ts
            JOIN trainingseinheit te ON te.id = ts.trainingseinheit_id
            WHERE ts.uebung = ?
            ORDER BY te.datum
        """, (name,)).fetchall()

        # Pro Tag die beste (höchste) berechnete Maximalleistung nehmen,
        # falls an dem Tag mehrere Sätze dieser Übung gemacht wurden.
        beste_je_tag = {}
        for satz in saetze:
            e1rm = berechne_e1rm(satz["gewicht"], satz["wiederholungen"])
            if satz["datum"] not in beste_je_tag or e1rm > beste_je_tag[satz["datum"]]:
                beste_je_tag[satz["datum"]] = e1rm

        chart_daten[name] = [
            {"datum": tag, "e1rm": beste_je_tag[tag]} for tag in sorted(beste_je_tag)
        ]

    conn.close()

    return render_template(
        "verlauf.html",
        einheiten=einheiten,
        alle_uebungen=alle_uebungen,
        ausgewaehlte_uebungen=ausgewaehlte_uebungen,
        chart_daten_json=json.dumps(chart_daten, ensure_ascii=False),
    )


if __name__ == "__main__":
    init_db()
    # host="0.0.0.0" macht die Seite im ganzen WLAN erreichbar (fürs Handy nötig)
    app.run(host="0.0.0.0", port=5000, debug=True)
