/* ControlOS - Lovelace Dashboard-Strategie (v6, Altsystem-Look).
 * Generiert das komplette Dashboard aus den ControlOS-Bereichen:
 *   Einstellungen (Bereiche verwalten) | je Bereich ein Monitoring-Tab
 *   (Grafiken, VPD-Map, Steuerung, Grow-Kalender) | je Bereich eine
 *   Einstellungen-Subview | Phasen-Standard-Subview.
 * Design: bubble-card-Separatoren + Selects/Switches/Slider wie im
 * Altsystem, gruene Akzente, Kiosk-Theme pro View.
 */

const DASH = "controlos-core";
const THEME = "ControlOS Kiosk";
const GREEN = "#166534";

const NUM_CLIMATE = [
  "ziel_temp_tag", "ziel_temp_nacht", "temp_toleranz",
  "ziel_feuchte_tag", "ziel_feuchte_nacht", "feuchte_toleranz",
  "vpd_ziel", "vpd_toleranz", "co2_ziel", "co2_toleranz",
];
const SEL_STEUER = ["klima_steuermodus", "entfeuchter_steuermodus", "prio"];
const SEL_SENSOR = ["sensor_temp_luft", "sensor_feuchte_luft", "sensor_co2",
  "sensor_temp_zuluft", "sensor_feuchte_zuluft", "sensor_temp_blatt"];
const SEL_GERAET = ["geraet_befeuchter", "geraet_entfeuchter", "geraet_klima",
  "geraet_heizung", "geraet_co2_ventil", "geraet_licht", "geraet_undercanopy",
  "geraet_abluft", "geraet_ventilator", "geraet_umluft"];
const SW_VORHANDEN = [
  "vorhanden_befeuchter", "vorhanden_entfeuchter", "vorhanden_klima",
  "vorhanden_heizung", "vorhanden_co2", "vorhanden_licht",
  "vorhanden_undercanopy", "vorhanden_abluft", "vorhanden_ventilator",
  "vorhanden_umluft",
];
const SW_OPTIONS = ["ki_modus", "nacht_statisch", "schalten_klima"];
const SHADOW = ["status", "licht", "undercanopy", "befeuchter", "entfeuchter",
  "heizung", "klima", "abluft", "co2", "ventilator", "umluft"];

function slug(name) {
  let o = "";
  for (const ch of (name || "").toLowerCase()) {
    o += (ch >= "a" && ch <= "z") || (ch >= "0" && ch <= "9") ? ch : "_";
  }
  while (o.includes("__")) o = o.replace("__", "_");
  return o.replace(/^_+|_+$/g, "") || "bereich";
}

function findAreas(hass) {
  const out = [];
  for (const d of Object.values(hass.devices || {})) {
    const idf = (d.identifiers || []).find((x) => x[0] === "controlos");
    if (idf && d.model !== "Standard-Profile")
      out.push({ entry_id: idf[1], title: d.name_by_user || d.name });
  }
  out.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
  return out;
}

/* ---- Design (global, Hub-Selects; Strategie liest bei Generierung) ---- */
const DESIGN = { layout: "large", bg: null };
const DESIGN_LAYOUTS = { "Bubble Groß": "large", "Bubble Kompakt": "normal",
  "Bubble 2-Zeilen": "large-2-rows" };
const DESIGN_BGS = { "Grün": "#16a34a", "Blau": "#3b82f6",
  "Violett": "#8b5cf6", "Orange": "#f59e0b", "Rot": "#ef4444" };

function readDesign(hass) {
  const stil = hass.states["select.controlos_design_stil"];
  const bg = hass.states["select.controlos_design_hintergrund"];
  DESIGN.layout = DESIGN_LAYOUTS[stil && stil.state] || "large";
  DESIGN.bg = DESIGN_BGS[bg && bg.state] || null;
}

function applyDesign(c) {
  c.card_layout = DESIGN.layout;
  if (DESIGN.bg) {
    // Akzentfarbe: faerbt den AKTIVEN Teil (Slider-Fuellung, an-Zustaende),
    // der Rest der Karte bleibt dunkel wie im ausgeschalteten Zustand.
    const css = ":host { --bubble-accent-color: " + DESIGN.bg + "; }\n";
    c.styles = (c.styles || "") + css;
  }
  return c;
}

/* ---- Bausteine (Altsystem-Look) ---- */
function sep(name, icon) {
  return { type: "custom:bubble-card", card_type: "separator", name, icon,
    card_layout: "large", color: GREEN,
    styles: ".bubble-line { background: white; opacity: 1; }\n",
    grid_options: { columns: "full" } };
}
function bsel(entity, name) {
  const c = { type: "custom:bubble-card", card_type: "select", entity,
    card_layout: "large" };
  if (name) c.name = name;
  return applyDesign(c);
}
function bsw(entity, name, icon) {
  const c = { type: "custom:bubble-card", card_type: "button",
    button_type: "switch", entity, card_layout: "large" };
  if (name) c.name = name;
  if (icon) c.icon = icon;
  return applyDesign(c);
}
function bslider(entity, name) {
  const c = { type: "custom:bubble-card", card_type: "button",
    button_type: "slider", entity, card_layout: "large", show_state: true };
  if (name) c.name = name;
  return applyDesign(c);
}
function bstate(entity, name, icon) {
  return applyDesign({ type: "custom:bubble-card", card_type: "button",
    button_type: "state", entity, name, icon, card_layout: "large",
    show_state: true, scrolling_effect: true, tap_action: { action: "more-info" } });
}
function mg(name, decimals, entities, extra) {
  return Object.assign({ type: "custom:mini-graph-card", name, hours_to_show: 24,
    points_per_hour: 6, line_width: 2, decimals, height: 100, hour24: true,
    show: { legend: false, fill: "fade" }, entities }, extra || {});
}

/* Graph-Popup: grosser Graph im Dashboard-Design mit live umschaltbarer
   Zeitachse (Zeitraum-Select + sichtbarkeitsgesteuerte Varianten). */
