#!/usr/bin/env python3
"""
NRW Niederschlag Monitor
========================
Lädt stündliche Niederschlagsdaten vom Hochwasserportal NRW,
berechnet die 24h-Summe je Station und schreibt das Ergebnis als JSON.

Quelle: https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip

Hinweis: Die Stationsdatei (OpenHygon-Niederschlag-Stationen_EPSG4326.txt)
ist NICHT im ZIP enthalten und liegt fest unter data/ im Repository.

Änderungen gegenüber Originalversion:
  - Alle Timestamps werden intern auf UTC normiert (vermeidet Timezone-Vergleichsfehler)
  - ZIP-Bomb-Schutz: unkomprimierte Größe wird vor dem Entpacken geprüft
  - Download-Größenbeschränkung (max. 100 MB)
  - Pfad-Traversal-Schutz beim Lesen aus ZIP
  - meta.auswertung_24h_ab zeigt jetzt den tatsächlich verwendeten Startzeitpunkt
  - KLASSE_KEIN_NIEDERSCHLAG als eigene Konstante (kein Index-Zugriff auf KLASSEN[-1])
  - Stationen mit Messwerten außerhalb des Fensters werden als VERALTET statt INAKTIV markiert
  - Python-Version-Kompatibilität: Optional[float] statt float | None
  - Lat/Lon-Felder werden beim Einlesen validiert
  - Logging-Ausgabe bei korrupten Messwerten (alle NaN trotz vorhandener Zeilen)
"""

import io
import json
import logging
import posixpath
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
DATA_URL      = "https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip"
OUTPUT_FILE   = Path("output/niederschlag_nrw.json")
# Stationsdatei liegt fest im Repo – ist NICHT im ZIP des Portals enthalten
STATIONS_FILE = Path("data/OpenHygon-Niederschlag-Stationen_EPSG4326.txt")

# Alle Zeitvergleiche intern in UTC – Quelldaten kommen mit +01:00-Offset
UTC = timezone.utc

# Schwellenwert: ab wann gilt ein Stationswert als „nicht aktuell"
# Basis ist die echte Systemzeit (UTC) – nicht der neueste Zeitstempel im Datensatz
MAX_AGE_HOURS = 2

# Sicherheitsgrenzen für den Download
MAX_DOWNLOAD_BYTES     = 100 * 1024 * 1024   # 100 MB komprimiert
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024   # 500 MB unkomprimiert (ZIP-Bomb-Schutz)

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

# Explizite Konstanten statt Index-Zugriff auf KLASSEN[-1]
KLASSE_KEIN_NIEDERSCHLAG = ("Kein Niederschlag", "#FFFFFF")
KLASSE_INAKTIV           = ("zurzeit inaktive Station", "#FFE4E1")
KLASSE_VERALTET          = ("nicht aktuelle Werte",     "#808080")
KLASSE_DATENFEHLER       = ("Datenfehler",               "#C0C0C0")

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
    """
    Lädt das ZIP-Archiv vom Hochwasserportal und gibt die rohen Bytes zurück.
    Bricht ab, wenn die Antwort die Größenbeschränkung überschreitet.
    """
    log.info("Lade Daten von %s …", url)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    # Sicherheit: Größe der komprimierten Antwort prüfen
    if len(resp.content) > MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"Download zu groß: {len(resp.content) / 1_048_576:.1f} MB "
            f"(Limit: {MAX_DOWNLOAD_BYTES // 1_048_576} MB)"
        )

    log.info("Download abgeschlossen (%.1f MB)", len(resp.content) / 1_048_576)
    return resp.content


