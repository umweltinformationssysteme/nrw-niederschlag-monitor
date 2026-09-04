#!/usr/bin/env python3
"""
NRW Niederschlag Monitor
========================
Lädt stündliche Niederschlagsdaten vom Hochwasserportal NRW,
berechnet die 24h-Summe je Station und schreibt das Ergebnis als JSON.

Quelle: https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip
"""

import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
DATA_URL = "https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip"
OUTPUT_FILE = Path("output/niederschlag_nrw.json")

# Zeitzone MEZ/MESZ (UTC+1 wie in den Quelldaten)
TZ_NRW = timezone(timedelta(hours=1))

# Schwellenwert in Stunden: ab wann gilt ein Wert als „nicht aktuell"
MAX_AGE_HOURS = 3

# ---------------------------------------------------------------------------
# Niederschlagsklassen – Reihenfolge: höchster Schwellenwert zuerst
# ---------------------------------------------------------------------------
KLASSEN = [
    (100.0, "> 100 mm",              "#4D090D"),
    ( 80.0, "> 80 mm",               "#76180A"),
    ( 60.0, "> 60 mm",               "#E4141F"),
    ( 40.0, "> 40 mm",               "#CF3ACE"),
    ( 25.0, "> 25 mm",               "#8D39C3"),
    ( 15.0, "> 15 mm",               "#0721F0"),
    ( 10.0, "> 10 mm",               "#229FDD"),
    (  5.0, "> 5 mm",                "#1BDAD8"),
    (  2.0, "> 2 mm",                "#47C774"),
    (  1.0, "> 1 mm",                "#9CD433"),
    (  0.1, "> 0,1 mm",              "#FDFB6E"),
    (  0.0, "Kein Niederschlag",     "#FFFFFF"),
]
KLASSE_INAKTIV    = ("zurzeit inaktive Station", "#FFE4E1")
KLASSE_VERALTET   = ("nicht aktuelle Werte",     "#808080")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def lade_zip_von_url(url: str) -> bytes:
    """Lädt das ZIP-Archiv vom Hochwasserportal und gibt die rohen Bytes zurück."""
    log.info("Lade Daten von %s …", url)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    log.info("Download abgeschlossen (%.1f MB)", len(resp.content) / 1_048_576)
    return resp.content


