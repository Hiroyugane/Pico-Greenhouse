"""
Transfer files from SD card to logs/ folder with timestamped organization.

Copies every file from the SD card root to a timestamped folder in logs/,
preserving the relative directory structure. After successful copy, deletes the
files from the SD card unless --keep-source is supplied.

Usage:
    python transfer_logs.py [--sd-drive G:] [--dry-run] [--keep-source]
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path


def _normalize_sd_path(sd_drive: str) -> Path:
    """Return the root path for a Windows drive letter or an explicit path."""

    sd_path = Path(sd_drive)
    if len(sd_drive) == 2 and sd_drive[1] == ":":
        return Path(f"{sd_drive}\\")
    return sd_path


def transfer_logs(sd_drive: str = "G:", dry_run: bool = False, keep_source: bool = False) -> None:
    """
    Transfer files from SD card to logs folder.

    Args:
        sd_drive: Drive letter of the SD card (default: G:)
        dry_run: If True, only print what would be copied without actually copying
        keep_source: If True, keep files on SD card after copying (default: False)
    """
    # Define paths
    sd_path = _normalize_sd_path(sd_drive)
    logs_base = Path(__file__).parent / "logs"

    # Create timestamp for the archive folder
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_folder = logs_base / timestamp

    # Check if SD card is accessible
    if not sd_path.exists():
        print(f"[ERROR] SD card not found at {sd_drive}")
        print(f"        Please ensure the SD card is mounted at {sd_drive}")
        return

    # Find all files on the SD card recursively.
    log_files = [path for path in sd_path.rglob("*") if path.is_file()]

    if not log_files:
        print(f"[INFO] No files found on {sd_drive}")
        return

    # Print summary
    print(f"[INFO] Found {len(log_files)} file(s) on {sd_drive}")
    for log_file in log_files:
        print(f"       - {log_file.relative_to(sd_path)}")

    if dry_run:
        print(f"\n[DRY RUN] Would copy to {archive_folder}")
        if not keep_source:
            print(f"[DRY RUN] Would delete files from {sd_drive} after copying")
        return

    # Create archive folder
    archive_folder.mkdir(parents=True, exist_ok=True)
    print(f"\n[INFO] Created archive folder: {archive_folder}")

    # Copy files
    copied_count = 0
    failed_count = 0
    deleted_count = 0

    for log_file in log_files:
        rel_path = log_file.relative_to(sd_path)
        try:
            dest = archive_folder / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(log_file, dest)
            print(f"[OK] Copied: {rel_path}")
            copied_count += 1

            # Delete from SD card after successful copy
            if not keep_source:
                try:
                    log_file.unlink()
                    print(f"[OK] Deleted from SD: {rel_path}")
                    deleted_count += 1
                except Exception as e:
                    print(f"[WARN] Failed to delete {rel_path} from SD card: {e}")

        except Exception as e:
            print(f"[ERROR] Failed to copy {rel_path}: {e}")
            failed_count += 1

    # Summary
    print(f"\n{'=' * 60}")
    print("[INFO] Transfer complete!")
    print(f"       Copied: {copied_count} file(s)")
    if not keep_source:
        print(f"       Deleted from SD: {deleted_count} file(s)")
    if failed_count:
        print(f"       Failed: {failed_count} file(s)")
    print(f"       Location: {archive_folder}")
    print(f"{'=' * 60}")


def main() -> None:
    """Parse arguments and run the transfer."""
    parser = argparse.ArgumentParser(
        description="Transfer files from SD card to logs/ folder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python transfer_logs.py                    # Transfer from G: and delete from SD
  python transfer_logs.py --sd-drive H:      # Transfer from H: drive
  python transfer_logs.py --dry-run          # Preview without copying
  python transfer_logs.py --keep-source      # Copy but keep files on SD card
        """,
    )
    parser.add_argument("--sd-drive", default="G:", help="Drive letter of the SD card (default: G:)")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be copied without actually copying")
    parser.add_argument(
        "--keep-source",
        action="store_true",
        help="Keep files on SD card after copying (default: delete after copy)",
    )

    args = vars(parser.parse_args())
    transfer_logs(
        sd_drive=args["sd_drive"],
        dry_run=args["dry_run"],
        keep_source=args["keep_source"],
    )


if __name__ == "__main__":
    main()