const GRAPH_RANGES = [["1 h", 1, 60], ["6 h", 6, 30], ["12 h", 12, 12],
  ["24 h", 24, 6], ["48 h", 48, 3], ["7 Tage", 168, 1]];

function graphDefs(s) {
  const D = "sensor.controlos_" + s + "_data_";
  return [
    ["temp", "Temperatur", 1,
      [{ entity: D + "temp_luft", name: "Ist", color: "#ef4444" },
       { entity: D + "ziel_temp", name: "Ziel", color: "#9ca3af" }]],
    ["hum", "Luftfeuchtigkeit", 1,
      [{ entity: D + "feuchte_luft", name: "Ist", color: "#3b82f6" },
       { entity: D + "ziel_feuchte", name: "Ziel", color: "#9ca3af" }]],
    ["vpd", "VPD", 2,
      [{ entity: D + "vpd", name: "VPD", color: "#a855f7" },
       { entity: "number.controlos_" + s + "_vpd_ziel", name: "Ziel", color: "#9ca3af" }]],
    ["co2", "CO2", 0,
      [{ entity: D + "co2", name: "CO2", color: "#22c55e" },
       { entity: "number.controlos_" + s + "_co2_ziel", name: "Ziel", color: "#9ca3af" }]],
    ["blatt", "Blatttemperatur", 1,
      [{ entity: D + "temp_blatt", name: "Blatt", color: "#f97316" }]],
    ["zutemp", "Zuluft Temperatur", 1,
      [{ entity: D + "temp_zuluft", name: "Zuluft", color: "#06b6d4" }]],
    ["zuhum", "Zuluft Feuchtigkeit", 1,
      [{ entity: D + "feuchte_zuluft", name: "Zuluft", color: "#0ea5e9" }]],
  ];
}

/* Graphen-Seite: alle Graphen gross, Zeitachse live umschaltbar. */
function graphenView(a) {
  const s = slug(a.title);
  const sp = "select.controlos_" + s + "_";
  const zr = sp + "graph_zeitraum";
  const zuluftVis = { zutemp: sp + "sensor_temp_zuluft",
    zuhum: sp + "sensor_feuchte_zuluft" };
  const cards = [
    sep("Zeitraum", "mdi:chart-timeline"),
    applyDesign({ type: "custom:bubble-card", card_type: "select",
      entity: zr, name: "Zeitachse", card_layout: "large" }),
    sep("Graphen", "mdi:chart-line"),
  ];
  for (const [key, name, dec, ents] of graphDefs(s)) {
    for (const [opt, hours, pph] of GRAPH_RANGES) {
      const vis = [{ condition: "state", entity: zr, state: opt }];
      if (zuluftVis[key])
        vis.push({ condition: "state", entity: zuluftVis[key], state_not: "Keine" });
      cards.push(Object.assign(
        mg(name, dec, ents,
          { hours_to_show: hours, points_per_hour: pph, height: 220,
            show: { legend: true, fill: "fade" } }),
        { visibility: vis }));
    }
  }
  return { title: a.title + " · Graphen", path: "graphen-" + s,
    icon: "mdi:chart-line", subview: true, theme: THEME,
    type: "sections", max_columns: 2,
    sections: [{ type: "grid", column_span: 2, cards }] };
}
function vpdChart(areas) {
  return { type: "custom:ha-vpd-chart",
    sensors: areas.map((a) => {
      const s = slug(a.title);
      return { temperature: "sensor.controlos_" + s + "_data_temp_luft",
        humidity: "sensor.controlos_" + s + "_data_feuchte_luft",
        leaf_temperature: "sensor.controlos_" + s + "_data_temp_blatt",
        name: a.title };
    }),
    air_text: "Temp", rh_text: "Hum", kpa_text: "VPD",
    min_height: 400, min_temperature: 15, max_temperature: 35,
    min_humidity: 35, max_humidity: 90,
    enable_ghostmap: true, enable_axes: true, enable_triangle: true,
    is_bar_view: false,
    vpd_phases: [
      { upper: 0.58, className: "too low", color: "#ce4134" },
      { lower: 0.58, upper: 0.74, className: "tolerance Low", color: "#ecf000" },
      { lower: 0.74, upper: 1, className: "vegetative Phase", color: "#40b800" },
      { lower: 1, upper: 1.18, className: "generative Phase", color: "#1f7500" },
      { lower: 1.18, upper: 1.45, className: "Endphase", color: "#57c52f" },
      { lower: 1.45, upper: 1.58, className: "Tolerance high", color: "#ecf000" },
      { lower: 1.58, className: "too high", color: "#ce4134" },
    ],
    leaf_temperature_offset: 2, enable_tooltip: true, enable_ghostclick: true,
    enable_crosshair: true, enable_fahrenheit: false, enable_zoom: true,
    enable_show_always_informations: true, enable_legend: true,
    ghostmap_hours: 24, unit_temperature: "°C",
    grid_options: { columns: "full" } };
}

