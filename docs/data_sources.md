# Data sources: verification log

Checked on **14 Nov 2026** (around 05:00 HKT) by calling each endpoint. "Verified" means a real response was
inspected. Anything not checked is listed as such.

## 1. A&E waiting times (core)

| Item | Status | Detail |
|---|---|---|
| Live JSON `https://www.ha.org.hk/opendata/aed/aedwtdata2-en.json` | **Not reachable from the dev machine** | Connection reset (curl, in-app browser, cloud fetcher). Content verified through the archive copy below. `-tc`, `-sc` and `.xlsx` variants are listed on data.gov.hk but untested for the same reason. |
| Archive API `https://api.data.gov.hk/v1/historical-archive` | Verified | `list-file-versions?url=…&start=YYYYMMDD&end=YYYYMMDD` (end must be yesterday or earlier) and `get-file?url=…&time=YYYYMMDD-HHMM` (works for today; 404 when no snapshot). |
| Update frequency | Verified | One snapshot per 15 minutes: 94–96 per day. The 05:30 slot was available at 05:30 HKT. |
| History depth | Verified | Numeric feed from **14 Oct 2025**: 36,751 snapshots to 13 Nov 2026, about 139 MB raw. |
| Data spec PDF | **Not read** | Hosted on ha.org.hk. Field meanings below come from the brief and the data itself. |
| Hospital coordinates | Verified | CSDI FeatureServer `https://portal.csdi.gov.hk/server/rest/services/common/fhb_rcd_1636947932221_94410/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=json` returns `hospName_EN/TC/SC`, `LATITUDE`, `LONGITUDE`. |

### Record format (snapshot of 13 Nov 2026 23:00)

```json
{"waitTime": [
  {"hospName": "Kwong Wah Hospital",
   "t1wt": "0 minute", "manageT1case": "N",
   "t2wt": "less than 15 minutes", "manageT2case": "Y",
   "t3p50": "26 minutes", "t3p95": "85 minutes",
   "t45p50": "7.5 hours", "t45p95": "11 hours"}
 ],
 "updateTime": "13/11/2026 10:45PM"}
```

Things the cleaner must handle:

- Every value is a **string with its unit**. `t3*` are minutes; `t45*` are hours in 0.5 steps.
- Singular and plural both occur: `"1 hour"`, `"4 hour"`, `"2.5 hours"`, `"0 minute"`.
- `manageT1case` / `manageT2case` (`Y`/`N`) are **not in the brief**. Likely "currently managing a triage I / II
  case", i.e. the resuscitation flag. Meaning to be confirmed against the spec PDF.
- `updateTime` is `D/M/YYYY h:mmAM|PM` in Hong Kong time, and ran 15 minutes behind the archive slot in
  the samples seen (slot 23:00 → 10:45PM).
- Not yet seen but expected: non-numeric values (e.g. "N/A") during outages. To be counted in M1.

### Earlier formats (not used; see DECISIONS.md D2)

| Period | URL | Format |
|---|---|---|
| 14 Oct 2025 → now | `aedwtdata2-en.json` | Numeric, as above |
| 13 Oct 2025 | | HA announced the revised dataset |
| 11 Sep – 13 Oct 2025 | | No snapshots in the archive |
| 28 Aug – 10 Sep 2025 | `aedwtdata2-en.json` | Text bands: `"Around 2 hours"`, `"Majority within 3 hours"`; no t1/t2 fields |
| ≤ mid-2025 (seen 2022, 2024, Jan 2025) | `aedwtdata-en.json` | One field: `"topWait": "Over 2 hours"` |

## 2. Public transport

