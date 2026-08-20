# Google Drive Sync & Cleanup Tool

A high-performance, incremental synchronization tool for mirroring a local directory to Google Drive. The system is designed to minimize redundant operations by detecting filesystem changes precisely and maintaining a persistent mapping between local files and their corresponding Google Drive items.

Repository: [https://github.com/shadow30812/drivesync](https://github.com/shadow30812/drivesync)

---

## Overview

This project provides:

* Incremental, one-way synchronization from a local directory to Google Drive
* Reliable change detection using inode-based tracking
* Efficient API usage to reduce unnecessary uploads and updates
* A cleanup utility to remove common development artifacts from Google Drive
* A high-speed, chunked download utility for targeted file or folder retrieval
* Persistent state management using SQLite

---

## Key Features

### Incremental Synchronization

The system detects and processes only the changes since the last run:

* New files and folders
* Modified files (based on last modified time)
* Renamed or moved items (detected via inode consistency)
* Local deletions (mirrors local removals by moving the corresponding Drive items to the Trash)

This significantly reduces execution time and API usage compared to full re-sync approaches.

### Inode-Based Change Tracking

A central design feature of this project is the use of filesystem inodes as stable identifiers for files and directories.

#### What is an inode?

An inode is a unique identifier assigned by the operating system to each file or directory. Unlike file paths, inodes remain constant even if a file is renamed or moved within the same filesystem.

#### Why use inodes?

Traditional sync tools rely on file paths, which makes it difficult to distinguish between:

* A renamed file
* A moved file
* A deleted file followed by a new file with the same name

By using inodes, this tool can:

* Detect renames and moves without re-uploading data
* Preserve identity of files across structural changes
* Avoid duplication on Google Drive

#### How it works

* Each scanned file is identified by its inode (`st_ino`)
* A persistent SQLite database stores:

  * inode
  * path
  * Google Drive file ID
  * modification time
* During subsequent scans:

  * If an inode exists but the path has changed → treated as rename/move
  * If modification time increases → treated as modified
  * If inode is new → treated as a new file

This approach provides both accuracy and efficiency.

---

### Deep Redundancy & Integrity Checking (Dual-Layer Architecture)

While the inode-based scanner is extremely fast, dynamically generated inodes (especially when mounting Windows NTFS/exFAT partitions on Linux) can sometimes collide or change, causing files to be silently skipped.  

To guarantee absolute data integrity, the system employs a dual-layer approach:

1. **The Fast Pass:** Uses OS-level inodes and modification times for rapid daily syncing.
2. **The Deep Check:** An optional, rigorous verification layer that bypasses OS metadata entirely.

**How the Deep Check works:**

* **Cryptographic Verification:** Computes local MD5 hashes and compares them directly against Google Drive's native `md5Checksum` metadata.
* **Phase 1 (Upload Verification):** Treats your local drive as the absolute master. Identifies skipped, missing, or corrupted files on Drive and forces an upload/update, then automatically injects the corrected metadata back into the SQLite database so the fast scanner recognizes it.
* **Phase 2 (Download Verification):** Treats Google Drive as the absolute master. Scans your local download directory for any missing chunks or corrupted files and automatically pulls accurate copies from the cloud.

---

### Persistent State Management

State is stored in a local SQLite database (`sync_state.db`).

Tracked metadata includes:

* Inode
* File path
* Google Drive file ID
* Last modified timestamp
* Parent inode

This allows the system to resume operations reliably across runs.

---

### Efficient Directory Scanning

The scanner uses:

* `os.scandir()` for faster directory traversal
* An explicit stack instead of recursion

This results in improved performance, especially for large directory trees.

---

### Google Drive Integration

The system integrates with the Google Drive API to:

* Create folders
* Upload files (resumable uploads)
* Update file contents
* Move and rename files
* Query remote state efficiently

Authentication is handled using OAuth2.

---

### Remote State Mapping Optimization

Before processing new files, the system builds an in-memory map of existing Drive items:

* Reduces redundant folder/file creation
* Avoids duplicate uploads
* Enables faster existence checks

---

### Cleanup Utility

A separate cleanup tool identifies and trashes unnecessary files and directories on Google Drive.

Targets include:

* `.git`
* `node_modules`
* `__pycache__`
* Virtual environments (`venv`, `.venv`, etc.)
* IDE and system files

All operations are logged for audit purposes.

---

### High-Speed Targeted Downloading

A dedicated utility (`download.py`) for pulling specific files or mirroring entire remote directories to your local machine.

Features include:

* **Pre-Execution Safety:** Automatically maps the remote file sizes and cross-references them against your local partition's available free space, aborting if the disk is too full.
* **Chunked Streaming:** Bypasses memory limitations by streaming binary data in 5MB chunks.
* **Smart Delta Checks:** If a file already exists locally, it only calculates the difference in required space.
* **Live Progress Tracking:** Utilizes `tqdm` for real-time, byte-level progress bars across uploads, downloads, and cleanups.

---

### Logging and Audit Trail

The system maintains detailed logs:

* `sync_audit.log` — synchronization operations
* `cleanup_audit.log` — cleanup actions
* `skipped_files.log` — ignored or unsupported files

This enables traceability and debugging.

---

## Project Structure

```txt
.
├── main.py              # Entry point for synchronization
├── drive_api.py         # Google Drive API wrapper
├── local_scanner.py     # Filesystem scanning and change detection
├── state_manager.py     # SQLite-based state tracking
├── cleanup.py           # Drive cleanup utility
├── download.py          # Targeted high-speed download utility
├── redundancy_check.py  # MD5-based deep verification utility
├── blacklist.py         # Ignored file/folder definitions
├── sync_state.db        # State database (auto-created)
├── credentials.json     # Google API credentials (user-provided)
├── token.json           # OAuth token (auto-generated)
```

---

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/shadow30812/drivesync
cd drivesync
```

### 2. Install Dependencies

```bash
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

### 3. Configure Google Drive API

1. Open Google Cloud Console
2. Enable the Google Drive API
3. Create OAuth credentials (Desktop Application)
4. Download `credentials.json` into the project root

---

## Usage

### Configure Paths

Edit `main.py`:

```python
LOCAL_DIRECTORY = "/path/to/local/folder"
DRIVE_LINK = "https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
```

### Run Synchronization

```bash
python main.py
```

_Note: Upon completion of the fast sync, the CLI will prompt you to optionally run the Deep Redundancy Check to verify all uploads using MD5 checksums. Logs for repairs are tagged with (DEEP REPAIR) in sync_audit.log._

### Run Cleanup Utility

```bash
python cleanup.py
```

### Run Download Utility

1. Edit `download.py` and provide exactly **one** of the following in the configuration block:
   * `TARGET_FILE_ID` (for a single file)
   * `TARGET_FOLDER_ID` (to recursively map and download a folder)
2. Define your `DESTINATION_PATH`.
3. Run the script:

```bash
python download.py
```

_Note: Upon completion of the fast download stream, the CLI will prompt you to optionally run the Deep Redundancy Check to ensure no files were corrupted or dropped due to network instability._

---

## Synchronization Workflow

1. Initialize state manager and Drive API
2. Scan local directory
3. Detect changes (new, modified, renamed/moved)
4. Process in order:

   * Renames and moves
   * New files and folders
   * Modified files
5. Update local state database

---

## Limitations

* Strictly one-way synchronization (changes or deletions made directly on Google Drive are not synced back to the local machine in case of uploads)
* Symbolic links are skipped
* Requires broad Drive API permissions
* Initial scans on large directories may be time-consuming

**Deep Check Overhead:** The MD5 redundancy check provides 100% mathematical certainty but is significantly slower than the fast pass, as it requires hashing every local file and fetching full cloud metadata trees.

---

## Security Considerations

* Keep `credentials.json` and `token.json` confidential
* Do not commit sensitive files to version control

---

## Future Improvements

* Two-way synchronization
* Conflict detection and resolution
* Parallelized uploads
* User interface (CLI enhancements or GUI)

---

## License

MIT License 2026

Check [LICENSE](LICENSE) for more details.

---

## Contributing

Contributions are welcome. Please open issues or submit pull requests for improvements.