/* ---- Views ---- */
function settingsView(areas) {
  const cards = [sep("Bereiche", "mdi:home-group")];
  if (areas.length === 0)
    cards.push({ type: "markdown", content: "_Noch keine Bereiche. Unten „Bereich hinzufügen“._" });
  areas.forEach((a, i) => {
    cards.push({
      type: "custom:mushroom-template-card",
      icon: "mdi:sprout", icon_color: "green",
      primary: a.title, secondary: "Bereich " + (i + 1) + " · Einstellungen öffnen",
      tap_action: { action: "navigate", navigation_path: "/" + DASH + "/bereich-" + slug(a.title) + "-config" },
    });
  });
  cards.push({
    type: "custom:mushroom-template-card",
    icon: "mdi:plus-box", icon_color: "blue",
    primary: "Bereich hinzufügen", secondary: "Neues Zelt / neuen Raum anlegen",
    tap_action: { action: "navigate", navigation_path: "/config/integrations/dashboard/add?domain=controlos" },
  });
  cards.push(sep("Weitere Einstellungen", "mdi:tune-vertical"));
  cards.push({
    type: "custom:mushroom-template-card",
    icon: "mdi:sprout-outline", icon_color: "teal",
    primary: "Wachstumsphasen (Standard)", secondary: "Profile für alle Bereiche",
    tap_action: { action: "navigate", navigation_path: "/" + DASH + "/phasen-standard" },
  });
  cards.push(sep("Design", "mdi:palette"));
  cards.push(bsel("select.controlos_design_stil", "Karten-Stil"));
  cards.push({ type: "horizontal-stack",
    cards: ["Standard"].concat(Object.keys(DESIGN_BGS)).map((opt) => {
      const dot = DESIGN_BGS[opt] || "#42a5f5";
      return { type: "custom:bubble-card", card_type: "button",
        button_type: "name", name: "", icon: "mdi:circle",
        card_layout: "normal",
        tap_action: { action: "call-service",
          service: "select.select_option",
          target: { entity_id: "select.controlos_design_hintergrund" },
          data: { option: opt } },
        styles: ".bubble-icon { color: " + dot + " !important; " +
          "filter: drop-shadow(0 0 2px rgba(255,255,255,0.55)); }\n" +
          ".bubble-name { display: none; }\n",
        card_mod: { style: "ha-card { border: {{ '2px solid var(--primary-text-color)' " +
          "if is_state('select.controlos_design_hintergrund','" + opt + "') " +
          "else '1px solid transparent' }} !important; }" } };
    }) });
  cards.push({ type: "markdown",
    content: "Design-Änderungen werden nach einem **Neuladen der Seite** wirksam." });
  return { title: "Einstellungen", path: "einstellungen", theme: THEME,
    type: "sections", max_columns: 4, sections: [{ type: "grid", cards }] };
}

