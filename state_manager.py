import sqlite3


class StateManager:
    def __init__(self, db_path="sync_state.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._setup_table()

    def _setup_table(self):
        """Creates the database schema if it doesn't exist."""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    inode TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    drive_id TEXT,
                    mtime REAL NOT NULL,
                    is_folder INTEGER NOT NULL,
                    parent_inode TEXT
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON files(path)")

    def get_record(self, inode):
        """Fetches a single file's state by its OS inode."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM files WHERE inode = ?", (str(inode),))
        row = cursor.fetchone()
        return dict(row) if row else None

    def upsert_record(self, inode, path, drive_id, mtime, is_folder, parent_inode):
        """Inserts a new file record, or updates it if the inode already exists."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO files (inode, path, drive_id, mtime, is_folder, parent_inode)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(inode) DO UPDATE SET
                    path = excluded.path,
                    drive_id = excluded.drive_id,
                    mtime = excluded.mtime,
                    parent_inode = excluded.parent_inode
            """,
                (
                    str(inode),
                    path,
                    drive_id,
                    mtime,
                    int(is_folder),
                    str(parent_inode) if parent_inode else None,
                ),
            )

    def close(self):
        self.conn.close()
