"""
cleanup_tags.py — Remove noisy tags from Immich in two phases

Phase 1 — Pattern cleanup (--apply):
  Deletes tags that are prices, dates, pure numbers/measurements, times,
  ages, ratings, or filenames. Regex handles clear cases; digit-containing
  tags that don't match regex are sent to Ollama (qwen2.5:7b) for a second
  opinion. Runs a dry-run preview by default.

Phase 2 — Small-tag review (--export-small FILE):
  Writes all remaining tags with ≤5 assets to a text file. One line per tag.
  Delete lines you want to KEEP, then run --apply-file to delete the rest.

Phase 3 — Apply review file (--apply-file FILE):
  Deletes every tag still listed in FILE via the Immich API.

Usage:
    # Preview what pattern cleanup would delete
    ./venv/bin/python cleanup_tags.py

    # Run pattern cleanup and export ≤5 tags for review
    ./venv/bin/python cleanup_tags.py --apply --export-small /tmp/small_tags.txt

    # After editing the review file, delete the remainder
    ./venv/bin/python cleanup_tags.py --apply-file /tmp/small_tags.txt
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import ollama

API_KEY = "l2NOuHnPXOpT3FeAJjGQ1iAgicI8bXUFVGsouWB78"
IMMICH_API = "http://localhost:2283/api/tags"
OLLAMA_HOST = "http://192.168.68.16:11435"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_BATCH = 80
SMALL_TAG_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
          r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_YEAR = r"(?:19|20)\d{2}"

PATTERNS = [
    # Prices
    (re.compile(r"^\s*[£$€¥₹]\s*[\d.,]+\s*$", re.I), "price"),
    (re.compile(r"^\s*[\d.,]+\s*[£$€¥₹]\s*$", re.I), "price"),
    (re.compile(r"^\s*\d+\s*p\s*$", re.I), "price"),            # 50p
    (re.compile(r"\bprice\b", re.I), "price"),                   # "800 price"

    # Standalone year or date
    (re.compile(r"^\s*" + _YEAR + r"\s*$"), "date"),
    (re.compile(r"^\s*" + _MONTH + r"\s+" + _YEAR + r"\s*$", re.I), "date"),
    (re.compile(r"^\s*" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*" + _YEAR + r"\s*$", re.I), "date"),
    (re.compile(r"^\s*\d{4}[-/]\d{2}[-/]\d{2}\s*$"), "date"),   # ISO date

    # Pure numbers or numbers with units (no other words)
    (re.compile(r"^\s*\d+(?:[.,]\d+)?\s*$"), "number"),
    (re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:km|m|cm|mm|kg|g|lb|lbs|oz|mph|kph|ml|cl|l|ft|in|px|mb|gb|tb|hz|rpm|k)\s*$", re.I), "number"),
    (re.compile(r"^\s*\d+(?:[.,]\d+)?\s*%\s*$"), "number"),     # 100%

    # Times
    (re.compile(r"^\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*$", re.I), "time"),
    (re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*$"), "time"),  # 24hr

    # Ages / durations with "old" or "old" implied
    (re.compile(r"^\s*\d+[-\s]?(?:month|months|year|years|week|weeks|day|days)[-\s]?old\b", re.I), "age"),
    (re.compile(r"^\s*\d+[-\s]month[-\s]old\b", re.I), "age"),

    # Ratings
    (re.compile(r"^\s*rating\s*[:\s]\s*\d+\s*$", re.I), "rating"),
    (re.compile(r"^\s*photo\s+quality\s+\d+\s*$", re.I), "rating"),
    (re.compile(r"^\s*number\s+of\s+subjects\s*[:\s]\s*\d+\s*$", re.I), "rating"),

    # Filenames (with or without extension)
    (re.compile(r"^\s*\S+\.(?:jpg|jpeg|png|gif|heic|tiff?|raw|nef|cr2|mp4|mov|avi)\s*$", re.I), "filename"),
    (re.compile(r"^\s*(?:dsc|img|dsc_|img_|p_|pic|photo|photograph)\d+\s*$", re.I), "filename"),

    # Quoted bare numbers: "10", "42"
    (re.compile(r'^\s*["\']?\d+["\']?\s*$'), "number"),

    # Number ranges with no context: 1-2, 10-15, 13-14
    (re.compile(r"^\s*\d+\s*[-–]\s*\d+\s*$"), "number"),

    # Number ranges followed only by a count noun: 10-15 people, 1-2 persons
    (re.compile(r"^\s*\d+(?:\s*[-–]\s*\d+)?\s*(?:people|persons?|women|men|man|woman|girls?|boys?|kids?|adults?|children)\s*$", re.I), "number"),

    # Bare headcounts: 2 people, 6 women
    (re.compile(r"^\s*\d+\s+(?:people|persons?|women|men|man|woman|girls?|boys?|kids?|adults?|children)\s*$", re.I), "number"),

    # Temperature
    (re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:degrees?|°)\s*(?:c(?:elsius)?|f(?:ahrenheit)?)?\s*$", re.I), "number"),

    # Age ranges: 60+, 20s (bare decade as age), early 30s, mid-20s
    (re.compile(r"^\s*\d+\+\s*$"), "number"),
    (re.compile(r"^\s*(?:early|mid|late)[-\s]*\d+s\s*$", re.I), "number"),
    (re.compile(r"^\s*\d+s\s*$"), "number"),               # bare "20s", "30s" alone

    # Measurements with screen/display units: 24-inch screen
    (re.compile(r"^\s*\d+\s*[-–]?\s*(?:inch|in|\")\s*(?:screen|monitor|display|tv)?\s*$", re.I), "number"),

    # Century references: 12th century, 21st century
    (re.compile(r"^\s*\d+(?:st|nd|rd|th)\s+century\s*$", re.I), "date"),

    # Specific month + day (no year): april 4th, june 15th, january 13
    (re.compile(r"^\s*" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?\s*$", re.I), "date"),

    # Day-of-week + date: friday 5th april, monday june 4th, thursday 19th july 2019
    (re.compile(r"^\s*(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
                r"\s+.{0,30}(?:\d{4})?\s*$", re.I), "date"),

    # Time ranges: 10am-1pm, 17:30-20:30, 6 pm - 8 pm
    (re.compile(r"^\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*[-–to]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*$", re.I), "time"),
    (re.compile(r"^\s*\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\s*$"), "time"),

    # AI labelling meta-garbage: comments about folder names, keyword absence, etc.
    (re.compile(r"from\s+folder", re.I), "meta"),
    (re.compile(r"from\s+(?:the\s+)?(?:\"?\d+\"?|'?\d+'?)\s+folder", re.I), "meta"),
    (re.compile(r"mentioned\s+but\s+not", re.I), "meta"),
    (re.compile(r"not\s+fitting\s+from\s+context", re.I), "meta"),
    (re.compile(r"keyword\s+unknown", re.I), "meta"),
    (re.compile(r"not\s+included\s+in\s+keywords?", re.I), "meta"),
    (re.compile(r"(?:no|not)\s+(?:07|08|09|0[1-9])\b", re.I), "meta"),
    (re.compile(r"\brelated\s+keyword\b", re.I), "meta"),
    (re.compile(r"speculative\b", re.I), "meta"),
    (re.compile(r"from\s+context\s+of\s+image", re.I), "meta"),
    (re.compile(r"photo(?:graph)?\s+\d+\b", re.I), "meta"),   # "photo 06", "photograph 06"
    (re.compile(r"image\s+number\s+\d+", re.I), "meta"),
    (re.compile(r"^\s*\d+(?:st|nd|rd|th)\s+photo\b", re.I), "meta"),
    (re.compile(r"^\s*folder\s+['\"]?\d+['\"]?\s*$", re.I), "meta"),  # folder '02'
    (re.compile(r"^\s*\d+th\s+folder\s*$", re.I), "meta"),
    (re.compile(r"\bnumber\s+\d+\b", re.I), "meta"),          # "number 07", "number 149"
    (re.compile(r"\bpaper\s+crown\s+\d+\b", re.I), "meta"),  # AI paper-crown numbering
    (re.compile(r"\b(?:part|no\.?|no\s+)\s*\d+\b.*\bkeyword", re.I), "meta"),
    (re.compile(r"15[-–]20\s+keywords?", re.I), "meta"),
    (re.compile(r"^year\s+['\"]?\d{2,4}['\"]?\s*$", re.I), "date"),     # year '08, year 2006
    (re.compile(r"^photo\s+from\s+\d{4}\s*$", re.I), "date"),

    # Ordinal day + month (no year): 10th september, 15th march
    (re.compile(r"^\s*\d+(?:st|nd|rd|th)\s+" + _MONTH + r"(?:\s+" + _YEAR + r")?\s*$", re.I), "date"),

    # Month + date range: january 20-22, june 19th-23rd
    (re.compile(r"^\s*" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?\s*[-–]\s*\d{1,2}(?:st|nd|rd|th)?(?:\s+" + _YEAR + r")?\s*$", re.I), "date"),

    # Headcounts (small groups): 3-person, 3-men, 3-person group
    (re.compile(r"^\s*\d+\s*[-–]?\s*(?:person|men|man|woman|women)\b.*$", re.I), "number"),

    # Age ranges: under 26, over 20+
    (re.compile(r"^\s*(?:under|over|above|below)\s+\d+\+?\s*$", re.I), "number"),

    # Duration constructs: 60-day payment terms, 30 cycle
    (re.compile(r"^\s*\d+[-\s]day\s+\w", re.I), "number"),
    (re.compile(r"^\s*\d+\s+cycle\s*$", re.I), "number"),

    # Month fragment: 30 nov, 29 nov, aug 12 (day + month or month + day without year)
    (re.compile(r"^\s*\d{1,2}\s+" + _MONTH + r"\s*$", re.I), "date"),
    (re.compile(r"^\s*" + _MONTH + r"\s+\d{1,2}\s*$", re.I), "date"),

    # Academic/school numbering junk: academic year 101, semester 11
    (re.compile(r"^\s*academic\s+year\s+\d+\s*$", re.I), "meta"),
    (re.compile(r"^\s*semester\s+\d+\s*$", re.I), "meta"),

    # Vehicle licence plates and alphanumeric codes (letters+digits, no spaces meaning)
    # Heuristic: 2-8 chars, mix of letters and digits, no vowel-rich words
    (re.compile(r"^\s*[a-z]{1,3}\d{2,4}[a-z]{0,3}\s*$", re.I), "code"),
    (re.compile(r"^\s*[a-z]\d{3,6}\s*$", re.I), "code"),   # a66, k21, d1006

    # Date in DD.MM.YYYY or DD/MM/YYYY format
    (re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}\s*$"), "date"),

    # Month + day + optional event suffix: september 9th event
    (re.compile(r"^\s*" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?\s+\w*\s*$", re.I), "date"),

    # AI meta patterns: (as per '04'), (from 07 folder), part of a number (07)
    (re.compile(r"\(as per\s+['\"]?\d+['\"]?\)", re.I), "meta"),
    (re.compile(r"\bpart\s+of\s+a\s+number\b", re.I), "meta"),
    (re.compile(r"\bno\s+focus\s+on\b", re.I), "meta"),
    (re.compile(r"\bfrom\s+['\"]?\d+['\"]?\s+folder\b", re.I), "meta"),
    (re.compile(r"\b07\b|\b08\b|\b09\b|\b0[1-9]\b.*\bvisible\b", re.I), "meta"),

    # Licence plate patterns: w653 ayd, AB12 CDE
    (re.compile(r"^\s*[a-z]{1,2}\d{2,4}\s+[a-z]{2,4}\s*$", re.I), "code"),

    # Calendar references: 2021 calendar
    (re.compile(r"^\s*" + _YEAR + r"\s+calendar\s*$", re.I), "date"),

    # Takeout import tags: takeout-20260403T164713Z-3
    (re.compile(r"^takeout-\d{8}T", re.I), "import"),
]


# Tags matching these patterns are always KEPT, even if PATTERNS or Ollama
# would otherwise flag them. Checked before any delete decision.
KEEP_PATTERNS = [
    re.compile(r"\d+(?:st|nd|rd|th)\s+(?:century|floor|anniversary|birthday)", re.I),
    re.compile(r"\d+\s*(?:st|nd|rd|th)\s+(?:century|floor|anniversary|birthday)", re.I),
    re.compile(r"\d+k\s+race", re.I),                    # 10k race, 5k race
    re.compile(r"\b(?:19|18|17|20)\d{2}s\b", re.I),     # 1960s, 1950s, 1920s (decade era)
    re.compile(r"\d+s\s+\w", re.I),                      # 1960s decor, 1950s style
    re.compile(r"19th\s+century|20th\s+century|18th\s+century", re.I),
    re.compile(r"24[-\s]hour\s+\w", re.I),               # 24-hour delivery/service/etc
    re.compile(r"\d+[-\s](?:story|storey|floor)\b", re.I),
    re.compile(r"world\s+war", re.I),
    re.compile(r"(?:nikon|canon|sony|fuji|leica|olympus|panasonic)\s+\w", re.I),
    re.compile(r"\b3d\s+\w", re.I),                      # 3d printing, 3d puzzle, 3d movie
    re.compile(r"\bcovid[-\s]?\d+", re.I),               # covid-19
    re.compile(r"\b360\s+\w", re.I),                     # 360 panoramic, 360 view
    re.compile(r"class\s+of\s+\d{4}", re.I),             # class of 2005
    re.compile(r"4th\s+of\s+july|july\s+4th", re.I),    # US holiday
    re.compile(r"\bvitamin\s+[a-z]\d?\b", re.I),       # vitamin b2, vitamin d3
    re.compile(r"\b\d+rd\s+avenue\b|\b\d+th\s+avenue\b|\bstreet\b|\broad\b|\bterrace\b|\bavenue\b|\blane\b", re.I),  # street addresses
    re.compile(r"\bgate[s]?\s+\d+|\bplatform\s+\d+|\broom\s+\d+|\bfloor\s+\d+", re.I),  # locations
    re.compile(r"\b(?:sarah|tom|nadia|alex|emma|james|john|mike|kate)\b", re.I),  # names (keep person tags)
]


def is_kept_by_override(value: str) -> bool:
    return any(rx.search(value) for rx in KEEP_PATTERNS)


def pattern_reason(value: str) -> str | None:
    if is_kept_by_override(value):
        return None
    for rx, label in PATTERNS:
        if rx.search(value):
            return label
    return None


# ---------------------------------------------------------------------------
# Ollama classification
# ---------------------------------------------------------------------------

OLLAMA_PROMPT = """Classify each tag as DELETE or KEEP.