function monitorView(a, hass) {
  const s = slug(a.title);
  const D = "sensor.controlos_" + s + "_data_";
  const S = "sensor.controlos_" + s + "_shadow_";
  const G = "sensor.controlos_" + s + "_";
  const B = "binary_sensor.controlos_" + s + "_data_";
  const wp = "switch.controlos_" + s + "_", sp = "select.controlos_" + s + "_";
  const shadowIcons = { status: "mdi:radar", licht: "mdi:lightbulb-on",
    undercanopy: "mdi:lightbulb-group",
    befeuchter: "mdi:air-humidifier",
    entfeuchter: "mdi:air-humidifier-off", heizung: "mdi:radiator",
    klima: "mdi:air-conditioner", abluft: "mdi:fan", co2: "mdi:molecule-co2",
    ventilator: "mdi:fan-chevron-up", umluft: "mdi:weather-windy" };
  return { title: a.title, path: "bereich-" + s, icon: "mdi:sprout", theme: THEME,
    type: "sections", max_columns: 5, sections: [
      { type: "grid", cards: [
        sep("Status", "mdi:view-dashboard-outline"),
        bsw(wp + "aktiv", a.title + " Aktiv", "mdi:power"),
        bsel(sp + "betriebsmodus", "Betriebsmodus"),
        bstate(sp + "wuchsphase", "Wuchsphase", "mdi:sprout"),
        applyDesign({ type: "custom:bubble-card", card_type: "button", button_type: "state",
          entity: D + "tag_nacht", card_layout: "large",
          name: "Tag / Nacht", show_state: true,
          tap_action: { action: "more-info" },
          sub_button: [
            { entity: "time.controlos_" + s + "_licht_start",
              icon: "mdi:weather-sunset-up", show_state: true,
              show_background: true, tap_action: { action: "more-info" } },
            { entity: "time.controlos_" + s + "_licht_ende",
              icon: "mdi:weather-sunset-down", show_state: true,
              show_background: true, tap_action: { action: "more-info" } },
          ] }),
        bstate(D + "ziel_temp", "Ziel Temperatur", "mdi:target"),
        bstate(D + "ziel_feuchte", "Ziel Feuchtigkeit", "mdi:target"),
        sep("Grow-Kalender", "mdi:calendar-month"),
        (() => {
          const typSt = hass.states[sp + "grow_typ"];
          const auto = typSt && typSt.state === "Autoflowering";
          const rows = [{ entity: "date.controlos_" + s + "_grow_start", name: "Grow-Start" }];
          if (auto) {
            rows.push({ entity: G + "grow_tag", name: "Grow/Blüte-Tag" });
            rows.push({ entity: G + "phase_tag", name: "Tag in Phase" });
          } else {
            rows.push({ entity: "date.controlos_" + s + "_bluete_start", name: "Blüte-Start" });
            rows.push({ entity: G + "grow_tag", name: "Grow-Tag" });
            rows.push({ entity: G + "phase_tag", name: "Tag in Phase" });
            rows.push({ entity: G + "bluete_tag", name: "Blüte-Tag" });
          }
          return { type: "entities", entities: rows };
        })(),
        { type: "custom:mushroom-template-card",
          icon: "mdi:calendar-text", icon_color: "teal",
          primary: "Grow-Kalender öffnen",
          secondary: "Phasen-Tagebuch, Notizen & Erinnerungen",
          tap_action: { action: "navigate",
            navigation_path: "/" + DASH + "/grow-kalender-" + s } },
        sep("KI-Prognose", "mdi:brain"),
        bstate(G + "ki_vpd_prognose", "VPD in 15 Minuten", "mdi:chart-timeline-variant"),
        bstate(G + "ki_status", "KI Status", "mdi:brain"),
      ] },
      (() => {
        const nav = { action: "navigate",
          navigation_path: "/" + DASH + "/graphen-" + s };
        const byKey = {};
        for (const d of graphDefs(s)) byKey[d[0]] = d;
        const tile = (k, extraVis) => {
          const [, name, dec, ents] = byKey[k];
          const c = mg(name, dec, ents, { tap_action: nav });
          if (extraVis) c.visibility = extraVis;
          return c;
        };
        return { type: "grid", column_span: 2, cards: [
          sep("Klima (" + a.title + ")", "mdi:tent"),
          tile("temp"), tile("hum"), tile("vpd"), tile("co2"), tile("blatt"),
          Object.assign(sep("Zuluft (Raum)", "mdi:home-import-outline"),
            { visibility: [{ condition: "or", conditions: [
              { condition: "state", entity: sp + "sensor_temp_zuluft", state_not: "Keine" },
              { condition: "state", entity: sp + "sensor_feuchte_zuluft", state_not: "Keine" },
            ] }] }),
          tile("zutemp", [{ condition: "state", entity: sp + "sensor_temp_zuluft", state_not: "Keine" }]),
          tile("zuhum", [{ condition: "state", entity: sp + "sensor_feuchte_zuluft", state_not: "Keine" }]),
        ] };
      })(),
      { type: "grid", column_span: 2, cards: [
        sep("VPD-Map", "mdi:water-opacity"),
        vpdChart([a]),
        sep("Steuerung", "mdi:radar"),
        ...SHADOW.filter((k) => k !== "status").map((k) => {
          const eid = S + k;
          const label = k === "co2" ? "CO2" : k.charAt(0).toUpperCase() + k.slice(1);
          const selMap = { licht: "geraet_licht", undercanopy: "geraet_undercanopy",
            befeuchter: "geraet_befeuchter", entfeuchter: "geraet_entfeuchter",
            heizung: "geraet_heizung", klima: "geraet_klima",
            co2: "geraet_co2_ventil", abluft: "geraet_abluft",
            ventilator: "geraet_ventilator", umluft: "geraet_umluft" };
          const selSt = hass.states[sp + selMap[k]];
          const real = selSt && selSt.state && selSt.state !== "Keine" ? selSt.state : null;
          const c = { type: "custom:bubble-card", card_type: "button",
            button_type: "name", entity: eid, name: label,
            icon: shadowIcons[k], card_layout: "large",
            tap_action: { action: "more-info" },
            visibility: [{ condition: "state",
              entity: wp + "vorhanden_" + (k === "co2" ? "co2" : k), state: "on" }] };
          if (real) {
            const subs = [];
            let extraCss = "";
            if (k === "entfeuchter") {
              const tankSt = hass.states[sp + "sensor_tank"];
              const tankEid = (tankSt && tankSt.state && tankSt.state !== "Keine")
                ? tankSt.state : null;
              let sIdx = 0, fIdx = 0;
              const stufeSt = hass.states[sp + "stufe_entfeuchter"];
              if (stufeSt && stufeSt.state && stufeSt.state !== "Keine") {
                subs.push({ entity: stufeSt.state, icon: "mdi:fan",
                  show_state: true, show_background: true,
                  tap_action: { action: "more-info" } });
                sIdx = subs.length;
              }
              const gsens = hass.states[sp + "sensor_entfeuchter"];
              if (gsens && gsens.state && gsens.state !== "Keine") {
                subs.push({ entity: gsens.state,
                  icon: "mdi:water-percent", show_state: true,
                  show_background: true, tap_action: { action: "more-info" } });
                fIdx = subs.length;
                extraCss +=
                  ".bubble-sub-button-" + fIdx + " { background-color: #3b82f6 !important; }\n" +
                  ".bubble-sub-button-" + fIdx + " ha-icon { color: #fff !important; }\n";
              }
              if (tankEid) {
                // Tank voll: Stufe+Feuchte ausblenden, roten "Tank Voll!" zeigen
                subs.push({ entity: tankEid, name: "Tank Voll!",
                  show_name: true, icon: "mdi:cup-water",
                  show_background: true, tap_action: { action: "more-info" } });
                const tIdx = subs.length;
                const normale = [sIdx, fIdx].filter(Boolean)
                  .map((i) => ".bubble-sub-button-" + i).join(", ");
                if (normale)
                  extraCss += normale + " { display: {{ 'none' if is_state('" +
                    tankEid + "','on') else 'flex' }} !important; }\n";
                extraCss +=
                  ".bubble-sub-button-" + tIdx + " { display: {{ 'flex' if is_state('" +
                  tankEid + "','on') else 'none' }} !important; " +
                  "background-color: #dc2626 !important; }\n" +
                  ".bubble-sub-button-" + tIdx + ", .bubble-sub-button-" + tIdx +
                  " ha-icon { color: #fff !important; }\n";
              }
            }
            if (k === "undercanopy") {
              // Ist-Helligkeit (gelb wenn LED an, rot wenn aus);
              // Tap oeffnet den Zielhelligkeits-Slider
              subs.push({ entity: "sensor.controlos_" + s + "_data_uc_helligkeit",
                icon: "mdi:brightness-6", show_state: true,
                show_background: true,
                tap_action: { action: "navigate",
                  navigation_path: "#uc-" + s } });
              const hIdx = subs.length;
              extraCss +=
                ".bubble-sub-button-" + hIdx + " { background-color: {{ '#f59e0b' if is_state('" +
                real + "','on') else '#dc2626' }} !important; }\n" +
                ".bubble-sub-button-" + hIdx + " ha-icon { color: #fff !important; }\n";
            }
            if (k === "klima") {
              subs.push({ entity: real, icon: "mdi:thermostat",
                show_state: true, show_background: true,
                tap_action: { action: "more-info" } });
              subs.push({ entity: real, icon: "mdi:thermometer",
                show_attribute: true, attribute: "current_temperature",
                show_background: true, tap_action: { action: "more-info" } });
              // Modus: Blau=Kühlen, Gelb=Auto, Rot=Heizen, sonst dunkel
              extraCss +=
                ".bubble-sub-button-1 { background-color: {{ '#3b82f6' if is_state('" + real + "','cool') " +
                "else ('#f59e0b' if is_state('" + real + "','auto') " +
                "else ('#ef4444' if is_state('" + real + "','heat') else '#3a3a3e')) }} !important; }\n" +
                ".bubble-sub-button-1 ha-icon { color: #fff !important; }\n" +
                // Ist-Temp: Blau, aber Rot sobald ueber Ziel+Toleranz
                ".bubble-sub-button-2 { background-color: {{ '#ef4444' " +
                "if (state_attr('" + real + "','current_temperature')|float(0)) > " +
                "((states('" + D + "ziel_temp')|float(99)) + (states('number.controlos_" + s + "_temp_toleranz')|float(0))) " +
                "else '#3b82f6' }} !important; }\n" +
                ".bubble-sub-button-2 ha-icon { color: #fff !important; }\n";
            }
            // Power-Button einheitlich als letzter Sub-Button (ganz rechts)
            subs.push({ entity: real, icon: "mdi:power",
              show_background: true, tap_action: { action: "more-info" } });
            c.sub_button = subs;
            const pIdx = subs.length;
            c.card_mod = { style: extraCss +
              ".bubble-sub-button-" + pIdx + " { background-color: {{ '#dc2626' if states('" +
              real + "') in ['off','unavailable','unknown'] else '#16a34a' }} !important; }\n" +
              ".bubble-sub-button-" + pIdx + " ha-icon { color: #fff !important; }\n" };
          }
          return applyDesign(c);
        }),
        // Standalone-Pop-up (Bubble v3.2): Inhalt IN der Karte verschachtelt
        { type: "custom:bubble-card", card_type: "pop-up",
          name: "Undercanopy Helligkeit", icon: "mdi:brightness-6",
          hash: "#uc-" + s,
          cards: [
            bslider("number.controlos_" + s + "_licht_helligkeit", "Zielhelligkeit"),
            bstate(D + "uc_helligkeit", "Ist-Helligkeit", "mdi:brightness-6"),
          ] },
      ] },
    ] };
}