| Item | Status | Detail |
|---|---|---|
| TD GTFS `https://static.data.gov.hk/td/pt-headway-en/gtfs.zip` | Verified | 13.8 MB zip, last modified 10 Nov 2026. 2,466 routes, 9,458 stops, 76k frequency rows. Headway-based: only the first stop of a trip has times. |
| What it covers | Verified | Agencies: KMB, LWB, Citybus, NLB, MTR Bus (feeder), green minibus, ferries, trams, Peak Tram, residents' and cross-boundary coaches. **No MTR heavy rail or Light Rail.** |
| MTR CSV `https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv` | Verified | Line, direction, station code/ID, names, sequence. Fares CSV also present. No timetables or coordinates. |
| Community GTFS `github.com/wheelstransit/hongkong-community-gtfs` | Exists, not evaluated | MIT, last push 5 Nov 2026, one release tagged "testing" (Nov 2025). Candidate for v2 routing because it includes MTR. |
| Real-time bus ETAs | Not checked | Optional in the brief; not needed for v1. |

## 3. Context features

| Item | Status | Detail |
|---|---|---|
| HKO current weather `https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en` | Verified | Rainfall by district, temperature by station, humidity, warning messages. |
| HKO warnings `…?dataType=warnsum&lang=en` | Verified | Active warnings with code, issue and expiry times. |
| HKO history | **Not available** via the archive | 0 archived versions. A daily climate CSV endpoint returned only headers for the query tried; unverified. |
| Open-Meteo archive `https://archive-api.open-meteo.com/v1/archive` | Verified | Hourly temperature, precipitation, humidity for any past date, `timezone=Asia/Hong_Kong`. Third-party, not government data. |
| Public holidays `https://www.1823.gov.hk/common/ical/en.json` | Verified | iCal-as-JSON, 17 holidays each for 2025, 2026, 2027. File starts with a byte-order mark. |
| School holidays, flu season | Not checked | Optional. |

## 4. Geography and population

| Item | Status | Detail |
|---|---|---|
| Address Lookup Service `https://www.als.gov.hk/lookup?q=…&n=1` (header `Accept: application/json`) | Verified | Returns latitude/longitude and district. "Kennedy Town" matched the fire station, so place names resolve to a building, not an area centre. |
| Location search `https://www.map.gov.hk/gs/api/v1.0.0/locationSearch?q=…` | Verified | Returns place names with HK1980 grid `x`,`y` (needs converting to lat/long). Better for place names. `geodata.gov.hk` no longer resolves. |
| 2021 Census by district `https://www.census2021.gov.hk/doc/DC_21C.zip` | Listed, **not opened** | 18 districts. Age columns unconfirmed. |
| 2021 Census by constituency area `…/DCCA_21C.zip` | Listed, **not opened** | Finer areas, for the care-deserts map. |
| District boundaries | Listed, not opened | Bundled with the census datasets on CSDI. |

## 5. Triage knowledge base (for RAG, M4)

Not collected yet: the HA pages could not be opened from the dev machine. Known so far from HA's fee-reform
FAQ and government press releases found by search (to be re-read and cited properly in M4):

- Five triage categories: critical, emergency, urgent, semi-urgent, non-urgent.
- A&E fee for eligible persons rose from $180 to $400 on 1 Jan 2026; triage I and II are exempt.
- Candidate sources: `https://www.ha.org.hk/ho/corpcomm/fncr/index-en.html`, info.gov.hk press releases.

## 6. Crisis numbers (for the safety rules)

| Service | Number | Status |
|---|---|---|
| Emergency | 999 | — |
| The Samaritans | 2896 0000 | Confirmed on samaritans.org.hk: 24-hour, multilingual |
| Suicide Prevention Services | 2382 0000 | Confirmed on several listings: 24-hour; one source says Cantonese only |

## Credits and terms

A&E data: Hospital Authority, via data.gov.hk. Transport: Transport Department, MTR Corporation.
Weather: Hong Kong Observatory; Open-Meteo. Holidays: 1823. Geography and census: Lands Department,
Census and Statistics Department, CSDI. Use follows the data.gov.hk Terms and Conditions.
This project is not affiliated with or endorsed by the Hospital Authority.
