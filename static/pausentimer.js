// Pausentimer: reine Stoppuhr, kein Alarm/Ton. Der Startzeitpunkt wird im
// Browser (localStorage) je Drening gemerkt, damit der Timer auch beim
// Wechsel zwischen "Drening-Übersicht" und "Übung hinzufügen" weiterläuft.
(function () {
    const box = document.getElementById("pausen-timer-box");
    if (!box) return;
    const anzeige = document.getElementById("pausen-timer-anzeige");
    const schluessel = "pausentimer_start_" + box.dataset.einheitId;
    const MAX_ALTER_MS = 3 * 60 * 60 * 1000; // älter als 3 Std. = veraltet
    let intervallId = null;

    function lesen() {
        try {
            const wert = parseInt(localStorage.getItem(schluessel), 10);
            if (!wert || Date.now() - wert > MAX_ALTER_MS) return null;
            return wert;
        } catch (e) { return null; }
    }

    function schreiben(wert) {
        try {
            if (wert === null) localStorage.removeItem(schluessel);
            else localStorage.setItem(schluessel, String(wert));
        } catch (e) { /* ohne Speicher läuft er nur auf dieser Seite */ }
    }

    let startZeit = lesen();

    function aktualisieren() {
        const s = Math.max(0, Math.floor((Date.now() - startZeit) / 1000));
        anzeige.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    }

    function anzeigen() {
        box.hidden = false;
        if (intervallId) clearInterval(intervallId);
        intervallId = setInterval(aktualisieren, 1000);
        aktualisieren();
    }

    window.pausenTimerStarten = function () {
        startZeit = Date.now();
        schreiben(startZeit);
        anzeigen();
    };

    window.pausenTimerLaeuft = function () { return startZeit !== null; };

    window.pausenTimerLoeschen = function () {
        startZeit = null;
        schreiben(null);
    };

    // Beim Zurückkehren in die App/den Tab sofort die richtige Zeit zeigen.
    document.addEventListener("visibilitychange", function () {
        if (startZeit !== null && !document.hidden) aktualisieren();
    });

    if (startZeit !== null) anzeigen();
})();
