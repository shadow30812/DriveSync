import hashlib
import logging
import os

from blacklist import should_ignore


def compute_md5(file_path):
    """Computes the MD5 hash of a local file to match Google Drive's format."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except OSError:
        return None


def build_remote_tree(drive_api, root_id, local_base_path):
    """Fetches Drive files and maps them strictly to their expected local paths."""
    print("   -> Fetching cloud state and checksums...")
    files = []
    page_token = None
    while True:
        request = drive_api.service.files().list(
            q="trashed=false",
            spaces="drive",
            fields="nextPageToken, files(id, name, parents, md5Checksum, mimeType)",
            pageSize=1000,
            pageToken=page_token,
        )
        results = drive_api.safe_execute(request)
        files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    id_to_file = {f["id"]: f for f in files}
    remote_path_map = {}

    def resolve_path(file_item):
        path_parts = [file_item["name"]]
        current = file_item
        found_target_root = False

        while current.get("parents"):
            parent_id = current["parents"][0]
            if parent_id == root_id:
                found_target_root = True
                break
            if parent_id not in id_to_file:
                return None
            current = id_to_file[parent_id]
            path_parts.insert(0, current["name"])

        if not found_target_root:
            return None

        return os.path.join(local_base_path, *path_parts)

    for f in files:
        if f["mimeType"] != "application/vnd.google-apps.folder":
            full_path = resolve_path(f)
            if full_path:
                remote_path_map[full_path] = f

    return remote_path_map


def verify_uploads(drive_api, db, local_directory, root_drive_id):
    """Verifies Drive has 100% accurate copies of local files."""
    print("\n--- Deep Redundancy Check: Verifying Uploads ---")
    logging.info("--- Deep Redundancy Check Started (Uploads) ---")

    remote_map = build_remote_tree(drive_api, root_drive_id, local_directory)
    local_files = []

    for root, dirs, files in os.walk(local_directory):
        dirs[:] = [d for d in dirs if not should_ignore(d)]
        for file in files:
            if not should_ignore(file):
                local_files.append(os.path.join(root, file))

    for local_path in local_files:
        remote_file = remote_map.get(local_path)
        needs_upload = False
        drive_id = None

        stat = os.stat(local_path)
        inode = str(stat.st_ino)
        parent_inode = str(os.stat(os.path.dirname(local_path)).st_ino)

        if not remote_file:
            print(
                f"[MISSING UPLOAD] {os.path.basename(local_path)} not found on Drive."
            )
            needs_upload = True
        else:
            local_md5 = compute_md5(local_path)
            if local_md5 != remote_file.get("md5Checksum"):
                print(
                    f"[CORRUPTED UPLOAD] {os.path.basename(local_path)} checksum mismatch."
                )
                needs_upload = True
                drive_id = remote_file["id"]

        if needs_upload:
            try:
                if drive_id:
                    print(f"   -> Fixing content for {os.path.basename(local_path)}...")
                    drive_api.update_modified_file(local_path, drive_id)
                    logging.info(
                        f"UPDATED CONTENT (DEEP REPAIR) | ID: {drive_id} | Path: {local_path}"
                    )
                else:
                    print(
                        f"   -> Uploading missing file {os.path.basename(local_path)}..."
                    )
                    parent_record = db.get_record(parent_inode)
                    if parent_record:
                        drive_id = drive_api.upload_new_file(
                            local_path, parent_record["drive_id"]
                        )
                        logging.info(
                            f"UPLOADED FILE (DEEP REPAIR) | ID: {drive_id} | Path: {local_path}"
                        )
                    else:
                        error_msg = f"Cannot upload {local_path}. Fast-sync must establish the folder structure first."
                        print(f"   -> [ERROR] {error_msg}")
                        logging.warning(f"SKIPPED REPAIR | {error_msg}")
                        continue

                db.upsert_record(
                    inode, local_path, drive_id, stat.st_mtime, False, parent_inode
                )
            except Exception as e:
                print(f"   -> Failed to sync {local_path}: {e}")
                logging.error(f"FAILED REPAIR UPLOAD | Path: {local_path} | Error: {e}")

    print("Upload verification complete.")
    logging.info("--- Deep Redundancy Check Completed (Uploads) ---")


def verify_downloads(drive_api, target_folder_id, target_file_id, destination_path):
    """Verifies local machine has 100% accurate copies of Drive files."""
    print("\n--- Deep Redundancy Check: Verifying Downloads ---")
    logging.info("--- Deep Redundancy Check Started (Downloads) ---")

    if target_folder_id:
        remote_map = build_remote_tree(drive_api, target_folder_id, destination_path)

        for expected_local_path, remote_file in remote_map.items():
            needs_download = False

            if not os.path.exists(expected_local_path):
                print(
                    f"[MISSING DOWNLOAD] {os.path.basename(expected_local_path)} not found locally."
                )
                needs_download = True
            else:
                local_md5 = compute_md5(expected_local_path)
                if local_md5 != remote_file.get("md5Checksum"):
                    print(
                        f"[CORRUPTED DOWNLOAD] {os.path.basename(expected_local_path)} checksum mismatch."
                    )
                    needs_download = True

            if needs_download:
                print(
                    f"   -> Securing full download for {os.path.basename(expected_local_path)}..."
                )
                os.makedirs(os.path.dirname(expected_local_path), exist_ok=True)
                try:
                    drive_api.download_file(remote_file["id"], expected_local_path)
                    logging.info(
                        f"DOWNLOADED (DEEP REPAIR) | ID: {remote_file['id']} | Path: {expected_local_path}"
                    )
                except Exception as e:
                    print(f"   -> Failed to download {expected_local_path}: {e}")
                    logging.error(
                        f"FAILED REPAIR DOWNLOAD | ID: {remote_file['id']} | Error: {e}"
                    )

    elif target_file_id:
        request = drive_api.service.files().get(
            fileId=target_file_id, fields="id, name, md5Checksum"
        )
        remote_file = drive_api.safe_execute(request)

        if not os.path.exists(destination_path) or compute_md5(
            destination_path
        ) != remote_file.get("md5Checksum"):
            print(
                f"[FIXING DOWNLOAD] Pulling accurate copy of {remote_file['name']}..."
            )
            try:
                drive_api.download_file(remote_file["id"], destination_path)
                logging.info(
                    f"DOWNLOADED (DEEP REPAIR) | ID: {remote_file['id']} | Path: {destination_path}"
                )
            except Exception as e:
                print(f"   -> Failed to download {destination_path}: {e}")
                logging.error(
                    f"FAILED REPAIR DOWNLOAD | ID: {remote_file['id']} | Error: {e}"
                )

    print("Download verification complete.")
    logging.info("--- Deep Redundancy Check Completed (Downloads) ---")
