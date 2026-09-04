#!/usr/bin/env python3
"""
NRW Niederschlag Monitor
========================
Lädt stündliche Niederschlagsdaten vom Hochwasserportal NRW,
berechnet die 24h-Summe je Station und schreibt das Ergebnis als JSON.

Quelle: https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip

Hinweis: Die Stationsdatei (OpenHygon-Niederschlag-Stationen_EPSG4326.txt)
ist NICHT im ZIP enthalten und liegt fest unter data/ im Repository.
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
DATA_URL      = "https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip"
OUTPUT_FILE   = Path("output/niederschlag_nrw.json")
# Stationsdatei liegt fest im Repo – ist NICHT im ZIP des Portals enthalten
STATIONS_FILE = Path("data/OpenHygon-Niederschlag-Stationen_EPSG4326.txt")

# Zeitzone MEZ/MESZ (UTC+1 wie in den Quelldaten)
TZ_NRW = timezone(timedelta(hours=1))

# Schwellenwert in Stunden: ab wann gilt ein Wert als „nicht aktuell"
MAX_AGE_HOURS = 3

# ---------------------------------------------------------------------------
# Niederschlagsklassen – Reihenfolge: höchster Schwellenwert zuerst
# ---------------------------------------------------------------------------
KLASSEN = [
    (100.0, "> 100 mm",          "#4D090D"),
    ( 80.0, "> 80 mm",           "#76180A"),
    ( 60.0, "> 60 mm",           "#E4141F"),
    ( 40.0, "> 40 mm",           "#CF3ACE"),
    ( 25.0, "> 25 mm",           "#8D39C3"),
    ( 15.0, "> 15 mm",           "#0721F0"),
    ( 10.0, "> 10 mm",           "#229FDD"),
    (  5.0, "> 5 mm",            "#1BDAD8"),
    (  2.0, "> 2 mm",            "#47C774"),
    (  1.0, "> 1 mm",            "#9CD433"),
    (  0.1, "> 0,1 mm",          "#FDFB6E"),
    (  0.0, "Kein Niederschlag", "#FFFFFF"),
]
KLASSE_INAKTIV  = ("zurzeit inaktive Station", "#FFE4E1")
KLASSE_VERALTET = ("nicht aktuelle Werte",     "#808080")

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


def lies_messungen_aus_zip(zip_bytes: bytes) -> pd.DataFrame:
    """Liest niederschlag.txt aus dem ZIP-Archiv."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        log.info("ZIP enthält: %s", names)
        treffer = [n for n in names if "niederschlag" in n.lower() and n.endswith(".txt")]
        if not treffer:
            raise FileNotFoundError(
                f"Keine Messwertdatei im ZIP gefunden. Vorhandene Dateien: {names}"
            )
        log.info("Lese '%s' aus ZIP …", treffer[0])
        with zf.open(treffer[0]) as f:
            return pd.read_csv(f, sep=";", encoding="utf-8-sig", low_memory=False,
                               names=["station_no", "time", "wert"], header=0)


