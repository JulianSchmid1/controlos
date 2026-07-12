"""ControlOS - Konstanten & Parameter-Modell.

Die Entity-Schluessel (keys) sind bewusst identisch zu den Helfer-Suffixen des
erprobten Add-ons (core.py), damit die spaeter portierte Regel-Logik (Area.tick)
1:1 auf die Integrations-Entities zugreifen kann.
"""

DOMAIN = "controlos"

PLATFORMS = ["number", "select", "switch", "sensor", "binary_sensor",
             "button", "date", "time", "todo", "calendar", "text"]

# TEXT: Freitext-Eingaben (Grow-Verwaltung)
TEXT_PARAMS = {
    "grow_name":   {"name": "Grow-Name", "icon": "mdi:sprout", "default": "Mein Grow"},
    "strain_name": {"name": "Strain (Sorte)", "icon": "mdi:cannabis", "default": ""},
    "notiz_text":  {"name": "Neue Notiz / Erinnerung", "icon": "mdi:note-edit", "default": ""},
    "duenger_hersteller": {"name": "Hersteller", "icon": "mdi:factory", "default": ""},
    "duenger_name":       {"name": "Produktname", "icon": "mdi:bottle-tonic", "default": ""},
}

# Duengeplan: Typen je Kategorie
DUENGER_TYPEN = {
    "Dünger": ["Wachstum", "Blüte", "CalMag", "Wurzelstimulator", "Enzyme",
               "Mikroorganismen/Tee", "PK-Booster",
               "Bodenhilfsstoff (Amendment)", "NPK-Dünger",
               "Bodenaktivator", "Sonstiges"],
    "Pflanzenschutzmittel": ["Insektizid", "Fungizid"],
    "Nützlinge": [
        "SF-Nematoden (Steinernema feltiae)",
        "HB-Nematoden (Heterorhabditis bacteriophora)",
        "Raubmilben (Phytoseiulus persimilis)",
        "Raubmilben (Amblyseius californicus)",
        "Raubmilben (Amblyseius cucumeris)",
        "Raubmilben (Amblyseius swirskii)",
        "Bodenraubmilben (Stratiolaelaps scimitus)",
        "Bodenraubmilben (Macrocheles robustulus)",
        "Florfliegenlarven (Chrysoperla carnea)",
        "Schlupfwespen (Encarsia formosa)",
        "Schlupfwespen (Aphidius colemani)",
        "Gallmücken (Aphidoletes aphidimyza)",
        "Marienkäfer (Adalia bipunctata)",
        "Kurzflügelkäfer (Atheta coriaria)",
    ],
}

# TIME: Licht-Zeitplan je Bereich (zeitbasiert -> unabhaengig von Sensorik)
TIME_PARAMS = {
    "licht_start": {"name": "Licht Start", "icon": "mdi:weather-sunset-up",   "default": "05:00"},
    "licht_ende":  {"name": "Licht Ende",  "icon": "mdi:weather-sunset-down", "default": "23:00"},
}

# Coordinator-Intervall (s) fuer abgeleitete Sensoren + Regelung.
UPDATE_INTERVAL = 30
MIN_SWITCH_S = 180  # Mindestlaufzeit an/aus je Geraet (Anti-Flattern)

# MQTT-Watchdog: haengt der Broker (keine frischen Sensordaten mehr), wird er
# neu gestartet. Cooldown verhindert Restart-Schleifen.
MQTT_BROKER_ADDON = "core_mosquitto"
MQTT_RESTART_COOLDOWN_S = 900  # 15 min Ruhe nach einem Restart

# ---------------------------------------------------------------------------
# WUCHSPHASEN + zentrale Standard-Profile (10 Klima-Keys je Phase)
# ---------------------------------------------------------------------------
PHASES = ["Keimling / Klon", "Vegetation", "Vorblüte", "Hauptblüte",
          "Spätblüte", "Trocknen"]
# Zelt-Typ bestimmt die verfuegbaren Phasen (Wuchsphase + Phasen-Editor):
#   Growzelt = voller Zyklus | Mutterzelt = nur Vegetation |
#   Stecklingszelt = nur Keimling/Klon (Stecklingsphase)
ZELT_TYPEN = ["Growzelt", "Mutterzelt", "Stecklingszelt"]
ZELT_PHASES = {
    "Growzelt": PHASES,
    "Mutterzelt": ["Vegetation"],
    "Stecklingszelt": ["Keimling / Klon"],
}
# Mutter-/Stecklingszelt: nur vegetative Lichtzyklen (kein 12/12-Blüteumschalten)
VEG_ZYKLEN = ["16/8", "18/6", "20/4", "22/2"]
PHASE_KEYS = ["ziel_temp_tag", "ziel_temp_nacht", "temp_toleranz",
              "ziel_feuchte_tag", "ziel_feuchte_nacht", "feuchte_toleranz",
              "vpd_ziel", "vpd_toleranz", "co2_ziel", "co2_toleranz"]
