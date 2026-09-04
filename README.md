# Trainings- und Ernährungstracker

Ein selbstgebautes Web-Tool für Körpergewicht, Ernährung (kcal + Makros)
und Trainingslogs mit Verlaufsdiagrammen, berechneter Maximalleistung
(e1RM), 3-Monats-Gewichtsprojektion, Benutzerkonten für mehrere Personen,
Wochenrückblick, Trainings-Kalender, CSV-Export und Dunkelmodus.

## Projektstruktur

```
tracker/
├── app.py                    # die ganze Logik: Routen, Datenbank-Zugriffe
├── requirements.txt           # Python-Pakete, die gebraucht werden
├── Dockerfile / docker-compose.yml   # optional, fürs Selbsthosten mit Docker
├── templates/                  # HTML-Seiten
└── static/
    └── style.css                # Design (mobile-first)
```

`tracker.db` (die Datenbank) wird beim ersten Start automatisch angelegt
und liegt danach im selben Ordner wie `app.py`.

## Hosting auf PythonAnywhere (empfohlen, kostenlos, ohne eigenes Netzwerk offenzulegen)

PythonAnywhere hostet die App dauerhaft unter einer eigenen
`https://DEINNAME.pythonanywhere.com`-Adresse. Kostenlos, keine
Kreditkarte nötig, dein Heimnetz/Umbrel bleibt davon komplett unberührt.

**Mehrere Personen, eine App:** Seit der Benutzerkonten-Funktion braucht
ihr nur noch EINEN PythonAnywhere-Account. Du und dein Freund registriert
euch beide über die Login-Seite der App mit eigenem Benutzernamen/Passwort
-- eure Daten (Gewicht, Ernährung, Training) sind komplett getrennt,
obwohl beide dieselbe Adresse nutzen.

### 1. Account erstellen

