"""
One-off fix: 13 Samsung panoramas had DateTimeOriginal backfilled with the
filesystem copy date (2026-04-06) instead of the correct capture date.
Each file has the correct date in EXIF:CreateDate. This script copies it across.
"""
import sys
import exiftool
sys.path.insert(0, "/opt/photo-labelling/PhotoLabelling")
from integrity import hash_pixels, verify_write, backup_path

FILES = [
    "/mnt/peach_storage/immich/library/library/admin/2018/04/P_20180421_153146_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/04/P_20180421_165458_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/05/P_20180526_064955_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/05/P_20180527_145626_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/05/P_20180526_182151_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/05/P_20180526_103522_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/03/P_20180325_160421_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/03/P_20180329_165156_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/03/P_20180329_165141_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/03/P_20180325_163527_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/03/P_20180325_172637_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/03/P_20180324_175259_PN.jpg",
    "/mnt/peach_storage/immich/library/library/admin/2018/03/P_20180326_122519_PN.jpg",
]

DRY_RUN = "--apply" not in sys.argv

if DRY_RUN:
    print("DRY RUN — pass --apply to write changes\n")

with exiftool.ExifToolHelper(encoding="utf-8") as et:
    for path in FILES:
        tags = et.get_metadata(path)[0]
        create_date = tags.get("EXIF:CreateDate")
        dto = tags.get("EXIF:DateTimeOriginal")
        name = path.split("/")[-1]

        if not create_date:
            print(f"SKIP {name}: no CreateDate found")
            continue

        if DRY_RUN:
            print(f"DRY RUN {name}: DateTimeOriginal {dto!r} → {create_date!r}")
            continue

        to_write = {"EXIF:DateTimeOriginal": create_date}
        before_pixels = hash_pixels(path)
        et.set_tags(path, to_write)
        after_pixels = hash_pixels(path)
        after_tags = et.get_metadata(path)[0]

        ok, reason = verify_write(tags, after_tags, before_pixels, after_pixels, set(to_write.keys()))
        if ok:
            bp = backup_path(path)
            if bp.exists():
                bp.unlink()
            print(f"FIXED {name}: DateTimeOriginal = {create_date}")
        else:
            print(f"WARNING {name}: integrity check failed — {reason}")
            print(f"  Backup preserved: {backup_path(path).name}")
