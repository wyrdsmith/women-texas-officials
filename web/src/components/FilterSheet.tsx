import { useMemo } from "react";
import { ALL_GENDERS, GENDER_META, type GenderCode } from "../types";

interface FilterSheetProps {
  isOpen: boolean;
  onClose: () => void;
  roles: string[];
  selectedGenders: Set<GenderCode>;
  onToggleGender: (gender: GenderCode) => void;
  onSetGenders: (genders: GenderCode[]) => void;
  selectedRoles: Set<number>;
  onToggleRole: (roleIndex: number) => void;
  onClearRoles: () => void;
  titleQuery: string;
  onTitleQueryChange: (value: string) => void;
  genderCounts: Record<GenderCode, number>;
  roleCounts: number[];
  matchingCityCount: number;
  matchingOfficialCount: number;
  onApplyPreset: (preset: "female" | "female_mayors" | "all") => void;
}

export function FilterSheet({
  isOpen,
  onClose,
  roles,
  selectedGenders,
  onToggleGender,
  onSetGenders,
  selectedRoles,
  onToggleRole,
  onClearRoles,
  titleQuery,
  onTitleQueryChange,
  genderCounts,
  roleCounts,
  matchingCityCount,
  matchingOfficialCount,
  onApplyPreset,
}: FilterSheetProps) {
  const mayorIndex = useMemo(() => roles.indexOf("Mayor"), [roles]);

  const isFemaleOnly =
    selectedGenders.size === 1 &&
    selectedGenders.has("f") &&
    selectedRoles.size === 0 &&
    !titleQuery.trim();

  const isFemaleMayors =
    selectedGenders.size === 1 &&
    selectedGenders.has("f") &&
    selectedRoles.size === 1 &&
    mayorIndex >= 0 &&
    selectedRoles.has(mayorIndex) &&
    !titleQuery.trim();

  const isAll =
    selectedGenders.size === ALL_GENDERS.length &&
    selectedRoles.size === 0 &&
    !titleQuery.trim();

  if (!isOpen) return null;

  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} aria-hidden="true" />
      <aside
        className="sheet filter-sheet"
        role="dialog"
        aria-label="Filter officials"
      >
        <div className="sheet-handle-row">
          <div className="sheet-handle" />
        </div>

        <div className="sheet-header">
          <div>
            <h2 className="sheet-title">Filter Officials</h2>
            <p className="sheet-subtitle">
              Showing{" "}
              <strong>{matchingOfficialCount.toLocaleString()}</strong>{" "}
              {matchingOfficialCount === 1 ? "official" : "officials"} in{" "}
              <strong>{matchingCityCount.toLocaleString()}</strong>{" "}
              {matchingCityCount === 1 ? "city" : "cities"}
            </p>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close filters"
          >
            ✕
          </button>
        </div>

        <div className="sheet-body">
          {/* Quick Presets */}
          <section className="filter-section">
            <div className="section-header">
              <span className="section-label">Quick Views</span>
            </div>
            <div className="preset-row">
              <button
                type="button"
                className={`preset-chip ${isFemaleOnly ? "active" : ""}`}
                onClick={() => onApplyPreset("female")}
              >
                Women Officials
              </button>
              <button
                type="button"
                className={`preset-chip ${isFemaleMayors ? "active" : ""}`}
                onClick={() => onApplyPreset("female_mayors")}
              >
                Women Mayors
              </button>
              <button
                type="button"
                className={`preset-chip ${isAll ? "active" : ""}`}
                onClick={() => onApplyPreset("all")}
              >
                Everyone
              </button>
            </div>
          </section>

          {/* Gender Multi-Select */}
          <section className="filter-section">
            <div className="section-header">
              <span className="section-label">Gender (multi-select)</span>
              <button
                type="button"
                className="text-action-btn"
                onClick={() =>
                  onSetGenders(
                    selectedGenders.size === ALL_GENDERS.length
                      ? ["f"]
                      : [...ALL_GENDERS]
                  )
                }
              >
                {selectedGenders.size === ALL_GENDERS.length
                  ? "Women only"
                  : "Select all"}
              </button>
            </div>

            <div className="gender-grid">
              {ALL_GENDERS.map((code) => {
                const meta = GENDER_META[code];
                const checked = selectedGenders.has(code);
                return (
                  <button
                    key={code}
                    type="button"
                    className={`gender-toggle ${checked ? "checked" : ""}`}
                    style={
                      checked
                        ? {
                            borderColor: meta.borderColor,
                            backgroundColor: meta.bg,
                            color: meta.textColor,
                          }
                        : undefined
                    }
                    onClick={() => onToggleGender(code)}
                    aria-pressed={checked}
                  >
                    <span
                      className="swatch-dot"
                      style={{
                        backgroundColor: meta.color,
                        boxShadow:
                          code === "u"
                            ? "inset 0 0 0 1px rgba(120, 102, 10, 0.45)"
                            : undefined,
                      }}
                    />
                    <span className="gender-toggle-label">{meta.label}</span>
                    <span className="count-pill">
                      {genderCounts[code].toLocaleString()}
                    </span>
                  </button>
                );
              })}
            </div>
            {selectedGenders.size === 0 && (
              <p className="inline-hint">
                Select at least one gender above to display cities on the map.
              </p>
            )}
          </section>

          {/* Position / Title Multi-Select */}
          <section className="filter-section">
            <div className="section-header">
              <span className="section-label">
                Position / Title{" "}
                {selectedRoles.size > 0
                  ? `(${selectedRoles.size} selected)`
                  : "(all)"}
              </span>
              {selectedRoles.size > 0 && (
                <button
                  type="button"
                  className="text-action-btn"
                  onClick={onClearRoles}
                >
                  Show all positions
                </button>
              )}
            </div>

            <div className="keyword-input-wrap">
              <input
                type="search"
                className="text-input"
                placeholder="Optional title keyword (e.g. Fire Chief, Place 1)..."
                value={titleQuery}
                onChange={(e) => onTitleQueryChange(e.target.value)}
                aria-label="Filter by exact title keyword"
              />
              {titleQuery && (
                <button
                  type="button"
                  className="clear-input-btn"
                  onClick={() => onTitleQueryChange("")}
                  aria-label="Clear title keyword"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="role-list" role="group" aria-label="Position categories">
              <button
                type="button"
                className={`role-chip ${selectedRoles.size === 0 ? "checked" : ""}`}
                onClick={onClearRoles}
                aria-pressed={selectedRoles.size === 0}
              >
                <span className="role-check">
                  {selectedRoles.size === 0 ? "✓" : ""}
                </span>
                <span className="role-name">All Positions</span>
              </button>

              {roles.map((roleName, idx) => {
                const checked = selectedRoles.has(idx);
                const count = roleCounts[idx] ?? 0;
                return (
                  <button
                    key={roleName}
                    type="button"
                    className={`role-chip ${checked ? "checked" : ""}`}
                    onClick={() => onToggleRole(idx)}
                    aria-pressed={checked}
                  >
                    <span className="role-check">{checked ? "✓" : ""}</span>
                    <span className="role-name">{roleName}</span>
                    <span className="role-count">{count.toLocaleString()}</span>
                  </button>
                );
              })}
            </div>
          </section>
        </div>

        <div className="sheet-footer">
          <button type="button" className="primary-btn" onClick={onClose}>
            View {matchingCityCount.toLocaleString()}{" "}
            {matchingCityCount === 1 ? "City" : "Cities"} on Map
          </button>
        </div>
      </aside>
    </>
  );
}
