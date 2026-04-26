"""
Re-run the write pipeline for records that failed during the original label-run.
Reads failed filenames from the log, finds their records in descriptions.jsonl,
and re-attempts the write with the improved pipeline.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/opt/photo-labelling/PhotoLabelling")
from descriptions import load_descriptions, write_record
import exiftool

LOG_FILE = Path("/opt/photo-labelling/output/label-run.log")

def load_failed_names(log_path: Path) -> set[str]:
    failed = set()
    for line in log_path.read_text().splitlines():
        m = re.match(r"^FAILED (.+?): ", line)
        if m:
            failed.add(m.group(1))
    return failed

def main():
    dry_run = "--apply" not in sys.argv

    failed_names = load_failed_names(LOG_FILE)
    print(f"Found {len(failed_names)} failed filenames in log")

    all_records = load_descriptions()
    by_name = {Path(r["path"]).name: r for r in all_records}

    to_retry = []
    for name in sorted(failed_names):
        rec = by_name.get(name)
        if rec:
            to_retry.append(rec)
        else:
            print(f"  WARNING: no record found for {name!r}")

    print(f"Matched {len(to_retry)} records to retry")
    if dry_run:
        print("DRY RUN — pass --apply to write changes\n")

    with exiftool.ExifToolHelper(encoding="utf-8") as et:
        for record in to_retry:
            write_record(record, et, dry_run=dry_run, update=True)

if __name__ == "__main__":
    main()
