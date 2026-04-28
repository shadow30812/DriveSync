import logging
import os
import re
from logging.handlers import RotatingFileHandler

from drive_api import DriveAPI
from local_scanner import LocalScanner
from state_manager import StateManager

# --- Configuration ---
LOCAL_DIRECTORY = r"/media/shadow30812/Windows-SSD/Well"
DRIVE_LINK = (
    "https://drive.google.com/drive/u/0/folders/1UQ6wQeFpzeQ9NuzMNvQ4NXCgEqKKbjwg"
)

log_handler = RotatingFileHandler(
    "sync_audit.log", maxBytes=10 * 1024 * 1024, backupCount=2
)
logging.basicConfig(
    handlers=[log_handler],
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def extract_drive_id(link):
    """Extracts the folder ID from a standard Google Drive URL."""
    match = re.search(r"/folders/([a-zA-Z0-9-_]+)", link)
    return match.group(1) if match else link


def main():
    root_drive_id = extract_drive_id(DRIVE_LINK)
    root_stat = os.stat(LOCAL_DIRECTORY)

    print("1. Initializing Systems...")
    db = StateManager()
    drive = DriveAPI()
    scanner = LocalScanner(LOCAL_DIRECTORY, db)

    db.upsert_record(
        inode=str(root_stat.st_ino),
        path=LOCAL_DIRECTORY,
        drive_id=root_drive_id,
        mtime=root_stat.st_mtime,
        is_folder=True,
        parent_inode=None,
    )

    print("2. Scanning local files...")
    changes = scanner.scan()

    # --- Process Deletions ---
    if changes.get("deleted"):
        print(f"-> Processing {len(changes['deleted'])} deleted items...")
        for item in changes["deleted"]:
            name = os.path.basename(item["path"])
            print(f"   -> Moving to Trash: {name}")

            drive.trash_item(item["drive_id"])
            db.delete_record(item["inode"])
            logging.info(f"TRASHED | ID: {item['drive_id']} | Path: {item['path']}")

    # --- Process Renames and Moves ---
    deferred_moves = []

    if changes["renamed_or_moved"]:
        print(
            f"3. Processing {len(changes['renamed_or_moved'])} moved/renamed items..."
        )
        for item in changes["renamed_or_moved"]:
            new_name = os.path.basename(item["new_path"])
            parent_record = db.get_record(item["new_parent_inode"])
            if not parent_record:
                print(f"   -> Deferring {new_name}: Parent folder not synced yet.")
                deferred_moves.append(item)
                continue

            print(f"   -> Moving/Renaming to: {new_name}")
            drive.rename_or_move(item["drive_id"], new_name, parent_record["drive_id"])
            logging.info(
                f"MOVED/RENAMED | ID: {item['drive_id']} | Path: {item['new_path']}"
            )
            stat = os.stat(item["new_path"])
            db.upsert_record(
                item["inode"],
                item["new_path"],
                item["drive_id"],
                stat.st_mtime,
                item["is_folder"],
                item["new_parent_inode"],
            )

    # --- Process New Items ---
    if changes["new"]:
        print(f"4. Processing {len(changes['new'])} unmapped items...")
        remote_map = drive.get_full_remote_map()
        changes["new"].sort(key=lambda x: x["path"].count(os.sep))

        for item in changes["new"]:
            name = os.path.basename(item["path"])
            parent_record = db.get_record(item["parent_inode"])
            if not parent_record:
                print(f"   -> Skipping {name}: Parent folder not synced yet.")
                continue

            parent_drive_id = parent_record["drive_id"]
            existing_id = remote_map.get(parent_drive_id, {}).get(name)

            if existing_id:
                new_drive_id = existing_id
            elif item["is_folder"]:
                print(f"   -> Creating New Folder: {name}")
                new_drive_id = drive.create_folder(name, parent_drive_id)
                logging.info(
                    f"CREATED FOLDER | ID: {new_drive_id} | Path: {item['path']}"
                )
                if parent_drive_id not in remote_map:
                    remote_map[parent_drive_id] = {}
                remote_map[parent_drive_id][name] = new_drive_id
            else:
                try:
                    print(f"   -> Uploading New File: {name}")
                    new_drive_id = drive.upload_new_file(item["path"], parent_drive_id)
                    logging.info(
                        f"UPLOADED FILE | ID: {new_drive_id} | Path: {item['path']}"
                    )
                except OSError as e:
                    print(f"   -> ERROR reading file {name}: {e}. Skipping upload.")
                    continue

            db.upsert_record(
                item["inode"],
                item["path"],
                new_drive_id,
                item["mtime"],
                item["is_folder"],
                item["parent_inode"],
            )

    # --- Process Deferred Moves ---
    if deferred_moves:
        print(f"-> Processing {len(deferred_moves)} deferred moves...")
        for item in deferred_moves:
            new_name = os.path.basename(item["new_path"])
            parent_record = db.get_record(item["new_parent_inode"])
            if not parent_record:
                print(f"   -> Error: Parent for {new_name} still not found. Skipping.")
                continue

            print(f"   -> Moving/Renaming to: {new_name}")
            drive.rename_or_move(item["drive_id"], new_name, parent_record["drive_id"])
            logging.info(
                f"MOVED/RENAMED (DEFERRED) | ID: {item['drive_id']} | Path: {item['new_path']}"
            )
            stat = os.stat(item["new_path"])
            db.upsert_record(
                item["inode"],
                item["new_path"],
                item["drive_id"],
                stat.st_mtime,
                item["is_folder"],
                item["new_parent_inode"],
            )

    # --- Process Modified Items ---
    if changes["modified"]:
        print(f"5. Processing {len(changes['modified'])} modified files...")
        for item in changes["modified"]:
            name = os.path.basename(item["path"])
            try:
                print(f"   -> Updating Content: {name}")
                drive.update_modified_file(item["path"], item["drive_id"])
                logging.info(
                    f"UPDATED CONTENT | ID: {item['drive_id']} | Path: {item['path']}"
                )
            except OSError as e:
                print(f"   -> ERROR reading file {name}: {e}. Skipping update.")
                continue

            db.upsert_record(
                item["inode"],
                item["path"],
                item["drive_id"],
                item["mtime"],
                False,
                item["parent_inode"],
            )

    print("\nFast Sync Complete!")

    try:
        user_input = input(
            "\nWould you like to run a deep redundancy check for missing/corrupted files? (This compares MD5 checksums and is significantly slower) [Y/n]: "
        )
        if user_input.lower() != "n":
            from redundancy_check import verify_uploads

            verify_uploads(drive, db, LOCAL_DIRECTORY, root_drive_id)

    except KeyboardInterrupt:
        pass

    db.close()


if __name__ == "__main__":
    main()
