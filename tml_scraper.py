"""Scrape Texas cities and their officials from the TML Directory."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

RESULTS_URL = "https://directory.tml.org/results?search%5Bsubmit%5D="
DEFAULT_CITIES_OUTPUT = Path("tml_cities.csv")
DEFAULT_OFFICIALS_OUTPUT = Path("tml_officials.csv")

# directory.tml.org returns HTTP 406 Not Acceptable unless an HTML Accept header is sent.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class CityRecord:
    """A single city entry from the TML search results page."""

    name: str
    profile_url: str


@dataclass(frozen=True, slots=True)
class OfficialRecord:
    """A single official entry from a TML city profile page."""

    city_name: str
    county_name: str
    individual_name: str
    individual_position: str


def _normalize_text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


class CityListParser(HTMLParser):
    """Extract city names and profile URLs from `<div class="... td-city ...">` blocks."""

    def __init__(self, base_url: str = RESULTS_URL) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.cities: list[CityRecord] = []

        self._td_city_depth = 0
        self._captured_first_link = False
        self._in_target_link = False
        self._current_href: str | None = None
        self._current_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)

        if tag == "div":
            if self._td_city_depth > 0:
                self._td_city_depth += 1
            else:
                classes = (attr_map.get("class") or "").split()
                if "td-city" in classes:
                    self._td_city_depth = 1
                    self._captured_first_link = False
            return

        if (
            tag == "a"
            and self._td_city_depth > 0
            and not self._captured_first_link
            and not self._in_target_link
        ):
            self._in_target_link = True
            self._current_href = attr_map.get("href")
            self._current_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_target_link:
            self._current_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_target_link:
            city_name = _normalize_text(self._current_text_parts)
            profile_url = (
                urljoin(self.base_url, self._current_href.strip())
                if self._current_href
                else ""
            )
            if city_name or profile_url:
                self.cities.append(CityRecord(name=city_name, profile_url=profile_url))

            self._in_target_link = False
            self._captured_first_link = True
            self._current_href = None
            self._current_text_parts = []
            return

        if tag == "div" and self._td_city_depth > 0:
            self._td_city_depth -= 1
            if self._td_city_depth == 0:
                self._captured_first_link = False
                self._in_target_link = False
                self._current_href = None
                self._current_text_parts = []


class CityOfficialsParser(HTMLParser):
    """Extract county name and officials from a TML city profile page."""

    def __init__(self, city_name: str) -> None:
        super().__init__(convert_charrefs=True)
        self.city_name = city_name
        self.county_name: str = ""
        self._raw_officials: list[tuple[str, str]] = []

        self._in_dt = False
        self._dt_parts: list[str] = []
        self._expect_county_dd = False
        self._in_county_dd = False
        self._county_dd_parts: list[str] = []

        self._individuals_depth = 0
        self._individual_depth = 0
        self._position_depth = 0
        self._name_depth = 0

        self._position_parts: list[str] = []
        self._name_link_parts: list[str] = []
        self._name_fallback_parts: list[str] = []
        self._in_name_link = False
        self._captured_name_link = False

    @property
    def officials(self) -> list[OfficialRecord]:
        return [
            OfficialRecord(
                city_name=self.city_name,
                county_name=self.county_name,
                individual_name=name,
                individual_position=position,
            )
            for name, position in self._raw_officials
        ]

    def _reset_individual(self) -> None:
        self._individual_depth = 0
        self._position_depth = 0
        self._name_depth = 0
        self._position_parts = []
        self._name_link_parts = []
        self._name_fallback_parts = []
        self._in_name_link = False
        self._captured_name_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "dt" and not self.county_name:
            self._in_dt = True
            self._dt_parts = []
            self._expect_county_dd = False
            return

        if tag == "dd" and self._expect_county_dd:
            self._expect_county_dd = False
            self._in_county_dd = True
            self._county_dd_parts = []
            return

        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())

        if tag == "div":
            if self._individuals_depth == 0:
                if "individuals" in classes:
                    self._individuals_depth = 1
                return

            self._individuals_depth += 1

            if self._individual_depth == 0:
                if "individual" in classes:
                    self._reset_individual()
                    self._individual_depth = 1
                return

            self._individual_depth += 1

            if self._position_depth > 0:
                self._position_depth += 1
            elif self._name_depth > 0:
                self._name_depth += 1
            elif "position" in classes:
                self._position_depth = 1
            elif "name" in classes:
                self._name_depth = 1
            return

        if (
            tag == "a"
            and self._name_depth > 0
            and not self._captured_name_link
            and not self._in_name_link
        ):
            self._in_name_link = True

    def handle_data(self, data: str) -> None:
        if self._in_dt:
            self._dt_parts.append(data)
        if self._in_county_dd:
            self._county_dd_parts.append(data)
        if self._position_depth > 0:
            self._position_parts.append(data)
        elif self._name_depth > 0:
            if self._in_name_link:
                self._name_link_parts.append(data)
            self._name_fallback_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "dt" and self._in_dt:
            self._in_dt = False
            dt_text = _normalize_text(self._dt_parts)
            self._expect_county_dd = "county" in dt_text.lower()
            self._dt_parts = []
            return

        if tag == "dd" and self._in_county_dd:
            self._in_county_dd = False
            self.county_name = _normalize_text(self._county_dd_parts)
            self._county_dd_parts = []
            return

        if tag == "a" and self._in_name_link:
            self._in_name_link = False
            self._captured_name_link = True
            return

        if tag != "div" or self._individuals_depth == 0:
            return

        if self._position_depth > 0:
            self._position_depth -= 1
        elif self._name_depth > 0:
            self._name_depth -= 1
            if self._name_depth == 0:
                self._in_name_link = False

        if self._individual_depth > 0:
            self._individual_depth -= 1
            if self._individual_depth == 0:
                position = _normalize_text(self._position_parts)
                name_source = (
                    self._name_link_parts
                    if self._captured_name_link
                    else self._name_fallback_parts
                )
                name = _normalize_text(name_source)
                if name or position:
                    self._raw_officials.append((name, position))
                self._reset_individual()

        self._individuals_depth -= 1


def fetch_html(
    url: str,
    timeout: float = 30.0,
    retries: int = 3,
    backoff: float = 1.5,
) -> str:
    """Download the HTML content at *url*, retrying transient failures."""
    attempts = max(1, retries)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        request = Request(url, headers=REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_HTTP_STATUSES or attempt == attempts:
                raise
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == attempts:
                raise

        time.sleep(backoff * attempt)

    assert last_error is not None
    raise last_error


def parse_cities(html: str, base_url: str = RESULTS_URL) -> list[CityRecord]:
    """Parse all city records from the TML directory results HTML."""
    parser = CityListParser(base_url=base_url)
    parser.feed(html)
    parser.close()
    return parser.cities


def parse_officials(html: str, city_name: str) -> list[OfficialRecord]:
    """Parse all officials from a TML city profile page."""
    parser = CityOfficialsParser(city_name=city_name)
    parser.feed(html)
    parser.close()
    return parser.officials


def read_cities_csv(input_path: Path) -> list[CityRecord]:
    """Read city records from a previously generated cities CSV file."""
    cities: list[CityRecord] = []
    with input_path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            name = (row.get("city_name") or "").strip()
            profile_url = (row.get("profile_url") or "").strip()
            if name or profile_url:
                cities.append(CityRecord(name=name, profile_url=profile_url))
    return cities


def write_cities_csv(cities: list[CityRecord], output_path: Path) -> None:
    """Write city records to a UTF-8 CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["city_name", "profile_url"])
        for city in cities:
            writer.writerow([city.name, city.profile_url])


