"""Geocode Texas cities from tml_officials_with_gender.csv and build map data.

Uses official 2026 U.S. Census Bureau Gazetteer files (Places + Counties) to get
authoritative city centroids and disambiguate duplicate Texas city names (such as
the two Cities of Reno in Parker/Tarrant vs. Lamar County) using proximity to the
city's listed county centroid(s). Falls back to OpenStreetMap Nominatim only for
recently incorporated municipalities not yet listed in the Gazetteer.

Outputs:
  - tml_cities_geocoded.csv: All 1,226 cities with coordinates, QA distance, and counts.
  - texas_female_officials.geojson: MapLibre-ready GeoJSON of cities with female officials.
  - web/public/texas_officials.json: Compact full-dataset JSON for the interactive React map
    (supports multi-select filtering by gender and position/role category).
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

DEFAULT_INPUT = Path("tml_officials_with_gender.csv")
DEFAULT_CSV_OUTPUT = Path("tml_cities_geocoded.csv")
DEFAULT_GEOJSON_OUTPUT = Path("texas_female_officials.geojson")
DEFAULT_WEB_JSON_OUTPUT = Path("web/public/texas_officials.json")
DEFAULT_CACHE_DIR = Path(".cache/census_gazetteer")

CENSUS_PLACE_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2026_Gazetteer/2026_Gaz_place_national.zip"
)
CENSUS_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2026_Gazetteer/2026_Gaz_counties_national.zip"
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "women-texas-officials-geocoder/1.0 (https://github.com/Wyrdsmith)"

# Texas geographic bounding box for sanity validation
TX_LAT_MIN, TX_LAT_MAX = 25.8, 36.6
TX_LNG_MIN, TX_LNG_MAX = -106.7, -93.4
MAX_EXPECTED_COUNTY_DIST_MI = 60.0

# Known legal-name / Census naming differences between TML and the Census Gazetteer
TML_TO_CENSUS_ALIASES: dict[str, str] = {
    "anthony city": "anthony",
    "buffalo springs": "buffalo springs lake",
    "cashion": "cashion community",
    "gary": "gary city",
    "pecos city": "town of pecos",
    "woodbranch village": "woodbranch",
}

MAYOR_RE = re.compile(r"^(?:mayor|acting mayor|interim mayor)(?!'s\b)(?:\b|$)", re.IGNORECASE)

# Ordered position-category rules (first match wins)
ROLE_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Mayor Pro Tem", re.compile(r"\bmayor\s+pro[\s-]*tem", re.IGNORECASE)),
    ("Mayor", MAYOR_RE),
    (
        "City Council / Alderman",
        re.compile(
            r"\b(?:council\s*member|councilmember|council\s*man|council\s*woman|"
            r"council\s*person|city\s*council|council\s*(?:place|dist|district|ward|seat|pos|position)|"
            r"alderman|alderwoman|alderperson|commissioner|trustee)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "City Manager / Administrator",
        re.compile(
            r"\b(?:city\s*manager|city\s*administrator|town\s*manager|town\s*administrator|"
            r"village\s*administrator|chief\s*administrative|chief\s*operating|chief\s*of\s*staff)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "City Secretary / Clerk",
        re.compile(
            r"\b(?:city\s*secretary|town\s*secretary|village\s*secretary|"
            r"city\s*clerk|town\s*clerk|records\s*manager|records\s*management)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "City Attorney / Legal",
        re.compile(r"\b(?:attorney|counsel|legal|prosecutor|paralegal)\b", re.IGNORECASE),
    ),
    (
        "Municipal Court / Judge",
        re.compile(r"\b(?:judge|court|magistrate|bailiff|warrant)\b", re.IGNORECASE),
    ),
    (
        "Police / Public Safety",
        re.compile(
            r"\b(?:police|marshal|constable|patrol|detective|dispatch|public\s*safety|"
            r"animal\s*control|code\s*enforcement|code\s*compliance|"
            r"lieutenant|sergeant|captain|commander)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Fire / Emergency Mgmt",
        re.compile(
            r"\b(?:fire|ems|emergency\s*management|emergency\s*medical|paramedic|battalion\s*chief)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Finance / Tax / Purchasing",
        re.compile(
            r"\b(?:finance|financial|treasurer|controller|comptroller|accountant|accounting|"
            r"accounts\s*payable|accounts\s*receivable|budget|tax\s*assessor|purchasing|"
            r"procurement|payroll|billing|audit|auditor|cfo|risk\s*manager)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Public Works / Utilities",
        re.compile(
            r"\b(?:public\s*works|water|wastewater|sewer|utilities|utility|street|streets|"
            r"sanitation|solid\s*waste|electric|gas|fleet|maintenance|superintendent|operations)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Planning / Building / Eng.",
        re.compile(
            r"\b(?:planning|planner|plans\s*examiner|zoning|building|engineer|engineering|"
            r"inspector|development|gis|permit|permits|economic\s*dev|\bedc\b|"
            r"transportation|traffic|airport|aviation)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Parks / Library / Community",
        re.compile(
            r"\b(?:park|parks|recreation|library|librarian|museum|cultural|golf|aquatics|"
            r"senior|youth|community\s*services|civic|tourism|convention|cemetery|housing)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "HR / IT / Communications",
        re.compile(
            r"\b(?:human\s*resources?|hr|personnel|information\s*tech|chief\s*information|\bit\b|"
            r"technology|cio|communications|public\s*information|public\s*relations|\bpio\b|"
            r"marketing|media|multimedia|administrative|executive\s*assistant|office\s*manager|"
            r"health|medical)\b",
            re.IGNORECASE,
        ),
    ),
]

# Display order for the UI multi-select (Mayor first, then Mayor Pro Tem, etc.)
ROLE_CATEGORIES: list[str] = [
    "Mayor",
    "Mayor Pro Tem",
    *[
        name
        for name, _ in ROLE_CATEGORY_RULES
        if name not in ("Mayor", "Mayor Pro Tem")
    ],
    "Other",
]
ROLE_TO_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(ROLE_CATEGORIES)}
GENDER_TO_CODE: dict[str, str] = {"female": "f", "male": "m", "unknown": "u"}


@dataclass(frozen=True, slots=True)
class PlaceCandidate:
    """A candidate Texas place from the U.S. Census Gazetteer."""

    geoid: str
    gaz_name: str
    is_cdp: bool
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class GeocodeMatch:
    """Resolved coordinates and provenance for a Texas city."""

    latitude: float
    longitude: float
    census_geoid: str
    census_name: str
    source: str
    county_distance_miles: float


def categorize_position(position: str) -> str:
    """Map a raw TML position/title string into a clean multi-select role category."""
    text = (position or "").strip()
    for category, pattern in ROLE_CATEGORY_RULES:
        if pattern.search(text):
            return category
    return "Other"


def _clean_common(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"[.'\u2019-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_tml_city(city_name: str) -> str:
    """Normalize a TML city name by stripping only the leading municipal prefix."""
    stripped = re.sub(
        r"^(?:city|town|village)\s+of\s+", "", city_name.strip(), flags=re.IGNORECASE
    )
    return _clean_common(stripped)


def normalize_gazetteer_place(place_name: str) -> str:
    """Normalize a Census Gazetteer place name by stripping its trailing LSAD type."""
    stripped = re.sub(
        r"\s+(?:city|town|village|cdp|municipality)$",
        "",
        place_name.strip(),
        flags=re.IGNORECASE,
    )
    return _clean_common(stripped)


def normalize_county(county_name: str) -> str:
    """Normalize a Texas county name."""
    stripped = re.sub(r"\s+county$", "", county_name.strip(), flags=re.IGNORECASE)
    return _clean_common(stripped)


def slugify_city_id(city_name: str, county_name: str) -> str:
    """Create a stable, unique ID combining city and county (disambiguates Reno, TX)."""
    city_slug = re.sub(r"[^a-z0-9]+", "-", city_name.lower()).strip("-")
    county_slug = re.sub(r"[^a-z0-9]+", "-", county_name.lower()).strip("-")
    return f"{city_slug}--{county_slug}"


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in statute miles between two WGS84 points."""
    earth_radius_mi = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * earth_radius_mi * math.asin(math.sqrt(a))


