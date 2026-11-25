import { useMemo, useRef, useState } from "react";
import type { FilteredCity } from "../types";

interface CitySearchProps {
  cities: FilteredCity[];
  onSelectCity: (city: FilteredCity) => void;
}

export function CitySearch({ cities, onSelectCity }: CitySearchProps) {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return cities
      .filter(
        (city) =>
          city.name.toLowerCase().includes(q) ||
          city.county.toLowerCase().includes(q)
      )
      .slice(0, 8);
  }, [cities, query]);

  const showDropdown = focused && query.trim().length > 0;

  return (
    <div
      className="city-jump-search"
      ref={containerRef}
      onBlur={(e) => {
        if (!containerRef.current?.contains(e.relatedTarget as Node | null)) {
          setFocused(false);
        }
      }}
    >
      <div className="search-field-wrap">
        <span className="search-icon" aria-hidden="true">
          ⌕
        </span>
        <input
          type="search"
          className="search-input"
          placeholder="Search city or county..."
          value={query}
          onFocus={() => setFocused(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            setFocused(true);
          }}
          aria-label="Search Texas cities or counties"
        />
        {query && (
          <button
            type="button"
            className="clear-input-btn"
            onClick={() => setQuery("")}
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {showDropdown && (
        <ul className="search-dropdown" role="listbox">
          {suggestions.length === 0 ? (
            <li className="search-empty">No matching cities with current filters</li>
          ) : (
            suggestions.map((city) => (
              <li key={city.id}>
                <button
                  type="button"
                  className="search-option"
                  onClick={() => {
                    onSelectCity(city);
                    setQuery("");
                    setFocused(false);
                  }}
                >
                  <span className="search-option-name">{city.name}</span>
                  <span className="search-option-meta">
                    {city.county} · {city.matches.length}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
