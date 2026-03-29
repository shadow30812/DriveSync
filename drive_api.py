import io
import os
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveAPI:
    def __init__(self):
        self.service = self._authenticate()

    def _clear_expired_token(self, token_path="token.json"):
        """Deletes the token if it's older than 7 days to prevent invalid_grant errors."""
        if not os.path.exists(token_path):
            return

        seven_days_sec = 7 * 24 * 60 * 60
        token_age = time.time() - os.path.getmtime(token_path)

        if token_age > seven_days_sec:
            print(
                f"\n[INFO] OAuth token is older than 7 days ({(token_age / 86400):.1f} days). Deleting to force re-authentication..."
            )
            try:
                os.remove(token_path)
            except OSError as e:
                print(f"[ERROR] Failed to delete expired token: {e}")

    def _authenticate(self):
        """Authenticates the user and returns the Drive API service."""
        self._clear_expired_token()
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(
                        f"\n[INFO] Token refresh failed ({e}). Forcing re-authentication..."
                    )
                    os.remove("token.json")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        "credentials.json", SCOPES
                    )
                    creds = flow.run_local_server(port=0)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())

        return build("drive", "v3", credentials=creds)

    def create_folder(self, name, parent_id):
        """Creates a folder on Drive and returns its ID."""
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        folder = self.service.files().create(body=metadata, fields="id").execute()
        return folder.get("id")

    def upload_new_file(self, file_path, parent_id):
        """Uploads a new file, skipping resumable requests for small files."""
        name = os.path.basename(file_path)
        metadata = {"name": name, "parents": [parent_id]}
        file_size = os.path.getsize(file_path)
        use_resumable = file_size > (5 * 1024 * 1024)

        media = MediaFileUpload(file_path, resumable=use_resumable)
        file = (
            self.service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        return file.get("id")

    def update_modified_file(self, file_path, drive_id):
        """Overwrites the content of an existing Drive file,
        skipping resumable requests for small files."""
        file_size = os.path.getsize(file_path)
        use_resumable = file_size > (5 * 1024 * 1024)

        media = MediaFileUpload(file_path, resumable=use_resumable)
        self.service.files().update(fileId=drive_id, media_body=media).execute()
        return drive_id

    def rename_or_move(self, drive_id, new_name, new_parent_id):
        """Updates the name and/or parent folder of a Drive item."""
        file = self.service.files().get(fileId=drive_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents", []))

        metadata = {"name": new_name}
        self.service.files().update(
            fileId=drive_id,
            body=metadata,
            addParents=new_parent_id,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()

    def find_item_by_name(self, name, parent_id, is_folder=False):
        """Checks if a file/folder already exists in a specific Drive folder."""
        safe_name = name.replace("'", "\\'")
        mime_query = (
            "mimeType='application/vnd.google-apps.folder'"
            if is_folder
            else "mimeType!='application/vnd.google-apps.folder'"
        )

        query = f"name='{safe_name}' and '{parent_id}' in parents and {mime_query} and trashed=false"
        results = (
            self.service.files()
            .list(q=query, spaces="drive", fields="files(id, name)")
            .execute()
        )

        items = results.get("files", [])
        return items[0].get("id") if items else None

    def get_full_remote_map(self):
        """Downloads the metadata of the entire Google Drive tree into RAM."""
        print("Downloading cloud state map... (This might take a minute)")
        remote_map = {}

        page_token = None
        while True:
            results = (
                self.service.files()
                .list(
                    q="trashed=false",
                    spaces="drive",
                    fields="nextPageToken, files(id, name, parents)",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )

            for item in results.get("files", []):
                file_id = item.get("id")
                name = item.get("name")
                parents = item.get("parents", [])

                if parents:
                    parent_id = parents[0]
                    if parent_id not in remote_map:
                        remote_map[parent_id] = {}
                    remote_map[parent_id][name] = file_id

            page_token = results.get("nextPageToken", None)
            if page_token is None:
                break

        print(
            f"Cloud state downloaded! Mapped {sum(len(v) for v in remote_map.values())} remote items."
        )
        return remote_map

    def trash_item(self, drive_id):
        """Moves a Drive item to the trash."""
        try:
            self.service.files().update(
                fileId=drive_id, body={"trashed": True}
            ).execute()
        except Exception as e:
            print(e)

    def get_file_metadata(self, file_id):
        """Fetches metadata for a specific file, specifically its size."""
        return (
            self.service.files().get(fileId=file_id, fields="id, name, size").execute()
        )

    def download_file(self, file_id, destination_path):
        """Downloads a file from Drive to the local filesystem using chunked streams."""
        request = self.service.files().get_media(fileId=file_id)

        with io.FileIO(destination_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=5 * 1024 * 1024)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