function kalenderView(a) {
  const s = slug(a.title);
  const G = "sensor.controlos_" + s + "_";
  const diary =
    "{% set h = state_attr('" + G + "grow_tag','phasen_historie') or [] %}\n" +
    "{% set gs = states('date.controlos_" + s + "_grow_start') %}\n" +
    "**Grow-Start:** {{ gs }}\n\n" +
    "{% if h %}{% for e in h %}" +
    "- **Tag {{ (((as_timestamp(e.start) - as_timestamp(gs)) / 86400) | round(0,'floor') | int) + 1 }}** " +
    "({{ e.start }}) → **{{ e.phase }}**\n" +
    "{% endfor %}{% else %}_Noch keine Phasenwechsel aufgezeichnet._{% endif %}";
  return { title: a.title + " · Grow-Kalender", path: "grow-kalender-" + s,
    icon: "mdi:calendar-text", subview: true, theme: THEME,
    type: "sections", max_columns: 2, sections: [
      { type: "grid", column_span: 2, cards: [
        sep("Kalender", "mdi:calendar-month"),
        { type: "calendar", initial_view: "dayGridMonth",
          entities: ["calendar.controlos_" + s + "_kalender"],
          grid_options: { columns: "full", rows: 6 } },
      ] },
      { type: "grid", cards: [
        sep("Phasen-Tagebuch", "mdi:book-open-variant"),
        { type: "entities", entities: [
          { entity: G + "grow_tag", name: "Grow-Tag" },
          { entity: G + "phase_tag", name: "Tag in aktueller Phase" }] },
        { type: "markdown", content: diary },
      ] },
      { type: "grid", cards: [
        sep("Notizen & Erinnerungen", "mdi:notebook-edit"),
        { type: "todo-list", entity: "todo.controlos_" + s + "_notizen",
          hide_completed: false },
        { type: "markdown", content:
          "Einträge mit **Fälligkeitsdatum** werden als Push gemeldet — Häufigkeit per Steuerwort " +
          "im Titel oder der Beschreibung:\n\n" +
          "- *(ohne)* → **einmalig** am Fälligkeitstag\n" +
          "- `!täglich` → jeden Tag, bis abgehakt\n" +
          "- `!wöchentlich` → alle 7 Tage\n" +
          "- `!stumm` → keine Benachrichtigung" },
      ] },
    ] };
}

/* Einstellungs-Hub: Grundlegendes + Navigation zu den Themen-Unterseiten. */
function configView(a) {
  const s = slug(a.title);
  const sp = "select.controlos_" + s + "_";
  const wp = "switch.controlos_" + s + "_", bp = "button.controlos_" + s + "_";
  const nav = (titel, untertitel, icon, farbe, pfad) => ({
    type: "custom:mushroom-template-card", icon, icon_color: farbe,
    primary: titel, secondary: untertitel,
    tap_action: { action: "navigate",
      navigation_path: "/" + DASH + "/bereich-" + s + "-" + pfad } });
  return { title: a.title + " · Einstellungen", path: "bereich-" + s + "-config",
    icon: "mdi:cog", subview: true, theme: THEME,
    type: "sections", max_columns: 2, sections: [
      { type: "grid", cards: [
        sep("Bereich", "mdi:sprout"),
        bsw(wp + "aktiv", a.title + " Aktiv", "mdi:power"),
        bsel(sp + "betriebsmodus", "Betriebsmodus (Monitor/Steuern)"),
        sep("Wuchsphase & Grow", "mdi:sprout-outline"),
        bsel(sp + "grow_typ", "Grow-Typ (Photoperiodisch/Autoflowering)"),
        bsel(sp + "wuchsphase", "Aktuelle Phase"),
        { type: "entities", entities: [
          { entity: "date.controlos_" + s + "_grow_start", name: "Grow-Startdatum" },
          { entity: "date.controlos_" + s + "_bluete_start", name: "Blüte-Startdatum" },
          { entity: bp + "phase_override_speichern", name: "Phase für diesen Bereich speichern" },
          { entity: bp + "phase_override_reset", name: "Phase auf Standard zurücksetzen" }] },
      ] },
      { type: "grid", cards: [
        sep("Einstellungen", "mdi:tune"),
        nav("Klima-Regelung", "Ziele, Steuermodi, AC, CO2, Lüfter, KI", "mdi:thermostat", "red", "klima"),
        nav("Licht", "Zeitplan, Zyklus, Sonnenauf-/-untergang", "mdi:lightbulb-on", "amber", "licht"),
        nav("Geräte & Sensoren", "Zuordnung, Dimmer, Quellen", "mdi:power-plug", "blue", "geraete"),
        nav("System & Benachrichtigungen", "Watchdog, Speicher, Push", "mdi:bell-cog", "teal", "system"),
        { type: "custom:controlos-delete-button", entry_id: a.entry_id,
          area_name: a.title, redirect: "/" + DASH + "/einstellungen" },
      ] },
    ] };
}