def ensure_downloaded(url: str, destination: Path, timeout: float = 30.0) -> Path:
    """Download *url* to *destination* if it does not already exist."""
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    destination.write_bytes(data)
    return destination


def load_gazetteer_zip(zip_path: Path) -> pd.DataFrame:
    """Read a Census Gazetteer zip archive into a stripped string DataFrame."""
    with zipfile.ZipFile(zip_path) as archive:
        txt_members = [name for name in archive.namelist() if name.endswith(".txt")]
        if not txt_members:
            raise ValueError(f"No .txt file found inside {zip_path}")
        raw = archive.read(txt_members[0]).decode("utf-8", errors="replace")

    first_line = raw.splitlines()[0]
    sep = "|" if "|" in first_line else "\t"
    df = pd.read_csv(io.StringIO(raw), sep=sep, dtype=str)
    df.columns = [col.strip() for col in df.columns]
    for col in df.columns:
        df[col] = df[col].str.strip()
    return df


def build_gazetteer_indexes(
    cache_dir: Path,
) -> tuple[
    dict[str, list[PlaceCandidate]],
    dict[str, list[PlaceCandidate]],
    dict[str, tuple[float, float]],
]:
    """Load Texas place and county centroid indexes from Census Gazetteer files."""
    place_zip = ensure_downloaded(
        CENSUS_PLACE_URL, cache_dir / "2026_Gaz_place_national.zip"
    )
    county_zip = ensure_downloaded(
        CENSUS_COUNTY_URL, cache_dir / "2026_Gaz_counties_national.zip"
    )

    places_df = load_gazetteer_zip(place_zip)
    counties_df = load_gazetteer_zip(county_zip)

    tx_places = places_df[places_df["USPS"] == "TX"]
    tx_counties = counties_df[counties_df["USPS"] == "TX"]

    county_coords: dict[str, tuple[float, float]] = {
        normalize_county(row["NAME"]): (float(row["INTPTLAT"]), float(row["INTPTLONG"]))
        for _, row in tx_counties.iterrows()
    }

    places_by_key: dict[str, list[PlaceCandidate]] = {}
    places_by_compact: dict[str, list[PlaceCandidate]] = {}
    for _, row in tx_places.iterrows():
        cand = PlaceCandidate(
            geoid=row["GEOID"],
            gaz_name=row["NAME"],
            is_cdp=row["NAME"].lower().endswith(" cdp"),
            latitude=float(row["INTPTLAT"]),
            longitude=float(row["INTPTLONG"]),
        )
        key = normalize_gazetteer_place(row["NAME"])
        compact = key.replace(" ", "")
        places_by_key.setdefault(key, []).append(cand)
        places_by_compact.setdefault(compact, []).append(cand)

    return places_by_key, places_by_compact, county_coords