STD_PHASE_DEFAULTS = {
    "Keimling / Klon": {"ziel_temp_tag": 24, "ziel_temp_nacht": 22, "temp_toleranz": 0.5,
                        "ziel_feuchte_tag": 75, "ziel_feuchte_nacht": 75, "feuchte_toleranz": 5,
                        "vpd_ziel": 0.6, "vpd_toleranz": 0.15, "co2_ziel": 500, "co2_toleranz": 100},
    "Vegetation":      {"ziel_temp_tag": 25, "ziel_temp_nacht": 22, "temp_toleranz": 0.5,
                        "ziel_feuchte_tag": 65, "ziel_feuchte_nacht": 65, "feuchte_toleranz": 5,
                        "vpd_ziel": 0.95, "vpd_toleranz": 0.2, "co2_ziel": 800, "co2_toleranz": 200},
    "Vorblüte":        {"ziel_temp_tag": 26, "ziel_temp_nacht": 22, "temp_toleranz": 0.5,
                        "ziel_feuchte_tag": 60, "ziel_feuchte_nacht": 60, "feuchte_toleranz": 5,
                        "vpd_ziel": 1.1, "vpd_toleranz": 0.2, "co2_ziel": 1000, "co2_toleranz": 200},
    "Hauptblüte":      {"ziel_temp_tag": 26, "ziel_temp_nacht": 21, "temp_toleranz": 0.5,
                        "ziel_feuchte_tag": 55, "ziel_feuchte_nacht": 55, "feuchte_toleranz": 5,
                        "vpd_ziel": 1.25, "vpd_toleranz": 0.2, "co2_ziel": 1100, "co2_toleranz": 200},
    "Spätblüte":       {"ziel_temp_tag": 24, "ziel_temp_nacht": 19, "temp_toleranz": 0.5,
                        "ziel_feuchte_tag": 48, "ziel_feuchte_nacht": 48, "feuchte_toleranz": 4,
                        "vpd_ziel": 1.4, "vpd_toleranz": 0.2, "co2_ziel": 700, "co2_toleranz": 150},
    "Trocknen":        {"ziel_temp_tag": 19, "ziel_temp_nacht": 19, "temp_toleranz": 0.5,
                        "ziel_feuchte_tag": 58, "ziel_feuchte_nacht": 58, "feuchte_toleranz": 3,
                        "vpd_ziel": 0.9, "vpd_toleranz": 0.1, "co2_ziel": 400, "co2_toleranz": 100},
}

# Shadow-/Status-Ausgaenge der Regelung (Text-Sensoren je Bereich)
SHADOW_KEYS = ["status", "licht", "undercanopy", "uv", "befeuchter",
               "entfeuchter", "heizung", "klima", "abluft", "co2",
               "ventilator", "umluft"]

# Buttons je Bereich (Phasen-Override)
BUTTON_PARAMS = {
    "phase_override_speichern": {"name": "Phase-Profil speichern", "icon": "mdi:content-save-edit"},
    "phase_override_reset":     {"name": "Phase-Profil auf Standard zurücksetzen", "icon": "mdi:backup-restore"},
    "strain_add":    {"name": "Strain hinzufügen",         "icon": "mdi:plus-circle"},
    "strain_remove": {"name": "Gewählten Strain entfernen", "icon": "mdi:minus-circle"},
    "grow_neu":      {"name": "Neuen Grow starten",         "icon": "mdi:sprout"},
    "grow_beenden":  {"name": "Grow beenden (leer weiterlaufen)", "icon": "mdi:stop-circle-outline"},
    "strain_ernten": {"name": "Gewählten Strain ernten",    "icon": "mdi:content-cut"},
    "benachrichtigung_add":    {"name": "Zielgerät hinzufügen",         "icon": "mdi:cellphone-check"},
    "benachrichtigung_remove": {"name": "Gewähltes Zielgerät entfernen", "icon": "mdi:cellphone-remove"},
    "notiz_anlegen": {"name": "Notiz hinzufügen", "icon": "mdi:note-plus"},
    "duenger_anlegen":   {"name": "Produkt anlegen",             "icon": "mdi:plus-circle"},
    "duenger_hersteller_neu": {"name": "Hersteller anlegen",     "icon": "mdi:factory"},
    "duenger_regel_add":    {"name": "Regel zum Produkt hinzufügen", "icon": "mdi:calendar-plus"},
    "duenger_regel_remove": {"name": "Gewählte Regel entfernen",     "icon": "mdi:calendar-minus"},
    "duenger_entfernen": {"name": "Gewähltes Produkt entfernen", "icon": "mdi:minus-circle"},
    "duenger_link":      {"name": "Mit Strain verknüpfen",       "icon": "mdi:link-variant"},
    "duenger_unlink":    {"name": "Verknüpfung trennen",         "icon": "mdi:link-variant-off"},
    "duenger_h_link":    {"name": "Hersteller-Methode verknüpfen", "icon": "mdi:factory"},
    "duenger_h_unlink":  {"name": "Hersteller-Methode trennen",    "icon": "mdi:link-variant-off"},
    "duenger_extra_add":    {"name": "Extra-Regel für Strain anlegen", "icon": "mdi:star-plus"},
    "duenger_extra_remove": {"name": "Gewählte Extra-Regel entfernen", "icon": "mdi:star-minus"},
}

