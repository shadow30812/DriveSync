import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveAPI:
    def __init__(self):
        self.service = self._authenticate()

    def _authenticate(self):
        """Authenticates the user and returns the Drive API service."""
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
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
        """Uploads a new file using resumable uploads."""
        name = os.path.basename(file_path)
        metadata = {"name": name, "parents": [parent_id]}
        media = MediaFileUpload(file_path, resumable=True)

        file = (
            self.service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        return file.get("id")

    def update_modified_file(self, file_path, drive_id):
        """Overwrites the content of an existing Drive file."""
        media = MediaFileUpload(file_path, resumable=True)
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