def nearest_county_distance(
    lat: float,
    lng: float,
    county_points: list[tuple[float, float]],
) -> float:
    """Return distance in miles from (lat, lng) to the nearest listed county centroid."""
    if not county_points:
        return 0.0
    return min(haversine_miles(lat, lng, clat, clng) for clat, clng in county_points)


def load_nominatim_cache(cache_path: Path) -> dict[str, dict[str, object]]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return {}


def save_nominatim_cache(
    cache_path: Path, cache: dict[str, dict[str, object]]
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def geocode_with_nominatim(
    city_name: str,
    county_name: str,
    county_points: list[tuple[float, float]],
    nominatim_cache: dict[str, dict[str, object]],
    nominatim_cache_path: Path,
    timeout: float = 20.0,
) -> GeocodeMatch | None:
    """Fallback geocoder via OpenStreetMap Nominatim (with local disk cache)."""
    cache_key = f"{city_name}|{county_name}"
    if cache_key in nominatim_cache:
        entry = nominatim_cache[cache_key]
        lat = float(entry["latitude"])  # type: ignore[arg-type]
        lng = float(entry["longitude"])  # type: ignore[arg-type]
        dist = nearest_county_distance(lat, lng, county_points)
        return GeocodeMatch(
            latitude=round(lat, 6),
            longitude=round(lng, 6),
            census_geoid="",
            census_name=str(entry.get("display_name", "")),
            source="nominatim",
            county_distance_miles=round(dist, 2),
        )

    short_city = re.sub(
        r"^(?:city|town|village)\s+of\s+", "", city_name.strip(), flags=re.IGNORECASE
    )
    primary_county = county_name.split(",")[0].strip()
    queries = [
        f"{short_city}, {primary_county} County, Texas, USA",
        f"{short_city}, Texas, USA",
    ]

    for query in queries:
        params = urlencode(
            {
                "q": query,
                "format": "jsonv2",
                "limit": 5,
                "countrycodes": "us",
            }
        )
        request = Request(
            f"{NOMINATIM_URL}?{params}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        time.sleep(1.1)  # Respect Nominatim's 1 request/second policy
        with urlopen(request, timeout=timeout) as response:
            results = json.loads(response.read().decode("utf-8"))

        tx_results: list[tuple[float, float, str, float]] = []
        for item in results:
            lat = float(item["lat"])
            lng = float(item["lon"])
            if not (TX_LAT_MIN <= lat <= TX_LAT_MAX and TX_LNG_MIN <= lng <= TX_LNG_MAX):
                continue
            dist = nearest_county_distance(lat, lng, county_points)
            tx_results.append((lat, lng, str(item.get("display_name", "")), dist))

        if tx_results:
            tx_results.sort(key=lambda r: r[3])
            lat, lng, display_name, dist = tx_results[0]
            nominatim_cache[cache_key] = {
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "display_name": display_name,
            }
            save_nominatim_cache(nominatim_cache_path, nominatim_cache)
            return GeocodeMatch(
                latitude=round(lat, 6),
                longitude=round(lng, 6),
                census_geoid="",
                census_name=display_name,
                source="nominatim",
                county_distance_miles=round(dist, 2),
            )

    return None


def resolve_city_coordinates(
    city_name: str,
    county_name: str,
    places_by_key: dict[str, list[PlaceCandidate]],
    places_by_compact: dict[str, list[PlaceCandidate]],
    county_coords: dict[str, tuple[float, float]],
    nominatim_cache: dict[str, dict[str, object]],
    nominatim_cache_path: Path,
    *,
    allow_nominatim: bool = True,
) -> GeocodeMatch | None:
    """Resolve coordinates for a single (city_name, county_name) pair."""
    county_keys = [
        normalize_county(part) for part in county_name.split(",") if part.strip()
    ]
    county_points = [county_coords[k] for k in county_keys if k in county_coords]

    key = normalize_tml_city(city_name)
    candidates: list[PlaceCandidate] = []
    source = "census_gazetteer"

    if key in places_by_key:
        candidates = places_by_key[key]
    elif key.replace(" ", "") in places_by_compact:
        candidates = places_by_compact[key.replace(" ", "")]
        source = "census_gazetteer_compact"
    elif key in TML_TO_CENSUS_ALIASES and TML_TO_CENSUS_ALIASES[key] in places_by_key:
        candidates = places_by_key[TML_TO_CENSUS_ALIASES[key]]
        source = "census_gazetteer_alias"

    if candidates:
        def rank(cand: PlaceCandidate) -> tuple[bool, bool, float]:
            dist = nearest_county_distance(cand.latitude, cand.longitude, county_points)
            return (dist > MAX_EXPECTED_COUNTY_DIST_MI, cand.is_cdp, dist)

        best = min(candidates, key=rank)
        dist = nearest_county_distance(best.latitude, best.longitude, county_points)
        return GeocodeMatch(
            latitude=round(best.latitude, 6),
            longitude=round(best.longitude, 6),
            census_geoid=best.geoid,
            census_name=best.gaz_name,
            source=source,
            county_distance_miles=round(dist, 2),
        )

    if allow_nominatim:
        return geocode_with_nominatim(
            city_name, county_name, county_points, nominatim_cache, nominatim_cache_path
        )

    return None


def build_outputs(
    officials_df: pd.DataFrame,
    cache_dir: Path,
    *,
    include_zero_female: bool = False,
    allow_nominatim: bool = True,
) -> tuple[pd.DataFrame, dict[str, object], dict[str, object], list[tuple[str, str]]]:
    """Geocode all unique cities and build CSV summary, GeoJSON, and web app JSON."""
    places_by_key, places_by_compact, county_coords = build_gazetteer_indexes(cache_dir)
    nominatim_cache_path = cache_dir / "nominatim_cache.json"
    nominatim_cache = load_nominatim_cache(nominatim_cache_path)

    city_rows: list[dict[str, object]] = []
    features: list[dict[str, object]] = []
    web_cities: list[dict[str, object]] = []
    unresolved: list[tuple[str, str]] = []

    grouped = officials_df.groupby(["city_name", "county_name"], sort=False)

    for (city_name, county_name), group in grouped:
        city_str = str(city_name)
        county_str = str(county_name)
        match = resolve_city_coordinates(
            city_str,
            county_str,
            places_by_key,
            places_by_compact,
            county_coords,
            nominatim_cache,
            nominatim_cache_path,
            allow_nominatim=allow_nominatim,
        )
        if match is None:
            unresolved.append((city_str, county_str))
            continue

        total_rows = len(group)
        filled_group = group[group["gender"] != "vacant"]
        filled_count = len(filled_group)
        female_group = filled_group[filled_group["gender"] == "female"]
        female_count = len(female_group)
        male_count = int((filled_group["gender"] == "male").sum())
        unknown_count = int((filled_group["gender"] == "unknown").sum())
        female_pct = (
            round(female_count / filled_count * 100.0, 1) if filled_count > 0 else 0.0
        )
        has_female_mayor = bool(
            female_group["individual_position"]
            .fillna("")
            .str.strip()
            .str.match(MAYOR_RE)
            .any()
        )
        city_id = slugify_city_id(city_str, county_str)

        city_rows.append(
            {
                "city_id": city_id,
                "city_name": city_str,
                "county_name": county_str,
                "latitude": match.latitude,
                "longitude": match.longitude,
                "census_geoid": match.census_geoid,
                "census_name": match.census_name,
                "geocode_source": match.source,
                "county_distance_miles": match.county_distance_miles,
                "total_officials": total_rows,
                "filled_officials": filled_count,
                "female_officials": female_count,
                "male_officials": male_count,
                "unknown_officials": unknown_count,
                "female_pct": female_pct,
                "has_female_mayor": has_female_mayor,
            }
        )

        # Compact full-dataset records for interactive gender + position filtering
        compact_officials = [
            [
                str(row["individual_name"]),
                str(row["individual_position"]),
                GENDER_TO_CODE.get(str(row["gender"]), "u"),
                ROLE_TO_INDEX[categorize_position(str(row["individual_position"]))],
            ]
            for _, row in filled_group.iterrows()
        ]
        web_cities.append(
            {
                "id": city_id,
                "name": city_str,
                "county": county_str,
                "lng": match.longitude,
                "lat": match.latitude,
                "o": compact_officials,
            }
        )

        if include_zero_female or female_count > 0:
            female_officials_list = [
                {
                    "name": str(row["individual_name"]),
                    "position": str(row["individual_position"]),
                }
                for _, row in female_group.iterrows()
            ]
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [match.longitude, match.latitude],
                    },
                    "properties": {
                        "id": city_id,
                        "city_name": city_str,
                        "county_name": county_str,
                        "female_count": female_count,
                        "filled_count": filled_count,
                        "female_pct": female_pct,
                        "has_female_mayor": has_female_mayor,
                        "officials": female_officials_list,
                    },
                }
            )

    cities_df = pd.DataFrame(city_rows)
    geojson: dict[str, object] = {
        "type": "FeatureCollection",
        "features": features,
    }
    web_payload: dict[str, object] = {
        "roles": ROLE_CATEGORIES,
        "cities": web_cities,
    }
    return cities_df, geojson, web_payload, unresolved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Geocode Texas cities and export GeoJSON + web JSON for the officials map."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Input classified officials CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=DEFAULT_CSV_OUTPUT,
        help="Output CSV path with geocoded city summaries (default: %(default)s)",
    )
    parser.add_argument(
        "--geojson-output",
        type=Path,
        default=DEFAULT_GEOJSON_OUTPUT,
        help="Output GeoJSON path for female officials (default: %(default)s)",
    )
    parser.add_argument(
        "--web-json-output",
        type=Path,
        default=DEFAULT_WEB_JSON_OUTPUT,
        help="Output compact full-dataset JSON for the React web app (default: %(default)s)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Directory for caching Census Gazetteer and Nominatim data (default: %(default)s)",
    )
    parser.add_argument(
        "--include-zero-female",
        action="store_true",
        help="Include cities with 0 classified female officials in the GeoJSON output",
    )
    parser.add_argument(
        "--no-nominatim",
        action="store_true",
        help="Disable OpenStreetMap Nominatim fallback for cities absent from Census",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    officials_df = pd.read_csv(args.input)

    cities_df, geojson, web_payload, unresolved = build_outputs(
        officials_df,
        args.cache_dir,
        include_zero_female=args.include_zero_female,
        allow_nominatim=not args.no_nominatim,
    )

    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    cities_df.to_csv(args.csv_output, index=False)

    args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
    args.geojson_output.write_text(
        json.dumps(geojson, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    args.web_json_output.parent.mkdir(parents=True, exist_ok=True)
    args.web_json_output.write_text(
        json.dumps(web_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    feature_count = len(geojson["features"])  # type: ignore[arg-type]
    geojson_kb = args.geojson_output.stat().st_size / 1024.0
    web_kb = args.web_json_output.stat().st_size / 1024.0
    print(f"Geocoded {len(cities_df)} cities -> {args.csv_output}")
    print(
        f"Wrote {feature_count} city features ({geojson_kb:.1f} KB) -> {args.geojson_output}"
    )
    print(
        f"Wrote {len(web_payload['cities'])} cities ({web_kb:.1f} KB) -> {args.web_json_output}"  # type: ignore[arg-type]
    )

    print("\nGeocode sources:")
    for source, count in cities_df["geocode_source"].value_counts().items():
        print(f"  {source:<26} {count:>5}")

    out_of_box = cities_df[
        ~cities_df["latitude"].between(TX_LAT_MIN, TX_LAT_MAX)
        | ~cities_df["longitude"].between(TX_LNG_MIN, TX_LNG_MAX)
    ]
    far = cities_df[cities_df["county_distance_miles"] > MAX_EXPECTED_COUNTY_DIST_MI]
    print(
        f"\nQA checks: out_of_texas_bbox={len(out_of_box)}, "
        f"far_from_county_centroid={len(far)}, unresolved={len(unresolved)}"
    )
    if len(far) > 0:
        print(
            far[
                [
                    "city_name",
                    "county_name",
                    "census_name",
                    "county_distance_miles",
                ]
            ].to_string(index=False),
            file=sys.stderr,
        )

    if unresolved:
        print("Unresolved cities:", file=sys.stderr)
        for cname, cnty in unresolved:
            print(f"  - {cname} ({cnty})", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
