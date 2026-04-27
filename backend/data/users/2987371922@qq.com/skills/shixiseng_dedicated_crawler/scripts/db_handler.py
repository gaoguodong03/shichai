from file_store import FileStore


class DBHandler(FileStore):
    """Backward-compatible alias for the old DB-oriented name."""

    def __init__(self, db_path=None):
        super().__init__(storage_dir=db_path)
