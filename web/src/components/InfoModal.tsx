import { useMemo } from "react";
import {
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  type PieLabelRenderProps,
} from "recharts";
import {
  ALL_GENDERS,
  GENDER_META,
  TWU_COLORS,
  type DatasetPayload,
  type GenderCode,
} from "../types";

interface InfoModalProps {
  isOpen: boolean;
  onClose: () => void;
  dataset: DatasetPayload | null;
}

interface PieSlice {
  code: GenderCode;
  name: string;
  value: number;
  fill: string;
  labelColor: string;
}

interface CategoryStats {
  roleName: string;
  total: number;
  slices: PieSlice[];
}

const RADIAN = Math.PI / 180;

function buildSlices(counts: Record<GenderCode, number>): PieSlice[] {
  return ALL_GENDERS.map((code) => ({
    code,
    name: GENDER_META[code].label,
    value: counts[code],
    fill: GENDER_META[code].color,
    labelColor: code === "u" ? "#3f3500" : "#ffffff",
  })).filter((slice) => slice.value > 0);
}

function makeSliceLabelRenderer(mode: "count" | "percent", fontSize: number) {
  return function renderSliceLabel(props: PieLabelRenderProps) {
    const cx = Number(props.cx ?? 0);
    const cy = Number(props.cy ?? 0);
    const midAngle = Number(props.midAngle ?? 0);
    const innerRadius = Number(props.innerRadius ?? 0);
    const outerRadius = Number(props.outerRadius ?? 0);
    const percent = Number(props.percent ?? 0);
    const value = Number(props.value ?? 0);

    // Hide cramped inside labels on very small slices (still visible in tooltip)
    if (percent < 0.065 || value <= 0) return null;

    const radius = innerRadius + (outerRadius - innerRadius) * 0.58;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);

    const payload = props.payload as PieSlice | undefined;
    const fill = payload?.labelColor ?? "#ffffff";
    const text =
      mode === "count"
        ? value.toLocaleString()
        : `${Math.round(percent * 100)}%`;

    return (
      <text
        x={x}
        y={y}
        fill={fill}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={fontSize}
        fontWeight={700}
        style={{ pointerEvents: "none" }}
      >
        {text}
      </text>
    );
  };
}

const renderOverallLabel = makeSliceLabelRenderer("count", 13);
const renderCategoryLabel = makeSliceLabelRenderer("percent", 11);

function GenderLegend() {
  return (
    <div className="chart-legend" aria-label="Chart gender color key">
      {ALL_GENDERS.map((code) => (
        <span key={code} className="chart-legend-item">
          <span
            className={`legend-dot ${code === "u" ? "legend-dot-gold" : ""}`}
            style={{ backgroundColor: GENDER_META[code].color }}
            aria-hidden="true"
          />
          <span>{GENDER_META[code].label}</span>
        </span>
      ))}
    </div>
  );
}

