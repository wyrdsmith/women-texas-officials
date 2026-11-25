"""Classify Texas municipal officials' gender using mysoc-gender-detect.

Combines strict US SSA first-name matching (threshold=0.95, lower_threshold=0.75)
with high-precision name-cleaning and structural rules, while exporting both a
`gender_source` provenance column and a continuous `p_female` probability column
for transparent aggregate analysis of below-threshold names.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from mysoc_gender_detect import GenderDetect
from mysoc_gender_detect.datasets import load_dataset

DEFAULT_INPUT = Path("tml_officials.csv")
DEFAULT_OUTPUT = Path("tml_officials_with_gender.csv")

VACANT_RE = re.compile(r"\b(?:vacant|unfilled|tbd)\b", re.IGNORECASE)
FEMALE_TITLE_RE = re.compile(
    r"\b(?:alderwoman|councilwoman|chairwoman)\b", re.IGNORECASE
)
INITIAL_TOKEN_RE = re.compile(r"^(?:[A-Za-z]\.?|[A-Za-z]\.[A-Za-z]\.?)$")
NICKNAME_RE = re.compile(r'"[^"]*"|\([^)]*\)')

MALE_HONORIFICS = frozenset({"mr"})
FEMALE_HONORIFICS = frozenset({"mrs", "ms", "miss"})
NEUTRAL_HONORIFICS = frozenset(
    {
        "dr",
        "hon",
        "honorable",
        "rev",
        "reverend",
        "judge",
        "chief",
        "capt",
        "captain",
        "lt",
        "sgt",
        "col",
        "gen",
        "prof",
        "mayor",
    }
)
ALL_HONORIFICS = MALE_HONORIFICS | FEMALE_HONORIFICS | NEUTRAL_HONORIFICS
JR_SR_SUFFIXES = frozenset({"Jr", "Jr.", "Sr", "Sr."})
ROMAN_SUFFIXES = frozenset({"II", "III", "IV"})
GENERATIONAL_SUFFIXES = JR_SR_SUFFIXES | ROMAN_SUFFIXES


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Result of classifying a single official row."""

    gender: str
    gender_source: str
    p_female: float | None


@dataclass(frozen=True, slots=True)
class ParsedName:
    """Structured components extracted from an official's full name string."""

    candidate: str | None
    candidate_kind: str | None
    honorific_gender: str | None
    has_jr_sr_suffix: bool
    has_roman_suffix: bool


def ascii_fold(text: str) -> str:
    """Strip diacritics / combining marks (e.g., 'Renée' -> 'Renee')."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_token(token: str) -> str:
    """Normalize a single name token to match mysoc_gender_detect's US table."""
    folded = ascii_fold(token).lower()
    return re.sub(r"[^\w\s]", "", folded).strip()


def is_initial(token: str) -> bool:
    """Return True if *token* is a single or double initial (e.g. 'J.', 'E.A.')."""
    return bool(INITIAL_TOKEN_RE.match(token.strip()))


def build_probability_lookup(country: str) -> dict[str, float]:
    """Map every normalized name in *country*'s dataset to P(female)."""
    frame = load_dataset(country)
    p_female_series = frame["winner_proportion"].where(
        frame["predicted"] == "F", 1.0 - frame["winner_proportion"]
    )
    return dict(zip(frame["name"], p_female_series.astype(float), strict=True))