/* Unterseite: Klima-Regelung */
function klimaView(a) {
  const s = slug(a.title);
  const np = "number.controlos_" + s + "_", sp = "select.controlos_" + s + "_";
  const wp = "switch.controlos_" + s + "_";
  const cOn = (ent) => ({ condition: "state", entity: ent, state: "on" });
  const cEq = (ent, st) => ({ condition: "state", entity: ent, state: st });
  const V = (card, ...conds) => Object.assign(card, { visibility: conds });
  const co2vis = { visibility: [cOn(wp + "vorhanden_co2")] };
  return { title: a.title + " · Klima", path: "bereich-" + s + "-klima",
    icon: "mdi:thermostat", subview: true, theme: THEME,
    type: "sections", max_columns: 4, sections: [
      { type: "grid", cards: [
        sep("Ziele & Toleranzen (aktuelle Phase)", "mdi:target"),
        ...NUM_CLIMATE.map((k) => bslider(np + k, null)),
        bslider(np + "blatt_offset", "Blatt-Offset (ohne Blattsensor)"),
      ] },
      { type: "grid", cards: [
        sep("Steuermodi", "mdi:cog"),
        bsel(sp + "klima_modus", "Klima Modus"),
        bsel(sp + "system_modus", "System Modus"),
        V(bsel(sp + "klima_steuermodus", null), cOn(wp + "vorhanden_klima")),
        V(bsel(sp + "entfeuchter_steuermodus", null), cOn(wp + "vorhanden_entfeuchter")),
        bsel(sp + "prio", null),
        sep("Optionen", "mdi:toggle-switch"),
        ...SW_OPTIONS.map((k) => bsw(wp + k, null)),
        sep("KI-Bias (nur VPD, tagsüber)", "mdi:brain"),
        bslider(np + "vpd_bias_tag", "VPD-Bias Tag (gelernt)"),
      ] },
      { type: "grid", cards: [
        V(sep("Klimaanlage (AC)", "mdi:air-conditioner"), cOn(wp + "vorhanden_klima")),
        V(bslider(np + "klima_ziel_tag", "AC-Ziel Tag"), cOn(wp + "vorhanden_klima")),
        V(bslider(np + "klima_ziel_nacht", "AC-Ziel Nacht"), cOn(wp + "vorhanden_klima")),
        V(bsel(sp + "klima_modus_tag", "AC-Modus Tag"), cOn(wp + "vorhanden_klima")),
        V(bsel(sp + "klima_modus_nacht", "AC-Modus Nacht"), cOn(wp + "vorhanden_klima")),
        V(bsel(sp + "klima_fan_tag", "AC-Lüfter Tag"), cOn(wp + "vorhanden_klima")),
        V(bsel(sp + "klima_fan_nacht", "AC-Lüfter Nacht"), cOn(wp + "vorhanden_klima")),
        V(bslider(np + "klima_hybrid_gewicht", "Hybrid-Gewicht (Area↔AC-Sensor)"),
          cOn(wp + "vorhanden_klima"), cEq(sp + "klima_steuermodus", "Hybrid")),
        Object.assign(sep("CO2-Steuerung", "mdi:molecule-co2"), co2vis),
        Object.assign(bsw(wp + "co2_automatik", "CO2 Automatik", "mdi:robot-outline"), co2vis),
        Object.assign(bsel(sp + "co2_betrieb_modus", "Betriebsart (Dauer/Intervall)"), co2vis),
        V(bslider(np + "co2_dauer_min", "Dosier-Dauer"),
          cOn(wp + "vorhanden_co2"), cEq(sp + "co2_betrieb_modus", "Intervall")),
        V(bslider(np + "co2_intervall_min", "Intervall"),
          cOn(wp + "vorhanden_co2"), cEq(sp + "co2_betrieb_modus", "Intervall")),
        Object.assign(bslider(np + "co2_max_laufzeit_min", "Max-Laufzeit (Schutz)"), co2vis),
      ] },
      { type: "grid", cards: [
        V(sep("Entfeuchter (Autonom/Hybrid)", "mdi:air-humidifier-off"),
          cOn(wp + "vorhanden_entfeuchter")),
        V(bslider(np + "entfeuchter_autonom_ziel_tag", "Autonom-Ziel Tag"),
          cOn(wp + "vorhanden_entfeuchter"), cEq(sp + "entfeuchter_steuermodus", "Autonom")),
        V(bslider(np + "entfeuchter_autonom_ziel_nacht", "Autonom-Ziel Nacht"),
          cOn(wp + "vorhanden_entfeuchter"), cEq(sp + "entfeuchter_steuermodus", "Autonom")),
        V(bslider(np + "entfeuchter_hybrid_gewicht", "Hybrid-Gewicht (Area↔Geräte-Sensor)"),
          cOn(wp + "vorhanden_entfeuchter"), cEq(sp + "entfeuchter_steuermodus", "Hybrid")),
        V(sep("Abluft", "mdi:fan"), cOn(wp + "vorhanden_abluft")),
        V(bsel(sp + "abluft_modus", "Abluft-Modus"), cOn(wp + "vorhanden_abluft")),
        V(bslider(np + "abluft_backup_temp", "Backup ab Temp"), cOn(wp + "vorhanden_abluft")),
        V(bslider(np + "abluft_backup_hum", "Backup ab Feuchte"), cOn(wp + "vorhanden_abluft")),
        V(bslider(np + "abluft_backup_vpd", "Backup ab VPD"), cOn(wp + "vorhanden_abluft")),
        V(bslider(np + "abluft_backup_co2", "Backup ab CO2"), cOn(wp + "vorhanden_abluft")),
        V(bslider(np + "abluft_backup_disarm_min", "Backup-Nachlauf"), cOn(wp + "vorhanden_abluft")),
        V(sep("Ventilator", "mdi:fan-chevron-up"), cOn(wp + "vorhanden_ventilator")),
        V(bsel(sp + "ventilator_modus", "Ventilator-Modus"), cOn(wp + "vorhanden_ventilator")),
        V(bslider(np + "ventilator_speed", "Ventilator-Stufe"), cOn(wp + "vorhanden_ventilator")),
        V(bslider(np + "ventilator_ein_min", "Ventilator Ein-Dauer"),
          cOn(wp + "vorhanden_ventilator"), cEq(sp + "ventilator_modus", "Intervall")),
        V(bslider(np + "ventilator_intervall_min", "Ventilator Intervall"),
          cOn(wp + "vorhanden_ventilator"), cEq(sp + "ventilator_modus", "Intervall")),
        V(sep("Umluft", "mdi:weather-windy"), cOn(wp + "vorhanden_umluft")),
        V(bsel(sp + "umluft_modus", "Umluft-Modus"), cOn(wp + "vorhanden_umluft")),
        V(bslider(np + "umluft_ein_min", "Umluft Ein-Dauer"),
          cOn(wp + "vorhanden_umluft"), cEq(sp + "umluft_modus", "Intervall")),
        V(bslider(np + "umluft_intervall_min", "Umluft Intervall"),
          cOn(wp + "vorhanden_umluft"), cEq(sp + "umluft_modus", "Intervall")),
        bslider(np + "dimm_mindestleistung", "Dimm-Mindestleistung"),
      ] },
    ] };
}

