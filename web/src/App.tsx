import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapGL, {
  Layer,
  NavigationControl,
  Source,
  type LayerProps,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre";
import { CitySearch } from "./components/CitySearch";
import { CitySheet } from "./components/CitySheet";
import { FilterSheet } from "./components/FilterSheet";
import { InfoModal } from "./components/InfoModal";
import {
  ALL_GENDERS,
  GENDER_META,
  TWU_COLORS,
  type DatasetPayload,
  type FilteredCity,
  type GenderCode,
  type Official,
} from "./types";

const OPENFREEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

// Exact geographic extent of Texas (El Paso -> Beaumont, Brownsville -> Panhandle)
const TEXAS_BOUNDS: [number, number, number, number] = [
  -106.65, 25.84, -93.51, 36.5,
];

function getInitialViewState() {
  const width = typeof window !== "undefined" ? window.innerWidth : 1280;
  const isMobile = width < 768;
  const isWideDesktop = width >= 1100;

  return {
    bounds: TEXAS_BOUNDS,
    fitBoundsOptions: {
      padding: isMobile
        ? { top: 155, right: 16, bottom: 56, left: 16 }
        : isWideDesktop
          ? { top: 36, right: 36, bottom: 48, left: 410 }
          : { top: 155, right: 24, bottom: 56, left: 24 },
    },
  };
}

const INITIAL_VIEW = getInitialViewState();

const TEXAS_MAX_BOUNDS: [number, number, number, number] = [
  -114.0, 21.0, -86.0, 41.0,
];

type DotColorKey = GenderCode | "mixed";

function getBrandDotColor(selectedGenders: Set<GenderCode>): string {
  if (selectedGenders.size === 1) {
    const only = nextGender(selectedGenders);
    if (only) return GENDER_META[only].color;
  }
  return TWU_COLORS.maroon;
}

function nextGender(set: Set<GenderCode>): GenderCode | undefined {
  for (const g of set) return g;
  return undefined;
}

export default function App() {
  const mapRef = useRef<MapRef>(null);

  const [dataset, setDataset] = useState<DatasetPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Filter state: default to Female officials across all positions
  const [selectedGenders, setSelectedGenders] = useState<Set<GenderCode>>(
    () => new Set<GenderCode>(["f"])
  );
  const [selectedRoles, setSelectedRoles] = useState<Set<number>>(
    () => new Set<number>()
  );
  const [titleQuery, setTitleQuery] = useState("");

  // UI state
  const [selectedCityId, setSelectedCityId] = useState<string | null>(null);
  const [hoveredCity, setHoveredCity] = useState<{
    name: string;
    county: string;
    count: number;
    x: number;
    y: number;
  } | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [cursor, setCursor] = useState<"grab" | "pointer">("grab");

  useEffect(() => {
    let cancelled = false;
    fetch("./texas_officials.json")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<DatasetPayload>;
      })
      .then((data) => {
        if (!cancelled) setDataset(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(
            err instanceof Error ? err.message : "Failed to load officials data"
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Compute filtered cities, live counts for gender/role selectors, and GeoJSON
  const {
    filteredCities,
    filteredById,
    geojson,
    totalMatchingOfficials,
    genderCounts,
    roleCounts,
    colorCounts,
  } = useMemo(() => {
    const emptyGenderCounts: Record<GenderCode, number> = { f: 0, m: 0, u: 0 };
    const emptyColorCounts: Record<DotColorKey, number> = {
      f: 0,
      m: 0,
      u: 0,
      mixed: 0,
    };
    if (!dataset) {
      return {
        filteredCities: [] as FilteredCity[],
        filteredById: new Map<string, FilteredCity>(),
        geojson: { type: "FeatureCollection" as const, features: [] },
        totalMatchingOfficials: 0,
        genderCounts: emptyGenderCounts,
        roleCounts: [] as number[],
        colorCounts: emptyColorCounts,
      };
    }

    const roles = dataset.roles;
    const roleCountsArr = new Array<number>(roles.length).fill(0);
    const gCounts: Record<GenderCode, number> = { f: 0, m: 0, u: 0 };
    const cCounts: Record<DotColorKey, number> = { f: 0, m: 0, u: 0, mixed: 0 };
    const normalizedTitleQuery = titleQuery.trim().toLowerCase();
    const filterByRole = selectedRoles.size > 0;

    const matchingCities: FilteredCity[] = [];
    const byId = new Map<string, FilteredCity>();
    const features: Array<{
      type: "Feature";
      geometry: { type: "Point"; coordinates: [number, number] };
      properties: {
        id: string;
        name: string;
        county: string;
        count: number;
        colorKey: DotColorKey;
      };
    }> = [];
    let officialSum = 0;

    for (const city of dataset.cities) {
      const matches: Official[] = [];
      let hasF = false;
      let hasM = false;
      let hasU = false;

      for (const [name, position, gender, roleIndex] of city.o) {
        const matchesTitle =
          !normalizedTitleQuery ||
          position.toLowerCase().includes(normalizedTitleQuery);
        if (!matchesTitle) continue;

        const matchesRole = !filterByRole || selectedRoles.has(roleIndex);
        if (matchesRole) {
          gCounts[gender] += 1;
        }

        const matchesGender = selectedGenders.has(gender);
        if (matchesGender) {
          roleCountsArr[roleIndex] += 1;
        }

        if (matchesGender && matchesRole) {
          if (gender === "f") hasF = true;
          else if (gender === "m") hasM = true;
          else hasU = true;

          matches.push({
            name,
            position,
            gender,
            roleIndex,
            roleName: roles[roleIndex] ?? "Other",
          });
        }
      }

      if (matches.length > 0) {
        // Put Mayors (0) & Mayor Pro Tem (1) first, then alphabetical by position & name
        matches.sort((a, b) => {
          const priority = (r: number) => (r <= 1 ? r : 2);
          const pa = priority(a.roleIndex);
          const pb = priority(b.roleIndex);
          if (pa !== pb) return pa - pb;
          return a.position.localeCompare(b.position) || a.name.localeCompare(b.name);
        });

        const distinctGenders = Number(hasF) + Number(hasM) + Number(hasU);
        const colorKey: DotColorKey =
          distinctGenders > 1 ? "mixed" : hasF ? "f" : hasM ? "m" : "u";
        cCounts[colorKey] += 1;

        const record: FilteredCity = {
          id: city.id,
          name: city.name,
          county: city.county,
          lng: city.lng,
          lat: city.lat,
          totalFilled: city.o.length,
          matches,
        };
        matchingCities.push(record);
        byId.set(city.id, record);
        officialSum += matches.length;

        features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: [city.lng, city.lat] },
          properties: {
            id: city.id,
            name: city.name,
            county: city.county,
            count: matches.length,
            colorKey,
          },
        });
      }
    }

    return {
      filteredCities: matchingCities,
      filteredById: byId,
      geojson: {
        type: "FeatureCollection" as const,
        features,
      },
      totalMatchingOfficials: officialSum,
      genderCounts: gCounts,
      roleCounts: roleCountsArr,
      colorCounts: cCounts,
    };
  }, [dataset, selectedGenders, selectedRoles, titleQuery]);

  const selectedCity = selectedCityId ? filteredById.get(selectedCityId) ?? null : null;

  // Clear selection if current filters hide the selected city
  useEffect(() => {
    if (selectedCityId && !filteredById.has(selectedCityId)) {
      setSelectedCityId(null);
    }
  }, [selectedCityId, filteredById]);

  const brandDotColor = useMemo(
    () => getBrandDotColor(selectedGenders),
    [selectedGenders]
  );

  const stateBorderLayer: LayerProps = useMemo(
    () => ({
      id: "state-borders",
      type: "line",
      source: "openmaptiles",
      "source-layer": "boundary",
      minzoom: 3,
      filter: [
        "all",
        ["==", ["get", "admin_level"], 4],
        ["!=", ["get", "maritime"], 1],
        ["!=", ["get", "disputed"], 1],
      ],
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": "#94a3b8",
        "line-opacity": 0.9,
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.2, 8, 2.0, 12, 2.5],
      },
    }),
    []
  );

  const countryBorderLayer: LayerProps = useMemo(
    () => ({
      id: "country-borders",
      type: "line",
      source: "openmaptiles",
      "source-layer": "boundary",
      minzoom: 3,
      filter: [
        "all",
        ["==", ["get", "admin_level"], 2],
        ["!=", ["get", "maritime"], 1],
        ["!=", ["get", "disputed"], 1],
      ],
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": "#64748b",
        "line-opacity": 0.95,
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.5, 8, 2.4, 12, 3.0],
      },
    }),
    []
  );

  const circleLayer: LayerProps = useMemo(
    () => ({
      id: "city-dots",
      type: "circle",
      paint: {
        "circle-color": [
          "match",
          ["get", "colorKey"],
          "f",
          TWU_COLORS.amaranth,
          "m",
          TWU_COLORS.eggplant,
          "u",
          TWU_COLORS.gold,
          TWU_COLORS.maroon,
        ],
        "circle-opacity": 0.88,
        "circle-stroke-color": [
          "match",
          ["get", "colorKey"],
          "u",
          GENDER_META.u.dotStroke,
          TWU_COLORS.white,
        ],
        "circle-stroke-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          4.5,
          1.0,
          9,
          1.75,
        ],
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          4.5,
          [
            "interpolate",
            ["linear"],
            ["get", "count"],
            1,
            3.6,
            5,
            5.0,
            20,
            7.2,
            60,
            10.0,
          ],
          8.5,
          [
            "interpolate",
            ["linear"],
            ["get", "count"],
            1,
            6.5,
            5,
            8.5,
            20,
            12.0,
            60,
            16.5,
          ],
          12,
          [
            "interpolate",
            ["linear"],
            ["get", "count"],
            1,
            9.5,
            5,
            12.0,
            20,
            16.0,
            60,
            21.0,
          ],
        ],
      },
    }),
    []
  );

  const selectedHaloLayer: LayerProps = useMemo(
    () => ({
      id: "city-dot-selected",
      type: "circle",
      filter: ["==", ["get", "id"], selectedCity?.id ?? ""],
      paint: {
        "circle-color": "transparent",
        "circle-stroke-color": "#111827",
        "circle-stroke-width": 2.8,
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          4.5,
          10,
          8.5,
          16,
          12,
          22,
        ],
      },
    }),
    [selectedCity?.id]
  );

  const handleToggleGender = useCallback((code: GenderCode) => {
    setSelectedGenders((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const handleSetGenders = useCallback((genders: GenderCode[]) => {
    setSelectedGenders(new Set(genders));
  }, []);

  const handleToggleRole = useCallback((roleIndex: number) => {
    setSelectedRoles((prev) => {
      const next = new Set(prev);
      if (next.has(roleIndex)) next.delete(roleIndex);
      else next.add(roleIndex);
      return next;
    });
  }, []);

  const handleClearRoles = useCallback(() => {
    setSelectedRoles(new Set());
  }, []);

  const handleApplyPreset = useCallback(
    (preset: "female" | "female_mayors" | "all") => {
      setTitleQuery("");
      if (preset === "female") {
        setSelectedGenders(new Set<GenderCode>(["f"]));
        setSelectedRoles(new Set());
      } else if (preset === "female_mayors") {
        setSelectedGenders(new Set<GenderCode>(["f"]));
        const mayorIdx = dataset?.roles.indexOf("Mayor") ?? -1;
        setSelectedRoles(mayorIdx >= 0 ? new Set([mayorIdx]) : new Set());
      } else {
        setSelectedGenders(new Set<GenderCode>(ALL_GENDERS));
        setSelectedRoles(new Set());
      }
    },
    [dataset]
  );

  const focusCity = useCallback((city: FilteredCity) => {
    setSelectedCityId(city.id);
    setFilterOpen(false);
    const map = mapRef.current;
    if (map) {
      const currentZoom = map.getZoom();
      map.flyTo({
        center: [city.lng, city.lat],
        zoom: Math.max(currentZoom, 8.5),
        duration: 650,
      });
    }
  }, []);

  const handleMapClick = useCallback((event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (feature && feature.properties?.id) {
      setSelectedCityId(String(feature.properties.id));
      setFilterOpen(false);
    } else {
      setSelectedCityId(null);
    }
  }, []);

  const handleMouseMove = useCallback((event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (feature && feature.properties?.name) {
      setCursor("pointer");
      setHoveredCity({
        name: String(feature.properties.name),
        county: String(feature.properties.county ?? ""),
        count: Number(feature.properties.count ?? 0),
        x: event.point.x,
        y: event.point.y,
      });
    } else {
      setCursor("grab");
      setHoveredCity(null);
    }
  }, []);

  const activeFilterSummary = useMemo(() => {
    const parts: string[] = [];
    if (selectedGenders.size === 0) {
      parts.push("No gender");
    } else if (selectedGenders.size === ALL_GENDERS.length) {
      parts.push("All genders");
    } else {
      parts.push(
        ALL_GENDERS.filter((g) => selectedGenders.has(g))
          .map((g) => GENDER_META[g].label)
          .join(" + ")
      );
    }

    if (selectedRoles.size === 1 && dataset) {
      const onlyIdx = [...selectedRoles][0];
      parts.push(dataset.roles[onlyIdx] ?? "1 role");
    } else if (selectedRoles.size > 1) {
      parts.push(`${selectedRoles.size} positions`);
    }

    if (titleQuery.trim()) {
      parts.push(`"${titleQuery.trim()}"`);
    }

    return parts.join(" · ");
  }, [selectedGenders, selectedRoles, titleQuery, dataset]);

  const mayorIndex = dataset?.roles.indexOf("Mayor") ?? -1;
  const isFemaleMayorsActive =
    selectedGenders.size === 1 &&
    selectedGenders.has("f") &&
    selectedRoles.size === 1 &&
    mayorIndex >= 0 &&
    selectedRoles.has(mayorIndex) &&
    !titleQuery.trim();

  const isFemaleAllActive =
    selectedGenders.size === 1 &&
    selectedGenders.has("f") &&
    selectedRoles.size === 0 &&
    !titleQuery.trim();

  return (
    <div className="app-shell">
      {/* Top Floating HUD */}
      <header className="top-hud">
        <div className="hud-card">
          <div className="hud-top-row">
            <div className="brand-block">
              <span
                className="brand-dot"
                style={{
                  backgroundColor: brandDotColor,
                  boxShadow:
                    selectedGenders.size === 1 && selectedGenders.has("u")
                      ? "inset 0 0 0 1px rgba(120, 102, 10, 0.55), 0 0 0 3px rgba(227, 211, 83, 0.28)"
                      : "0 0 0 3px rgba(133, 9, 40, 0.14)",
                }}
                aria-hidden="true"
              />
              <div>
                <h1 className="app-title">Texas Municipal Officials</h1>
                <p className="app-stats">
                  {dataset ? (
                    <>
                      <strong>{filteredCities.length.toLocaleString()}</strong>{" "}
                      {filteredCities.length === 1 ? "city" : "cities"} ·{" "}
                      <strong>
                        {totalMatchingOfficials.toLocaleString()}
                      </strong>{" "}
                      {totalMatchingOfficials === 1 ? "official" : "officials"}
                    </>
                  ) : (
                    "Loading dataset..."
                  )}
                </p>
              </div>
            </div>

            <div className="hud-actions">
              <button
                type="button"
                className="filter-trigger-btn"
                onClick={() => {
                  setFilterOpen((open) => !open);
                  setSelectedCityId(null);
                }}
              >
                <span aria-hidden="true">☰</span>
                <span>Filters</span>
              </button>
              <button
                type="button"
                className="icon-btn subtle-btn"
                onClick={() => setInfoOpen(true)}
                aria-label="About this data"
                title="About this data"
              >
                i
              </button>
            </div>
          </div>

          <div className="hud-controls-row">
            <CitySearch cities={filteredCities} onSelectCity={focusCity} />
          </div>

          <div className="quick-bar" aria-label="Quick filter status">
            <button
              type="button"
              className={`mini-pill ${isFemaleAllActive ? "active" : ""}`}
              onClick={() => handleApplyPreset("female")}
            >
              Women
            </button>
            <button
              type="button"
              className={`mini-pill ${isFemaleMayorsActive ? "active" : ""}`}
              onClick={() => handleApplyPreset("female_mayors")}
            >
              Women Mayors
            </button>
            <button
              type="button"
              className="mini-pill summary-pill"
              onClick={() => {
                setFilterOpen(true);
                setSelectedCityId(null);
              }}
              title="Open gender and position filters"
            >
              {activeFilterSummary} ▾
            </button>
          </div>
        </div>
      </header>

      {/* Map Canvas */}
      <main className="map-container">
        {loadError && (
          <div className="error-banner" role="alert">
            Could not load officials dataset ({loadError}).
          </div>
        )}

        <MapGL
          ref={mapRef}
          initialViewState={INITIAL_VIEW}
          mapStyle={OPENFREEMAP_STYLE}
          maxBounds={TEXAS_MAX_BOUNDS}
          minZoom={3.2}
          maxZoom={14}
          cursor={cursor}
          interactiveLayerIds={["city-dots"]}
          onClick={handleMapClick}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => {
            setCursor("grab");
            setHoveredCity(null);
          }}
        >
          <NavigationControl position="bottom-right" showCompass={false} />

          <Layer {...stateBorderLayer} />
          <Layer {...countryBorderLayer} />

          <Source id="texas-cities" type="geojson" data={geojson}>
            <Layer {...circleLayer} />
            <Layer {...selectedHaloLayer} />
          </Source>
        </MapGL>

        {/* Compact Map Legend (shown when multiple genders are selected) */}
        {selectedGenders.size > 1 && filteredCities.length > 0 && (
          <div className="map-legend" aria-label="Map dot color legend">
            {(
              [
                {
                  key: "f" as const,
                  label: "Women",
                  color: TWU_COLORS.amaranth,
                  stroke: false,
                },
                {
                  key: "m" as const,
                  label: "Men",
                  color: TWU_COLORS.eggplant,
                  stroke: false,
                },
                {
                  key: "u" as const,
                  label: "Unknown",
                  color: TWU_COLORS.gold,
                  stroke: true,
                },
                {
                  key: "mixed" as const,
                  label: "Mixed",
                  color: TWU_COLORS.maroon,
                  stroke: false,
                },
              ] as const
            )
              .filter((item) => colorCounts[item.key] > 0)
              .map((item) => (
                <span key={item.key} className="legend-item">
                  <span
                    className={`legend-dot ${item.stroke ? "legend-dot-gold" : ""}`}
                    style={{ backgroundColor: item.color }}
                    aria-hidden="true"
                  />
                  <span className="legend-label">{item.label}</span>
                  <span className="legend-count">
                    {colorCounts[item.key].toLocaleString()}
                  </span>
                </span>
              ))}
          </div>
        )}

        {/* Desktop hover tooltip */}
        {hoveredCity && !selectedCity && !filterOpen && (
          <div
            className="hover-tooltip"
            style={{ left: hoveredCity.x + 14, top: hoveredCity.y - 12 }}
          >
            <div className="tooltip-name">{hoveredCity.name}</div>
            <div className="tooltip-meta">
              {hoveredCity.county} ·{" "}
              <strong>{hoveredCity.count}</strong>{" "}
              {hoveredCity.count === 1 ? "match" : "matches"}
            </div>
          </div>
        )}
      </main>

      {/* City Detail Bottom Sheet / Side Drawer */}
      <CitySheet
        city={selectedCity}
        showGenderBadges={selectedGenders.size > 1}
        onClose={() => setSelectedCityId(null)}
      />

      {/* Multi-Select Filter Sheet */}
      <FilterSheet
        isOpen={filterOpen}
        onClose={() => setFilterOpen(false)}
        roles={dataset?.roles ?? []}
        selectedGenders={selectedGenders}
        onToggleGender={handleToggleGender}
        onSetGenders={handleSetGenders}
        selectedRoles={selectedRoles}
        onToggleRole={handleToggleRole}
        onClearRoles={handleClearRoles}
        titleQuery={titleQuery}
        onTitleQueryChange={setTitleQuery}
        genderCounts={genderCounts}
        roleCounts={roleCounts}
        matchingCityCount={filteredCities.length}
        matchingOfficialCount={totalMatchingOfficials}
        onApplyPreset={handleApplyPreset}
      />

      {/* Methodology & Attribution Modal */}
      <InfoModal
        isOpen={infoOpen}
        onClose={() => setInfoOpen(false)}
        dataset={dataset}
      />
    </div>
  );
}