def parse_name_components(full_name: str) -> ParsedName:
    """Extract candidate name info from an official's full name string."""
    segments = [seg.strip() for seg in full_name.split(",") if seg.strip()]
    base = segments[0] if segments else ""
    trailing_segments = segments[1:]

    # Generational suffix in its own comma-separated segment (avoids matching "Attorney II")
    has_jr_sr = any(seg in JR_SR_SUFFIXES for seg in trailing_segments)
    has_roman = any(seg in ROMAN_SUFFIXES for seg in trailing_segments)

    # Remove quoted or parenthesized nicknames for core token parsing
    cleaned_base = NICKNAME_RE.sub(" ", base)
    tokens = [tok for tok in cleaned_base.split() if tok]

    # Strip leading honorific prefixes (e.g., "Dr.", "Hon.", "Mr.")
    had_prefix = False
    honorific_gender: str | None = None
    while tokens:
        lead_key = normalize_token(tokens[0])
        if lead_key in ALL_HONORIFICS:
            had_prefix = True
            if lead_key in MALE_HONORIFICS:
                honorific_gender = "male"
            elif lead_key in FEMALE_HONORIFICS:
                honorific_gender = "female"
            tokens.pop(0)
        else:
            break

    # Also detect a trailing generational suffix without a preceding comma
    if len(tokens) >= 3 and tokens[-1] in GENERATIONAL_SUFFIXES:
        suffix = tokens.pop()
        if suffix in JR_SR_SUFFIXES:
            has_jr_sr = True
        else:
            has_roman = True

    if not tokens:
        return ParsedName(None, None, honorific_gender, has_jr_sr, has_roman)

    first = tokens[0]
    if is_initial(first):
        # When the first token is an initial and there is a non-initial middle given name
        # before the surname (e.g. "J. Paul Coker", "L. Monique J. Taylor"), use it.
        if len(tokens) >= 3 and not is_initial(tokens[1]):
            return ParsedName(
                tokens[1],
                "initial_middle_name",
                honorific_gender,
                has_jr_sr,
                has_roman,
            )
        return ParsedName(None, None, honorific_gender, has_jr_sr, has_roman)

    kind = "prefix_stripped" if had_prefix else "name_us_95"
    return ParsedName(first, kind, honorific_gender, has_jr_sr, has_roman)


def _match_candidate_name(
    candidate: str,
    candidate_kind: str | None,
    strict_lookup: dict[str, str],
    prob_lookup: dict[str, float],
) -> tuple[str | None, str | None, float | None]:
    """Look up *candidate* in the strict SSA table (plus hyphenated fallback)."""
    raw_norm = re.sub(r"[^\w\s]", "", candidate.lower()).strip()
    folded_norm = normalize_token(candidate)
    p_val = prob_lookup.get(folded_norm)
    p_female = round(p_val, 4) if p_val is not None else None

    strict_hit = strict_lookup.get(folded_norm)
    if strict_hit is not None:
        gender = "male" if strict_hit == "M" else "female"
        source = candidate_kind or "name_us_95"
        if source == "name_us_95" and folded_norm != raw_norm:
            source = "name_accent_folded"
        return gender, source, p_female

    if "-" in candidate:
        part_hits: set[str] = set()
        part_probs: list[float] = []
        for part in candidate.split("-"):
            part_norm = normalize_token(part)
            if not part_norm or is_initial(part):
                continue
            hit = strict_lookup.get(part_norm)
            if hit is not None:
                part_hits.add(hit)
            part_p = prob_lookup.get(part_norm)
            if part_p is not None:
                part_probs.append(part_p)

        if p_female is None and part_probs:
            p_female = round(sum(part_probs) / len(part_probs), 4)

        if len(part_hits) == 1:
            only_hit = next(iter(part_hits))
            gender = "male" if only_hit == "M" else "female"
            return gender, "hyphenated_name", p_female

    return None, None, p_female


def classify_official(
    individual_name: str,
    individual_position: str,
    strict_lookup: dict[str, str],
    prob_lookup: dict[str, float],
) -> ClassificationResult:
    """Classify a single official row with provenance and continuous P(female).

    Precedence:
      1. Vacant / empty placeholder
      2. Explicit signals: gendered honorific, explicitly female title, Jr./Sr. suffix
      3. Direct first-name strict SSA match (name_us_95 / prefix_stripped / accent / hyphen)
      4. Indirect fallbacks: Roman numeral suffix (II/III/IV), then initial_middle_name
    """
    name = (individual_name or "").strip()
    position = (individual_position or "").strip()

    if not name or VACANT_RE.search(name):
        return ClassificationResult(gender="vacant", gender_source="vacant", p_female=None)

    parsed = parse_name_components(name)

    name_gender: str | None = None
    name_source: str | None = None
    p_female: float | None = None
    if parsed.candidate is not None:
        name_gender, name_source, p_female = _match_candidate_name(
            parsed.candidate, parsed.candidate_kind, strict_lookup, prob_lookup
        )

    # 2a. Gendered honorific prefix (Mr. / Mrs. / Ms. / Miss)
    if parsed.honorific_gender is not None:
        return ClassificationResult(
            gender=parsed.honorific_gender,
            gender_source="honorific",
            p_female=p_female,
        )

    # 2b. Explicitly female job title (Alderwoman / Councilwoman / Chairwoman)
    if FEMALE_TITLE_RE.search(position):
        return ClassificationResult(
            gender="female",
            gender_source="title_female",
            p_female=p_female,
        )

    # 2c. Unambiguous Jr. / Sr. generational suffix
    if parsed.has_jr_sr_suffix:
        return ClassificationResult(
            gender="male",
            gender_source="generational_suffix",
            p_female=p_female,
        )

    # 3. Direct first-name strict SSA match (before Roman numerals, which can be job grades)
    if name_gender is not None and parsed.candidate_kind != "initial_middle_name":
        return ClassificationResult(
            gender=name_gender,
            gender_source=name_source or "name_us_95",
            p_female=p_female,
        )

    # 4a. Roman numeral generational suffix (II / III / IV)
    if parsed.has_roman_suffix:
        return ClassificationResult(
            gender="male",
            gender_source="generational_suffix",
            p_female=p_female,
        )

    # 4b. Middle name rescued after a leading initial (e.g. "J. Paul Coker")
    if name_gender is not None:
        return ClassificationResult(
            gender=name_gender,
            gender_source=name_source or "initial_middle_name",
            p_female=p_female,
        )

    return ClassificationResult(
        gender="unknown", gender_source="unknown", p_female=p_female
    )


