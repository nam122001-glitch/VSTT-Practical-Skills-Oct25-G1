#!/usr/bin/env python3
"""
VSTT Tableau assignment - cleaning & preprocessing pipeline
Source: Rijden de Treinen open data (services + station lookup), CC BY 4.0.

Usage:  python3 clean_rdt.py services-2024-01.csv.gz services-2024-03.csv.gz ...

Outputs (in ./out):
  train_stops_clean.csv   row-level fact table, one row per station stop
  stations_clean.csv      station lookup (397 NL stations + coords/type)
  cleaning_log.csv        before/after counts for the report's Data Preparation section
"""
import sys, os
import pandas as pd
import numpy as np

STATIONS = "/root/.claude/uploads/769059c2-9140-542a-a053-f435f232ba17/3a018718-stations-2023-09-nl.csv"
OUT = "out"
BOOLCOLS = ["Service:Completely cancelled", "Service:Partly cancelled",
            "Stop:Arrival cancelled", "Stop:Departure cancelled", "Stop:Platform change"]
log = []


def note(step, detail, n=None):
    log.append({"step": step, "detail": detail, "rows_affected": n})
    print(f"  [{step}] {detail}" + (f" ({n:,})" if n is not None else ""))


# ---------------------------------------------------------------- stations
def load_stations():
    st = pd.read_csv(STATIONS)
    note("stations.read", "rows read from stations-2023-09-nl.csv", len(st))

    # Cleaning step: one station (Nieuw Amsterdam, uic 8400454) has an empty
    # station code in BOTH files. Assign a synthetic code so the join works.
    miss = st["code"].isna()
    assert miss.sum() <= 1
    if miss.any():
        st.loc[miss, "code"] = "NWAD"
        note("stations.fix", "empty station code filled with synthetic 'NWAD' (Nieuw Amsterdam)", int(miss.sum()))

    st["code"] = st["code"].str.upper()
    assert st["code"].is_unique

    st = st.rename(columns={
        "id": "station_id", "code": "station_code", "uic": "station_uic",
        "name_long": "station_name", "name_medium": "station_name_medium",
        "type": "station_type", "geo_lat": "lat", "geo_lng": "lng"})

    # Grouping step: collapse the 8 raw RDT station types into 4 readable tiers
    # ("knooppunt" = junction variants of the same tier) for use as a Tableau group.
    tier = {
        "megastation": "Mega station",
        "knooppuntIntercitystation": "Intercity station",
        "intercitystation": "Intercity station",
        "knooppuntSneltreinstation": "Fast-train station",
        "sneltreinstation": "Fast-train station",
        "knooppuntStoptreinstation": "Local station",
        "stoptreinstation": "Local station",
        "facultatiefStation": "Local station",
    }
    st["station_tier"] = st["station_type"].map(tier)
    assert st["station_tier"].notna().all()
    st["is_junction"] = st["station_type"].str.startswith("knooppunt")

    # Sanity: coordinates must sit inside the Netherlands bounding box
    bad = ~(st["lat"].between(50.7, 53.6) & st["lng"].between(3.3, 7.3))
    assert not bad.any(), st.loc[bad]
    note("stations.verify", "all coordinates inside NL bounding box", len(st))

    cols = ["station_code", "station_name", "station_name_medium", "station_uic",
            "station_type", "station_tier", "is_junction", "country", "lat", "lng"]
    return st[cols]


