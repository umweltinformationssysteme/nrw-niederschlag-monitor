#!/usr/bin/env python3
"""
Aktualisiert die Top-10-Tabelle und den Zeitstempel in der README.md.
Wird nach process_niederschlag.py aufgerufen.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

JSON_PATH  = Path("output/niederschlag_nrw.json")
README_PATH = Path("README.md")

MARKER_START = "<!-- TOP10_START -->"
MARKER_END   = "<!-- TOP10_END -->"
TS_MARKER    = "<!-- LAST_UPDATE -->"

LEGENDE = {
    "> 100 mm":              "#4D090D",
    "> 80 mm":               "#76180A",
    "> 60 mm":               "#E4141F",
    "> 40 mm":               "#CF3ACE",
    "> 25 mm":               "#8D39C3",
    "> 15 mm":               "#0721F0",
    "> 10 mm":               "#229FDD",
    "> 5 mm":                "#1BDAD8",
    "> 2 mm":                "#47C774",
    "> 1 mm":                "#9CD433",
    "> 0,1 mm":              "#FDFB6E",
    "Kein Niederschlag":     "#FFFFFF",
    "zurzeit inaktive Station": "#FFE4E1",
    "nicht aktuelle Werte":  "#808080",
}


def farb_badge(klasse: str, farbe: str) -> str:
    """Erzeugt ein kompaktes Farbquadrat via shields.io."""
    label = klasse.replace(" ", "_").replace(",", ".")
    return (
        f'![{klasse}](https://img.shields.io/badge/-{label}'
        f'-{farbe.lstrip("#")}?style=flat-square)'
    )


def baue_tabelle(stationen: list[dict]) -> str:
    top = sorted(
        [s for s in stationen if s.get("summe_mm_24h") is not None],
        key=lambda x: x["summe_mm_24h"],
        reverse=True,
    )[:10]

    zeilen = [
        "| # | Station | Summe 24 h | Letzter Wert | Stufe |",
        "|---|---------|:----------:|:------------:|-------|",
    ]
    for i, s in enumerate(top, 1):
        badge = farb_badge(s["klasse"], s["farbcode"])
        datum_uhrzeit = (
            f'{s["letzter_messwert_datum"]} {s["letzter_messwert_uhrzeit"]}'
            if s["letzter_messwert_datum"] else "–"
        )
        name_kurz = s["name"].replace("_NRW", "").replace("_", " ")
        zeilen.append(
            f'| {i} | {name_kurz} | **{s["summe_mm_24h"]:.1f} mm** '
            f'| {datum_uhrzeit} | {badge} {s["klasse"]} |'
        )
    return "\n".join(zeilen)


def main() -> None:
    if not JSON_PATH.exists():
        print(f"JSON nicht gefunden: {JSON_PATH}")
        return

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    stationen = data["stationen"]

    readme = README_PATH.read_text(encoding="utf-8")

    # Top-10-Tabelle ersetzen
    tabelle = baue_tabelle(stationen)
    block = f"{MARKER_START}\n{tabelle}\n{MARKER_END}"
    readme = re.sub(
        rf"{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}",
        block,
        readme,
        flags=re.DOTALL,
    )

    # Zeitstempel ersetzen
    jetzt = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    readme = re.sub(
        rf"{re.escape(TS_MARKER)}.*",
        f"{TS_MARKER} _{jetzt}_",
        readme,
    )

    README_PATH.write_text(readme, encoding="utf-8")
    print(f"README aktualisiert ({len(stationen)} Stationen, Top-10 eingetragen).")


if __name__ == "__main__":
    main()