def classify_dataframe(
    df: pd.DataFrame,
    *,
    country: str = "us",
    threshold: float = 0.95,
    lower_threshold: float = 0.75,
) -> pd.DataFrame:
    """Return a copy of *df* with `gender`, `gender_source`, and `p_female` columns."""
    detector = GenderDetect(
        country=country, threshold=threshold, lower_threshold=lower_threshold
    )
    prob_lookup = build_probability_lookup(country)

    results = [
        classify_official(
            str(name) if pd.notna(name) else "",
            str(pos) if pd.notna(pos) else "",
            detector.lookup,
            prob_lookup,
        )
        for name, pos in zip(
            df["individual_name"], df["individual_position"], strict=True
        )
    ]

    out = df.copy()
    out["gender"] = [r.gender for r in results]
    out["gender_source"] = [r.gender_source for r in results]
    out["p_female"] = pd.Series(
        [r.p_female for r in results], index=out.index, dtype="Float64"
    )
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify genders of Texas municipal officials from TML data."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Input officials CSV path (default: %(default)s)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output CSV path with gender columns (default: %(default)s)",
    )
    parser.add_argument(
        "--country",
        default="us",
        help="mysoc-gender-detect dataset ID (default: %(default)s)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.95,
        help="Minimum winner_proportion for strict name match (default: %(default)s)",
    )
    parser.add_argument(
        "--lower-threshold",
        type=float,
        default=0.75,
        help="Minimum confidence lower bound for strict name match (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    df = pd.read_csv(args.input)
    classified = classify_dataframe(
        df,
        country=args.country,
        threshold=args.threshold,
        lower_threshold=args.lower_threshold,
    )
    classified.to_csv(args.output, index=False)

    total = len(classified)
    non_vacant = classified[classified["gender"] != "vacant"]
    real_total = len(non_vacant)
    gender_counts = classified["gender"].value_counts()
    source_counts = classified["gender_source"].value_counts()

    print(f"Wrote {total} rows to {args.output}")
    print("\nOverall gender counts:")
    for label, count in gender_counts.items():
        print(f"  {label:<10} {count:>6} ({count / total * 100:5.2f}%)")

    print(f"\nAmong {real_total} filled positions (excluding vacant):")
    for label in ("male", "female", "unknown"):
        count = int((non_vacant["gender"] == label).sum())
        print(f"  {label:<10} {count:>6} ({count / real_total * 100:5.2f}%)")

    print("\nBreakdown by gender_source:")
    for source, count in source_counts.items():
        print(f"  {source:<22} {count:>6}")

    # Probabilistic aggregate estimate using p_female for below-threshold unknowns
    unk_with_prob = non_vacant[
        (non_vacant["gender"] == "unknown") & (non_vacant["p_female"].notna())
    ]
    unk_no_prob = non_vacant[
        (non_vacant["gender"] == "unknown") & (non_vacant["p_female"].isna())
    ]
    strict_female = int((non_vacant["gender"] == "female").sum())
    expected_unk_female = float(unk_with_prob["p_female"].sum())
    denom_with_prob = real_total - len(unk_no_prob)
    print(
        f"\nProbabilistic estimate (strict female + sum of p_female on {len(unk_with_prob)} "
        f"unknowns in SSA; {len(unk_no_prob)} have no SSA probability):"
    )
    print(
        f"  Expected female: {strict_female + expected_unk_female:,.1f} / "
        f"{denom_with_prob:,} ({(strict_female + expected_unk_female) / denom_with_prob * 100:.2f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
