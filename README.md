# 🌧️ NRW Niederschlag Monitor

Stündlich aktualisierte Auswertung der **24h-Niederschlagssummen** aller Messstationen des
[Hochwasserportals NRW](https://www.hochwasserportal.nrw/webpublic/index.html#/overview/Niederschlag).

> Letzter Update: <!-- LAST_UPDATE --> _2026-09-04 20:12 UTC_

---

## 📊 Top 10 Stationen – Niederschlag letzte 24 Stunden

<!-- TOP10_START -->
| # | Station | Summe 24 h | Letzter Wert | Stufe |
|---|---------|:----------:|:------------:|-------|
| 1 | Rinteln-Goldbeck HB | **13.1 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 2 | Lengerich KA | **12.6 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 3 | Tecklenburg | **12.3 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 4 | Bünde-Spradow KA | **12.3 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 5 | Schöppingen KA | **11.7 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 6 | Oeynhausen, Bad KA | **11.1 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 7 | Stadtlohn-Wendfeld | **10.9 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 8 | Gescher KA | **10.7 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 9 | Vreden KA | **10.4 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
| 10 | Rödinghausen-Schwenningdorf RBF | **10.3 mm** | 2026-09-04 16:00 | ![> 10 mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) > 10 mm |
<!-- TOP10_END -->

---

## 🗂️ Datenquelle

| Eigenschaft | Wert |
|-------------|------|
| **Betreiber** | Landesamt für Natur, Umwelt und Verbraucherschutz NRW (LANUV) |
| **Portal** | [hochwasserportal.nrw](https://www.hochwasserportal.nrw) |
| **Download-URL** | `https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip` |
| **Messgröße** | Niederschlag in mm/h (stündliche Werte) |
| **Anzahl Stationen** | ~314 (NRW-weit) |
| **Koordinatensystem** | WGS84 / EPSG:4326 |
| **Aktualisierung Quelle** | ca. stündlich |

Das ZIP-Archiv enthält zwei Dateien:

- `niederschlag.txt` – Messzeitreihe (`station_no;time;value(mm/h)`)
- `OpenHygon-Niederschlag-Stationen_EPSG4326.txt` – Stationsmetadaten (`lat;lon;name;station_no;…`)

---

## 📁 Projektstruktur

```
nrw-niederschlag-monitor/
├── .github/
│   └── workflows/
│       └── update_niederschlag.yml   # GitHub Actions – stündlicher Cron-Job
├── output/
│   └── niederschlag_nrw.json         # Aktuelles Auswertungsergebnis (auto-generiert)
├── scripts/
│   ├── process_niederschlag.py       # Kernskript: Download → Berechnung → JSON
│   └── update_readme.py              # Aktualisiert Top-10-Tabelle in dieser README
├── requirements.txt
└── README.md
```

---

## ⚙️ Funktionsweise

### 1. Datenbezug
Das Skript `process_niederschlag.py` lädt das ZIP-Archiv per HTTP-GET und entpackt es im
Arbeitsspeicher – es wird keine temporäre Datei auf der Festplatte erstellt.

### 2. Auswertungsfenster
Als Referenzzeitpunkt gilt der **neueste Zeitstempel im Datensatz**.
Alle Messwerte der letzten **24 Stunden** relativ dazu werden summiert.

### 3. Klassifizierung
Jede Station erhält eine Klasse und einen Farbcode:

| Stufe | Hex |
|-------|-----|
| > 100 mm | ![>100mm](https://img.shields.io/badge/->_100_mm-4D090D?style=flat-square) `#4D090D` |
| > 80 mm  | ![>80mm](https://img.shields.io/badge/->_80_mm-76180A?style=flat-square) `#76180A` |
| > 60 mm  | ![>60mm](https://img.shields.io/badge/->_60_mm-E4141F?style=flat-square) `#E4141F` |
| > 40 mm  | ![>40mm](https://img.shields.io/badge/->_40_mm-CF3ACE?style=flat-square) `#CF3ACE` |
| > 25 mm  | ![>25mm](https://img.shields.io/badge/->_25_mm-8D39C3?style=flat-square) `#8D39C3` |
| > 15 mm  | ![>15mm](https://img.shields.io/badge/->_15_mm-0721F0?style=flat-square) `#0721F0` |
| > 10 mm  | ![>10mm](https://img.shields.io/badge/->_10_mm-229FDD?style=flat-square) `#229FDD` |
| > 5 mm   | ![>5mm](https://img.shields.io/badge/->_5_mm-1BDAD8?style=flat-square) `#1BDAD8` |
| > 2 mm   | ![>2mm](https://img.shields.io/badge/->_2_mm-47C774?style=flat-square) `#47C774` |
| > 1 mm   | ![>1mm](https://img.shields.io/badge/->_1_mm-9CD433?style=flat-square) `#9CD433` |
| > 0,1 mm | ![>0.1mm](https://img.shields.io/badge/->_0,1_mm-FDFB6E?style=flat-square) `#FDFB6E` |
| Kein Niederschlag | ![kein](https://img.shields.io/badge/-Kein_Niederschlag-FFFFFF?style=flat-square) `#FFFFFF` |
| Zurzeit inaktive Station | ![inaktiv](https://img.shields.io/badge/-inaktiv-FFE4E1?style=flat-square) `#FFE4E1` |
| **nicht aktuelle Werte** | ![veraltet](https://img.shields.io/badge/-nicht_aktuell-808080?style=flat-square) `#808080` |

> **„nicht aktuelle Werte"** wird angezeigt, wenn der jüngste zurückliegende Messwert
> einer Station **älter als 3 Stunden** ist (relativ zum neuesten Gesamtzeitstempel im Datensatz).

### 4. JSON-Ausgabe
Die Ergebnisse werden in `output/niederschlag_nrw.json` gespeichert und via Git in das
Repository committed – damit ist die Zeitreihe nachvollziehbar und die Datei direkt per
GitHub Raw-URL abrufbar.

---

## 🗃️ JSON-Format

```json
{
  "meta": {
    "quelle": "Hochwasserportal NRW – Niederschlag",
    "url": "https://www.hochwasserportal.nrw/data/downloads/niederschlag.zip",
    "generiert_am": "2026-09-04T10:10:00+00:00",
    "auswertung_24h_ab": "2026-09-03T10:00:00+01:00",
    "anzahl_stationen": 314
  },
  "stationen": [
    {
      "station_no": "44170037",
      "name": "Soest-Ampen_WW_NRW",
      "lat": 51.567,
      "lon": 8.134,
      "summe_mm_24h": 12.4,
      "letzter_messwert_datum": "2026-09-04",
      "letzter_messwert_uhrzeit": "09:00",
      "klasse": "> 10 mm",
      "farbcode": "#229FDD"
    }
  ]
}
```

### Felder

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `station_no` | `string` | Eindeutige Stationsnummer (LANUV) |
| `name` | `string` | Stationsname |
| `lat` | `number` | Breitengrad (WGS84) |
| `lon` | `number` | Längengrad (WGS84) |
| `summe_mm_24h` | `number \| null` | Niederschlagssumme der letzten 24 h in mm (`null` = inaktiv) |
| `letzter_messwert_datum` | `string \| null` | Datum des letzten Messwertes (`YYYY-MM-DD`) |
| `letzter_messwert_uhrzeit` | `string \| null` | Uhrzeit des letzten Messwertes (`HH:MM`) |
| `klasse` | `string` | Niederschlagsklasse gemäß Legende |
| `farbcode` | `string` | Hex-Farbcode der Klasse |

---

## 🚀 Lokale Ausführung

```bash
# Repository klonen
git clone https://github.com/<dein-user>/nrw-niederschlag-monitor.git
cd nrw-niederschlag-monitor

# Abhängigkeiten installieren
pip install -r requirements.txt

# Auswertung starten (lädt Daten direkt vom Hochwasserportal)
python scripts/process_niederschlag.py

# README aktualisieren (optional)
python scripts/update_readme.py
```

> **Hinweis:** Es wird eine aktive Internetverbindung benötigt, um die Daten vom
> Hochwasserportal NRW herunterzuladen.

---

## 🤖 GitHub Actions

Der Workflow `.github/workflows/update_niederschlag.yml` läuft automatisch:

| Trigger | Beschreibung |
|---------|--------------|
| `cron: "10 * * * *"` | Jede Stunde zur Minute 10 (UTC) |
| `workflow_dispatch` | Manueller Start über die GitHub-Oberfläche |

Bei jeder Ausführung werden `output/niederschlag_nrw.json` und `README.md` (Top-10-Tabelle)
aktualisiert und direkt ins Repository committed, sofern sich Daten geändert haben.

**Benötigte Repository-Berechtigungen:**
Unter *Settings → Actions → General → Workflow permissions* muss
**"Read and write permissions"** aktiviert sein.

---

## 📄 Lizenz

Die Auswertungsskripte stehen unter der [MIT-Lizenz](LICENSE).

Die Messdaten sind Eigentum des **Landesamts für Natur, Umwelt und Verbraucherschutz NRW (LANUV)**
und unterliegen den Nutzungsbedingungen des [Hochwasserportals NRW](https://www.hochwasserportal.nrw).

---

## 🔗 Verwandte Projekte

- [NRW Thermal Risk Index](https://github.com/umweltinformationssysteme/NRW-thermal-risk-index) – Analoges Projekt für den Wärmebelastungsindex
- [Hochwasserportal NRW](https://www.hochwasserportal.nrw/webpublic/index.html#/overview/Niederschlag) – Offizielle Kartenansicht Niederschlag