def lies_messungen_aus_zip(zip_bytes: bytes) -> pd.DataFrame:
    """
    Liest niederschlag.txt aus dem ZIP-Archiv.
    Prüft vor dem Entpacken auf ZIP-Bombs und Pfad-Traversal-Versuche.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        log.info("ZIP enthält: %s", names)

        # Sicherheit: unkomprimierte Gesamtgröße prüfen (ZIP-Bomb-Schutz)
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"ZIP-Inhalt zu groß (unkomprimiert): "
                f"{total_uncompressed / 1_048_576:.1f} MB "
                f"(Limit: {MAX_UNCOMPRESSED_BYTES // 1_048_576} MB)"
            )

        # Sicherheit: Pfad-Traversal-Schutz
        treffer = [
            n for n in names
            if "niederschlag" in n.lower()
            and n.endswith(".txt")
            and ".." not in posixpath.normpath(n)
            and not posixpath.isabs(n)
        ]

        if not treffer:
            raise FileNotFoundError(
                f"Keine Messwertdatei im ZIP gefunden. Vorhandene Dateien: {names}"
            )

        log.info("Lese '%s' aus ZIP …", treffer[0])
        with zf.open(treffer[0]) as f:
            return pd.read_csv(
                f, sep=";", encoding="utf-8-sig", low_memory=False,
                names=["station_no", "time", "wert"], header=0,
            )


def lade_stationen() -> dict:
    """
    Liest die Stationsdatei aus dem Repo (data/).
    Validiert Lat/Lon auf numerische Werte und entfernt unvollständige Einträge.
    """
    if not STATIONS_FILE.exists():
        raise FileNotFoundError(
            f"Stationsdatei nicht gefunden: {STATIONS_FILE}\n"
            "Bitte die Datei 'OpenHygon-Niederschlag-Stationen_EPSG4326.txt' "
            "unter data/ im Repository ablegen."
        )

    df = pd.read_csv(STATIONS_FILE, sep=";", encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    df["station_no"] = df["station_no"].astype(str).str.strip()

    # Lat/Lon auf numerisch prüfen – Zeilen mit fehlenden Koordinaten verwerfen
    df["station_latitude"]  = pd.to_numeric(df["station_latitude"],  errors="coerce")
    df["station_longitude"] = pd.to_numeric(df["station_longitude"], errors="coerce")
    vor = len(df)
    df = df.dropna(subset=["station_latitude", "station_longitude"])
    nach = len(df)
    if vor != nach:
        log.warning(
            "%d Station(en) wegen fehlender/ungültiger Koordinaten verworfen.", vor - nach
        )

    # Duplikate entfernen: vollständigen Namen bevorzugen (letzter Eintrag)
    df = df.drop_duplicates(subset="station_no", keep="last")
    log.info("%d Stationen aus %s geladen.", len(df), STATIONS_FILE)

    return df.set_index("station_no")[
        ["station_name", "station_latitude", "station_longitude"]
    ].to_dict("index")


def klassifiziere(
    summe_mm: Optional[float],
    ist_inaktiv: bool,
    ist_veraltet: bool,
    hat_datenfehler: bool = False,
) -> tuple:
    """Gibt (klasse_text, farbcode) zurück."""
    if ist_inaktiv:
        return KLASSE_INAKTIV
    if ist_veraltet:
        return KLASSE_VERALTET
    if hat_datenfehler:
        return KLASSE_DATENFEHLER
    if summe_mm is None:
        return KLASSE_INAKTIV
    for schwellenwert, label, farbe in KLASSEN:
        if summe_mm > schwellenwert:
            return label, farbe
    return KLASSE_KEIN_NIEDERSCHLAG


# ---------------------------------------------------------------------------
# Kernverarbeitung
# ---------------------------------------------------------------------------

def verarbeite(zip_bytes: bytes) -> list:
    """Liest Messwerte + Stationen, berechnet 24h-Summen, gibt Ergebnisliste zurück."""

    # -- Stationsdaten aus Repo ----------------------------------------------
    station_lookup = lade_stationen()

    # -- Messwerte aus ZIP ---------------------------------------------------
    messungen = lies_messungen_aus_zip(zip_bytes)
    messungen["station_no"] = messungen["station_no"].astype(str).str.strip()
    messungen["wert"] = pd.to_numeric(messungen["wert"], errors="coerce")

    # Doppelte Einträge aus Quelldaten entfernen (gleiche Station + Zeitstempel)
    vor = len(messungen)
    messungen = messungen.drop_duplicates(subset=["station_no", "time"], keep="first")
    nach = len(messungen)
    if vor != nach:
        log.info(
            "Duplikate entfernt: %d Zeilen -> %d Zeilen (%d entfernt)",
            vor, nach, vor - nach,
        )

    # Timestamps nach UTC parsen – utc=True ist schnell (vektorisiert) und
    # erzeugt einen einheitlichen DatetimeTZDtype, sodass alle Vergleiche
    # mit timezone-aware datetime-Objekten (ebenfalls UTC) typsicher sind.
    messungen["ts"] = pd.to_datetime(messungen["time"], utc=True, errors="coerce")
    messungen = messungen.dropna(subset=["ts"])
    log.info("%d Messzeitreihen-Zeilen geladen.", len(messungen))

    # -- Referenzzeitpunkt: echte Systemzeit in UTC --------------------------
    # WICHTIG: Nicht den neuesten Datensatz-Zeitstempel verwenden –
    # sondern die tatsächliche Uhrzeit. Nur so werden Stationen korrekt
    # als "nicht aktuell" markiert, wenn das Portal keine neuen Daten liefert.
    jetzt_utc          = datetime.now(tz=UTC)
    neuester_datensatz = messungen["ts"].max()  # UTC-aware pandas Timestamp
    veraltet_ab        = jetzt_utc - timedelta(hours=MAX_AGE_HOURS)

    # Auswertungsfenster: letzter Messzeitpunkt im Datensatz als Ende,
    # genau 24 Stunden zurück als Start (inklusiv beider Enden).
    # Hinweis: Bei stündlichen Daten liefert ein 24h-Fenster 25 Stundenwerte.
    # Das NRW-Portal verwendet scheinbar 23h zurück (= 24 Stundenwerte);
    # hier wird das vollständige 24h-Fenster verwendet.
    ende_fenster = neuester_datensatz
    start_24h    = ende_fenster - timedelta(hours=24)

    log.info("Systemzeit UTC (Referenz): %s", jetzt_utc.isoformat())
    log.info("Neuester Datensatz-TS:     %s", neuester_datensatz.isoformat())
    log.info(
        "Auswertungsfenster 24h:    %s  ->  %s",
        start_24h.isoformat(), ende_fenster.isoformat(),
    )
    log.info(
        "Veraltet-Schwelle (%dh):   %s", MAX_AGE_HOURS, veraltet_ab.isoformat()
    )

    # Warnung wenn der gesamte Datensatz veraltet ist
    datensatz_alter_h = (jetzt_utc - neuester_datensatz).total_seconds() / 3600
    if datensatz_alter_h > MAX_AGE_HOURS:
        log.warning(
            "Datensatz insgesamt veraltet! Neuester Wert ist %.1f Stunden alt "
            "(Schwelle: %d h). Alle Stationen werden als 'nicht aktuell' markiert.",
            datensatz_alter_h, MAX_AGE_HOURS,
        )

    # >= und <= damit beide Endpunkte eingeschlossen sind
    fenster = messungen[
        (messungen["ts"] >= start_24h) & (messungen["ts"] <= ende_fenster)
    ].copy()

    # -- Je Station aggregieren ----------------------------------------------
    ergebnisse: list = []

    for station_id, info in station_lookup.items():
        df_s = fenster[fenster["station_no"] == station_id]
        alle  = messungen[messungen["station_no"] == station_id]

        # Fall 1: Station hat überhaupt keine Messwerte im gesamten Datensatz
        if alle.empty:
            klasse, farbe = KLASSE_INAKTIV
            ergebnisse.append({
                "station_no":               station_id,
                "name":                     info["station_name"],
                "lat":                      float(info["station_latitude"]),
                "lon":                      float(info["station_longitude"]),
                "summe_mm_24h":             None,
                "letzter_messwert_datum":   None,
                "letzter_messwert_uhrzeit": None,
                "klasse":                   klasse,
                "farbcode":                 farbe,
            })
            continue

        letzter_ts = alle["ts"].max()

        # NaT abfangen: alle Zeitstempel dieser Station waren ungültig
        if pd.isna(letzter_ts):
            klasse, farbe = KLASSE_INAKTIV
            ergebnisse.append({
                "station_no":               station_id,
                "name":                     info["station_name"],
                "lat":                      float(info["station_latitude"]),
                "lon":                      float(info["station_longitude"]),
                "summe_mm_24h":             None,
                "letzter_messwert_datum":   None,
                "letzter_messwert_uhrzeit": None,
                "klasse":                   klasse,
                "farbcode":                 farbe,
            })
            continue

        # Veraltet: letzter Messwert älter als MAX_AGE_HOURS relativ zur Systemzeit.
        # Beide Seiten sind UTC-aware -> Vergleich typsicher.
        ist_veraltet = letzter_ts < veraltet_ab

        # Fall 2: Station hat Messwerte, aber keinen im 24h-Fenster
        # (z.B. Station seit >24h ausgefallen) -> als VERALTET markieren, nicht INAKTIV
        if df_s.empty:
            klasse, farbe = KLASSE_VERALTET
            # Ausgabe-Timestamp in MEZ/MESZ (UTC+1) – Quelldaten verwenden +01:00
            letzter_ts_lokal = letzter_ts.astimezone(timezone(timedelta(hours=1)))
            ergebnisse.append({
                "station_no":               station_id,
                "name":                     info["station_name"],
                "lat":                      float(info["station_latitude"]),
                "lon":                      float(info["station_longitude"]),
                "summe_mm_24h":             None,
                "letzter_messwert_datum":   letzter_ts_lokal.strftime("%Y-%m-%d"),
                "letzter_messwert_uhrzeit": letzter_ts_lokal.strftime("%H:%M"),
                "klasse":                   klasse,
                "farbcode":                 farbe,
            })
            continue

        # Summe berechnen; min_count=1 -> NaN wenn alle Fensterwerte NaN sind
        summe = df_s["wert"].sum(min_count=1)

        hat_datenfehler = False
        if pd.isna(summe):
            # Messwerte vorhanden, aber alle konnten nicht geparst werden
            log.warning(
                "Station %s: %d Zeilen im Fenster, alle Messwerte ungültig (NaN).",
                station_id, len(df_s),
            )
            summe = None
            hat_datenfehler = True

        klasse, farbe = klassifiziere(
            summe,
            ist_inaktiv=False,
            ist_veraltet=ist_veraltet,
            hat_datenfehler=hat_datenfehler,
        )

        # Ausgabe-Timestamp in MEZ (UTC+1) – entspricht dem Quelldaten-Format
        # Hinweis: Die Quelldaten liefern konstant +01:00, auch im Sommer (MESZ).
        # Die Zeitangaben im Output sind daher MEZ, nicht MESZ.
        letzter_ts_lokal = letzter_ts.astimezone(timezone(timedelta(hours=1)))

        ergebnisse.append({
            "station_no":               station_id,
            "name":                     info["station_name"],
            "lat":                      float(info["station_latitude"]),
            "lon":                      float(info["station_longitude"]),
            "summe_mm_24h":             round(float(summe), 2) if summe is not None else None,
            "letzter_messwert_datum":   letzter_ts_lokal.strftime("%Y-%m-%d"),
            "letzter_messwert_uhrzeit": letzter_ts_lokal.strftime("%H:%M"),
            "klasse":                   klasse,
            "farbcode":                 farbe,
        })

    log.info("Auswertung abgeschlossen für %d Stationen.", len(ergebnisse))
    return ergebnisse


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def schreibe_json(ergebnisse: list, pfad: Path, start_24h: datetime) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "quelle":            "Hochwasserportal NRW – Niederschlag",
            "url":               DATA_URL,
            "generiert_am":      datetime.now(tz=UTC).isoformat(),
            # Tatsächlich verwendeter Startzeitpunkt des Auswertungsfensters
            "auswertung_24h_ab": start_24h.isoformat(),
            "anzahl_stationen":  len(ergebnisse),
            "hinweis_zeitzone":  (
                "Zeitangaben in MEZ (UTC+1). "
                "Das Hochwasserportal NRW liefert Daten konstant mit +01:00-Offset, "
                "auch im Sommer (MESZ)."
            ),
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
    try:
        zip_bytes = lade_zip_von_url(DATA_URL)

        # start_24h für die JSON-Metadata ermitteln (nach dem Download bekannt)
        messungen_preview = lies_messungen_aus_zip(zip_bytes)
        messungen_preview["ts"] = pd.to_datetime(
            messungen_preview["time"], utc=True, errors="coerce"
        )
        neuester_ts = messungen_preview["ts"].max()
        start_24h   = neuester_ts - timedelta(hours=24)

        ergebnisse = verarbeite(zip_bytes)
        schreibe_json(ergebnisse, OUTPUT_FILE, start_24h)

    except Exception:
        log.exception("Fehler bei der Verarbeitung – Abbruch.")
        sys.exit(1)

    top10 = sorted(
        [e for e in ergebnisse if e["summe_mm_24h"] is not None],
        key=lambda x: x["summe_mm_24h"], reverse=True,
    )[:10]
    log.info("Top 10 Stationen (24h-Summe):")
    for i, s in enumerate(top10, 1):
        log.info(
            "  %2d. %-55s  %6.1f mm  %s",
            i, s["name"], s["summe_mm_24h"], s["klasse"],
        )

    veraltet = sum(1 for e in ergebnisse if e["klasse"] == KLASSE_VERALTET[0])
    inaktiv  = sum(1 for e in ergebnisse if e["klasse"] == KLASSE_INAKTIV[0])
    fehler   = sum(1 for e in ergebnisse if e["klasse"] == KLASSE_DATENFEHLER[0])
    log.info(
        "Gesamt: %d veraltet, %d inaktiv, %d Datenfehler",
        veraltet, inaktiv, fehler,
    )


if __name__ == "__main__":
    main()
