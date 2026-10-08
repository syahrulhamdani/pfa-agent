"""In-memory hand-off of uploaded files from Telegram to the extraction graph.

Receipts and statements are personal financial documents, so they are never written
to disk or to the database. The bot downloads the file into memory, the extraction
node reads it from here, and it is discarded as soon as extraction ends. The graph
state only carries the upload id, so the checkpointer never stores file bytes either.
"""


class FileStash:
    """Holds downloaded files by upload id, in this process's memory only."""

    def __init__(self) -> None:
        """Creates an empty stash."""
        self._files: dict[int, bytes] = {}

    def put(self, upload_id: int, content: bytes) -> None:
        """Keeps a file until it is discarded."""
        self._files[upload_id] = content

    def get(self, upload_id: int) -> bytes:
        """Returns a file without removing it.

        Raises:
            LookupError: If there is no file for this upload, for example after
                the app restarted, since nothing is kept on disk.
        """
        try:
            return self._files[upload_id]
        except KeyError:
            raise LookupError(f"no file held for upload {upload_id}") from None

    def discard(self, upload_id: int) -> None:
        """Forgets a file. Safe to call when there is none."""
        self._files.pop(upload_id, None)

    def __len__(self) -> int:
        """Returns how many files are currently held."""
        return len(self._files)
