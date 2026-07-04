# ControlOS 🌱

**Grow-Tent-Klimaautomatisierung als native Home-Assistant-Integration** — vollständig über das Dashboard konfigurierbar, kein YAML nötig.

## Features

- **Bereiche (Zelte/Räume)** per UI anlegen/löschen — jeder Bereich ist ein eigenes Gerät mit ~90 Entities
- **Klima-Regelung**: VPD/Feuchte/Temperatur mit Hysterese + Mindestlaufzeiten, Befeuchter/Entfeuchter-Paarlogik, Klima-Steuermodi (Area/Gerät/Hybrid/Autonom), CO2-Dosierung (Dauer/Intervall + Max-Laufzeit-Schutz), Abluft Haupt-/Backup-Rolle
- **Betriebsmodus je Bereich**: *Monitor* (nur beobachten) oder *Steuern* (echtes Schalten, selbstheilend gegen externe Eingriffe)
- **Licht**: Zeitplan mit Lichtzyklus (18/6, 12/12, …), Sunrise/Sunset-Dimmrampen, „Undercanopy als Sonnenauf-/-untergang"
- **Wachstumsphasen**: zentrale Standard-Profile + Overrides je Bereich, Auto-Laden beim Phasenwechsel
- **Grow-Kalender**: Grow-/Blüte-Tag (Photoperiodisch/Autoflowering), Phasen-Tagebuch, Notizen & Erinnerungen (Todo), grafischer Monatskalender
- **KI**: adaptiver Setpoint-Bias + VPD-Prognose (eigenes Datenarchiv, stündliches Training, keine externen Abhängigkeiten)
- **Benachrichtigungen**: Tank voll, CO2-Alarm, Sensor-Ausfall, fällige Notizen — Push aufs Wunschgerät
- **Robustheit**: MQTT-Watchdog (Broker-Neustart bei Sensor-Ausfall), Selbstheilung, alles Neustart-persistent
- **Dashboard**: generiert sich selbst aus den Bereichen (Lovelace-Strategie, bubble-card-Design, VPD-Map mit Phasenzonen)

## Installation

1. **HACS** → Integrationen → Benutzerdefinierte Repositories → dieses Repo hinzufügen (Kategorie *Integration*) → installieren
2. Home Assistant neu starten
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → ControlOS** → Bereichsnamen eingeben
4. Dashboard: `www/controlos-dashboard.js` nach `/config/www/` kopieren, als Ressource einbinden (`/local/controlos-dashboard.js`, Typ *Modul*) und ein Dashboard mit der Strategie `custom:controlos` anlegen

### Benötigte HACS-Frontend-Karten
`bubble-card` · `mini-graph-card` · `mushroom` · `ha-vpd-chart` · `card-mod` · `kiosk-mode` (optional)

## Hinweis

Regelung auf eigene Verantwortung — Betriebsmodus **Monitor** erlaubt gefahrloses Testen, bevor *Steuern* aktiviert wird.
