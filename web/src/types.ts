export type GenderCode = "f" | "m" | "u";

/** Compact tuple stored in texas_officials.json: [name, position, genderCode, roleIndex] */
export type CompactOfficial = [string, string, GenderCode, number];

export interface RawCityRecord {
  id: string;
  name: string;
  county: string;
  lng: number;
  lat: number;
  o: CompactOfficial[];
}

export interface DatasetPayload {
  roles: string[];
  cities: RawCityRecord[];
}

export interface Official {
  name: string;
  position: string;
  gender: GenderCode;
  roleIndex: number;
  roleName: string;
}

export interface FilteredCity {
  id: string;
  name: string;
  county: string;
  lng: number;
  lat: number;
  totalFilled: number;
  matches: Official[];
}

/** Official Texas Woman's University (TWU) Brand Palette */
export const TWU_COLORS = {
  maroon: "#850928",
  white: "#FFFFFF",
  amaranth: "#CA1E50",
  eggplant: "#5C315E",
  gold: "#E3D353",
} as const;

export const GENDER_META: Record<
  GenderCode,
  {
    label: string;
    shortLabel: string;
    color: string;
    dotStroke: string;
    textColor: string;
    borderColor: string;
    bg: string;
  }
> = {
  f: {
    label: "Women",
    shortLabel: "Woman",
    color: TWU_COLORS.amaranth, // #CA1E50
    dotStroke: TWU_COLORS.white,
    textColor: "#A61640",
    borderColor: TWU_COLORS.amaranth,
    bg: "#FCECF1",
  },
  m: {
    label: "Men",
    shortLabel: "Man",
    color: TWU_COLORS.eggplant, // #5C315E
    dotStroke: TWU_COLORS.white,
    textColor: TWU_COLORS.eggplant,
    borderColor: TWU_COLORS.eggplant,
    bg: "#F3ECF4",
  },
  u: {
    label: "Unknown",
    shortLabel: "Unknown",
    color: TWU_COLORS.gold, // #E3D353
    dotStroke: "#78660A", // Dark gold stroke so Gold dots pop cleanly on Positron
    textColor: "#6B5A00", // WCAG AA accessible text for Gold chips/badges
    borderColor: "#B8A51E",
    bg: "#FBF7D5",
  },
};

export const ALL_GENDERS: GenderCode[] = ["f", "m", "u"];