# ---------------------------------------------------------------------------
# NUMBER: Zielwerte, Toleranzen, KI-Bias, Geraete-Parameter
# ---------------------------------------------------------------------------
NUMBER_PARAMS = {
    # -- Klima-Zielwerte + Toleranzen --
    "ziel_temp_tag":     {"name": "Ziel Temperatur Tag",   "min": 10, "max": 40, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer", "default": 24},
    "ziel_temp_nacht":   {"name": "Ziel Temperatur Nacht", "min": 10, "max": 40, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer", "default": 22},
    "temp_toleranz":     {"name": "Temp-Toleranz (±)",     "min": 0,  "max": 5,  "step": 0.1, "unit": "°C", "icon": "mdi:thermometer-lines", "default": 0.5},
    "ziel_feuchte_tag":  {"name": "Ziel Feuchtigkeit Tag", "min": 20, "max": 95, "step": 1,   "unit": "%",  "icon": "mdi:water-percent", "default": 60},
    "ziel_feuchte_nacht": {"name": "Ziel Feuchtigkeit Nacht", "min": 20, "max": 95, "step": 1, "unit": "%", "icon": "mdi:water-percent", "default": 60},
    "feuchte_toleranz":  {"name": "Feuchte-Toleranz (±)",  "min": 0,  "max": 20, "step": 1,   "unit": "%",  "icon": "mdi:water-off", "default": 5},
    "vpd_ziel":          {"name": "VPD Ziel",              "min": 0.0, "max": 2.5, "step": 0.05, "unit": "kPa", "icon": "mdi:water-opacity", "default": 1.2},
    "vpd_toleranz":      {"name": "VPD-Toleranz (±)",      "min": 0.0, "max": 1.0, "step": 0.05, "unit": "kPa", "icon": "mdi:water-alert", "default": 0.2},
    "co2_ziel":          {"name": "CO2 Ziel",              "min": 300, "max": 2000, "step": 10, "unit": "ppm", "icon": "mdi:molecule-co2", "default": 800},
    "co2_toleranz":      {"name": "CO2-Toleranz (±)",      "min": 0,   "max": 500, "step": 10, "unit": "ppm", "icon": "mdi:molecule-co2", "default": 200},
    "blatt_offset":      {"name": "Blatt-Offset",          "min": -10, "max": 10, "step": 0.1, "unit": "°C", "icon": "mdi:leaf", "default": 2},
    "dimm_mindestleistung": {"name": "Dimm-Mindestleistung", "min": 0, "max": 100, "step": 1, "unit": "%", "icon": "mdi:speedometer-slow", "default": 30},
    "licht_helligkeit": {"name": "Licht Helligkeit", "min": 0, "max": 100, "step": 1, "unit": "%", "icon": "mdi:brightness-6", "default": 100},
    "mqtt_watchdog_min": {"name": "MQTT-Watchdog Zeitfenster", "min": 0, "max": 60, "step": 1, "unit": "min", "icon": "mdi:timer-alert", "default": 10},
    "co2_alarm_max": {"name": "CO2-Alarm ab", "min": 800, "max": 3000, "step": 50, "unit": "ppm", "icon": "mdi:molecule-co2", "default": 1500},
    # -- Klima-Alarm-Modus "Toleranz": Alarm ab Sollwert +- (Toleranz + Margin) --
    "temp_alarm_margin":    {"name": "Temp-Alarm-Puffer",    "min": 0, "max": 15, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer-alert", "default": 3},
    "feuchte_alarm_margin": {"name": "Feuchte-Alarm-Puffer", "min": 0, "max": 40, "step": 1, "unit": "%", "icon": "mdi:water-alert", "default": 15},
    "vpd_alarm_margin":     {"name": "VPD-Alarm-Puffer",     "min": 0, "max": 1.5, "step": 0.05, "unit": "kPa", "icon": "mdi:water-alert", "default": 0.5},
    # -- Klima-Alarm-Modus "Min/Max": absolute untere/obere Alarmschwelle je Parameter --
    "temp_alarm_min":    {"name": "Temp-Alarm min",    "min": 0, "max": 40, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer-low",  "default": 16},
    "temp_alarm_max":    {"name": "Temp-Alarm max",    "min": 0, "max": 50, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer-high", "default": 30},
    "feuchte_alarm_min": {"name": "Feuchte-Alarm min", "min": 0, "max": 100, "step": 1, "unit": "%", "icon": "mdi:water-minus", "default": 30},
    "feuchte_alarm_max": {"name": "Feuchte-Alarm max", "min": 0, "max": 100, "step": 1, "unit": "%", "icon": "mdi:water-plus",  "default": 70},
    "vpd_alarm_min":     {"name": "VPD-Alarm min",     "min": 0, "max": 3, "step": 0.05, "unit": "kPa", "icon": "mdi:water-minus", "default": 0.4},
    "vpd_alarm_max":     {"name": "VPD-Alarm max",     "min": 0, "max": 4, "step": 0.05, "unit": "kPa", "icon": "mdi:water-plus",  "default": 1.8},
    "sunrise_dauer": {"name": "Sonnenaufgang Dauer", "min": 0, "max": 120, "step": 5, "unit": "min", "icon": "mdi:weather-sunset-up", "default": 30},
    "sunset_dauer":  {"name": "Sonnenuntergang Dauer", "min": 0, "max": 120, "step": 5, "unit": "min", "icon": "mdi:weather-sunset-down", "default": 30},
    # -- UV-Licht --
    "uv_dauer":         {"name": "UV Dauer (Tagesmitte)", "min": 1, "max": 120, "step": 1, "unit": "min", "icon": "mdi:sun-wireless", "default": 60},
    "uv_dauer_morgens": {"name": "UV Dauer morgens (vor Licht)", "min": 1, "max": 30, "step": 1, "unit": "min", "icon": "mdi:weather-sunset-up", "default": 10},
    "uv_dauer_abends":  {"name": "UV Dauer abends (nach Licht)", "min": 1, "max": 30, "step": 1, "unit": "min", "icon": "mdi:weather-sunset-down", "default": 10},
    # -- Duengeplan --
    "duenger_zeitpunkt": {"name": "Zeitpunkt (Tag/Woche Nr.)", "min": 1, "max": 150, "step": 1, "unit": "", "icon": "mdi:calendar-cursor", "default": 1},
    "duenger_intervall": {"name": "Wiederholen alle", "min": 1, "max": 60, "step": 1, "unit": "", "icon": "mdi:repeat", "default": 7},
    "duenger_erinnerung_intervall": {"name": "Erinnern alle", "min": 1, "max": 48, "step": 1, "unit": "", "icon": "mdi:bell-ring", "default": 4},
    "duenger_menge": {"name": "Menge je Anwendung", "min": 0, "max": 1000, "step": 0.5, "unit": "", "icon": "mdi:beaker", "default": 0},
    # -- KI-Bias (adaptiver Setpoint-Shift) --
    "vpd_bias_tag":   {"name": "VPD-Bias Tag",   "min": -0.5, "max": 0.5, "step": 0.01, "unit": "kPa", "icon": "mdi:brain", "default": 0},
    "vpd_bias_nacht": {"name": "VPD-Bias Nacht", "min": -0.5, "max": 0.5, "step": 0.01, "unit": "kPa", "icon": "mdi:brain", "default": 0},
    "temp_bias_tag":   {"name": "Temp-Bias Tag",   "min": -3, "max": 3, "step": 0.1, "unit": "°C", "icon": "mdi:brain", "default": 0},
    "temp_bias_nacht": {"name": "Temp-Bias Nacht", "min": -3, "max": 3, "step": 0.1, "unit": "°C", "icon": "mdi:brain", "default": 0},
    "hum_bias_tag":   {"name": "Feuchte-Bias Tag",   "min": -15, "max": 15, "step": 0.5, "unit": "%", "icon": "mdi:brain", "default": 0},
    "hum_bias_nacht": {"name": "Feuchte-Bias Nacht", "min": -15, "max": 15, "step": 0.5, "unit": "%", "icon": "mdi:brain", "default": 0},
    # -- KI-Vorsteuerung (Prognose-Lead auf das VPD-Regelsignal) --
    "ki_ff_staerke": {"name": "KI-Vorsteuerung Stärke", "min": 0, "max": 100, "step": 5, "unit": "%", "icon": "mdi:sine-wave", "default": 50},
    "ki_ff_max_mae": {"name": "KI-Vorsteuerung MAE-Grenze", "min": 0.02, "max": 0.5, "step": 0.01, "unit": "kPa", "icon": "mdi:target-variant", "default": 0.2},
    # -- Klima-Steuerung --
    "klima_ziel_tag":   {"name": "AC-Ziel Tag",   "min": 10, "max": 35, "step": 0.5, "unit": "°C", "icon": "mdi:air-conditioner", "default": 24},
    "klima_ziel_nacht": {"name": "AC-Ziel Nacht", "min": 10, "max": 35, "step": 0.5, "unit": "°C", "icon": "mdi:air-conditioner", "default": 22},
    "klima_hybrid_gewicht": {"name": "Klima Hybrid-Gewicht (% Area)", "min": 0, "max": 100, "step": 1, "unit": "%", "icon": "mdi:scale-balance", "default": 50},
    "klima_min_laufzeit": {"name": "AC Mindestlaufzeit", "min": 0, "max": 30, "step": 0.5, "unit": "min", "icon": "mdi:timer-lock", "default": 3},
    # Grenzen fuer das dynamische AC-Ziel der VPD->Temp-Kopplung (prio=feuchte)
    "klima_kopplung_min": {"name": "VPD-Kopplung Temp-Untergrenze", "min": 10, "max": 30, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer-chevron-down", "default": 16},
    "klima_kopplung_max": {"name": "VPD-Kopplung Temp-Obergrenze",  "min": 15, "max": 35, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer-chevron-up",   "default": 30},
    # -- Entfeuchter-Steuerung --
    "entfeuchter_hybrid_gewicht": {"name": "Entf. Hybrid-Gewicht (% Area)", "min": 0, "max": 100, "step": 1, "unit": "%", "icon": "mdi:scale-balance", "default": 50},
    "entfeuchter_min_laufzeit": {"name": "Entfeuchter Mindestlaufzeit", "min": 0, "max": 30, "step": 0.5, "unit": "min", "icon": "mdi:timer-lock", "default": 3},
    "entfeuchter_autonom_ziel_tag":   {"name": "Entf. Autonom-Ziel Tag",   "min": 20, "max": 90, "step": 1, "unit": "%", "icon": "mdi:water-off", "default": 60},
    "entfeuchter_autonom_ziel_nacht": {"name": "Entf. Autonom-Ziel Nacht", "min": 20, "max": 90, "step": 1, "unit": "%", "icon": "mdi:water-off", "default": 65},
    # -- CO2 --
    "co2_dauer_min":        {"name": "CO2 Dosier-Dauer", "min": 0, "max": 60, "step": 1, "unit": "min", "icon": "mdi:timer-play", "default": 5},
    "co2_intervall_min":    {"name": "CO2 Intervall",    "min": 1, "max": 240, "step": 1, "unit": "min", "icon": "mdi:timer-sync", "default": 30},
    "co2_max_laufzeit_min": {"name": "CO2 Max-Laufzeit", "min": 1, "max": 60, "step": 1, "unit": "min", "icon": "mdi:timer-alert-outline", "default": 15},
    # -- Ventilator / Umluft --
    "ventilator_ein_min":      {"name": "Ventilator Ein-Dauer", "min": 0, "max": 60, "step": 1, "unit": "min", "icon": "mdi:timer-play", "default": 5},
    "ventilator_intervall_min": {"name": "Ventilator Intervall", "min": 1, "max": 120, "step": 1, "unit": "min", "icon": "mdi:timer-sync", "default": 15},
    "ventilator_speed":        {"name": "Ventilator Geschwindigkeit", "min": 0, "max": 100, "step": 1, "unit": "%", "icon": "mdi:fan", "default": 100},
    "umluft_ein_min":      {"name": "Umluft Ein-Dauer", "min": 0, "max": 60, "step": 1, "unit": "min", "icon": "mdi:timer-play", "default": 5},
    "umluft_intervall_min": {"name": "Umluft Intervall", "min": 1, "max": 120, "step": 1, "unit": "min", "icon": "mdi:timer-sync", "default": 15},
    # -- Abluft-Backup-Schwellen --
    "abluft_backup_temp": {"name": "Abluft-Backup Temp",  "min": 20, "max": 45, "step": 0.5, "unit": "°C", "icon": "mdi:thermometer-alert", "default": 30},
    "abluft_backup_hum":  {"name": "Abluft-Backup Feuchte", "min": 40, "max": 95, "step": 1, "unit": "%", "icon": "mdi:water-percent-alert", "default": 70},
    "abluft_backup_co2":  {"name": "Abluft-Backup CO2",   "min": 800, "max": 3000, "step": 50, "unit": "ppm", "icon": "mdi:molecule-co2", "default": 1500},
    "abluft_backup_vpd":  {"name": "Abluft-Backup VPD",   "min": 1.0, "max": 3.0, "step": 0.05, "unit": "kPa", "icon": "mdi:water-alert", "default": 2.0},
    "abluft_backup_disarm_min": {"name": "Abluft-Backup Entschärf-Zeit", "min": 0, "max": 60, "step": 1, "unit": "min", "icon": "mdi:timer-off-outline", "default": 10},
    # -- Grow-Verwaltung --
    "strain_bluetezeit": {"name": "Blütezeit", "min": 1, "max": 300, "step": 1, "icon": "mdi:flower-outline", "default": 9},
}

# Phasen-Editor: Kopien der Phasen-Klimawerte (nur zum Bearbeiten der Profile,
# unabhaengig von den aktiven Steuerungswerten NUM_CLIMATE).
for _pk in PHASE_KEYS:
    _pe = dict(NUMBER_PARAMS[_pk])
    _pe["name"] = "Profil: " + _pe["name"]
    NUMBER_PARAMS["pe_" + _pk] = _pe

# ---------------------------------------------------------------------------
# SWITCH: Aktiv, Modi-Flags, Geraete-Vorhanden / Dimmbar / Dual
# ---------------------------------------------------------------------------
_DEVICES = ["befeuchter", "entfeuchter", "klima", "heizung", "co2",
            "licht", "undercanopy", "uv", "abluft", "ventilator", "umluft"]
_DIMMBAR = ["befeuchter", "entfeuchter", "heizung", "abluft",
            "licht", "undercanopy", "ventilator"]

SWITCH_PARAMS = {
    "aktiv":          {"name": "Aktiv",                "icon": "mdi:power", "default": False},
    "ki_engine":      {"name": "Echte KI (Datensammlung + Prognose)", "icon": "mdi:brain", "default": False},
    "ki_modus":       {"name": "KI-Bias (adaptiver Setpoint)", "icon": "mdi:auto-fix", "default": False},
    "ki_vorsteuerung": {"name": "KI-Vorsteuerung (Prognose dämpft Schwingungen)", "icon": "mdi:chart-timeline-variant-shimmer", "default": False},
    "mqtt_watchdog":  {"name": "MQTT-Watchdog (Broker-Neustart bei Sensor-Ausfall)", "icon": "mdi:restart-alert", "default": True},
    "benachrichtigungen": {"name": "Benachrichtigungen", "icon": "mdi:bell", "default": True},
    "nacht_statisch": {"name": "Nachts statisch regeln", "icon": "mdi:weather-night", "default": False},
    "co2_automatik":  {"name": "CO2 Automatik",        "icon": "mdi:robot-outline", "default": False},
    # -- Einzel-Toggles je Benachrichtigung (nur wirksam bei Master an) --
    "notify_tank":    {"name": "Meldung: Tank voll",        "icon": "mdi:bell", "default": True},
    "notify_co2":     {"name": "Meldung: CO2-Alarm",        "icon": "mdi:bell", "default": True},
    "notify_geraet":  {"name": "Meldung: Geräte-Ausfall",   "icon": "mdi:bell", "default": True},
    "notify_sensor":  {"name": "Meldung: Sensor-Ausfall",   "icon": "mdi:bell", "default": True},
    "notify_notizen": {"name": "Meldung: fällige Notizen",  "icon": "mdi:bell", "default": True},
    "notify_temp":    {"name": "Meldung: Temperatur-Alarm", "icon": "mdi:bell", "default": True},
    "notify_feuchte": {"name": "Meldung: Feuchte-Alarm",    "icon": "mdi:bell", "default": True},
    "notify_vpd":     {"name": "Meldung: VPD-Alarm",        "icon": "mdi:bell", "default": True},
    "notify_duenger": {"name": "Meldung: Pflanzenpflege fällig", "icon": "mdi:bell", "default": True},
    # "Enge Hysterese": Einzelgeraet schaltet am ZIEL ab (halbe Hysterese,
    # z.B. gegen Uebertrocknen). Aus = volle Hysterese bis zur gegenueber-
    # liegenden Bandkante (fuer sehr traege Geraete). Bei zwei Geraeten
    # (Be- UND Entfeuchter) automatisch aktiv.
    "dual_befeuchter":  {"name": "Befeuchter: enge Hysterese (am Ziel aus)", "icon": "mdi:arrow-collapse-vertical", "default": False},
    "dual_entfeuchter": {"name": "Entfeuchter: enge Hysterese (am Ziel aus)", "icon": "mdi:arrow-collapse-vertical", "default": False},
    "undercanopy_als_sonne": {"name": "Undercanopy als Sonnenauf-/-untergang", "icon": "mdi:weather-sunset", "default": False},
}
for _d in _DEVICES:
    SWITCH_PARAMS["vorhanden_%s" % _d] = {
        "name": "%s vorhanden?" % _d.capitalize(), "icon": "mdi:check-circle-outline", "default": False}
for _d in _DIMMBAR:
    SWITCH_PARAMS["dimmbar_%s" % _d] = {
        "name": "%s dimmbar?" % _d.capitalize(), "icon": "mdi:brightness-6", "default": False}
SWITCH_PARAMS["vorhanden_uv"]["name"] = "UV-Licht vorhanden?"
SWITCH_PARAMS["vorhanden_uv"]["icon"] = "mdi:sun-wireless-outline"

# ---------------------------------------------------------------------------
# SELECT: Modus-Auswahlen (statische Optionen). Geraete-Auswahl-Selects mit
# dynamischen Optionen kommen in Phase 1.
# ---------------------------------------------------------------------------
SELECT_PARAMS = {
    "betriebsmodus":   {"name": "Betriebsmodus", "icon": "mdi:shield-check", "options": ["Monitor", "Steuern"], "default": "Monitor"},
    "licht_zyklus":    {"name": "Lichtzyklus", "icon": "mdi:sun-clock", "options": ["Manuell", "24/0", "22/2", "20/4", "18/6", "16/8", "14/10", "12/12", "10/14"], "default": "18/6"},
    "licht_modus":     {"name": "Licht Schaltmodus", "icon": "mdi:weather-sunset", "options": ["An/Aus", "Sonnenauf-/-untergang"], "default": "An/Aus"},
    # UV: "Standard" = Leuchtdauer mittig in den Lichttag gelegt (UV-A/B);
    # "IPM" = buendig VOR Licht-Start und NACH Licht-Ende (UVC-Sterilisation).
    "uv_modus":        {"name": "UV Betriebsart", "icon": "mdi:sun-wireless", "options": ["Standard (Tagesmitte)", "IPM (vor/nach Licht)"], "default": "Standard (Tagesmitte)"},
    "klima_modus":     {"name": "Klima Modus",     "icon": "mdi:thermostat", "options": ["VPD", "Statisch"], "default": "VPD"},
    "system_modus":    {"name": "System Modus",    "icon": "mdi:tent", "options": ["Geschlossenes System", "Offenes System"], "default": "Geschlossenes System"},
    "klima_steuermodus": {"name": "Klima Steuermodus", "icon": "mdi:tune", "options": ["Area-Sensor", "Geräte-Sensor", "Hybrid", "Autonom"], "default": "Autonom"},
    "entfeuchter_steuermodus": {"name": "Entfeuchter Steuermodus", "icon": "mdi:tune", "options": ["Area-Sensor", "Geräte-Sensor", "Hybrid", "Autonom"], "default": "Area-Sensor"},
    "prio":            {"name": "Maßgebender Faktor", "icon": "mdi:swap-vertical", "options": ["temperatur", "feuchte"], "default": "temperatur"},
    "wuchsphase":      {"name": "Wuchsphase", "icon": "mdi:sprout", "options": ["Keimling / Klon", "Vegetation", "Vorblüte", "Hauptblüte", "Spätblüte", "Trocknen"], "default": "Vegetation"},
    "phase_editor":    {"name": "Phase bearbeiten", "icon": "mdi:pencil-ruler", "options": PHASES, "default": "Vegetation"},
    "grow_typ":        {"name": "Grow-Typ", "icon": "mdi:dna", "options": ["Photoperiodisch", "Autoflowering"], "default": "Photoperiodisch"},
    "zelt_typ":        {"name": "Zelt-Typ", "icon": "mdi:home-group", "options": ZELT_TYPEN, "default": "Growzelt"},
    "bluetezeit_einheit": {"name": "Blütezeit-Einheit", "icon": "mdi:calendar-clock", "options": ["Wochen", "Tage"], "default": "Wochen"},
    "benachrichtigung_modus": {"name": "Benachrichtigung an", "icon": "mdi:cellphone-message", "options": ["Alle Geräte", "Auswahl"], "default": "Alle Geräte"},
    # Erinnerungsart beim Anlegen einer Notiz (setzt intern das Steuerwort)
    "notiz_erinnerung": {"name": "Erinnerung", "icon": "mdi:bell-ring", "options": ["Einmalig (am Fälligkeitstag)", "Täglich bis erledigt", "Wöchentlich", "Stumm (keine Meldung)"], "default": "Einmalig (am Fälligkeitstag)"},
    # -- Duengeplan --
    "duenger_kategorie":  {"name": "Kategorie", "icon": "mdi:shape", "options": ["Dünger", "Pflanzenschutzmittel", "Nützlinge"], "default": "Dünger"},
    "duenger_plan_modus": {"name": "Anwendung", "icon": "mdi:repeat", "options": ["Einmalig", "Wiederholend"], "default": "Einmalig"},
    "duenger_zeiteinheit": {"name": "Zeiteinheit", "icon": "mdi:calendar-clock", "options": ["Tage", "Wochen"], "default": "Wochen"},
    "duenger_phase":      {"name": "Phase", "icon": "mdi:sprout", "options": ["Ganzer Grow", "Vegetation", "Blüte"], "default": "Ganzer Grow"},
    "duenger_erinnerung_modus": {"name": "Erinnerung (Push)", "icon": "mdi:bell-ring", "options": ["Einmalige Push-Nachricht", "Intervall bis abgehakt"], "default": "Einmalige Push-Nachricht"},
    "duenger_form": {"name": "Form", "icon": "mdi:water", "options": ["Flüssig (ml/L)", "Trocken (g/kg)"], "default": "Flüssig (ml/L)"},
    "duenger_extra_art": {"name": "Extra-Regel wirkt", "icon": "mdi:star-cog", "options": ["Zusätzlich zum Plan", "Ersetzt den Plan (individuell)"], "default": "Zusätzlich zum Plan"},
    "duenger_erinnerung_einheit": {"name": "Erinnerungs-Einheit", "icon": "mdi:timer-sand", "options": ["Stunden", "Tage"], "default": "Stunden"},
    # -- Klima-Alarm-Schwellenart je Parameter: Toleranz (um Sollwert) oder feste Min/Max --
    "temp_alarm_modus":    {"name": "Temp-Alarmart",    "icon": "mdi:thermometer-alert", "options": ["Toleranz", "Min/Max"], "default": "Toleranz"},
    "feuchte_alarm_modus": {"name": "Feuchte-Alarmart", "icon": "mdi:water-alert",       "options": ["Toleranz", "Min/Max"], "default": "Toleranz"},
    "vpd_alarm_modus":     {"name": "VPD-Alarmart",     "icon": "mdi:water-alert",       "options": ["Toleranz", "Min/Max"], "default": "Toleranz"},
    "speicherzeit":    {"name": "Speicherzeit Messdaten", "icon": "mdi:database-clock", "options": ["Unbegrenzt", "12 Monate", "6 Monate", "3 Monate"], "default": "Unbegrenzt"},
    "graph_zeitraum":  {"name": "Graph-Zeitraum", "icon": "mdi:chart-timeline", "options": ["1 h", "6 h", "12 h", "24 h", "48 h", "7 Tage"], "default": "24 h"},
    "co2_betrieb_modus": {"name": "CO2 Betriebsmodus", "icon": "mdi:molecule-co2", "options": ["Dauerbetrieb", "Intervall"], "default": "Dauerbetrieb"},
    "ventilator_modus": {"name": "Ventilator Modus", "icon": "mdi:fan-chevron-up", "options": ["Dauerbetrieb", "Intervall"], "default": "Dauerbetrieb"},
    "umluft_modus":    {"name": "Umluft Modus", "icon": "mdi:weather-windy", "options": ["Dauerbetrieb", "Intervall"], "default": "Dauerbetrieb"},
    "abluft_modus":    {"name": "Abluft Modus", "icon": "mdi:fan", "options": ["Auto", "Deaktiviert"], "default": "Auto"},
    "klima_modus_tag":   {"name": "AC-Modus Tag (Autonom)",   "icon": "mdi:weather-sunny", "options": ["Kühlen", "Heizen", "Auto", "Aus"], "default": "Kühlen"},
    "klima_modus_nacht": {"name": "AC-Modus Nacht (Autonom)", "icon": "mdi:weather-night", "options": ["Kühlen", "Heizen", "Auto", "Aus"], "default": "Aus"},
    # Sensor-Modi (Area/Geraet/Hybrid): Luefterstaerke je Zustand
    "klima_fan_aktiv":    {"name": "AC-Lüfter aktiv (Heizen/Kühlen)", "icon": "mdi:fan", "options": ["auto", "silent", "low", "medium", "high", "full"], "default": "auto"},
    "klima_fan_leerlauf": {"name": "AC-Lüfter Leerlauf (nur Lüfter)", "icon": "mdi:fan-minus", "options": ["auto", "silent", "low", "medium", "high", "full"], "default": "silent"},
    "klima_fan_tag":   {"name": "AC-Lüfter Tag",   "icon": "mdi:fan", "options": ["auto", "low", "medium", "high"], "default": "auto"},
    "klima_fan_nacht": {"name": "AC-Lüfter Nacht", "icon": "mdi:fan", "options": ["auto", "low", "medium", "high"], "default": "auto"},
}

# ---------------------------------------------------------------------------
# SELECT (Geraete-Auswahl): Optionen werden vom Coordinator dynamisch aus den
# vorhandenen HA-Entities der gelisteten Domains befuellt ("Keine" + Treffer).
# ---------------------------------------------------------------------------
_DEV_DOMAINS = {
    "befeuchter": ["switch", "light", "fan", "humidifier"],
    "entfeuchter": ["switch", "fan", "humidifier"],
    "klima": ["climate", "switch"],
    "heizung": ["switch", "climate", "light"],
    "co2_ventil": ["switch"],
    "licht": ["switch", "light"],
    "undercanopy": ["switch", "light"],
    "uv": ["switch", "light"],
    "abluft": ["switch", "fan"],
    "ventilator": ["switch", "fan"],
    "umluft": ["switch", "fan"],
}
_DIMMBAR = ["befeuchter", "entfeuchter", "heizung", "abluft", "licht", "undercanopy", "ventilator"]
_SENSOR_SRC = [
    ("temp_luft", "Lufttemperatur"), ("feuchte_luft", "Luftfeuchtigkeit"),
    ("co2", "CO2"), ("temp_zuluft", "Zuluft-Temperatur"),
    ("feuchte_zuluft", "Zuluft-Feuchtigkeit"), ("temp_blatt", "Blatttemperatur"),
]

SELECT_DEVICE_PARAMS = {}
for _d, _doms in _DEV_DOMAINS.items():
    SELECT_DEVICE_PARAMS["geraet_%s" % _d] = {
        "name": "Gerät: %s" % _d.replace("_", " ").title(),
        "icon": "mdi:power-plug", "domains": _doms}
for _d in _DIMMBAR:
    SELECT_DEVICE_PARAMS["dimmer_%s" % _d] = {
        "name": "Dimmer: %s" % _d.capitalize(),
        "icon": "mdi:brightness-6", "domains": ["light", "fan", "number"]}
for _s, _nm in _SENSOR_SRC:
    SELECT_DEVICE_PARAMS["sensor_%s" % _s] = {
        "name": "Sensor: %s" % _nm, "icon": "mdi:access-point",
        "domains": ["sensor", "number"]}
SELECT_DEVICE_PARAMS["sensor_entfeuchter"] = {
    "name": "Geräte-Feuchtesensor", "icon": "mdi:water-percent", "domains": ["sensor", "number"]}
SELECT_DEVICE_PARAMS["sensor_tank"] = {
    "name": "Tank-Sensor (voll)", "icon": "mdi:cup-water", "domains": ["binary_sensor"]}
SELECT_DEVICE_PARAMS["stufe_entfeuchter"] = {
    "name": "Lüfterstufe Entfeuchter", "icon": "mdi:fan", "domains": ["select", "fan"]}

# ---------------------------------------------------------------------------
# SENSOR / BINARY_SENSOR: abgeleitete Werte, vom Coordinator berechnet.
# ---------------------------------------------------------------------------
SENSOR_PARAMS = {
    "data_temp_luft":     {"name": "Lufttemperatur",   "unit": "°C",  "device_class": "temperature", "icon": "mdi:thermometer"},
    "data_feuchte_luft":  {"name": "Luftfeuchtigkeit", "unit": "%",   "device_class": "humidity",    "icon": "mdi:water-percent"},
    "data_co2":           {"name": "CO2",              "unit": "ppm", "device_class": "carbon_dioxide", "icon": "mdi:molecule-co2"},
    "data_temp_zuluft":   {"name": "Zuluft-Temperatur","unit": "°C",  "device_class": "temperature", "icon": "mdi:home-import-outline"},
    "data_feuchte_zuluft": {"name": "Zuluft-Feuchtigkeit", "unit": "%", "device_class": "humidity",  "icon": "mdi:home-import-outline"},
    "data_temp_blatt":    {"name": "Blatttemperatur",  "unit": "°C",  "device_class": "temperature", "icon": "mdi:leaf"},
    "data_vpd":           {"name": "VPD",              "unit": "kPa", "icon": "mdi:water-opacity"},
    "data_tag_nacht":     {"name": "Tag / Nacht",      "icon": "mdi:theme-light-dark"},
    "data_uc_helligkeit": {"name": "Undercanopy Ist-Helligkeit", "unit": "%", "icon": "mdi:brightness-6"},
    "data_ziel_temp":     {"name": "Ziel Temperatur",  "unit": "°C",  "device_class": "temperature", "icon": "mdi:target"},
    "data_ziel_feuchte":  {"name": "Ziel Feuchtigkeit","unit": "%",   "device_class": "humidity",    "icon": "mdi:target"},
    # Grow-Kalender (Tracking)
    "grow_tag":   {"name": "Grow-Tag",   "unit": "Tage", "icon": "mdi:calendar-today"},
    "phase_tag":  {"name": "Phasen-Tag", "unit": "Tage", "icon": "mdi:calendar-range"},
    "bluete_tag": {"name": "Blüte-Tag",  "unit": "Tage", "icon": "mdi:flower"},
    # Echte KI (Datenlogger + Prognose)
    "ki_vpd_prognose": {"name": "KI VPD-Prognose (15 min)", "unit": "kPa", "icon": "mdi:chart-timeline-variant"},
    "ki_status":       {"name": "KI Status", "icon": "mdi:brain"},
}
BINARY_PARAMS = {
    "data_ist_tag": {"name": "Tag/Nacht", "device_class": "light", "icon": "mdi:theme-light-dark"},
}
