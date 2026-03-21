import logging

from drive_api import DriveAPI
from blacklist import IGNORED_NAMES

logging.basicConfig(
    filename="cleanup_audit.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def clean_drive_bloat():
    print("Initializing Drive API for Cleanup...")
    drive = DriveAPI()

    print(f"Searching entire Drive for: {', '.join(IGNORED_NAMES)}")
    name_queries = " or ".join([f"name='{name}'" for name in IGNORED_NAMES])
    query = f"({name_queries}) and trashed=false"

    page_token = None
    trashed_count = 0

    while True:
        results = (
            drive.service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )

        items = results.get("files", [])

        for item in items:
            print(f"Moving to Trash: {item['name']} (ID: {item['id']})")
            try:
                drive.service.files().update(
                    fileId=item["id"], body={"trashed": True}
                ).execute()
                trashed_count += 1
                logging.info(f"TRASHED | ID: {item['id']} | Name: {item['name']}")
            except Exception as e:
                print(f"Failed to trash {item['name']}: {e}")

        page_token = results.get("nextPageToken", None)
        if not page_token:
            break

    print(
        f"\nCleanup Complete! Successfully sent {trashed_count} parent items to the Trash."
    )


if __name__ == "__main__":
    user_input = input(
        "This will move all blacklisted folders to your Drive Trash. Proceed? (y/n): "
    )
    if user_input.lower() == "y":
        clean_drive_bloat()
    else:
        print("Cleanup aborted.")
