# Trainings- und Ernährungstracker

Ein kleines, selbstgebautes Web-Tool für Körpergewicht, Kalorien und
Trainingslogs. Läuft auf deinem Rechner und ist im WLAN auch vom Handy
aus erreichbar.

## 1. Einmalig einrichten

Voraussetzung: Python 3 ist installiert (auf Mac/Linux meist schon vorhanden,
unter Windows ggf. von python.org herunterladen).

Terminal öffnen, in den Projektordner wechseln und Abhängigkeiten installieren:

```bash
cd tracker
pip install -r requirements.txt
```

## 2. Starten

```bash
python app.py
```

Im Terminal erscheint u.a. eine Zeile wie:

```
Running on http://0.0.0.0:5000
```

Auf deinem **Rechner** öffnest du dann im Browser: `http://localhost:5000`

## 3. Vom Handy aus öffnen

Handy und Rechner müssen im **gleichen WLAN** sein.

1. Auf dem Rechner die lokale IP-Adresse rausfinden:
   - Mac/Linux: Terminal → `ifconfig` (oder `ip a`) → nach `192.168...` suchen
   - Windows: Eingabeaufforderung → `ipconfig` → "IPv4-Adresse"
2. Auf dem Handy im Browser aufrufen: `http://DEINE-IP:5000`
   (z.B. `http://192.168.1.42:5000`)
3. Optional, damit es wie eine App aussieht:
   - iPhone (Safari): Teilen-Symbol → "Zum Home-Bildschirm"
   - Android (Chrome): Menü (⋮) → "Zum Startbildschirm hinzufügen"

Die App muss laufen (Terminal offen bleiben), solange du sie nutzen willst.

## Projektstruktur

```
tracker/
├── app.py              # die ganze Logik: Routen, Datenbank-Zugriffe
├── tracker.db           # wird beim ersten Start automatisch angelegt
├── requirements.txt      # Python-Pakete, die gebraucht werden
├── templates/            # HTML-Seiten
│   ├── base.html         # Grundgerüst mit Navigation
│   ├── index.html        # Dashboard
│   ├── gewicht.html       # Formular Gewicht
│   ├── gewicht_verlauf.html
│   ├── mahlzeit.html      # Formular Mahlzeit
│   └── training.html      # Formular Training
└── static/
    └── style.css          # Design (mobile-first)
```

## Wie es funktioniert (kurz erklärt)

- **Flask** ist ein Python-Framework, das HTTP-Anfragen (Browser-Aufrufe)
  entgegennimmt und darauf reagiert. Jede `@app.route(...)`-Funktion in
  `app.py` ist für eine bestimmte URL zuständig.
- **SQLite** ist eine Datenbank, die komplett in einer einzelnen Datei
  (`tracker.db`) lebt – kein separater Datenbank-Server nötig.
- **Templates** sind HTML-Dateien mit Platzhaltern (`{{ variable }}`), die
  Flask beim Aufruf mit echten Daten aus der Datenbank füllt.

## Zwei Instanzen (z.B. für dich und einen Freund)

Die App läuft komplett getrennt für zwei Personen – eigene Adresse/Port,
eigene Datenbank, eigene Ziele (Zielgewicht/Kalorienziel). Die
`docker-compose.yml` ist bereits für genau diesen Fall vorbereitet: zwei
Services (`tracker-benedikt`, `tracker-freund`) mit eigenem Port (5000 /
5001), eigenem Datenvolumen und eigenen Umgebungsvariablen.

Bevor du deployst: die Werte deines Freundes (`ZIELGEWICHT_KG`,
`KALORIENZIEL`) im Abschnitt `tracker-freund` in der `docker-compose.yml`
anpassen. Läuft alles über **eine einzige** Portainer-Stack-Definition –
du musst nichts doppelt anlegen, Portainer startet beide Container auf
einmal.

Nach dem Deploy erreichbar unter:
- Du: `http://umbrel.local:5000`
- Dein Freund: `http://umbrel.local:5001`

**Lokal auf Windows testen** (bevor du auf Umbrel deployst) geht das auch
ohne Docker – dann aber nacheinander, nicht gleichzeitig, weil sich sonst
beide dieselbe `tracker.db` teilen würden:

```
set ZIELGEWICHT_KG=80
set KALORIENZIEL=2800
python app.py
```

(unter Mac/Linux `export` statt `set`)

## Auf Umbrel installieren (dauerhaft laufen lassen)

Umbrel selbst hat keinen "Baue meine eigene App"-Knopf – der offiziell
empfohlene Weg für eigene Container ist **Portainer**. Kurzfassung:

1. **Code auf GitHub bringen** (kostenloser Account reicht):
   - Neues Repository erstellen, z.B. `fitness-tracker`
   - Alle Dateien aus diesem `tracker`-Ordner per Drag & Drop im Browser
     hochladen (GitHub → "Add file" → "Upload files")
2. **Portainer auf Umbrel installieren**: App Store öffnen → "Portainer"
   suchen → Installieren → öffnen → Passwort beim ersten Login setzen
3. In Portainer: **Stacks** → **Add stack**
   - Name: `fitness-tracker`
   - Build method: **Repository**
   - Repository URL: Link zu deinem GitHub-Repo
   - Compose path: `docker-compose.yml`
   - **Deploy the stack** klicken
4. Portainer baut den Container jetzt selbst (dauert beim ersten Mal
   1-2 Minuten). Danach läuft er automatisch weiter – auch nach einem
   Neustart deines Umbrel (dank `restart: unless-stopped`).
5. Aufrufen unter `http://umbrel.local:5000` (oder der lokalen IP deines
   Umbrel) – vom Handy aus im gleichen WLAN genauso wie vorher.

Deine Daten (`tracker.db`) landen dabei in einem **benannten Docker-Volume**
(`tracker-data`) – die bleiben auch erhalten, wenn du den Container später
über Portainer neu baust oder aktualisierst.

**Willst du auch von unterwegs (nicht nur im Heim-WLAN) drauf zugreifen?**
Umbrel unterstützt dafür Tailscale als Remote-Zugriff – sag Bescheid, wenn
du das einrichten willst, dann gehen wir das zusammen durch.

## Nächste mögliche Ausbaustufen

- Gewichtsverlauf als Diagramm statt Tabelle
- Kalorienverlauf über mehrere Tage
- Bearbeiten/Löschen von Einträgen
- Dauerhaft laufen lassen (z.B. auf deinem Home-Server statt auf dem
  eigenen Rechner), damit du nicht jedes Mal `python app.py` starten musst