export function InfoModal({ isOpen, onClose, dataset }: InfoModalProps) {
  const { totalCities, totalOfficials, overallSlices, categoryStats } =
    useMemo(() => {
      const overall: Record<GenderCode, number> = { f: 0, m: 0, u: 0 };
      if (!dataset) {
        return {
          totalCities: 0,
          totalOfficials: 0,
          overallSlices: [] as PieSlice[],
          categoryStats: [] as CategoryStats[],
        };
      }

      const byRole: Array<Record<GenderCode, number>> = dataset.roles.map(
        () => ({ f: 0, m: 0, u: 0 })
      );

      for (const city of dataset.cities) {
        for (const [, , gender, roleIndex] of city.o) {
          overall[gender] += 1;
          const bucket = byRole[roleIndex];
          if (bucket) bucket[gender] += 1;
        }
      }

      const stats: CategoryStats[] = dataset.roles.map((roleName, idx) => {
        const counts = byRole[idx] ?? { f: 0, m: 0, u: 0 };
        const total = counts.f + counts.m + counts.u;
        return {
          roleName,
          total,
          slices: buildSlices(counts),
        };
      });

      return {
        totalCities: dataset.cities.length,
        totalOfficials: overall.f + overall.m + overall.u,
        overallSlices: buildSlices(overall),
        categoryStats: stats,
      };
    }, [dataset]);

  if (!isOpen) return null;

  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} aria-hidden="true" />
      <div
        className="info-modal"
        role="dialog"
        aria-modal="true"
        aria-label="About this dataset and summary statistics"
      >
        <div className="sheet-handle-row">
          <div className="sheet-handle" />
        </div>

        <div className="sheet-header">
          <div>
            <h2 className="sheet-title">About This Map &amp; Data</h2>
            <p className="sheet-subtitle">
              Methodology, statewide gender breakdown, and credits
            </p>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close about dialog"
          >
            ✕
          </button>
        </div>

        <div className="info-modal-body">
          <p className="info-lead">
            This proof-of-concept maps municipal officials across{" "}
            <strong>
              {totalCities > 0 ? totalCities.toLocaleString() : "1,226"} Texas
              cities
            </strong>{" "}
            listed in the{" "}
            <a
              href="https://www.tml.org"
              target="_blank"
              rel="noreferrer"
            >
              Texas Municipal League (TML) Directory
            </a>
            .
          </p>

          {/* Section 1: Gender Classification */}
          <section className="info-section">
            <h3 className="info-section-title">Gender Classification</h3>
            <p>
              Gender is inferred probabilistically from first names using U.S.
              Social Security Administration baby name statistics (
              <code>mysoc-gender-detect</code>, 95% confidence threshold) plus
              high-precision rules for honorifics, generational suffixes, and
              explicitly gendered titles (such as <em>Alderwoman</em>). Roughly
              10% of officials have unisex or unlisted names and are labeled{" "}
              <strong>Unknown</strong>.
            </p>

            {totalOfficials > 0 && (
              <div className="overall-chart-card">
                <GenderLegend />
                <div className="overall-chart-box">
                  <ResponsiveContainer width="100%" height={230}>
                    <PieChart>
                      <Pie
                        data={overallSlices}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={96}
                        startAngle={90}
                        endAngle={-270}
                        stroke={TWU_COLORS.white}
                        strokeWidth={2}
                        label={renderOverallLabel}
                        labelLine={false}
                        isAnimationActive={false}
                      />
                      <Tooltip
                        formatter={(value, name) => {
                          const num = Number(value ?? 0);
                          const pct =
                            totalOfficials > 0
                              ? ((num / totalOfficials) * 100).toFixed(1)
                              : "0.0";
                          return [
                            `${num.toLocaleString()} (${pct}%)`,
                            String(name ?? ""),
                          ];
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <p className="chart-caption-total">
                  Total Officials:{" "}
                  <strong>{totalOfficials.toLocaleString()}</strong>
                </p>
              </div>
            )}
          </section>

          {/* Section 2: Position Categories */}
          <section className="info-section">
            <h3 className="info-section-title">Position Categories</h3>
            <p>
              Over 4,500 raw TML job titles are grouped into{" "}
              {categoryStats.length || 15} broad categories for filtering; exact
              titles are preserved when viewing a city.
            </p>

            {categoryStats.length > 0 && (
              <>
                <GenderLegend />
                <div className="category-charts-grid">
                  {categoryStats.map((cat) => (
                    <div key={cat.roleName} className="category-chart-card">
                      <div className="category-chart-box">
                        <ResponsiveContainer width="100%" height={168}>
                          <PieChart>
                            <Pie
                              data={cat.slices}
                              dataKey="value"
                              nameKey="name"
                              cx="50%"
                              cy="50%"
                              outerRadius={72}
                              startAngle={90}
                              endAngle={-270}
                              stroke={TWU_COLORS.white}
                              strokeWidth={1.5}
                              label={renderCategoryLabel}
                              labelLine={false}
                              isAnimationActive={false}
                            />
                            <Tooltip
                              formatter={(value, name) => {
                                const num = Number(value ?? 0);
                                const pct =
                                  cat.total > 0
                                    ? ((num / cat.total) * 100).toFixed(1)
                                    : "0.0";
                                return [
                                  `${num.toLocaleString()} (${pct}%)`,
                                  String(name ?? ""),
                                ];
                              }}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <h4 className="category-chart-name">{cat.roleName}</h4>
                      <p className="category-chart-count">
                        {cat.total.toLocaleString()}{" "}
                        {cat.total === 1 ? "official" : "officials"}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>

          {/* Section 3: Map & Geocoding */}
          <section className="info-section">
            <h3 className="info-section-title">Map &amp; Geocoding</h3>
            <p>
              City coordinates come from 2026 U.S. Census Gazetteer files
              (disambiguated by county, e.g. both Cities of Reno). Map tiles are
              provided by{" "}
              <a
                href="https://openfreemap.org"
                target="_blank"
                rel="noreferrer"
              >
                OpenFreeMap
              </a>{" "}
              using OpenStreetMap data, rendered with MapLibre GL JS.
            </p>
          </section>

          {/* Section 4: About the Creator */}
          <section className="info-section creator-section">
            <h3 className="info-section-title">About the Creator</h3>
            <p>
              Developed by{" "}
              <a
                href="https://wyrdsmith.io"
                target="_blank"
                rel="noreferrer"
              ><strong>Michael Smith</strong></a> for the{" "}
              <a
                href="https://twu.edu/institute-womens-leadership/"
                target="_blank"
                rel="noreferrer"
              ><strong>Jane Nelson Institute for Women&apos;s Leadership</strong></a>{" "}
              and the{" "}
              <strong>
                Center for Leadership Research and Workforce Development
              </strong>{" "}
              at{" "}
              <a
                href="https://twu.edu/"
                target="_blank"
                rel="noreferrer"
              ><strong>Texas Woman&apos;s University</strong></a>.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}
