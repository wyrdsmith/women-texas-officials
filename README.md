# Texas Municipal Officials Map

A proof-of-concept interactive web map and data pipeline exploring municipal officials across **1,226 Texas cities** listed in the [Texas Municipal League (TML) Directory](https://www.tml.org).

## Gender Classification

Gender is inferred probabilistically from first names using U.S. Social Security Administration baby name statistics ([`mysoc-gender-detect`](https://github.com/mysociety/gender-detect), 95% confidence threshold) combined with high-precision rules for gendered honorifics (`Mr.`, `Mrs.`, `Ms.`, `Miss`), generational suffixes (`Jr.`, `Sr.`, `II`, `III`, `IV`), explicitly gendered job titles (such as *Alderwoman*, *Councilwoman*, and *Chairwoman*), accent folding, and initial-plus-middle-name patterns.

Roughly 10% of officials have unisex or unlisted names and are labeled **Unknown** (with continuous U.S. SSA `p_female` probabilities preserved in `tml_officials_with_gender.csv` for aggregate analysis).

| Classification | Officials | Share of Filled Positions |
|---|---:|---:|
| Women | 8,201 | 39.11% |
| Men | 10,648 | 50.77% |
| Unknown | 2,122 | 10.12% |
| **Total Filled** | **20,971** | **100.00%** |

*(An additional 117 placeholder rows such as `Position Vacant` are tagged `vacant` and excluded from the map.)*

## Position Categories

Over 4,500 raw TML job titles are grouped into **15 broad categories** for mobile-friendly multi-select filtering—*Mayor*, *Mayor Pro Tem*, *City Council / Alderman*, *City Manager / Administrator*, *City Secretary / Clerk*, *City Attorney / Legal*, *Municipal Court / Judge*, *Police / Public Safety*, *Fire / Emergency Mgmt*, *Finance / Tax / Purchasing*, *Public Works / Utilities*, *Planning / Building / Eng.*, *Parks / Library / Community*, *HR / IT / Communications*, and *Other*—while each official's exact title is preserved when viewing a city.

## Map & Geocoding

City coordinates are sourced from the **2026 U.S. Census Bureau Gazetteer** files (Places and Counties), disambiguating duplicate Texas city names by proximity to each city's listed county centroid(s) (for example, separating the two Cities of Reno in Parker/Tarrant County and Lamar County), with an OpenStreetMap Nominatim fallback for newly incorporated municipalities not yet listed in the Gazetteer.

Map tiles are provided by [OpenFreeMap](https://openfreemap.org) using OpenStreetMap data and rendered with **MapLibre GL JS** in a responsive React + TypeScript + Vite web app styled with the Texas Woman's University brand palette.

## Running Locally

### Data Pipeline (Python 3.15)
```powershell
# 1. Scrape Texas cities and officials from the TML Directory
python tml_scraper.py

# 2. Classify officials' gender (requires pandas, numpy, pyarrow, mysoc-gender-detect)
python gender_classifier.py

# 3. Geocode all cities and export map JSON / GeoJSON
python geocode_cities.py
```

### Web App (React + Vite + MapLibre GL JS)
```powershell
cd web
npm install
npm run dev -- --host
```

Build a static production bundle (`web/dist/`) with:
```powershell
cd web
npm run build
```

## About the Creator

Developed by **Michael Smith** for the **Jane Nelson Institute for Women's Leadership** and the **Center for Leadership Research and Workforce Development** at **Texas Woman's University**.
