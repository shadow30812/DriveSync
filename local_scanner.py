import os

from blacklist import should_ignore
from state_manager import StateManager


class LocalScanner:
    def __init__(self, root_dir, state_manager: StateManager):
        self.root_dir = os.path.abspath(root_dir)
        self.db = state_manager

    def scan(self):
        print(f"Starting high-speed scan of {self.root_dir}...")

        root_stat = os.stat(self.root_dir)
        root_inode = str(root_stat.st_ino)
        stack = [(self.root_dir, str(root_stat.st_ino))]
        changes = {"new": [], "modified": [], "renamed_or_moved": [], "deleted": []}
        seen_inodes = {root_inode}

        while stack:
            current_dir, parent_inode = stack.pop()
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        if should_ignore(entry.name):
                            print(
                                f"Skipping ignored folder types: {entry.path}. \n\
                                Written to skipped_files.log"
                            )
                            with open(
                                "skipped_files.log", "a", encoding="utf-8"
                            ) as log_file:
                                log_file.write(f"IGNORED: {entry.path}\n")
                            continue

                        try:
                            if entry.is_symlink():
                                print(
                                    f"Skipping symlink (unsupported by Drive): {entry.path}. \n\
                                    Written to skipped_files.log"
                                )
                                with open(
                                    "skipped_files.log", "a", encoding="utf-8"
                                ) as log_file:
                                    log_file.write(f"SKIPPED SYMLINK: {entry.path}\n")
                                continue

                            stat = entry.stat(follow_symlinks=False)
                            inode = str(stat.st_ino)
                            mtime = stat.st_mtime

                            is_folder = entry.is_dir(follow_symlinks=False)
                            path = entry.path
                            seen_inodes.add(inode)

                            if is_folder:
                                stack.append((path, inode))

                            db_record = self.db.get_record(inode)
                            if db_record and bool(db_record["is_folder"]) != bool(
                                is_folder
                            ):
                                changes["deleted"].append(db_record)
                                db_record = None

                            if not db_record:
                                changes["new"].append(
                                    {
                                        "path": path,
                                        "inode": inode,
                                        "is_folder": is_folder,
                                        "parent_inode": parent_inode,
                                        "mtime": mtime,
                                    }
                                )
                            else:
                                if db_record["path"] != path:
                                    changes["renamed_or_moved"].append(
                                        {
                                            "old_path": db_record["path"],
                                            "new_path": path,
                                            "inode": inode,
                                            "drive_id": db_record["drive_id"],
                                            "new_parent_inode": parent_inode,
                                            "is_folder": is_folder,
                                        }
                                    )
                                elif not is_folder and db_record["mtime"] < mtime:
                                    changes["modified"].append(
                                        {
                                            "path": path,
                                            "inode": inode,
                                            "drive_id": db_record["drive_id"],
                                            "mtime": mtime,
                                            "parent_inode": parent_inode,
                                        }
                                    )
                        except OSError as e:
                            print(f"Skipping unreadable file {entry.path}: {e}")
                            continue

            except (PermissionError, OSError) as e:
                print(f"Skipping inaccessible folder {current_dir}: {e}")

        all_db_records = self.db.get_all_inodes()
        for record in all_db_records:
            if record["inode"] not in seen_inodes:
                changes["deleted"].append(record)

        changes["deleted"].sort(key=lambda x: x["path"].count(os.sep), reverse=True)
        return changes


if __name__ == "__main__":
    db = StateManager("test_sync.db")
    TEST_PATH = "./test_folder"
    os.makedirs(TEST_PATH, exist_ok=True)

    scanner = LocalScanner(TEST_PATH, db)
    detected_changes = scanner.scan()

    print("\n--- Scan Results ---")
    print(f"New Items: {len(detected_changes['new'])}")
    print(f"Modified Files: {len(detected_changes['modified'])}")
    print(f"Renamed/Moved: {len(detected_changes['renamed_or_moved'])}")

    db.close()