/* Unterseite: Licht */
function lichtView(a) {
  const s = slug(a.title);
  const np = "number.controlos_" + s + "_", sp = "select.controlos_" + s + "_";
  const wp = "switch.controlos_" + s + "_";
  const lichtVis = { visibility: [{ condition: "state",
    entity: wp + "vorhanden_licht", state: "on" }] };
  const LV = (c) => Object.assign(c, lichtVis);
  return { title: a.title + " · Licht", path: "bereich-" + s + "-licht",
    icon: "mdi:lightbulb-on", subview: true, theme: THEME,
    type: "sections", max_columns: 2, sections: [
      { type: "grid", cards: [
        { type: "markdown", content: "_Licht ist als „nicht vorhanden“ markiert — unter **Geräte & Sensoren** aktivieren._",
          visibility: [{ condition: "state", entity: wp + "vorhanden_licht", state_not: "on" }] },
        LV(sep("Licht-Zeitplan", "mdi:lightbulb-on-outline")),
        LV(bsel(sp + "licht_zyklus", "Lichtzyklus (Ende folgt automatisch)")),
        LV({ type: "entities", entities: [
          { entity: "time.controlos_" + s + "_licht_start", name: "Licht an um" },
          { entity: "time.controlos_" + s + "_licht_ende", name: "Licht aus um (bei Zyklus automatisch)" }] }),
        LV(bslider(np + "licht_helligkeit", "Zielhelligkeit (dimmbar)")),
      ] },
      { type: "grid", cards: [
        LV(sep("Sonnenauf-/-untergang (dimmbar)", "mdi:weather-sunset")),
        LV(bsel(sp + "licht_modus", "Schaltmodus (An/Aus oder Rampe)")),
        LV(bslider(np + "sunrise_dauer", "Sonnenaufgang Dauer")),
        LV(bslider(np + "sunset_dauer", "Sonnenuntergang Dauer")),
        Object.assign(
          bsw(wp + "undercanopy_als_sonne", "Undercanopy als Sonnenauf-/-untergang", "mdi:weather-sunset"),
          { visibility: [{ condition: "state",
            entity: wp + "vorhanden_undercanopy", state: "on" }] }),
      ] },
    ] };
}

/* Unterseite: Geräte & Sensoren */
function geraeteView(a) {
  const s = slug(a.title);
  const sp = "select.controlos_" + s + "_", wp = "switch.controlos_" + s + "_";
  const DIMMBAR = ["befeuchter", "entfeuchter", "heizung", "abluft",
    "licht", "undercanopy", "ventilator"];
  return { title: a.title + " · Geräte", path: "bereich-" + s + "-geraete",
    icon: "mdi:power-plug", subview: true, theme: THEME,
    type: "sections", max_columns: 4, sections: [
      { type: "grid", cards: [
        sep("Geräte vorhanden?", "mdi:devices"),
        ...SW_VORHANDEN.map((k) => bsw(wp + k, null)),
      ] },
      { type: "grid", cards: [
        sep("Geräte-Zuordnung", "mdi:power-plug"),
        ...SEL_GERAET.map((k) => Object.assign(bsel(sp + k, null),
          { visibility: [{ condition: "state",
            entity: wp + "vorhanden_" + k.replace("geraet_", "").replace("co2_ventil", "co2"),
            state: "on" }] })),
      ] },
      { type: "grid", cards: [
        sep("Dimmbar?", "mdi:brightness-6"),
        ...DIMMBAR.map((d) => Object.assign(bsw(wp + "dimmbar_" + d, null),
          { visibility: [{ condition: "state",
            entity: wp + "vorhanden_" + d, state: "on" }] })),
        sep("Dual-Geräte (können Gegenteil)", "mdi:swap-horizontal"),
        bsw(wp + "dual_befeuchter", null),
        bsw(wp + "dual_entfeuchter", null),
      ] },
      { type: "grid", cards: [
        sep("Dimmer-Zuordnung", "mdi:tune-vertical"),
        ...DIMMBAR.map((d) => Object.assign(bsel(sp + "dimmer_" + d, null),
          { visibility: [{ condition: "state",
            entity: wp + "dimmbar_" + d, state: "on" }] })),
        sep("Sensoren (Quellen)", "mdi:access-point"),
        ...SEL_SENSOR.map((k) => bsel(sp + k, null)),
        bsel(sp + "sensor_entfeuchter", "Geräte-Feuchtesensor (Entfeuchter)"),
        bsel(sp + "sensor_tank", "Tank-Sensor (voll)"),
        bsel(sp + "stufe_entfeuchter", "Lüfterstufe Entfeuchter"),
      ] },
    ] };
}

