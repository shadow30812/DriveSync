import logging
import os
import shutil
import sys

from drive_api import DriveAPI

TARGET_FILE_ID = None
TARGET_FOLDER_ID = "1UQ6wQeFpzeQ9NuzMNvQ4NXCgEqKKbjwg"

DESTINATION_PATH = r"/media/shadow30812/Windows-SSD/Well/DriveSync_Downloads"

logging.basicConfig(
    filename="download_audit.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_folder_contents(drive_api, folder_id, current_rel_path=""):
    """
    Recursively fetches all binary files and their relative paths within a Drive folder.
    """
    download_list = []
    query = f"'{folder_id}' in parents and trashed=false"
    page_token = None

    while True:
        results = (
            drive_api.service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )

        for item in results.get("files", []):
            item_path = os.path.join(current_rel_path, item["name"])

            if item["mimeType"] == "application/vnd.google-apps.folder":
                download_list.extend(
                    get_folder_contents(drive_api, item["id"], item_path)
                )
            else:
                if "size" in item:
                    download_list.append((item["id"], item_path, int(item["size"])))
                else:
                    print(
                        f"   -> Skipping {item['name']} (Workspace document, no direct binary)"
                    )
                    logging.warning(f"SKIPPED | Workspace document: {item['name']}")

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return download_list


def check_disk_space(target_dir, total_required_bytes):
    """Verifies the target partition has enough space to accommodate the download."""
    os.makedirs(target_dir, exist_ok=True)
    usage = shutil.disk_usage(target_dir)
    safe_required_bytes = total_required_bytes * 1.1

    if usage.free < safe_required_bytes:
        err_msg = f"Insufficient disk space. Required: {total_required_bytes / (1024 * 1024):.2f} MB, Free: {usage.free / (1024 * 1024):.2f} MB"
        print(f"\n[CRITICAL ERROR] {err_msg}")
        logging.error(f"TERMINATED | {err_msg}")
        sys.exit(1)

    print(
        f"Disk space check passed. Estimated additional space required: {total_required_bytes / (1024 * 1024):.2f} MB.\n"
    )


def main():
    logging.info("--- Download Session Started ---")

    if (TARGET_FILE_ID is None) == (TARGET_FOLDER_ID is None):
        print("[CRITICAL ERROR] Invalid Configuration.")
        print("You must provide EITHER a TARGET_FILE_ID OR a TARGET_FOLDER_ID.")
        print("Please edit the configuration block in download.py and try again.")
        sys.exit(1)

    print("Initializing Drive API for Download...")
    drive = DriveAPI()
    files_to_download = []
    total_download_size = 0

    print("Resolving target files and calculating storage delta...")
    if TARGET_FILE_ID:
        try:
            metadata = (
                drive.service.files()
                .get(fileId=TARGET_FILE_ID, fields="id, name, size")
                .execute()
            )
            if "size" in metadata:
                size = int(metadata["size"])
                files_to_download.append((TARGET_FILE_ID, DESTINATION_PATH, size))

                local_size = (
                    os.path.getsize(DESTINATION_PATH)
                    if os.path.exists(DESTINATION_PATH)
                    else 0
                )
                if size > local_size:
                    total_download_size += size - local_size
            else:
                print("[ERROR] Target is a Google Workspace document or has no size.")
                sys.exit(1)

        except Exception as e:
            print(f"[ERROR] Failed to fetch file metadata: {e}")
            sys.exit(1)

    elif TARGET_FOLDER_ID:
        resolved_items = get_folder_contents(drive, TARGET_FOLDER_ID)
        for file_id, rel_path, size in resolved_items:
            abs_path = os.path.join(DESTINATION_PATH, rel_path)

            if os.path.exists(abs_path):
                local_size = os.path.getsize(abs_path)
                if size > local_size:
                    total_download_size += size - local_size
            else:
                total_download_size += size

            files_to_download.append((file_id, abs_path, size))

    if not files_to_download:
        print("No valid files found to download.")
        return

    base_check_dir = (
        os.path.dirname(DESTINATION_PATH) if TARGET_FILE_ID else DESTINATION_PATH
    )
    check_disk_space(base_check_dir, total_download_size)

    print(f"Starting high-speed download of {len(files_to_download)} file(s)...")
    for file_id, dest_path, size in files_to_download:
        filename = os.path.basename(dest_path)
        print(f"-> Downloading '{filename}' ({(size / (1024 * 1024)):.2f} MB)...")

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        try:
            drive.download_file(file_id, dest_path)
            logging.info(f"DOWNLOADED | ID: {file_id} | Path: {dest_path}")
        except Exception as e:
            print(f"   [ERROR] Failed to download {file_id}: {e}")
            logging.error(f"FAILED DOWNLOAD | ID: {file_id} | Error: {e}")

    print("\nDownload Operations Complete.")
    logging.info("--- Download Session Completed ---")


if __name__ == "__main__":
    main()
