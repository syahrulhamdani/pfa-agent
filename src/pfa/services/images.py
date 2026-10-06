"""In-memory hand-off of receipt images from Telegram to the extraction graph.

Receipts are personal financial documents, so they are never written to disk or
to the database. The bot downloads the image into memory, the extraction node reads
it from here, and it is discarded as soon as extraction ends. The graph state only
carries the upload id, so the checkpointer never stores image bytes either.
"""


class ImageStash:
    """Holds downloaded images by upload id, in this process's memory only."""

    def __init__(self) -> None:
        """Creates an empty stash."""
        self._images: dict[int, bytes] = {}

    def put(self, upload_id: int, content: bytes) -> None:
        """Keeps an image until it is discarded."""
        self._images[upload_id] = content

    def get(self, upload_id: int) -> bytes:
        """Returns an image without removing it.

        Raises:
            LookupError: If there is no image for this upload, for example after
                the app restarted, since nothing is kept on disk.
        """
        try:
            return self._images[upload_id]
        except KeyError:
            raise LookupError(f"no image held for upload {upload_id}") from None

    def discard(self, upload_id: int) -> None:
        """Forgets an image. Safe to call when there is none."""
        self._images.pop(upload_id, None)

    def __len__(self) -> int:
        """Returns how many images are currently held."""
        return len(self._images)
