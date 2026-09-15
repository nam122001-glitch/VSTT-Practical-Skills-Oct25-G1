# Dutch Rail Punctuality — where the network loses time

Analysis of 7.4 million Dutch train station stops (Jan / Mar / Jul / Oct 2024) built for an
MSc Data Analytics assignment on visualisation and storytelling with Tableau.

**Core finding:** delay is not generated at departure. 97.76% of trains leave their origin on
time, but only 90.76% are still punctual by their twenty-first stop — a monotonic decline across
every stop-position band, consistent with knock-on delay propagation (Yuan and Hansen, 2007).

## Data

| Source | Licence |
|---|---|
| [Rijden de Treinen train archive](https://www.rijdendetreinen.nl/en/open-data/train-archive) — monthly service files | CC BY 4.0 |
| [Station lookup](https://opendata.rijdendetreinen.nl/public/stations/stations-2023-09-nl.csv) — coordinates and station class | CC0 |

Raw monthly files are **not** stored in this repository (~30 MB compressed each, ~625 MB once
processed). Download them directly:

```
https://opendata.rijdendetreinen.nl/public/services/services-2024-01.csv.gz
https://opendata.rijdendetreinen.nl/public/services/services-2024-03.csv.gz
https://opendata.rijdendetreinen.nl/public/services/services-2024-07.csv.gz
https://opendata.rijdendetreinen.nl/public/services/services-2024-10.csv.gz
```

Four months were selected by purposive seasonal sampling — one per season — rather than the full
year, which would be roughly 22 million rows without adding an analytical dimension.

## Reproducing the analysis

```bash
pip install pandas
python clean_rdt.py services-2024-01.csv.gz services-2024-03.csv.gz \
                    services-2024-07.csv.gz services-2024-10.csv.gz
python findings.py
```

`clean_rdt.py` writes to `out/`:

| File | Rows | Contents |
|---|---|---|
| `stops_2024-XX.csv` | 7,446,764 total | fact table — one row per station stop |
| `services.csv` | 836,627 | one row per train service, with route and service type |
| `stations_clean.csv` | 397 | station lookup with coordinates and tier |
| `cleaning_log.csv` | — | rows affected at every cleaning step, per month |

The pipeline is deterministic: the same inputs always produce identical outputs.

## What the cleaning does

- Parses RFC 3339 timestamps as UTC and converts to `Europe/Amsterdam`, so the CET→CEST change
  on 31/03/2024 does not shift the hour-of-day analysis by one hour.
- Labels structurally missing values rather than dropping them. An origin stop has no arrival
  time (11.25% of rows) and a terminus has no departure time (11.26%); both are tagged through
  `stop_role` instead of being deleted.
- Removes 3,365 records (0.05%): 3,349 with no timestamp at all, and 16 whose timestamp falls
  more than one day from the service date. Overnight services crossing midnight — 270,740
  records — are legitimate and retained.
- Repairs one station (Nieuw Amsterdam) whose code is blank in both source files.
- Flags 430,610 stops at German and Belgian stations, which have no coordinates in the NL-only
  lookup and are therefore excluded from station-level and map analysis.
- Derives stop sequence, stop role, route (origin–terminus pair) and a consolidated delay field.
  Date parts and punctuality thresholds are deliberately left to Tableau.

## Verification

`check_findings.csv` lists every headline figure with the exact filter that produces it, so any
number in the report can be reconciled against the Tableau workbook. Key figures were also
recomputed from the raw archive by an independent code path as a cross-check.

Measured on Dutch stations, NS services reach 94.65% punctuality at the five-minute threshold.
NS publishes 89.7% for 2023 and the EU reports 90% for regional services in 2022 — the three are
not interchangeable, because NS weights by passengers and measures journey arrival, the EU
measures whole services, and this analysis treats every station stop equally.

## Files

```
clean_rdt.py        cleaning and transformation pipeline
findings.py         analysis that produces every figure quoted in the report
cleaning_log.csv    audit trail of the cleaning run
stations_clean.csv  station dimension table (small enough to version)
check_findings.csv  figure-by-figure verification table
```

## Limitations

The archive contains no passenger counts, so this measures operational performance, not
passenger impact: a station with 11% late stops serving a few hundred travellers and one with 5%
serving tens of thousands rank the same here. It records *what* happened, not *why* — every
causal statement in the accompanying report is interpretation, not measurement.

## References

Compendium voor de Leefomgeving (2024) *Punctualiteit van de trein, 2014-2023*.

European Commission (2025) *Ninth monitoring report on the development of the rail market*,
COM(2025) 439 final.

Yuan, J. and Hansen, I.A. (2007) 'Optimizing capacity utilization of stations by estimating
knock-on train delays', *Transportation Research Part B: Methodological*, 41(2), pp. 202–217.