DELETE if the tag is primarily:
- A price: £2, $10.99, 50p, 800 price
- A standalone date or year: November 2024, 2019, april 2021, 2020
- A pure number, range, or measurement with no descriptive context: 42, "10", 904, 10km, 60 years, mid-20s, 1-2, 10-15, 13-14, 24-inch screen, 12th century
- A count of people with no other context: 1-2 people, 10-15 people, 2 women (just a count)
- A time: 12:30 pm, 11pm, 3:30am
- An age or duration: 3 months old, 12-months old, 12-month old dog
- A rating: rating: 4, rating 3
- A filename: dsc_6225.jpg, img_0042.jpg

KEEP if the tag has meaningful descriptive content, even with digits:
1960s decor, 3-story building, covid-19, 3d printing, july 4th,
19th century architecture, 20s fashion, world war 2, 21st birthday,
60th anniversary, 10th floor, 10k race, 24-hour service, nikon d3200,
strada provinciale 23 del colle di sestriere, gates 1-28

Reply ONLY with a valid JSON array of the exact tag strings to DELETE.
If none should be deleted, reply with [].

Tags:
"""


def ollama_classify(tags: list[str]) -> set[str]:
    """Ask Ollama which tags in the list should be deleted. Returns a set of values."""
    if not tags:
        return set()

    client = ollama.Client(host=OLLAMA_HOST)
    tag_list = "\n".join(f"- {t}" for t in tags)
    try:
        resp = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": OLLAMA_PROMPT + tag_list}],
            options={"temperature": 0},
        )
        raw = resp.message.content.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        if isinstance(result, list):
            return {str(t) for t in result}
    except Exception as e:
        print(f"  WARNING: Ollama batch failed — {e}")
    return set()


# ---------------------------------------------------------------------------
# Immich API helpers
# ---------------------------------------------------------------------------

def delete_tag(tag_id: str) -> bool:
    req = urllib.request.Request(
        f"{IMMICH_API}/{tag_id}",
        method="DELETE",
        headers={"x-api-key": API_KEY},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 204
    except urllib.error.HTTPError:
        return False


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def load_tags() -> list[tuple[str, str, int]]:
    """Return live list of (id, value, asset_count) from the Immich database."""
    import subprocess
    sql = (
        "SELECT t.id, t.value, COUNT(ta.\"assetId\") "
        "FROM tag t "
        "LEFT JOIN tag_asset ta ON ta.\"tagId\" = t.id "
        "GROUP BY t.id, t.value "
        "ORDER BY t.value;"
    )
    result = subprocess.run(
        ["docker", "exec", "immich-postgres", "psql",
         "-U", "immich", "-d", "immich", "-t", "-A", "-F", "\t", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            tag_id, value, count = parts
            rows.append((tag_id.strip(), value, int(count.strip())))
    return rows


def phase1_detect(tags: list[tuple[str, str, int]]) -> dict[str, str]:
    """Return {tag_id: reason} for all tags that should be deleted by pattern/Ollama."""
    to_delete: dict[str, str] = {}

    # Regex pass
    digit_candidates: list[tuple[str, str]] = []  # (id, value) for Ollama
    for tag_id, value, _ in tags:
        if is_kept_by_override(value):
            continue
        reason = pattern_reason(value)
        if reason:
            to_delete[tag_id] = reason
        elif re.search(r"[0-9]", value):
            digit_candidates.append((tag_id, value))

    print(f"  Regex: {len(to_delete):,} matched, {len(digit_candidates)} digit tags for Ollama")

    # Ollama pass — only digit-containing tags that didn't match regex
    if digit_candidates:
        ollama_deletes: set[str] = set()
        for i in range(0, len(digit_candidates), OLLAMA_BATCH):
            batch = digit_candidates[i:i + OLLAMA_BATCH]
            values = [v for _, v in batch]
            print(f"  Ollama batch {i // OLLAMA_BATCH + 1}/{-(-len(digit_candidates) // OLLAMA_BATCH)}: {len(values)} tags…")
            result = ollama_classify(values)
            ollama_deletes |= result

        for tag_id, value in digit_candidates:
            if value in ollama_deletes:
                to_delete[tag_id] = "ollama"

        print(f"  Ollama: {len(ollama_deletes)} additional matches")

    return to_delete


def phase2_export(tags: list[tuple[str, str, int]], exclude_ids: set[str], output_path: Path) -> int:
    """Write ≤SMALL_TAG_THRESHOLD tags (not already flagged) to output_path."""
    small = [(tag_id, value, count) for tag_id, value, count in tags
             if count <= SMALL_TAG_THRESHOLD and tag_id not in exclude_ids]
    small.sort(key=lambda r: (r[2], r[1].lower()))

    lines = [
        "# Immich tags with 5 or fewer assets",
        "# To KEEP a tag: delete its line from this file",
        "# To delete everything remaining: ./venv/bin/python cleanup_tags.py --apply-file <this_file>",
        "",
    ]
    for _, value, count in small:
        lines.append(f"{value} [{count}]")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(small)


def phase3_apply_file(file_path: Path) -> None:
    """Delete tags listed in file. Looks up each tag value in the DB to get its ID."""
    lines = [
        ln.strip() for ln in file_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    # Strip the " [N]" count suffix
    values = []
    for ln in lines:
        m = re.match(r"^(.*?)\s*\[\d+\]\s*$", ln)
        values.append(m.group(1).strip() if m else ln)

    if not values:
        print("No tags to delete in file.")
        return

    # Look up IDs from current TSV (or re-query if stale)
    tag_map: dict[str, str] = {}
    for tag_id, value, _ in load_tags():
        tag_map[value] = tag_id

    deleted = failed = 0
    for value in values:
        tag_id = tag_map.get(value)
        if not tag_id:
            print(f"  SKIP (not found): {value!r}")
            continue
        if delete_tag(tag_id):
            deleted += 1
        else:
            print(f"  FAILED: {value!r}")
            failed += 1

    print(f"\nDeleted {deleted:,}  failed {failed}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Delete pattern-matched tags (default: dry run)")
    parser.add_argument("--export-small", metavar="FILE",
                        help="Write ≤5-asset tags to FILE for manual review")
    parser.add_argument("--apply-file", metavar="FILE",
                        help="Delete all tags listed in FILE via the Immich API")
    args = parser.parse_args()

    if args.apply_file:
        phase3_apply_file(Path(args.apply_file))
        return

    print("Loading tags…")
    tags = load_tags()
    print(f"  {len(tags):,} tags loaded\n")

    print("Detecting pattern matches…")
    to_delete = phase1_detect(tags)

    # Summary by reason
    reasons: dict[str, int] = {}
    for reason in to_delete.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    print(f"\nWould delete {len(to_delete):,} tags:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:12s} {count:,}")

    if not args.apply:
        print("\nDRY RUN — pass --apply to delete, optionally with --export-small FILE")
        return

    # Phase 1: delete
    print(f"\nDeleting {len(to_delete):,} tags…")
    deleted = failed = 0
    for i, (tag_id, _) in enumerate(to_delete.items()):
        if delete_tag(tag_id):
            deleted += 1
        else:
            failed += 1
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(to_delete)}…")
    print(f"Deleted {deleted:,}  failed {failed}")

    # Phase 2: export small tags
    if args.export_small:
        deleted_ids = set(to_delete.keys())
        out = Path(args.export_small)
        n = phase2_export(tags, deleted_ids, out)
        print(f"\nExported {n:,} tags with ≤{SMALL_TAG_THRESHOLD} assets to {out}")
        print(f"Edit the file — remove lines you want to KEEP — then run:")
        print(f"  ./venv/bin/python cleanup_tags.py --apply-file {out}")


if __name__ == "__main__":
    main()
