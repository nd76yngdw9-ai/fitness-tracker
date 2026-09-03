# Trainings- und Ernährungstracker

Ein selbstgebautes Web-Tool für Körpergewicht, Ernährung (kcal + Makros)
und Trainingslogs mit Verlaufsdiagrammen, berechneter Maximalleistung
(e1RM) und einer 3-Monats-Gewichtsprojektion.

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

**Wichtig:** die kostenlose Version erlaubt nur EINE Web-App pro Account.
Für zwei Personen (dich + einen Freund) braucht ihr also zwei separate
kostenlose Accounts (unterschiedliche E-Mail-Adressen).

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

# Zielgewicht/Kalorienziel-Startwerte (später in der App unter
# "Einstellungen" änderbar) sowie Login-Zugangsdaten -- UNBEDINGT setzen,
# die App ist sonst für jeden im Internet offen und ohne Passwort nutzbar!
os.environ['ZIELGEWICHT_KG'] = '100'
os.environ['KALORIENZIEL'] = '3600'
os.environ['TRACKER_BENUTZER'] = 'dein-benutzername'
os.environ['TRACKER_PASSWORT'] = 'dein-sicheres-passwort'

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
angelegte `tracker.db`).

### 8. Neu laden

Auf der "Web"-Seite den großen grünen **"Reload"**-Button klicken. Danach
ist die App unter `https://DEINNAME.pythonanywhere.com` erreichbar --
auf jedem Gerät, ganz ohne zusätzliche App, einfach im Browser öffnen.
Beim ersten Aufruf fragt der Browser nach den Zugangsdaten aus Schritt 5.

### Für deinen Freund

Schritte 1-8 in einem zweiten, separaten PythonAnywhere-Account
wiederholen (andere E-Mail-Adresse), mit seinen eigenen Werten in Schritt 5
(`ZIELGEWICHT_KG`, `KALORIENZIEL`, eigener Benutzername/Passwort). Seine
Daten landen dann komplett getrennt in seinem eigenen Account.

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

Dann im Browser: `http://localhost:5000`. Ohne gesetzte
`TRACKER_BENUTZER`/`TRACKER_PASSWORT`-Umgebungsvariablen ist lokal kein
Login nötig.

## Wie es funktioniert (kurz erklärt)

- **Flask** ist ein Python-Framework, das HTTP-Anfragen (Browser-Aufrufe)
  entgegennimmt und darauf reagiert. Jede `@app.route(...)`-Funktion in
  `app.py` ist für eine bestimmte URL zuständig.
- **SQLite** ist eine Datenbank, die komplett in einer einzelnen Datei
  (`tracker.db`) lebt – kein separater Datenbank-Server nötig.
- **Templates** sind HTML-Dateien mit Platzhaltern (`{{ variable }}`), die
  Flask beim Aufruf mit echten Daten aus der Datenbank füllt.
- **Login-Schutz**: `app.py` prüft vor jeder Anfrage, ob
  `TRACKER_BENUTZER`/`TRACKER_PASSWORT` gesetzt sind. Wenn ja, verlangt der
  Browser einen Benutzernamen/Passwort (HTTP Basic Auth), bevor irgendeine
  Seite angezeigt wird.

## (Alternative) Selbsthosten mit Docker

Für den Fall, dass du die App später doch selbst hosten willst (z.B. auf
einem eigenen Server oder Umbrel via Portainer), liegen `Dockerfile` und
`docker-compose.yml` weiterhin im Projekt bereit -- inklusive derselben
Umgebungsvariablen für Zielgewicht/Kalorienziel/Login pro Instanz.

## Nächste mögliche Ausbaustufen

- Weitere Auswertungen (z.B. Wochenschnitt der Kalorien)
- Export der Daten als CSV
- Erinnerungen/Benachrichtigungen
