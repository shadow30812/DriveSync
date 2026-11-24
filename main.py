import logging
import os
import re
from logging.handlers import RotatingFileHandler

from console import console
from drive_api import DriveAPI
from local_scanner import LocalScanner
from state_manager import StateManager

# --- Configuration ---
LOCAL_DIRECTORY = r"/mnt/Windows/Well"
DRIVE_LINK = "https://drive.google.com/drive/folders/1EBhun3WyFgftQk2aoXGnphEWh39MdQrb"

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


def _has_ancestor_in(path, folder_paths):
    parent = os.path.dirname(path)
    while parent and parent != LOCAL_DIRECTORY and parent != os.path.dirname(parent):
        if parent in folder_paths:
            return True
        parent = os.path.dirname(parent)
    return False


def update_content(drive, db, path, drive_id, parent_inode):
    """Overwrites a Drive file's content, re-uploading it if the Drive copy
    is gone. Returns the Drive ID now holding the file, or None on failure."""
    try:
        if drive.update_modified_file(path, drive_id):
            logging.info(f"UPDATED CONTENT | ID: {drive_id} | Path: {path}")
            return drive_id

        parent_record = db.get_record(parent_inode)
        if not parent_record:
            print(
                f"   -> Error: Parent for {os.path.basename(path)} not found. Skipping."
            )
            return None
        console.action(
            f"   -> Remote copy missing for {os.path.basename(path)}, re-uploading..."
        )
        new_id = drive.upload_new_file(path, parent_record["drive_id"])
        logging.info(f"UPLOADED FILE (REMOTE MISSING) | ID: {new_id} | Path: {path}")
        return new_id
    except OSError as e:
        print(
            f"   -> ERROR reading file {os.path.basename(path)}: {e}. Skipping update."
        )
        return None


def confirm_deletions(deleted):
    """Asks before trashing an unusually large number of items, listing the
    top-level folders and files that would go."""
    folders = {item["path"] for item in deleted if item["is_folder"]}
    tops = [item for item in deleted if not _has_ancestor_in(item["path"], folders)]
    tops.sort(key=lambda item: item["path"])

    console.finish()
    print(f"\n[WARNING] {len(deleted)} tracked items are gone locally or now ignored.")
    print(
        f"They are under these {len(tops)} top-level items, which will be moved to Drive trash:"
    )
    for item in tops[:50]:
        kind = "DIR " if item["is_folder"] else "FILE"
        print(f"   {kind} {os.path.relpath(item['path'], LOCAL_DIRECTORY)}")
    if len(tops) > 50:
        print(f"   ... and {len(tops) - 50} more")
    answer = input("Move these to Drive trash? [y/N]: ")
    return answer.strip().lower() == "y"


def apply_move(drive, db, item, parent_drive_id, deferred=False):
    """Renames/moves an item on Drive. If its Drive copy no longer exists
    (e.g. purged from trash, or the local inode was reused by a new file),
    it is re-created from the local copy instead."""
    new_name = os.path.basename(item["new_path"])
    drive_id = item["drive_id"]
    tag = "MOVED/RENAMED (DEFERRED)" if deferred else "MOVED/RENAMED"

    if drive.rename_or_move(drive_id, new_name, parent_drive_id):
        logging.info(f"{tag} | ID: {drive_id} | Path: {item['new_path']}")
        if item.get("content_changed"):
            console.action(f"   -> Updating Content: {new_name}")
            drive_id = update_content(
                drive, db, item["new_path"], drive_id, item["new_parent_inode"]
            )
            if not drive_id:
                return
    else:
        console.action(f"   -> Remote copy missing for {new_name}, re-creating it...")
        try:
            if item["is_folder"]:
                drive_id = drive.create_folder(new_name, parent_drive_id)
                logging.info(
                    f"CREATED FOLDER (REMOTE MISSING) | ID: {drive_id} | Path: {item['new_path']}"
                )
            else:
                drive_id = drive.upload_new_file(item["new_path"], parent_drive_id)
                logging.info(
                    f"UPLOADED FILE (REMOTE MISSING) | ID: {drive_id} | Path: {item['new_path']}"
                )
        except OSError as e:
            print(f"   -> ERROR reading file {new_name}: {e}. Skipping.")
            return

    stat = os.stat(item["new_path"])
    db.upsert_record(
        item["inode"],
        item["new_path"],
        drive_id,
        stat.st_mtime,
        item["is_folder"],
        item["new_parent_inode"],
    )