# ---------------------------------------------------------------- services
def read_month(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    raw = len(df)
    note("services.read", f"rows read from {os.path.basename(path)}", raw)

    df = df.rename(columns={
        "Service:RDT-ID": "service_id", "Service:Date": "date",
        "Service:Type": "service_type", "Service:Company": "company",
        "Service:Train number": "train_number",
        "Service:Completely cancelled": "service_cancelled",
        "Service:Partly cancelled": "service_partly_cancelled",
        "Service:Maximum delay": "service_max_delay",
        "Stop:RDT-ID": "stop_id", "Stop:Station code": "station_code",
        "Stop:Station name": "station_name_raw",
        "Stop:Arrival time": "arrival_time", "Stop:Arrival delay": "arrival_delay",
        "Stop:Arrival cancelled": "arrival_cancelled",
        "Stop:Departure time": "departure_time", "Stop:Departure delay": "departure_delay",
        "Stop:Departure cancelled": "departure_cancelled",
        "Stop:Platform change": "platform_change",
        "Stop:Planned platform": "planned_platform",
        "Stop:Actual platform": "actual_platform"})

    # --- duplicates: stop_id is the natural key of one station stop
    d = int(df["stop_id"].duplicated().sum())
    if d:
        df = df.drop_duplicates(subset="stop_id")
    note("services.duplicates", "duplicate stop records removed", d)

    # --- data types
    for c in ["service_cancelled", "service_partly_cancelled", "arrival_cancelled",
              "departure_cancelled", "platform_change"]:
        df[c] = df[c].map({"true": True, "false": False}).astype("boolean")
    for c in ["arrival_delay", "departure_delay", "service_max_delay"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int32")
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")

    # RFC3339 with mixed +01:00 / +02:00 offsets (CET -> CEST switch on 31/03/2024).
    # Parse as UTC, then convert to local Dutch time so hour-of-day is correct.
    for c in ["arrival_time", "departure_time"]:
        t = pd.to_datetime(df[c], format="ISO8601", utc=True)
        df[c] = t.dt.tz_convert("Europe/Amsterdam").dt.tz_localize(None)
    note("services.dtypes", "booleans, Int32 delays and tz-aware times (Europe/Amsterdam) cast", raw)

    # --- station code: same empty-code station as in the lookup
    m = df["station_code"].isna() & (df["station_name_raw"] == "Nieuw Amsterdam")
    df.loc[m, "station_code"] = "NWAD"
    note("services.fix", "empty station code filled for Nieuw Amsterdam", int(m.sum()))
    still = int(df["station_code"].isna().sum())
    assert still == 0, f"{still} rows still have no station code"
    df["station_code"] = df["station_code"].str.upper()

    return df


def derive(df, station_codes):
    n = len(df)

    # --- structural missing values (NOT dirty data, must not be dropped):
    # the first stop of a service has no arrival, the last stop has no departure.
    is_origin = df["arrival_time"].isna()
    is_term = df["departure_time"].isna()
    df["stop_role"] = np.select([is_origin & ~is_term, is_term & ~is_origin, is_origin & is_term],
                                ["Origin", "Terminus", "Single stop"], default="Intermediate")
    note("derive.stop_role", "origin / intermediate / terminus derived from missing times",
         int((is_origin | is_term).sum()))

    # --- one time axis for Tableau: departure where known, else arrival
    df["stop_time"] = df["departure_time"].fillna(df["arrival_time"])
    unresolved = int(df["stop_time"].isna().sum())
    if unresolved:
        df = df[df["stop_time"].notna()]
    note("derive.stop_time", "stops dropped with neither arrival nor departure time", unresolved)

    # --- source data error: a few stops carry a timestamp months away from the
    # service date (e.g. service 14909088 dated 2024-03-19 with 2024-11-29 times).
    # Overnight services legitimately spill into the next day, so allow +/- 1 day.
    off = (df["stop_time"].dt.normalize() - df["date"]).dt.days
    overnight = int((off == 1).sum())
    bad_time = ~off.between(-1, 1)
    if bad_time.any():
        note("clean.bad_timestamp",
             "stops dropped: timestamp more than 1 day from the service date (source error)",
             int(bad_time.sum()))
        df = df[~bad_time]
    note("clean.overnight", "stops on the day after the service date (overnight trains, kept)",
         overnight)

    # --- date parts (Tableau also does this, but pre-computing keeps the sheets simple)
    t = df["stop_time"]
    df["hour"] = t.dt.hour.astype("int8")
    df["weekday"] = t.dt.day_name()
    df["weekday_no"] = (t.dt.weekday + 1).astype("int8")  # 1 = Monday, for sorting
    df["is_weekend"] = t.dt.weekday >= 5
    df["month"] = t.dt.month.astype("int8")
    df["month_name"] = t.dt.month_name()
    df["iso_week"] = t.dt.isocalendar().week.astype("int16")
    df["season"] = df["month"].map({1: "Winter", 3: "Spring", 7: "Summer", 10: "Autumn"})

    # --- punctuality. NS measures arrival punctuality at 5 and 15 minutes
    # (NS Annual Report 2023). Delay of a cancelled stop is meaningless -> null.
    delay = df["arrival_delay"].where(~df["arrival_cancelled"].fillna(False).astype(bool))
    delay = delay.fillna(df["departure_delay"].where(~df["departure_cancelled"].fillna(False).astype(bool)))
    df["delay_min"] = delay
    df["is_cancelled_stop"] = df["arrival_cancelled"].fillna(False).astype(bool) | df["departure_cancelled"].fillna(False).astype(bool)
    df["delayed_5"] = (delay >= 5)
    df["delayed_15"] = (delay >= 15)
    df["on_time_5"] = (delay < 5)
    note("derive.punctuality", "delay_min + 5/15-minute flags; cancelled stops excluded from delay",
         int(df["is_cancelled_stop"].sum()))

    # --- international stops: 5.9% of stops are German/Belgian stations that are
    # absent from the NL-only lookup (no coordinates -> must be excluded from maps).
    df["is_international"] = ~df["station_code"].isin(station_codes)
    note("derive.international", "stops at non-NL stations flagged", int(df["is_international"].sum()))

    # --- route = origin -> terminus of the service (for route-level analysis)
    idx = df.sort_values("stop_time").groupby("service_id")["station_name_raw"]
    ends = pd.DataFrame({"route_origin": idx.first(), "route_dest": idx.last()})
    ends["route"] = ends["route_origin"] + " - " + ends["route_dest"]
    df = df.merge(ends, left_on="service_id", right_index=True, how="left")
    df["stop_seq"] = df.sort_values("stop_time").groupby("service_id").cumcount() + 1
    note("derive.route", "route (origin - terminus) and stop sequence derived per service",
         int(ends["route"].nunique()))

    return df
    return df


# Fact table: one row per station stop. Date parts and the 5/15-minute punctuality
# flags are deliberately NOT pre-computed - they belong in Tableau as date functions
# and calculated fields (assignment feature checklist), and they double the file size.
FACTCOLS = ["stop_id", "service_id", "station_code", "stop_seq", "stop_role",
            "is_international", "stop_time", "arrival_delay", "departure_delay",
            "delay_min", "is_cancelled_stop", "platform_change",
            "planned_platform", "actual_platform"]

# Service dimension: one row per train service, joined to the fact on service_id.
SVCCOLS = ["service_id", "date", "service_type", "company", "train_number",
           "service_cancelled", "service_partly_cancelled", "service_max_delay",
           "route", "route_origin", "route_dest"]


def main(paths):
    os.makedirs(OUT, exist_ok=True)
    st = load_stations()
    st.to_csv(f"{OUT}/stations_clean.csv", index=False)
    codes = set(st["station_code"])

    total = 0
    for i, p in enumerate(paths):
        print(f"\n=== {os.path.basename(p)}")
        tag = os.path.basename(p).replace("services-", "").replace(".csv.gz", "")
        df = derive(read_month(p), codes)

        fact = f"{OUT}/stops_{tag}.csv"
        df[FACTCOLS].to_csv(fact, index=False, date_format="%Y-%m-%d %H:%M:%S")

        svc = df[SVCCOLS].drop_duplicates("service_id")
        svc = svc.merge(df.groupby("service_id").size().rename("n_stops"),
                        left_on="service_id", right_index=True)
        svc.to_csv(f"{OUT}/services.csv", index=False, mode="w" if i == 0 else "a",
                   header=(i == 0), date_format="%Y-%m-%d")

        note("output", f"{os.path.basename(fact)} ({os.path.getsize(fact)/1e6:.0f} MB) "
                       f"+ {len(svc):,} services", len(df))
        total += len(df)
        del df, svc

    pd.DataFrame(log).to_csv(f"{OUT}/cleaning_log.csv", index=False)
    print(f"\nTOTAL {total:,} stop rows across {len(paths)} month(s)")
    for f in sorted(os.listdir(OUT)):
        print(f"  {f:28s} {os.path.getsize(OUT+'/'+f)/1e6:8.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
