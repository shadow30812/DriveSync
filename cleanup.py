import logging

from blacklist import should_ignore
from drive_api import DriveAPI

TARGET_FOLDER_ID = "1UQ6wQeFpzeQ9NuzMNvQ4NXCgEqKKbjwg"

logging.basicConfig(
    filename="cleanup_audit.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def trash_item(drive, item_id, item_name):
    """Helper function to execute the trash command and log it."""
    print(f"Moving to Trash: {item_name} (ID: {item_id})")
    try:
        drive.service.files().update(fileId=item_id, body={"trashed": True}).execute()
        logging.info(f"TRASHED | ID: {item_id} | Name: {item_name}")
        return True
    except Exception as e:
        print(f"Failed to trash {item_name}: {e}")
        return False


def targeted_scan(drive, folder_id):
    """Recursively scans a specific folder and its subfolders."""
    query = f"'{folder_id}' in parents and trashed=false"
    page_token = None
    trashed_count = 0

    while True:
        results = (
            drive.service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )

        items = results.get("files", [])

        for item in items:
            if should_ignore(item["name"]):
                if trash_item(drive, item["id"], item["name"]):
                    trashed_count += 1
                continue

            if item["mimeType"] == "application/vnd.google-apps.folder":
                trashed_count += targeted_scan(drive, item["id"])

        page_token = results.get("nextPageToken", None)
        if not page_token:
            break

    return trashed_count


def global_scan(drive):
    """Scans the entire Drive in one flat pass."""
    query = "trashed=false"
    page_token = None
    trashed_count = 0

    while True:
        results = (
            drive.service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )

        items = results.get("files", [])

        for item in items:
            print(f"Moving to Trash: {item['name']} (ID: {item['id']})")
            try:
                if should_ignore(item["name"]):
                    if trash_item(drive, item["id"], item["name"]):
                        trashed_count += 1
                logging.info(f"TRASHED | ID: {item['id']} | Name: {item['name']}")
            except Exception as e:
                print(f"Failed to trash {item['name']}: {e}")

        page_token = results.get("nextPageToken", None)
        if not page_token:
            break

    return trashed_count


def clean_drive_bloat():
    print("Initializing Drive API for Cleanup...")
    drive = DriveAPI()

    if TARGET_FOLDER_ID:
        print(f"Initiating targeted recursive scan on Folder ID: {TARGET_FOLDER_ID}")
        trashed_count = targeted_scan(drive, TARGET_FOLDER_ID)
    else:
        print("Initiating global Drive scan... (This may take a moment)")
        trashed_count = global_scan(drive)

    print(
        f"\nCleanup Complete! Successfully sent {trashed_count} blacklisted items to the Trash."
    )


if __name__ == "__main__":
    scope_warning = (
        f"Folder ID: {TARGET_FOLDER_ID}" if TARGET_FOLDER_ID else "your ENTIRE Drive"
    )
    user_input = input(
        f"This will scan {scope_warning} and move ALL blacklisted items to your Trash. Proceed? (y/n): "
    )
    if user_input.lower() == "y":
        clean_drive_bloat()
    else:
        print("Cleanup aborted.")
