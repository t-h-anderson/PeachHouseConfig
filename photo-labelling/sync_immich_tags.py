"""
sync_immich_tags.py — Sync Immich tag assignments → EXIF keywords

For each photo, compares the tags currently assigned in Immich against what
was last synced. Adds new tags and removes deleted ones from IPTC:Keywords
and XMP:Subject in the actual photo files.

Removal tracking: after the first --apply run, this script records the
full Immich tag set for every photo as its baseline. On subsequent runs,
any tag that was in that baseline but has since been removed in Immich is
also removed from EXIF — including AI-labelling keywords. This means you
can remove a bad AI label in Immich and the next sync will propagate the
removal to the file itself.

Only the keywords that were in Immich at last sync are managed; any keywords
in EXIF that have never been in Immich are left untouched.

State is persisted in output/immich_tag_sync_state.json so reruns are
incremental: only photos whose Immich tags changed since the last run are
processed.

Usage:
    cd /opt/photo-labelling
    ./venv/bin/python sync_immich_tags.py            # dry run — preview changes
    ./venv/bin/python sync_immich_tags.py --apply    # write changes to files
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import exiftool
from PIL import Image

sys.path.insert(0, "/opt/photo-labelling/PhotoLabelling")
from integrity import hash_pixels, verify_write, backup_path

STATE_FILE = Path("/opt/photo-labelling/output/immich_tag_sync_state.json")
KEYWORD_TAGS = ["IPTC:Keywords", "XMP:Subject"]
DB_CONTAINER = "immich-postgres"
DB_USER = "immich"
DB_NAME = "immich"

# Immich stores paths as container-internal paths; translate to host paths.
CONTAINER_UPLOAD_ROOT = "/usr/src/app/upload"
HOST_UPLOAD_ROOT = "/mnt/peach_storage/immich/library"

_EXT_BY_FORMAT = {
    "JPEG": {".jpg", ".jpeg"},
    "PNG":  {".png"},
    "TIFF": {".tif", ".tiff"},
    "HEIC": {".heic"},
}

# exiftool cannot write metadata to these formats
_WRITE_UNSUPPORTED_EXTS = {".mkv", ".avi", ".wmv"}


# ---------------------------------------------------------------------------
# Immich data
# ---------------------------------------------------------------------------

def fetch_immich_tags() -> dict[str, list[str]]:
    """Return {originalPath: [tag, ...]} for all non-deleted assets with tags."""
    sql = (
        "SELECT a.\"originalPath\", ARRAY_AGG(t.value ORDER BY t.value) "
        "FROM asset a "
        "JOIN tag_asset ta ON ta.\"assetId\" = a.id "
        "JOIN tag t ON t.id = ta.\"tagId\" "
        "WHERE a.\"deletedAt\" IS NULL "
        "GROUP BY a.\"originalPath\" "
        "ORDER BY a.\"originalPath\";"
    )
    result = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql",
         "-U", DB_USER, "-d", DB_NAME, "-t", "-A", "-F", "\t", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    path_tags: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        path, raw = parts
        # postgres formats ARRAY_AGG as {val1,"val with comma",val3}
        raw = raw.strip("{}")
        tags = _parse_pg_array(raw)
        if tags:
            host_path = path.replace(CONTAINER_UPLOAD_ROOT, HOST_UPLOAD_ROOT, 1)
            path_tags[host_path] = tags
    return path_tags


def _parse_pg_array(raw: str) -> list[str]:
    """Parse a postgres text-format array value into a Python list."""
    items: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"' and not in_quotes:
            in_quotes = True
        elif ch == '"' and in_quotes:
            # check for escaped quote
            if i + 1 < len(raw) and raw[i + 1] == '"':
                current.append('"')
                i += 1
            else:
                in_quotes = False
        elif ch == ',' and not in_quotes:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current or raw:
        items.append("".join(current).strip())
    return [t for t in items if t]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state() -> dict[str, list[str]]:
    if STATE_FILE.exists():
        with STATE_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict[str, list[str]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def compute_diff(
    immich_tags: list[str],
    last_synced: list[str],
    current_exif: list[str],
) -> tuple[list[str], list[str]]:
    """
    Return (to_add, to_remove).

    to_add:    in Immich now, not yet in EXIF
    to_remove: previously synced from Immich, since removed in Immich,
               and still present in EXIF (won't remove what isn't there)
    """
    exif_lower = {k.lower(): k for k in current_exif}
    immich_lower = {t.lower() for t in immich_tags}
    last_lower = {t.lower() for t in last_synced}

    to_add = [t for t in immich_tags if t.lower() not in exif_lower]
    to_remove = [exif_lower[t] for t in (last_lower - immich_lower) if t in exif_lower]
    return to_add, to_remove


# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------

def read_keywords(meta: dict) -> list[str]:
    for tag in KEYWORD_TAGS:
        val = meta.get(tag)
        if not val:
            continue
        if isinstance(val, list):
            return [str(k).strip() for k in val if str(k).strip()]
        if isinstance(val, str):
            return [k.strip() for k in val.split(",") if k.strip()]
    return []


def build_updated_keywords(
    current: list[str],
    to_add: list[str],
    to_remove: list[str],
) -> list[str]:
    remove_lower = {t.lower() for t in to_remove}
    updated = [k for k in current if k.lower() not in remove_lower]
    seen = {k.lower() for k in updated}
    for t in to_add:
        if t.lower() not in seen:
            updated.append(t)
            seen.add(t.lower())
    return updated


def _actual_format(path: str) -> str | None:
    try:
        with Image.open(path) as img:
            return img.format
    except Exception:
        return None


def write_keywords_safe(et, path: str, keywords: list[str]) -> None:
    """Write keyword tags, handling format-extension mismatches."""
    to_write = {tag: keywords for tag in KEYWORD_TAGS}
    target_path = Path(path)
    actual_fmt = _actual_format(path)
    expected_exts = _EXT_BY_FORMAT.get(actual_fmt, {target_path.suffix.lower()})

    if actual_fmt and target_path.suffix.lower() not in expected_exts:
        correct_ext = ".jpg" if actual_fmt == "JPEG" else f".{actual_fmt.lower()}"
        shutil.copy2(path, backup_path(path))
        tmp = Path(tempfile.mktemp(dir=target_path.parent, suffix=correct_ext))
        shutil.copy2(path, tmp)
        try:
            et.set_tags(str(tmp), to_write)
            shutil.copy2(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
            Path(str(tmp) + "_original").unlink(missing_ok=True)
    else:
        et.set_tags(path, to_write)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default is dry run)")
    args = parser.parse_args()
    dry_run = not args.apply

    if dry_run:
        print("DRY RUN — pass --apply to write changes\n")

    print("Fetching tag assignments from Immich…")
    immich_tags = fetch_immich_tags()
    print(f"  {len(immich_tags):,} assets have tags in Immich")

    state = load_state()

    # Build the full set of paths to consider: anything tagged in Immich now,
    # plus anything we previously synced (in case all tags were removed).
    all_paths = set(immich_tags) | set(state)

    changed: list[str] = []
    skipped_missing = 0
    errors: list[str] = []

    with exiftool.ExifToolHelper(encoding="utf-8") as et:
        for path in sorted(all_paths):
            if not Path(path).exists():
                skipped_missing += 1
                continue

            if Path(path).suffix.lower() in _WRITE_UNSUPPORTED_EXTS:
                continue

            current_immich = immich_tags.get(path, [])
            last_synced = state.get(path, [])

            # Fast path: nothing changed since last sync
            if sorted(t.lower() for t in current_immich) == sorted(t.lower() for t in last_synced):
                continue

            try:
                meta = et.get_metadata(path)[0]
            except Exception as e:
                errors.append(f"{path}: failed to read metadata — {e}")
                continue

            current_exif = read_keywords(meta)
            to_add, to_remove = compute_diff(current_immich, last_synced, current_exif)

            if not to_add and not to_remove:
                # State is stale but EXIF already matches — update state, no write needed
                if not dry_run:
                    state[path] = list(current_immich)
                continue

            changed.append(path)
            name = Path(path).name

            if dry_run:
                print(f"  {name}")
                for t in to_add:
                    print(f"    ADD    {t}")
                for t in to_remove:
                    print(f"    REMOVE {t}")
                continue

            updated_keywords = build_updated_keywords(current_exif, to_add, to_remove)
            before_pixels = hash_pixels(path)
            before_tags = meta

            try:
                write_keywords_safe(et, path, updated_keywords)
            except Exception as e:
                errors.append(f"{path}: write failed — {e}")
                continue

            after_tags = et.get_metadata(path)[0]
            after_pixels = hash_pixels(path)

            ok, reason = verify_write(
                before_tags, after_tags,
                before_pixels, after_pixels,
                written_tags=set(KEYWORD_TAGS),
            )
            if ok:
                bp = backup_path(path)
                if bp.exists():
                    bp.unlink()
                print(f"  OK {name}"
                      + (f" (+{len(to_add)})" if to_add else "")
                      + (f" (-{len(to_remove)})" if to_remove else ""))
                state[path] = list(current_immich)
            else:
                print(f"  WARN {name}: integrity check failed — {reason}")
                print(f"    Backup preserved: {backup_path(path).name}")
                errors.append(f"{path}: integrity check failed — {reason}")

    print()
    if dry_run:
        print(f"Would update {len(changed):,} files  ({skipped_missing:,} not found on disk)")
    else:
        save_state(state)
        print(f"Updated {len(changed):,} files  ({skipped_missing:,} not found on disk)")
        if errors:
            print(f"\n{len(errors)} error(s):")
            for e in errors:
                print(f"  {e}")


if __name__ == "__main__":
    main()