def scrape_officials(
    cities: list[CityRecord],
    output_path: Path,
    *,
    workers: int = 8,
    timeout: float = 30.0,
    retries: int = 3,
    delay: float = 0.0,
) -> tuple[int, list[tuple[CityRecord, str]]]:
    """Fetch every city profile and stream officials to *output_path* in city order."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_cities = len(cities)
    total_officials = 0
    failures: list[tuple[CityRecord, str]] = []

    def fetch_city_officials(city: CityRecord) -> list[OfficialRecord]:
        if delay > 0:
            time.sleep(delay)
        html = fetch_html(city.profile_url, timeout=timeout, retries=retries)
        return parse_officials(html, city_name=city.name)

    with (
        output_path.open("w", newline="", encoding="utf-8") as csv_file,
        ThreadPoolExecutor(max_workers=max(1, workers)) as executor,
    ):
        writer = csv.writer(csv_file)
        writer.writerow(["city_name", "county_name", "individual_name", "individual_position"])
        csv_file.flush()

        futures: list[tuple[CityRecord, Future[list[OfficialRecord]]]] = [
            (city, executor.submit(fetch_city_officials, city)) for city in cities
        ]

        for idx, (city, future) in enumerate(futures, start=1):
            try:
                officials = future.result()
            except Exception as exc:  # noqa: BLE001
                failures.append((city, str(exc)))
                print(
                    f"[{idx}/{total_cities}] FAILED {city.name} ({city.profile_url}): {exc}",
                    file=sys.stderr,
                )
                continue

            for official in officials:
                writer.writerow(
                    [
                        official.city_name,
                        official.county_name,
                        official.individual_name,
                        official.individual_position,
                    ]
                )
            csv_file.flush()
            total_officials += len(officials)

            if idx == 1 or idx % 50 == 0 or idx == total_cities:
                print(
                    f"[{idx}/{total_cities}] {city.name}: {len(officials)} officials "
                    f"(running total: {total_officials})",
                    flush=True,
                )

    return total_officials, failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Texas cities and their officials from the TML Directory."
    )
    parser.add_argument(
        "--url",
        default=RESULTS_URL,
        help="TML results URL to scrape (default: %(default)s)",
    )
    parser.add_argument(
        "--cities-output",
        type=Path,
        default=DEFAULT_CITIES_OUTPUT,
        help="Output CSV path for the city list (default: %(default)s)",
    )
    parser.add_argument(
        "--from-cities-csv",
        type=Path,
        default=None,
        help="Read city list from an existing CSV instead of re-fetching the directory",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OFFICIALS_OUTPUT,
        help="Output CSV path for city officials (default: %(default)s)",
    )
    parser.add_argument(
        "--cities-only",
        action="store_true",
        help="Only scrape the city list CSV and skip scraping city profile pages",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of concurrent requests when scraping city profiles (default: %(default)s)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional per-request delay in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum attempts per HTTP request on transient errors (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of city profiles to scrape (useful for testing)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.from_cities_csv is not None:
        if not args.from_cities_csv.exists():
            print(f"Cities CSV not found: {args.from_cities_csv}", file=sys.stderr)
            return 1
        cities = read_cities_csv(args.from_cities_csv)
        print(f"Loaded {len(cities)} cities from {args.from_cities_csv}")
    else:
        try:
            html = fetch_html(args.url, timeout=args.timeout, retries=args.retries)
        except HTTPError as exc:
            print(
                f"HTTP error {exc.code} fetching {args.url}: {exc.reason}",
                file=sys.stderr,
            )
            return 1
        except URLError as exc:
            print(f"Network error fetching {args.url}: {exc.reason}", file=sys.stderr)
            return 1

        cities = parse_cities(html, base_url=args.url)
        if not cities:
            print("Warning: no cities found in the fetched page.", file=sys.stderr)
            return 1

        write_cities_csv(cities, args.cities_output)
        print(f"Wrote {len(cities)} cities to {args.cities_output}")

    if args.cities_only:
        return 0

    if args.limit is not None:
        cities = cities[: args.limit]

    total_officials, failures = scrape_officials(
        cities,
        args.output,
        workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
    )
    print(f"Wrote {total_officials} officials across {len(cities) - len(failures)} cities to {args.output}")

    if failures:
        print(f"Failed to scrape {len(failures)} city profile(s):", file=sys.stderr)
        for city, err in failures:
            print(f"  - {city.name} ({city.profile_url}): {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