def lade_stationen() -> dict:
    """Liest die Stationsdatei aus dem Repo (data/)."""
    if not STATIONS_FILE.exists():
        raise FileNotFoundError(
            f"Stationsdatei nicht gefunden: {STATIONS_FILE}\n"
            "Bitte die Datei 'OpenHygon-Niederschlag-Stationen_EPSG4326.txt' "
            "unter data/ im Repository ablegen."
        )
    df = pd.read_csv(STATIONS_FILE, sep=";", encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    df["station_no"] = df["station_no"].astype(str).str.strip()
    # Duplikate entfernen: vollständigen Namen bevorzugen (letzter Eintrag)
    df = df.drop_duplicates(subset="station_no", keep="last")
    log.info("%d Stationen aus %s geladen.", len(df), STATIONS_FILE)
    return df.set_index("station_no")[["station_name", "station_latitude", "station_longitude"]].to_dict("index")


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

    # -- Stationsdaten aus Repo ----------------------------------------------
    station_lookup = lade_stationen()

    # -- Messwerte aus ZIP ---------------------------------------------------
    messungen = lies_messungen_aus_zip(zip_bytes)
    messungen["station_no"] = messungen["station_no"].astype(str).str.strip()
    messungen["wert"] = pd.to_numeric(messungen["wert"], errors="coerce")
    messungen["ts"] = pd.to_datetime(messungen["time"], utc=False, errors="coerce")
    messungen = messungen.dropna(subset=["ts"])

    # Zeitzone sicherstellen
    messungen["ts"] = messungen["ts"].apply(
        lambda t: t if t.tzinfo else t.replace(tzinfo=TZ_NRW)
    )
    log.info("%d Messzeitreihen-Zeilen geladen.", len(messungen))

    # -- Referenzzeitpunkt ---------------------------------------------------
    jetzt     = messungen["ts"].max()
    start_24h = jetzt - timedelta(hours=24)
    log.info("Auswertungsfenster: %s  →  %s", start_24h.isoformat(), jetzt.isoformat())

    fenster = messungen[messungen["ts"] > start_24h].copy()

    # -- Je Station aggregieren ----------------------------------------------
    ergebnisse: list[dict] = []

    for station_id, info in station_lookup.items():
        df_s = fenster[fenster["station_no"] == station_id]
        alle  = messungen[messungen["station_no"] == station_id]

        if alle.empty:
            klasse, farbe = KLASSE_INAKTIV
            ergebnisse.append({
                "station_no": station_id,
                "name": info["station_name"],
                "lat":  float(info["station_latitude"]),
                "lon":  float(info["station_longitude"]),
                "summe_mm_24h": None,
                "letzter_messwert_datum":   None,
                "letzter_messwert_uhrzeit": None,
                "klasse": klasse, "farbcode": farbe,
            })
            continue

        letzter_ts    = alle["ts"].max()
        alter_stunden = (jetzt - letzter_ts).total_seconds() / 3600
        ist_veraltet  = alter_stunden > MAX_AGE_HOURS

        summe = df_s["wert"].sum(min_count=1) if not df_s.empty else None
        if pd.isna(summe):
            summe = None

        klasse, farbe = klassifiziere(summe, ist_inaktiv=False, ist_veraltet=ist_veraltet)

        ergebnisse.append({
            "station_no": station_id,
            "name":       info["station_name"],
            "lat":        float(info["station_latitude"]),
            "lon":        float(info["station_longitude"]),
            "summe_mm_24h": round(float(summe), 2) if summe is not None else None,
            "letzter_messwert_datum":   letzter_ts.strftime("%Y-%m-%d"),
            "letzter_messwert_uhrzeit": letzter_ts.strftime("%H:%M"),
            "klasse":   klasse,
            "farbcode": farbe,
        })

    log.info("Auswertung abgeschlossen für %d Stationen.", len(ergebnisse))
    return ergebnisse


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def schreibe_json(ergebnisse: list[dict], pfad: Path) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "quelle":           "Hochwasserportal NRW – Niederschlag",
            "url":              DATA_URL,
            "generiert_am":     datetime.now(tz=timezone.utc).isoformat(),
            "auswertung_24h_ab": (
                datetime.now(tz=timezone.utc) - timedelta(hours=24)
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
    zip_bytes  = lade_zip_von_url(DATA_URL)
    ergebnisse = verarbeite(zip_bytes)
    schreibe_json(ergebnisse, OUTPUT_FILE)

    top10 = sorted(
        [e for e in ergebnisse if e["summe_mm_24h"] is not None],
        key=lambda x: x["summe_mm_24h"], reverse=True,
    )[:10]
    log.info("Top 10 Stationen (24h-Summe):")
    for i, s in enumerate(top10, 1):
        log.info("  %2d. %-55s  %6.1f mm  %s", i, s["name"], s["summe_mm_24h"], s["klasse"])


if __name__ == "__main__":
    main()
