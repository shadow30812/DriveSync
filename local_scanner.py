import logging
import os
from logging.handlers import RotatingFileHandler

from blacklist import should_ignore_dir, should_ignore_file
from console import console
from state_manager import StateManager

skip_logger = logging.getLogger("skipped_files")
skip_logger.setLevel(logging.INFO)
skip_handler = RotatingFileHandler(
    "skipped_files.log", maxBytes=10 * 1024 * 1024, backupCount=1
)
skip_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
skip_logger.addHandler(skip_handler)
skip_logger.propagate = False


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
        unreadable = set()

        while stack:
            current_dir, parent_inode = stack.pop()
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        console.advance()
                        try:
                            entry_is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            entry_is_dir = False
                        ignored = (
                            should_ignore_dir(entry.path)
                            if entry_is_dir
                            else should_ignore_file(entry.path)
                        )
                        if ignored:
                            skip_logger.info(f"IGNORED: {entry.path}")
                            continue

                        try:
                            if entry.is_symlink():
                                skip_logger.info(f"SKIPPED SYMLINK: {entry.path}")
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
                                            "content_changed": not is_folder
                                            and db_record["mtime"] < mtime,
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
                            unreadable.add(entry.path)
                            continue

            except (PermissionError, OSError) as e:
                print(f"Skipping inaccessible folder {current_dir}: {e}")
                unreadable.add(current_dir)

        all_db_records = self.db.get_all_inodes()
        for record in all_db_records:
            if record["inode"] not in seen_inodes and not _is_under_any(
                record["path"], unreadable
            ):
                changes["deleted"].append(record)

        self._pair_replaced_files(changes)

        changes["deleted"].sort(key=lambda x: x["path"].count(os.sep), reverse=True)
        return changes

    @staticmethod
    def _pair_replaced_files(changes):
        """A file saved via write-to-temp-and-rename keeps its path but gets a
        new inode, so it shows up as deleted + new. Turn each such pair into a
        content update of the existing Drive file instead of trash + upload."""
        new_files = {
            item["path"]: item for item in changes["new"] if not item["is_folder"]
        }
        still_deleted = []
        for record in changes["deleted"]:
            item = None if record["is_folder"] else new_files.pop(record["path"], None)
            if item is None:
                still_deleted.append(record)
                continue
            changes["new"].remove(item)
            changes["modified"].append(
                {
                    "path": item["path"],
                    "inode": item["inode"],
                    "drive_id": record["drive_id"],
                    "mtime": item["mtime"],
                    "parent_inode": item["parent_inode"],
                    "old_inode": record["inode"],
                }
            )
        changes["deleted"] = still_deleted


def _is_under_any(path, roots):
    return any(path == root or path.startswith(root + os.sep) for root in roots)


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