/* Unterseite: System & Benachrichtigungen */
function systemView(a) {
  const s = slug(a.title);
  const np = "number.controlos_" + s + "_", sp = "select.controlos_" + s + "_";
  const wp = "switch.controlos_" + s + "_";
  return { title: a.title + " · System", path: "bereich-" + s + "-system",
    icon: "mdi:bell-cog", subview: true, theme: THEME,
    type: "sections", max_columns: 2, sections: [
      { type: "grid", cards: [
        sep("Sensor-Watchdog", "mdi:restart-alert"),
        bsw(wp + "mqtt_watchdog", "MQTT-Broker neu starten bei Sensor-Ausfall", "mdi:restart-alert"),
        bslider(np + "mqtt_watchdog_min", "Nach X Minuten ohne Daten"),
        sep("Speicher & KI", "mdi:database"),
        bsel(sp + "speicherzeit", "Speicherzeit Messdaten (KI-Archiv)"),
        bstate("sensor.controlos_" + s + "_ki_status", "KI Status", "mdi:brain"),
      ] },
      { type: "grid", cards: [
        sep("Benachrichtigungen", "mdi:bell"),
        bsw(wp + "benachrichtigungen", "Push + HA-Meldung (Tank, CO2, Sensor, Notizen)", "mdi:bell"),
        bsel(sp + "benachrichtigung_ziel", "Ziel-Gerät (Push)"),
        bslider(np + "co2_alarm_max", "CO2-Alarm ab"),
      ] },
    ] };
}

function stdPhaseView() {
  return { title: "Phasen-Standard", path: "phasen-standard",
    icon: "mdi:sprout-outline", subview: true, theme: THEME,
    type: "sections", max_columns: 4, sections: [{ type: "grid", cards: [
      sep("Wachstumsphasen · Standard (alle Bereiche)", "mdi:sprout-outline"),
      { type: "markdown", content: "Änderungen speichern **automatisch** in die gewählte Phase. Bereiche mit eigenem Override behalten ihre Werte." },
      bsel("select.controlos_std_phase_editor", "Phase wählen (Standard bearbeiten)"),
      ...NUM_CLIMATE.map((k) => bslider("number.controlos_std_" + k, null)),
    ] }] };
}

class ControlosDashboardStrategy {
  static async generate(config, hass) {
    readDesign(hass);
    const areas = findAreas(hass);
    const views = [settingsView(areas)];
    for (const a of areas) views.push(monitorView(a, hass));
    for (const a of areas) views.push(graphenView(a));
    for (const a of areas) views.push(kalenderView(a));
    for (const a of areas) views.push(configView(a));
    for (const a of areas) views.push(klimaView(a));
    for (const a of areas) views.push(lichtView(a));
    for (const a of areas) views.push(geraeteView(a));
    for (const a of areas) views.push(systemView(a));
    views.push(stdPhaseView());
    return { title: "ControlOS", views,
      kiosk_mode: { hide_search: true, hide_assistant: true,
        hide_edit_dashboard: true, hide_overflow: true, hide_refresh: true,
        hide_unused_entities: true, hide_reload_resources: true } };
  }
}
customElements.define("ll-strategy-dashboard-controlos", ControlosDashboardStrategy);

/* Lösch-Karte: löscht den Bereich + navigiert zurück zu den Einstellungen. */
class ControlosDeleteButton extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entry_id) throw new Error("entry_id fehlt");
    this._config = config;
  }
  set hass(h) { this._hass = h; if (!this._rendered) this._render(); }
  _render() {
    this._rendered = true;
    this._confirming = false;
    this.card = document.createElement("ha-card");
    this.card.style.cssText = "padding:16px;text-align:center;";
    this.appendChild(this.card);
    this._paint();
  }
  _paint() {
    if (!this._confirming) {
      this.card.style.cursor = "pointer";
      this.card.innerHTML =
        '<ha-icon icon="mdi:delete-alert" style="--mdc-icon-size:34px;color:#ef4444;"></ha-icon>' +
        '<div style="margin-top:6px;font-weight:600;color:#ef4444;">Bereich löschen</div>';
      this.card.onclick = () => { this._confirming = true; this._paint(); };
    } else {
      this.card.style.cursor = "default";
      this.card.onclick = null;
      this.card.innerHTML =
        '<div style="font-weight:600;margin-bottom:12px;">„' + (this._config.area_name || "") +
        '“ wirklich löschen? Alle Einstellungen gehen verloren.</div>' +
        '<div style="display:flex;gap:12px;justify-content:center;">' +
        '<mwc-button raised id="yes" style="--mdc-theme-primary:#ef4444;">Ja, löschen</mwc-button>' +
        '<mwc-button id="no">Abbrechen</mwc-button></div>';
      this.card.querySelector("#yes").addEventListener("click", () => this._del());
      this.card.querySelector("#no").addEventListener("click", () => { this._confirming = false; this._paint(); });
    }
  }
  async _del() {
    this.card.innerHTML = '<div style="padding:8px;">Lösche „' + (this._config.area_name || "") + '“ …</div>';
    try {
      await this._hass.callService("controlos", "remove_area", { entry_id: this._config.entry_id });
    } catch (e) {
      this.card.innerHTML = '<div style="color:#ef4444;padding:8px;">Löschen fehlgeschlagen: ' + e + '</div>';
      return;
    }
    window.location.href = this._config.redirect || ("/" + DASH + "/einstellungen");
  }
  getCardSize() { return 1; }
}
customElements.define("controlos-delete-button", ControlosDeleteButton);

console.info("%c ControlOS Dashboard v6 (Altsystem-Look) geladen", "color:#16a34a");