Auf [pythonanywhere.com](https://www.pythonanywhere.com) einen kostenlosen
"Beginner"-Account erstellen (keine Kreditkarte nötig).

### 2. Code hochladen

Im PythonAnywhere-Dashboard einen **Bash-Konsole** öffnen (Button "Bash"
unter "New console") und eintippen:

```bash
git clone https://github.com/DEINNAME/DEINREPO.git tracker
```

(Ersetze das durch die URL deines eigenen GitHub-Repos.)

### 3. Virtuelle Umgebung einrichten

Im selben Bash-Fenster:

```bash
cd tracker
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Web-App anlegen

Im Dashboard auf den Reiter **"Web"** → **"Add a new web app"** →
**"Manual configuration"** → passende Python-Version wählen (z.B. 3.10).

### 5. WSGI-Datei anpassen

Auf der Web-Seite den Link zur WSGI-Konfigurationsdatei anklicken (etwas
wie `/var/www/deinname_pythonanywhere_com_wsgi.py`). Den kompletten Inhalt
ersetzen durch:

```python
import sys
import os

pfad = '/home/DEINNAME/tracker'
if pfad not in sys.path:
    sys.path.insert(0, pfad)

# WICHTIG: ein eigener, langer Zufallswert -- damit Logins bei einem
# Neustart der App nicht ungültig werden. Einfach irgendeine lange,
# zufällige Zeichenkette eintragen (z.B. mit einem Passwort-Generator).
os.environ['SECRET_KEY'] = 'trag-hier-eine-lange-zufaellige-zeichenkette-ein'

# Startwerte für NEU REGISTRIERTE Benutzer (jeder kann sie danach unter
# "Einstellungen" individuell für sich ändern).
os.environ['ZIELGEWICHT_KG'] = '80'
os.environ['KALORIENZIEL'] = '2500'

# Optional: wenn gesetzt, muss man diesen Code bei der Registrierung
# eingeben -- verhindert, dass Fremde sich auf deiner öffentlichen App
# einfach ein Konto anlegen. Leer lassen/Zeile löschen für offene Registrierung.
os.environ['REGISTRIERUNGS_CODE'] = 'euer-geheimwort'

from app import app as application
```

(`DEINNAME` jeweils durch deinen PythonAnywhere-Benutzernamen ersetzen.)

### 6. Virtualenv verknüpfen

Zurück auf der "Web"-Seite, im Abschnitt "Virtualenv" den Pfad eintragen:
`/home/DEINNAME/tracker/venv`

### 7. Alte Daten übernehmen (optional)

Falls du schon eine `tracker.db` von einer früheren Installation hast:
im Dashboard auf **"Files"** gehen, in den Ordner `tracker/` navigieren,
und die Datei per Drag & Drop hochladen (überschreibt die leere, frisch
angelegte `tracker.db`). Wichtig: registriere dich danach als **erstes**
neues Konto -- deine alte (migrierte) Historie wird automatisch dem
allerersten neu registrierten Konto zugeordnet.

### 8. Neu laden

Auf der "Web"-Seite den großen grünen **"Reload"**-Button klicken. Danach
ist die App unter `https://DEINNAME.pythonanywhere.com` erreichbar.

### Konten anlegen

Einfach die Seite öffnen -- sie leitet automatisch zur Login-Seite um.
Dort auf "Registrieren" klicken, Benutzername/Passwort wählen (plus den
Registrierungscode aus Schritt 5, falls gesetzt). Du und dein Freund
registriert euch jeweils mit eigenem Benutzernamen -- fertig, eure Daten
sind komplett getrennt.

### Account "am Leben" halten

Kostenlose PythonAnywhere-Web-Apps laufen jeweils für einen Monat und
müssen danach im Dashboard mit einem Klick verlängert werden (Hinweis
erscheint automatisch im Dashboard, wenn es Zeit wird).

### Code-Änderungen später übernehmen

Wenn du hier im Chat weitere Änderungen an der App bekommst: die neuen
Dateien wie gewohnt auf GitHub hochladen, dann in der PythonAnywhere-Bash-
Konsole:

```bash
cd tracker
git pull
```

Danach auf der "Web"-Seite wieder auf **"Reload"** klicken.

## Lokal auf dem eigenen Rechner testen

```bash
cd tracker
python -m pip install -r requirements.txt
python app.py
```

Dann im Browser: `http://localhost:5000`. Die Seite leitet automatisch zur
Login-Seite -- dort einmalig über "Registrieren" ein Konto anlegen.

## Wie es funktioniert (kurz erklärt)

- **Flask** ist ein Python-Framework, das HTTP-Anfragen (Browser-Aufrufe)
  entgegennimmt und darauf reagiert. Jede `@app.route(...)`-Funktion in
  `app.py` ist für eine bestimmte URL zuständig.
- **SQLite** ist eine Datenbank, die komplett in einer einzelnen Datei
  (`tracker.db`) lebt – kein separater Datenbank-Server nötig.
- **Templates** sind HTML-Dateien mit Platzhaltern (`{{ variable }}`), die
  Flask beim Aufruf mit echten Daten aus der Datenbank füllt.
- **Login-Schutz**: Jede Seite verlangt eine aktive Anmeldung (`app.py`
  prüft das vor jeder Anfrage). Beim Login/Registrieren setzt Flask ein
  verschlüsseltes Cookie ("Session"), das merkt, wer eingeloggt ist --
  dafür ist der `SECRET_KEY` nötig. Passwörter werden nie im Klartext
  gespeichert, sondern als Hash (`generate_password_hash`).
- **7-Tage-Durchschnitt / Wochenschnitt**: gleitender bzw. einfacher
  Mittelwert der letzten 7 Kalendertage, direkt in SQL (`AVG(...)`) bzw.
  in Python berechnet -- glättet Tagesschwankungen.
- **Trainingsvolumen**: Gewicht × Wiederholungen, über alle Sätze
  aufsummiert -- eine gängige Kennzahl fürs Muskelwachstum, unabhängig
  vom reinen Maximalgewicht.
- **Trainings-Kalender**: ein CSS-Grid (`grid-auto-flow: column`) mit
  84 kleinen Kästchen, eins pro Tag der letzten 12 Wochen, eingefärbt
  wenn an dem Tag trainiert wurde.
- **Dunkelmodus**: reine CSS-Funktion (`@media (prefers-color-scheme:
  dark)`), folgt automatisch der Systemeinstellung des Geräts.
- **CSV-Export**: baut die Daten zur Laufzeit als ZIP mit drei CSV-Dateien
  (`csv`/`zipfile`/`io` aus der Python-Standardbibliothek) und schickt sie
  als Download-Antwort zurück -- landet nirgends als Datei auf dem Server.

## (Alternative) Selbsthosten mit Docker

Für den Fall, dass du die App später doch selbst hosten willst (z.B. auf
einem eigenen Server oder Umbrel via Portainer), liegen `Dockerfile` und
`docker-compose.yml` weiterhin im Projekt bereit -- inklusive derselben
Umgebungsvariablen für Zielgewicht/Kalorienziel/Login pro Instanz.

## Nächste mögliche Ausbaustufen

- Weitere Auswertungen (z.B. Wochenschnitt der Kalorien)
- Export der Daten als CSV
- Erinnerungen/Benachrichtigungen
