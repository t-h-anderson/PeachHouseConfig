"""
Normalize keywords in descriptions.jsonl and in EXIF across all photo files.

Fixes:
  - Trailing dots/commas      "landscape."   → "landscape"
  - Mixed capitalisation      "Outdoor Setting" → "outdoor setting"
  - Numeric folder junk       "07", "08 folder", "12 (folder name)" → removed
  - Plural/singular dupes     "tree, trees"  → "trees"  (within same photo only)

Run:
  python normalize_keywords.py           — preview stats only
  python normalize_keywords.py --apply   — write changes
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/opt/photo-labelling/PhotoLabelling")
import exiftool
from config import PHOTO_DIRS
from descriptions import KEYWORD_TAGS

DESCRIPTIONS = Path("/opt/photo-labelling/output/descriptions.jsonl")


# ── normalization ─────────────────────────────────────────────────────────────

# Matches single/double digit numbers (with optional folder-junk suffix)
# e.g. "07", "12", "07.", "08 folder", "12 (folder name)", "09-folder hint"
# Safe: 4-digit years, "3D", "15th Street", addresses etc. are NOT matched.
_NUMERIC_JUNK = re.compile(
    r"""
    ^ \d{1,2}                     # 1 or 2 leading digits
    (                             # optionally followed by:
        $                         #   end of string (bare number)
      | [\s\-_(].*folder          #   then "folder" anywhere
      | \s*\(                     #   then "(" e.g. "12 (folder name)"
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def normalize_list(raw) -> list[str]:
    """Parse raw keywords (str or list), apply all normalisation rules,
    return a deduplicated list of clean lowercase keywords."""
    if isinstance(raw, list):
        items = [str(k) for k in raw]
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        return []

    cleaned = []
    seen: set[str] = set()

    for k in items:
        k = k.strip().rstrip(".,;:").strip()
        k = k.lower()
        if not k:
            continue
        if _NUMERIC_JUNK.match(k):
            continue
        if k not in seen:
            seen.add(k)
            cleaned.append(k)

    # Within this photo: if both singular and plural form exist, keep plural.
    kw_set = set(cleaned)
    to_drop: set[str] = set()
    for k in cleaned:
        if k + "s" in kw_set:          # tree → trees
            to_drop.add(k)
        if k.endswith("y") and k[:-1] + "ies" in kw_set:   # sky → skies
            to_drop.add(k)

    return [k for k in cleaned if k not in to_drop]


def normalize_str(raw) -> str:
    return ", ".join(normalize_list(raw))


# ── descriptions.jsonl ────────────────────────────────────────────────────────

def fix_descriptions(dry_run: bool) -> int:
    records = []
    changed = 0
    with DESCRIPTIONS.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            field = "keywords" if "keywords" in rec else "description"
            original = rec.get(field, "")
            fixed = normalize_str(original)
            if fixed != original:
                changed += 1
                if not dry_run:
                    rec[field] = fixed
            records.append(rec)

    if not dry_run and changed:
        tmp = DESCRIPTIONS.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp.replace(DESCRIPTIONS)

    print(f"  descriptions.jsonl: {changed}/{len(records)} records updated")
    return changed


# ── EXIF normalisation ────────────────────────────────────────────────────────

def collect_photos() -> list[str]:
    paths = []
    for d in PHOTO_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".tiff"}:
                paths.append(str(p))
    return paths


CHECKPOINT = Path("output/normalize-done.txt")


def fix_exif(dry_run: bool, batch_size: int = 200) -> tuple[int, int]:
    """Read keywords from all PhotoLabelling-tagged files, normalise, write back.
    Returns (checked, updated)."""
    photos = collect_photos()

    # Load checkpoint: paths already written in a previous run
    done: set[str] = set()
    if not dry_run and CHECKPOINT.exists():
        done = set(CHECKPOINT.read_text().splitlines())
        if done:
            print(f"  Resuming: {len(done)} files already done, skipping them")

    remaining = [p for p in photos if p not in done]
    print(f"  Scanning {len(remaining)}/{len(photos)} photo files …")

    checked = updated = 0
    to_update: list[tuple[str, list[str]]] = []

    with exiftool.ExifToolHelper(encoding="utf-8") as et:
        for start in range(0, len(remaining), batch_size):
            batch = remaining[start : start + batch_size]
            try:
                tags_list = et.get_tags(
                    batch,
                    ["XMP:CreatorTool", "IPTC:Keywords", "XMP:Subject"],
                )
            except Exception as e:
                print(f"  WARN: batch {start}–{start+len(batch)} failed ({e}), retrying one-by-one")
                tags_list = []
                for path in batch:
                    try:
                        tags_list += et.get_tags([path], ["XMP:CreatorTool", "IPTC:Keywords", "XMP:Subject"])
                    except Exception as e2:
                        print(f"  SKIP: {path} ({e2})")
                        continue
            for tags in tags_list:
                if not str(tags.get("XMP:CreatorTool", "")).startswith("PhotoLabelling/"):
                    continue
                checked += 1

                raw = tags.get("IPTC:Keywords") or tags.get("XMP:Subject")
                if not raw:
                    continue

                if isinstance(raw, list):
                    stored = [str(k).strip() for k in raw if str(k).strip()]
                else:
                    stored = [k.strip() for k in str(raw).split(",") if k.strip()]

                desired = normalize_list(raw)

                if stored != desired:
                    to_update.append((tags["SourceFile"], desired))

            progress = min(start + batch_size, len(remaining))
            if progress % 5000 == 0 or progress == len(remaining):
                print(f"  Read {progress}/{len(remaining)}, {len(to_update)} queued for update", flush=True)

        print(f"  Read complete. {checked} PhotoLabelling files, {len(to_update)} need keyword update.")

        if dry_run:
            for path, kws in to_update[:5]:
                print(f"  Would update {Path(path).name}: {kws[:4]}{'…' if len(kws)>4 else ''}")
            if len(to_update) > 5:
                print(f"  … and {len(to_update)-5} more files")
        else:
            ckpt_fh = CHECKPOINT.open("a")
            for start in range(0, len(to_update), batch_size):
                chunk = to_update[start : start + batch_size]
                for path, kws in chunk:
                    try:
                        et.set_tags(
                            path,
                            {tag: kws for tag in KEYWORD_TAGS},
                            params=["-overwrite_original"],
                        )
                    except Exception as e:
                        print(f"  SKIP write: {path} ({e})")
                        continue
                    ckpt_fh.write(path + "\n")
                ckpt_fh.flush()
                progress = min(start + batch_size, len(to_update))
                if progress % 5000 == 0 or progress == len(to_update):
                    print(f"  Written {progress}/{len(to_update)}", flush=True)
            ckpt_fh.close()
            updated = len(to_update)

    return checked, updated


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--apply" not in sys.argv
    if dry_run:
        print("DRY RUN — pass --apply to write changes\n")

    print("── Step 1: Fix descriptions.jsonl ──")
    fix_descriptions(dry_run)

    print("\n── Step 2: Fix EXIF keywords on files ──")
    checked, updated = fix_exif(dry_run)

    if dry_run:
        print(f"\n  Would update keywords on ~{len([1])} files (run --apply to see full count)")
    else:
        print(f"\n  Done. {checked} PhotoLabelling files checked, {updated} updated.")


if __name__ == "__main__":
    main()
