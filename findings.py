import pandas as pd, numpy as np, glob
pd.set_option("display.width",200)
cols=["service_id","station_code","stop_seq","stop_role","is_international","stop_time",
      "delay_min","is_cancelled_stop","platform_change"]
f=pd.concat([pd.read_csv(p,usecols=cols,parse_dates=["stop_time"]) for p in sorted(glob.glob("out/stops_2024-*.csv"))],ignore_index=True)
st=pd.read_csv("out/stations_clean.csv")
sv=pd.read_csv("out/services.csv",parse_dates=["date"])
print("fact rows",len(f),"| services",len(sv),"| stations",len(st))
f["month"]=f.stop_time.dt.month
f["season"]=f.month.map({1:"Winter (Jan)",3:"Spring (Mar)",7:"Summer (Jul)",10:"Autumn (Oct)"})
f["hour"]=f.stop_time.dt.hour
f["dow"]=f.stop_time.dt.dayofweek
nl=f[~f.is_international]
ok=nl[~nl.is_cancelled_stop & nl.delay_min.notna()]

def pct(s): return round(s.mean()*100,2)
print("\n=== 1. PUNCTUALITY BY SEASON (NL stops, non-cancelled)")
g=ok.groupby("season")["delay_min"].agg(stops="size",on_time_5=lambda x:(x<5).mean()*100,
    delayed_5=lambda x:(x>=5).mean()*100,delayed_15=lambda x:(x>=15).mean()*100,mean_delay="mean")
c=nl.groupby("season")["is_cancelled_stop"].mean()*100
print(g.join(c.rename("cancelled_pct")).round(2).to_string())

print("\n=== 2. DELAY BY HOUR (>=5min %, all seasons)")
h=ok.groupby("hour")["delay_min"].agg(stops="size",delayed_5=lambda x:(x>=5).mean()*100).round(2)
print(h.to_string())

print("\n=== 3. WEEKDAY vs WEEKEND")
ok2=ok.assign(part=np.where(ok.dow>=5,"Weekend","Weekday"))
print(ok2.groupby("part")["delay_min"].agg(stops="size",delayed_5=lambda x:(x>=5).mean()*100,mean="mean").round(2).to_string())

print("\n=== 4. CASCADING DELAY along stop sequence")
b=pd.cut(ok.stop_seq,[0,1,3,5,8,12,20,40],labels=["1","2-3","4-5","6-8","9-12","13-20","21-40"])
print(ok.groupby(b,observed=True)["delay_min"].agg(stops="size",mean="mean",delayed_5=lambda x:(x>=5).mean()*100).round(2).to_string())

print("\n=== 5. WORST STATIONS (>=20000 stops over 4 months)")
g=ok.groupby("station_code")["delay_min"].agg(stops="size",delayed_5=lambda x:(x>=5).mean()*100,mean="mean")
g=g[g.stops>=20000].sort_values("delayed_5",ascending=False)
j=g.join(st.set_index("station_code")[["station_name","station_tier"]]).round(2)
print(j.head(12).to_string()); print("--- best 5 ---"); print(j.tail(5).to_string())

print("\n=== 6. PLATFORM CHANGES by station (>=20000 stops)")
p=nl.groupby("station_code")["platform_change"].agg(stops="size",pct=lambda x:x.mean()*100)
p=p[p.stops>=20000].sort_values("pct",ascending=False).join(st.set_index("station_code")["station_name"]).round(2)
print(p.head(8).to_string()); print("overall platform change %",pct(nl.platform_change))

print("\n=== 7. SERVICE TYPE (service level, max delay)")
t=sv.groupby("service_type").agg(services=("service_id","size"),mean_max_delay=("service_max_delay","mean"),
    cancelled_pct=("service_cancelled",lambda x:x.mean()*100))
print(t[t.services>=1000].sort_values("mean_max_delay",ascending=False).round(2).to_string())

print("\n=== 8. COMPANY")
c=sv.groupby("company").agg(services=("service_id","size"),mean_max_delay=("service_max_delay","mean"),
    cancelled_pct=("service_cancelled",lambda x:x.mean()*100))
print(c[c.services>=2000].sort_values("mean_max_delay",ascending=False).round(2).to_string())

print("\n=== 9. WORST ROUTES (>=400 services)")
r=sv.groupby("route").agg(services=("service_id","size"),mean_max_delay=("service_max_delay","mean"),
    pct_delayed5=("service_max_delay",lambda x:(x>=5).mean()*100),cancel=("service_cancelled",lambda x:x.mean()*100))
print(r[r.services>=400].sort_values("pct_delayed5",ascending=False).head(10).round(2).to_string())

print("\n=== 10. WORST DAYS (cancellation %)")
d=f.assign(day=f.stop_time.dt.date).groupby("day").agg(stops=("stop_id" if "stop_id" in f else "service_id","size"),
    cancelled=("is_cancelled_stop",lambda x:x.mean()*100))
print(d.sort_values("cancelled",ascending=False).head(8).round(2).to_string())

print("\n=== 11. SERVICE VOLUME BY SEASON (frequency)")
print(sv.assign(m=sv.date.dt.month).groupby("m").agg(services=("service_id","size"),days=("date","nunique")).assign(
    per_day=lambda x:(x.services/x.days).round(0)).to_string())
