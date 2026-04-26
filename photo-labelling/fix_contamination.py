"""
Fix metadata contamination from sensitive-vault / library filename collisions.

Three steps:
  1. Clear PhotoLabelling tags from the contaminated library files
     (files that received sensitive-vault content due to a path substitution bug)
  2. Fix all 957 vault-photo paths in descriptions.jsonl to point to the
     correct current location (vault if still there, library if moved)
  3. Re-run write_tags for every affected file

Run with --apply to write changes; default is a dry-run preview.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/photo-labelling/PhotoLabelling")
import exiftool
from descriptions import (
    write_record, load_descriptions,
    KEYWORD_TAGS, TITLE_TAGS, CAPTION_TAGS, RATING_TAG, PROVENANCE_TAGS,
)

DESCRIPTIONS = Path("/opt/photo-labelling/output/descriptions.jsonl")
METRICS      = Path("/opt/photo-labelling/output/metrics.jsonl")
LIBRARY_ROOT = Path("/mnt/peach_storage/immich/library/library")

# Every tag we ever write — used to wipe files clean before re-writing
ALL_OUR_TAGS = (
    list(KEYWORD_TAGS) + list(TITLE_TAGS) + list(CAPTION_TAGS)
    + [RATING_TAG] + list(PROVENANCE_TAGS)
    + ["XMP-iptcExt:Event"]
)


# ── helpers ──────────────────────────────────────────────────────────────────

def load_mismatches():
    """Return (line_idx, desc_record, actual_vault_path) for each line where
    the descriptions.jsonl path differs from the metrics.jsonl path but the
    filename is the same — i.e. vault content stored under a library path."""
    result = []
    with DESCRIPTIONS.open() as df, METRICS.open() as mf:
        for idx, (dl, ml) in enumerate(zip(df, mf)):
            d, m = json.loads(dl), json.loads(ml)
            if d["path"] != m["path"] and d["path"].split("/")[-1] == m["path"].split("/")[-1]:
                result.append((idx, d, m["path"]))
    return result


def is_wrong_year(desc_path: str, vault_path: str) -> bool:
    """True when the desc path and vault path have different year/month under /admin/."""
    try:
        dp = desc_path.split("/admin/")[-1].split("/")
        vp = vault_path.split("/admin/")[-1].split("/")
        return (dp[0], dp[1]) != (vp[0], vp[1])
    except IndexError:
        return False


def resolve_vault_path(vault_path: str) -> str | None:
    """Return the best current path for a vault file:
    vault path if the file still lives there, otherwise the mirrored
    library path (same year/month/filename under LIBRARY_ROOT/admin/)."""
    if Path(vault_path).exists():
        return vault_path
    if "/plain/originals/" in vault_path:
        relative = vault_path.split("/plain/originals/")[-1]   # admin/YYYY/MM/file
        lp = LIBRARY_ROOT / relative
        if lp.exists():
            return str(lp)
    return None


def clear_our_tags(et, path: str) -> None:
    """Delete every tag we wrote from the file (no backup created)."""
    args = [f"-{tag}=" for tag in ALL_OUR_TAGS]
    args += ["-overwrite_original", path]
    et.execute(*args)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--apply" not in sys.argv
    if dry_run:
        print("DRY RUN — pass --apply to write changes\n")

    # ── Load mismatch list ────────────────────────────────────────────────────
    print("Scanning descriptions/metrics for path mismatches …")
    mismatches = load_mismatches()
    wrong_year = [(i, d, vp) for i, d, vp in mismatches if is_wrong_year(d["path"], vp)]
    same_year  = [(i, d, vp) for i, d, vp in mismatches if not is_wrong_year(d["path"], vp)]
    print(f"  {len(mismatches)} total mismatches")
    print(f"  {len(wrong_year)} wrong-year (different photo contaminated)")
    print(f"  {len(same_year)} same-year (same photo, path just needs updating)")

    contaminated_lib_paths = {d["path"] for _, d, _ in wrong_year if Path(d["path"]).exists()}

    # ── Step 1: Clear contaminated library files ──────────────────────────────
    print(f"\n─── Step 1: Clear tags from {len(contaminated_lib_paths)} contaminated library files ───")
    if not dry_run:
        with exiftool.ExifToolHelper(encoding="utf-8") as et:
            for path in sorted(contaminated_lib_paths):
                clear_our_tags(et, path)
                print(f"  CLEARED {Path(path).name}")
    else:
        for p in sorted(contaminated_lib_paths):
            print(f"  Would clear: {p.split('/admin/')[-1]}")

    # ── Step 2: Fix paths in descriptions.jsonl ───────────────────────────────
    print(f"\n─── Step 2: Fix paths for {len(mismatches)} records ───")

    records = []
    with DESCRIPTIONS.open() as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    path_updates: dict[int, str] = {}   # line_idx → new path
    cannot_fix: list[tuple] = []

    for idx, drec, vault_path in mismatches:
        new_path = resolve_vault_path(vault_path)
        if new_path and new_path != drec["path"]:
            path_updates[idx] = new_path
        elif not new_path:
            cannot_fix.append((idx, vault_path))

    print(f"  {len(path_updates)} paths to update")
    if cannot_fix:
        print(f"  {len(cannot_fix)} paths cannot be located (file missing from both vault and library):")
        for idx, vp in cannot_fix:
            print(f"    line {idx+1}: {vp}")

    if not dry_run and path_updates:
        for idx, new_path in path_updates.items():
            records[idx]["path"] = new_path
        tmp = DESCRIPTIONS.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp.replace(DESCRIPTIONS)
        print(f"  Saved {len(path_updates)} fixes to descriptions.jsonl")

    # ── Step 3: Re-run write_tags ─────────────────────────────────────────────
    # Write to:
    #   a) the fixed vault/library paths (vault photo labels → correct files)
    #   b) the contaminated library files (now cleared; restore legitimate labels)
    to_write_paths = set(path_updates.values()) | contaminated_lib_paths
    fresh_records  = load_descriptions()   # re-reads the file we just fixed
    to_write       = [r for r in fresh_records if r["path"] in to_write_paths]

    print(f"\n─── Step 3: write_tags for {len(to_write)} records ───")
    print(f"  ({len(path_updates)} vault/fixed-path records + legitimate re-writes for cleared files)")

    if not dry_run:
        with exiftool.ExifToolHelper(encoding="utf-8") as et:
            for rec in to_write:
                write_record(rec, et, dry_run=False, update=False)
    else:
        by_path: dict[str, list] = {}
        for r in to_write:
            by_path.setdefault(r["path"], []).append(r)
        for path, recs in list(by_path.items())[:10]:
            print(f"  {path.split('/admin/')[-1]}")
            for r in recs:
                print(f"    → {r.get('title','')[:60]}")
        if len(by_path) > 10:
            print(f"  … and {len(by_path)-10} more files")

    print("\nDone.")


if __name__ == "__main__":
    main()
