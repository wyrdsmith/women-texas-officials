import { useEffect, useMemo, useState } from "react";
import { GENDER_META, type FilteredCity } from "../types";

interface CitySheetProps {
  city: FilteredCity | null;
  showGenderBadges: boolean;
  onClose: () => void;
}

export function CitySheet({
  city,
  showGenderBadges,
  onClose,
}: CitySheetProps) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    setQuery("");
  }, [city?.id]);

  const visibleOfficials = useMemo(() => {
    if (!city) return [];
    const q = query.trim().toLowerCase();
    if (!q) return city.matches;
    return city.matches.filter(
      (official) =>
        official.name.toLowerCase().includes(q) ||
        official.position.toLowerCase().includes(q)
    );
  }, [city, query]);

  if (!city) return null;

  const pct =
    city.totalFilled > 0
      ? Math.round((city.matches.length / city.totalFilled) * 100)
      : 0;

  return (
    <aside
      className="sheet city-sheet"
      role="dialog"
      aria-label={`Officials in ${city.name}`}
    >
      <div className="sheet-handle-row">
        <div className="sheet-handle" />
      </div>

      <div className="sheet-header">
        <div className="city-heading">
          <h2 className="sheet-title">{city.name}</h2>
          <p className="sheet-subtitle">
            {city.county} {city.county.includes(",") ? "Counties" : "County"}
            {" · "}
            <strong>{city.matches.length}</strong> of {city.totalFilled}{" "}
            {city.totalFilled === 1 ? "official" : "officials"} ({pct}%)
          </p>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Close city details"
        >
          ✕
        </button>
      </div>

      {city.matches.length > 8 && (
        <div className="city-search-row">
          <input
            type="search"
            className="text-input"
            placeholder={`Search ${city.matches.length} officials in ${city.name}...`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter officials in this city"
          />
        </div>
      )}

      <div className="sheet-body official-list-body">
        {visibleOfficials.length === 0 ? (
          <p className="empty-city-msg">
            No matching officials found for &ldquo;{query}&rdquo;.
          </p>
        ) : (
          <ul className="official-list">
            {visibleOfficials.map((official, idx) => {
              const meta = GENDER_META[official.gender];
              return (
                <li
                  key={`${official.name}-${official.position}-${idx}`}
                  className="official-item"
                >
                  <div className="official-main">
                    <span className="official-name">{official.name}</span>
                    <span className="official-position">{official.position}</span>
                  </div>
                  {showGenderBadges && (
                    <span
                      className="gender-badge"
                      style={{
                        color: meta.textColor,
                        backgroundColor: meta.bg,
                        border: `1px solid ${meta.borderColor}33`,
                      }}
                    >
                      {meta.shortLabel}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