def main():
    console.install("errors.log")
    root_drive_id = extract_drive_id(DRIVE_LINK)
    if not os.path.isdir(LOCAL_DIRECTORY) or not os.listdir(LOCAL_DIRECTORY):
        print(
            f"[CRITICAL ERROR] {LOCAL_DIRECTORY} is missing or empty. Is the drive mounted?"
        )
        return
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
    console.phase("Scanning")
    changes = scanner.scan()
    console.finish()

    # --- Process Deletions ---
    total_tracked = len(db.get_all_inodes())
    if changes["deleted"] and (
        len(changes["deleted"]) > 1000 or len(changes["deleted"]) > 0.1 * total_tracked
    ):
        if not confirm_deletions(changes["deleted"]):
            print("-> Deletions skipped for this run.")
            changes["deleted"] = []

    if changes["deleted"]:
        print(f"-> Processing {len(changes['deleted'])} deleted items...")
        deleted_folders = {
            item["path"] for item in changes["deleted"] if item["is_folder"]
        }
        console.phase("Trashing", len(changes["deleted"]))
        for item in changes["deleted"]:
            console.advance()
            name = os.path.basename(item["path"])

            if not _has_ancestor_in(item["path"], deleted_folders):
                console.action(f"   -> Moving to Trash: {name}")
                drive.trash_item(item["drive_id"])
            db.delete_record(item["inode"])
            logging.info(f"TRASHED | ID: {item['drive_id']} | Path: {item['path']}")

    # --- Process Renames and Moves ---
    deferred_moves = []

    if changes["renamed_or_moved"]:
        print(
            f"3. Processing {len(changes['renamed_or_moved'])} moved/renamed items..."
        )
        console.phase("Moving/Renaming", len(changes["renamed_or_moved"]))
        for item in changes["renamed_or_moved"]:
            console.advance()
            new_name = os.path.basename(item["new_path"])
            parent_record = db.get_record(item["new_parent_inode"])
            if not parent_record:
                print(f"   -> Deferring {new_name}: Parent folder not synced yet.")
                deferred_moves.append(item)
                continue

            console.action(f"   -> Moving/Renaming to: {new_name}")
            apply_move(drive, db, item, parent_record["drive_id"])

    # --- Process New Items ---
    if changes["new"]:
        print(f"4. Processing {len(changes['new'])} unmapped items...")
        remote_map = drive.get_full_remote_map()
        changes["new"].sort(key=lambda x: x["path"].count(os.sep))

        console.phase("Uploading", len(changes["new"]))
        for item in changes["new"]:
            console.advance()
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
                console.action(f"   -> Creating New Folder: {name}")
                new_drive_id = drive.create_folder(name, parent_drive_id)
                logging.info(
                    f"CREATED FOLDER | ID: {new_drive_id} | Path: {item['path']}"
                )
                if parent_drive_id not in remote_map:
                    remote_map[parent_drive_id] = {}
                remote_map[parent_drive_id][name] = new_drive_id
            else:
                try:
                    console.action(f"   -> Uploading New File: {name}")
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
        console.phase("Deferred moves", len(deferred_moves))
        for item in deferred_moves:
            console.advance()
            new_name = os.path.basename(item["new_path"])
            parent_record = db.get_record(item["new_parent_inode"])
            if not parent_record:
                print(f"   -> Error: Parent for {new_name} still not found. Skipping.")
                continue

            console.action(f"   -> Moving/Renaming to: {new_name}")
            apply_move(drive, db, item, parent_record["drive_id"], deferred=True)

    # --- Process Modified Items ---
    if changes["modified"]:
        print(f"5. Processing {len(changes['modified'])} modified files...")
        console.phase("Updating", len(changes["modified"]))
        for item in changes["modified"]:
            console.advance()
            name = os.path.basename(item["path"])
            console.action(f"   -> Updating Content: {name}")
            drive_id = update_content(
                drive, db, item["path"], item["drive_id"], item["parent_inode"]
            )
            if not drive_id:
                continue

            if item.get("old_inode"):
                db.delete_record(item["old_inode"])
            db.upsert_record(
                item["inode"],
                item["path"],
                drive_id,
                item["mtime"],
                False,
                item["parent_inode"],
            )

    console.finish()
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