def lies_csv_aus_zip(zip_bytes: bytes, dateiname: str, sep: str = ";") -> pd.DataFrame:
    """Liest eine benannte CSV-Datei aus dem ZIP-Archiv."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        treffer = [n for n in names if n.lower().endswith(dateiname.lower())]
        if not treffer:
            raise FileNotFoundError(
                f"'{dateiname}' nicht im ZIP gefunden. Vorhandene Dateien: {names}"
            )
        log.info("Lese '%s' aus ZIP …", treffer[0])
        with zf.open(treffer[0]) as f:
            return pd.read_csv(f, sep=sep, encoding="utf-8-sig", low_memory=False)


def klassifiziere(summe_mm: float | None, ist_inaktiv: bool, ist_veraltet: bool):
    """Gibt (klasse_text, farbcode) zurück."""
    if ist_inaktiv:
        return KLASSE_INAKTIV
    if ist_veraltet:
        return KLASSE_VERALTET
    if summe_mm is None:
        return KLASSE_INAKTIV
    for schwellenwert, label, farbe in KLASSEN:
        if summe_mm > schwellenwert:
            return label, farbe
    return KLASSEN[-1][1], KLASSEN[-1][2]  # "Kein Niederschlag"


# ---------------------------------------------------------------------------
# Kernverarbeitung
# ---------------------------------------------------------------------------

def verarbeite(zip_bytes: bytes) -> list[dict]:
    """Liest Messwerte + Stationen, berechnet 24h-Summen, gibt Ergebnisliste zurück."""

    # -- Stationsdaten -------------------------------------------------------
    stationen = lies_csv_aus_zip(
        zip_bytes,
        "OpenHygon-Niederschlag-Stationen_EPSG4326.txt",
    )
    stationen.columns = stationen.columns.str.strip()
    stationen = stationen.rename(columns={
        "station_no":        "station_no",
        "station_name":      "name",
        "station_latitude":  "lat",
        "station_longitude": "lon",
    })
    stationen["station_no"] = stationen["station_no"].astype(str).str.strip()
    # Duplikate entfernen: vollständigen Namen bevorzugen (letzter Eintrag)
    stationen = stationen.drop_duplicates(subset="station_no", keep="last")
    station_lookup: dict[str, dict] = (
        stationen[["station_no", "name", "lat", "lon"]]
        .set_index("station_no")
        .to_dict("index")
    )
    log.info("%d Stationen geladen.", len(station_lookup))

    # -- Messwerte -----------------------------------------------------------
    messungen = lies_csv_aus_zip(zip_bytes, "niederschlag.txt")
    messungen.columns = messungen.columns.str.strip()
    messungen = messungen.rename(columns={
        "station_no": "station_no",
        "time":       "time",
        # dritter Spaltenkopf variiert leicht (z. B. "value(mm/h)")
    })
    wert_spalte = [c for c in messungen.columns if c not in ("station_no", "time")][0]
    messungen = messungen.rename(columns={wert_spalte: "wert"})

    messungen["station_no"] = messungen["station_no"].astype(str).str.strip()
    messungen["wert"] = pd.to_numeric(messungen["wert"], errors="coerce")

    # Zeitstempel parsen – Zeitzone explizit setzen (Quelldaten: +01:00)
    messungen["ts"] = pd.to_datetime(
        messungen["time"], utc=False, errors="coerce"
    )
    # Zeitzone normalisieren (manche Zeilen könnten UTC+2 im Sommer enthalten)
    messungen = messungen.dropna(subset=["ts"])
    messungen["ts"] = messungen["ts"].apply(
        lambda t: t if t.tzinfo else t.replace(tzinfo=TZ_NRW)
    )
    log.info("%d Messzeitreihen-Zeilen geladen.", len(messungen))

    # -- Referenzzeitpunkt: neuester vorhandener Zeitstempel im Datensatz ----
    jetzt = messungen["ts"].max()
    start_24h = jetzt - timedelta(hours=24)
    log.info(
        "Auswertungsfenster: %s  →  %s",
        start_24h.isoformat(), jetzt.isoformat(),
    )

    # -- 24h-Fenster filtern -------------------------------------------------
    fenster = messungen[messungen["ts"] > start_24h].copy()

    # -- Je Station aggregieren ----------------------------------------------
    ergebnisse: list[dict] = []

    for station_id, info in station_lookup.items():
        df_s = fenster[fenster["station_no"] == station_id]

        if df_s.empty:
            # Station hat keine aktuellen Daten → inaktiv
            klasse, farbe = KLASSE_INAKTIV
            ergebnis = {
                "station_no":           station_id,
                "name":                 info["name"],
                "lat":                  info["lat"],
                "lon":                  info["lon"],
                "summe_mm_24h":         None,
                "letzter_messwert_datum": None,
                "letzter_messwert_uhrzeit": None,
                "klasse":               klasse,
                "farbcode":             farbe,
            }
            ergebnisse.append(ergebnis)
            continue

        # Letzter Zeitstempel dieser Station (auch außerhalb des 24h-Fensters)
        alle_station = messungen[messungen["station_no"] == station_id]
        letzter_ts = alle_station["ts"].max()

        # Veraltet-Prüfung: mehr als MAX_AGE_HOURS seit letzter Messung
        alter_stunden = (jetzt - letzter_ts).total_seconds() / 3600
        ist_veraltet = alter_stunden > MAX_AGE_HOURS

        # 24h-Summe (nur nicht-NaN Werte addieren)
        summe = df_s["wert"].sum(min_count=1)  # None wenn alle NaN
        if pd.isna(summe):
            summe = None

        klasse, farbe = klassifiziere(summe, ist_inaktiv=False, ist_veraltet=ist_veraltet)

        ergebnis = {
            "station_no":               station_id,
            "name":                     info["name"],
            "lat":                      float(info["lat"]),
            "lon":                      float(info["lon"]),
            "summe_mm_24h":             round(float(summe), 2) if summe is not None else None,
            "letzter_messwert_datum":   letzter_ts.strftime("%Y-%m-%d"),
            "letzter_messwert_uhrzeit": letzter_ts.strftime("%H:%M"),
            "klasse":                   klasse,
            "farbcode":                 farbe,
        }
        ergebnisse.append(ergebnis)

    log.info("Auswertung abgeschlossen für %d Stationen.", len(ergebnisse))
    return ergebnisse


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def schreibe_json(ergebnisse: list[dict], pfad: Path) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    # Metadaten-Wrapper analog zum thermal-risk-index-Projekt
    payload = {
        "meta": {
            "quelle":        "Hochwasserportal NRW – Niederschlag",
            "url":           DATA_URL,
            "generiert_am":  datetime.now(tz=timezone.utc).isoformat(),
            "auswertung_24h_ab": (
                max(
                    (
                        datetime.fromisoformat(e["letzter_messwert_datum"]
                                               + "T" + e["letzter_messwert_uhrzeit"])
                        for e in ergebnisse
                        if e["letzter_messwert_datum"]
                    ),
                    default=datetime.now(tz=timezone.utc),
                ) - timedelta(hours=24)
            ).isoformat(),
            "anzahl_stationen": len(ergebnisse),
        },
        "stationen": ergebnisse,
    }
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("JSON geschrieben: %s (%d Stationen)", pfad, len(ergebnisse))


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main() -> None:
    zip_bytes = lade_zip_von_url(DATA_URL)
    ergebnisse = verarbeite(zip_bytes)
    schreibe_json(ergebnisse, OUTPUT_FILE)

    # Top-10 Stationen nach Niederschlag
    top10 = sorted(
        [e for e in ergebnisse if e["summe_mm_24h"] is not None],
        key=lambda x: x["summe_mm_24h"],
        reverse=True,
    )[:10]
    log.info("Top 10 Stationen (24h-Summe):")
    for i, s in enumerate(top10, 1):
        log.info(
            "  %2d. %-55s  %6.1f mm  %s",
            i, s["name"], s["summe_mm_24h"], s["klasse"],
        )


if __name__ == "__main__":
    main()
