import os
import pickle
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive"]

# ---------- Authentication ----------


def authenticate():
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as f:
            pickle.dump(creds, f)

    return creds


creds = authenticate()

# One service per thread
thread_local = threading.local()


def service():
    if not hasattr(thread_local, "svc"):
        thread_local.svc = build(
            "drive",
            "v3",
            credentials=creds,
            cache_discovery=False,
        )
    return thread_local.svc


# ---------- Collect file IDs ----------

svc = service()

print("Collecting owned files...")

page_token = None
ids = []

while True:
    resp = (
        svc.files()
        .list(
            q="'me' in owners",
            fields="nextPageToken,files(id,name)",
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )

    ids.extend(resp.get("files", []))

    page_token = resp.get("nextPageToken")
    if page_token is None:
        break

print(f"Found {len(ids):,} owned files.")

# ---------- Delete ----------

deleted = 0
failed = 0
lock = threading.Lock()


def delete(file):
    global deleted, failed

    try:
        service().files().delete(
            fileId=file["id"],
            supportsAllDrives=True,
        ).execute()

        with lock:
            deleted += 1
            if deleted % 100 == 0:
                print(f"Deleted {deleted:,}/{len(ids):,}")

    except HttpError:
        with lock:
            failed += 1


with ThreadPoolExecutor(max_workers=16) as pool:
    futures = [pool.submit(delete, f) for f in ids]

    for _ in as_completed(futures):
        pass

print()
print(f"Deleted : {deleted:,}")
print(f"Failed  : {failed:,}")
print("Done.")
