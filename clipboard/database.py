import logging
from datetime import datetime, timezone
import pathlib
import sqlite3
from typing import List, Optional

from clipboard.models import ClipboardItem

logger = logging.getLogger(__name__)


def get_default_db_path() -> pathlib.Path:
    target = pathlib.Path.home() / ".local" / "share" / "klipora" / "clipboard.db"
    legacy_dirs = [
        pathlib.Path.home() / ".local" / "share" / "clipnova",
        pathlib.Path.home() / ".local" / "share" / "clipshelf",
        pathlib.Path.home() / ".local" / "share" / "ubuntu-clipboard",
    ]
    if not target.exists():
        for old_dir in legacy_dirs:
            if (old_dir / "clipboard.db").exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    import shutil

                    shutil.copy2(old_dir / "clipboard.db", target)
                    old_images = old_dir / "images"
                    if old_images.exists():
                        shutil.copytree(old_images, target.parent / "images", dirs_exist_ok=True)
                    break
                except Exception as e:
                    logger.warning("Could not auto-migrate legacy clipboard db: %s", e)
    return target


class ClipboardDatabase:
    """Manages SQLite storage for clipboard history with pinning and management support."""

    MAX_UNPINNED_ITEMS: int = 20
    MAX_PINNED_ITEMS: int = 10

    def __init__(self, db_path: Optional[pathlib.Path] = None):
        self.db_path = db_path if db_path is not None else get_default_db_path()
        self.images_dir = self.db_path.parent / "images"
        self._conn: Optional[sqlite3.Connection] = None
        self._content_is_not_null: bool = False

    def initialize(self) -> None:
        """Ensures storage directory exists, initializes SQLite schema, and safely migrates."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.images_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS clipboard_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT,
                        content_type TEXT NOT NULL DEFAULT 'text',
                        created_at TEXT NOT NULL,
                        is_pinned INTEGER NOT NULL DEFAULT 0,
                        image_path TEXT,
                        image_hash TEXT
                    );
                    """
                )
                cursor = self._conn.execute("PRAGMA table_info(clipboard_items);")
                cols = cursor.fetchall()
                col_names = [row["name"] for row in cols]
                for row in cols:
                    if row["name"] == "content":
                        self._content_is_not_null = bool(row["notnull"])

                if "is_pinned" not in col_names:
                    logger.info("Migrating database: adding 'is_pinned' column...")
                    self._conn.execute(
                        "ALTER TABLE clipboard_items ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0;"
                    )
                if "image_path" not in col_names:
                    logger.info("Migrating database: adding 'image_path' column...")
                    self._conn.execute(
                        "ALTER TABLE clipboard_items ADD COLUMN image_path TEXT;"
                    )
                if "image_hash" not in col_names:
                    logger.info("Migrating database: adding 'image_hash' column...")
                    self._conn.execute(
                        "ALTER TABLE clipboard_items ADD COLUMN image_hash TEXT;"
                    )

            # Clean up any unreferenced image files
            self.cleanup_orphaned_images()
            # Enforce FIFO unpinned limit on existing database records
            self.enforce_unpinned_limit()
            logger.info("Database initialized successfully at: %s", self.db_path)
        except sqlite3.Error as e:
            logger.error("Failed to initialize database: %s", e)
            raise

    def get_pinned_count(self) -> int:
        """Returns the current number of pinned items."""
        if self._conn is None:
            return 0
        try:
            cursor = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM clipboard_items WHERE is_pinned = 1"
            )
            row = cursor.fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error as e:
            logger.error("Error retrieving pinned count: %s", e)
            return 0

    def get_unpinned_count(self) -> int:
        """Returns the current number of unpinned items."""
        if self._conn is None:
            return 0
        try:
            cursor = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM clipboard_items WHERE is_pinned = 0"
            )
            row = cursor.fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error as e:
            logger.error("Error retrieving unpinned count: %s", e)
            return 0

    def can_pin(self) -> bool:
        """Checks if another item can be pinned without exceeding MAX_PINNED_ITEMS."""
        return self.get_pinned_count() < self.MAX_PINNED_ITEMS

    def enforce_unpinned_limit(
        self,
        max_count: Optional[int] = None,
        exclude_id: Optional[int] = None,
    ) -> List[int]:
        """Enforces FIFO limitation on unpinned items.

        Deletes the oldest unpinned items exceeding max_count from the database
        and deletes their stored image files. If exclude_id is provided, that item
        is protected from being pruned (e.g. freshly unpinned item).
        Returns the list of deleted item IDs.
        """
        if self._conn is None:
            return []

        limit = max_count if max_count is not None else self.MAX_UNPINNED_ITEMS
        try:
            cursor = self._conn.execute(
                """
                SELECT id, image_path FROM clipboard_items
                WHERE is_pinned = 0
                ORDER BY id DESC
                """
            )
            rows = cursor.fetchall()
            if len(rows) <= limit:
                return []

            candidates = [r for r in rows if exclude_id is None or r["id"] != exclude_id]
            num_to_delete = len(rows) - limit
            excess_rows = candidates[-num_to_delete:]

            deleted_ids = []
            for row in excess_rows:
                item_id = row["id"]
                if self.delete_item(item_id):
                    deleted_ids.append(item_id)
            if deleted_ids:
                logger.info(
                    "FIFO: pruned %d oldest unpinned clipboard items: %s",
                    len(deleted_ids),
                    deleted_ids,
                )
            return deleted_ids
        except sqlite3.Error as e:
            logger.error("Database error enforcing unpinned limit: %s", e)
            return []

    def add_item(
        self,
        content: str,
        content_type: str = "text",
        is_pinned: bool = False,
    ) -> Optional[ClipboardItem]:
        """Inserts a new text clipboard item into SQLite using parameterized query."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return None

        if is_pinned and self.get_pinned_count() >= self.MAX_PINNED_ITEMS:
            logger.warning(
                "Pinned items limit (%d) reached; saving item as unpinned",
                self.MAX_PINNED_ITEMS,
            )
            is_pinned = False

        created_at = datetime.now(timezone.utc).isoformat()
        pinned_val = 1 if is_pinned else 0
        try:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    INSERT INTO clipboard_items (content, content_type, created_at, is_pinned, image_path, image_hash)
                    VALUES (?, ?, ?, ?, NULL, NULL)
                    """,
                    (content, content_type, created_at, pinned_val),
                )
                item_id = cursor.lastrowid

            if not is_pinned:
                self.enforce_unpinned_limit()

            return ClipboardItem(
                id=item_id,
                content=content,
                content_type=content_type,
                created_at=created_at,
                is_pinned=is_pinned,
                image_path=None,
                image_hash=None,
            )
        except sqlite3.Error as e:
            logger.error("Database error adding text item: %s", e)
            return None

    def add_image_item(
        self,
        png_data: bytes,
        image_hash: str,
        is_pinned: bool = False,
    ) -> Optional[ClipboardItem]:
        """Inserts an image item into SQLite and saves the normalized PNG file."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return None

        if is_pinned and self.get_pinned_count() >= self.MAX_PINNED_ITEMS:
            logger.warning(
                "Pinned items limit (%d) reached; saving image as unpinned",
                self.MAX_PINNED_ITEMS,
            )
            is_pinned = False

        created_at = datetime.now(timezone.utc).isoformat()
        pinned_val = 1 if is_pinned else 0
        # If legacy schema had NOT NULL on content, store empty string; otherwise NULL
        content_val = "" if self._content_is_not_null else None

        item_id: Optional[int] = None
        file_path: Optional[pathlib.Path] = None

        try:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    INSERT INTO clipboard_items (content, content_type, created_at, is_pinned, image_path, image_hash)
                    VALUES (?, 'image', ?, ?, NULL, ?)
                    """,
                    (content_val, created_at, pinned_val, image_hash),
                )
                item_id = cursor.lastrowid

            self.images_dir.mkdir(parents=True, exist_ok=True)
            file_path = self.images_dir / f"{item_id}.png"

            with open(file_path, "wb") as f:
                f.write(png_data)

            with self._conn:
                self._conn.execute(
                    "UPDATE clipboard_items SET image_path = ? WHERE id = ?",
                    (str(file_path), item_id),
                )

            if not is_pinned:
                self.enforce_unpinned_limit()

            logger.info("Saved image clipboard item %d (%d bytes) to %s", item_id, len(png_data), file_path)
            return ClipboardItem(
                id=item_id,
                content=None,
                content_type="image",
                created_at=created_at,
                is_pinned=is_pinned,
                image_path=str(file_path),
                image_hash=image_hash,
            )
        except Exception as e:
            logger.error("Failed to persist image item: %s", e)
            if file_path and file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    pass
            if item_id is not None:
                try:
                    with self._conn:
                        self._conn.execute("DELETE FROM clipboard_items WHERE id = ?", (item_id,))
                except sqlite3.Error:
                    pass
            return None

    def get_items(self, limit: int = 100) -> List[ClipboardItem]:
        """Retrieves clipboard items with pinned items first, then newest unpinned items."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return []

        try:
            cursor = self._conn.execute(
                """
                SELECT id, content, content_type, created_at, is_pinned, image_path, image_hash
                FROM clipboard_items
                ORDER BY is_pinned DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                ClipboardItem(
                    id=row["id"],
                    content=row["content"] if row["content_type"] == "text" else None,
                    content_type=row["content_type"],
                    created_at=row["created_at"],
                    is_pinned=bool(row["is_pinned"]),
                    image_path=row["image_path"],
                    image_hash=row["image_hash"],
                )
                for row in rows
            ]
        except sqlite3.Error as e:
            logger.error("Database error retrieving items: %s", e)
            return []

    def get_latest(self) -> Optional[ClipboardItem]:
        """Retrieves the most recent clipboard item chronologically or None if empty."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return None

        try:
            cursor = self._conn.execute(
                """
                SELECT id, content, content_type, created_at, is_pinned, image_path, image_hash
                FROM clipboard_items
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row:
                return ClipboardItem(
                    id=row["id"],
                    content=row["content"] if row["content_type"] == "text" else None,
                    content_type=row["content_type"],
                    created_at=row["created_at"],
                    is_pinned=bool(row["is_pinned"]),
                    image_path=row["image_path"],
                    image_hash=row["image_hash"],
                )
            return None
        except sqlite3.Error as e:
            logger.error("Database error retrieving latest item: %s", e)
            return None

    def pin_item(self, item_id: int) -> bool:
        """Marks a clipboard item as pinned if the pinned limit has not been reached."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return False

        try:
            with self._conn:
                cursor = self._conn.execute(
                    "SELECT is_pinned FROM clipboard_items WHERE id = ?",
                    (item_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                if row["is_pinned"]:
                    return True

                if self.get_pinned_count() >= self.MAX_PINNED_ITEMS:
                    logger.warning(
                        "Cannot pin item %d: pinned limit (%d) reached",
                        item_id,
                        self.MAX_PINNED_ITEMS,
                    )
                    return False

                cursor = self._conn.execute(
                    "UPDATE clipboard_items SET is_pinned = 1 WHERE id = ?",
                    (item_id,),
                )
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error("Database error pinning item %d: %s", item_id, e)
            return False

    def unpin_item(self, item_id: int) -> bool:
        """Removes pinned status from a clipboard item."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return False

        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE clipboard_items SET is_pinned = 0 WHERE id = ?",
                    (item_id,),
                )
            success = cursor.rowcount > 0
            if success:
                self.enforce_unpinned_limit(exclude_id=item_id)
            return success
        except sqlite3.Error as e:
            logger.error("Database error unpinning item %d: %s", item_id, e)
            return False

    def toggle_pin(self, item_id: int) -> Optional[bool]:
        """Toggles the pinned state of an item and returns the new pinned state."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return None

        try:
            with self._conn:
                cursor = self._conn.execute(
                    "SELECT is_pinned FROM clipboard_items WHERE id = ?",
                    (item_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                currently_pinned = bool(row["is_pinned"])
                if not currently_pinned:
                    if self.get_pinned_count() >= self.MAX_PINNED_ITEMS:
                        logger.warning(
                            "Cannot pin item %d: pinned limit (%d) reached",
                            item_id,
                            self.MAX_PINNED_ITEMS,
                        )
                        return None
                    new_state = 1
                else:
                    new_state = 0

                self._conn.execute(
                    "UPDATE clipboard_items SET is_pinned = ? WHERE id = ?",
                    (new_state, item_id),
                )

            if new_state == 0:
                self.enforce_unpinned_limit(exclude_id=item_id)

            return bool(new_state)
        except sqlite3.Error as e:
            logger.error("Database error toggling pin for item %d: %s", item_id, e)
            return None

    def delete_item(self, item_id: int) -> bool:
        """Permanently deletes a single clipboard item and its stored image file if any."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return False

        image_path: Optional[str] = None
        try:
            cursor = self._conn.execute(
                "SELECT image_path FROM clipboard_items WHERE id = ?",
                (item_id,),
            )
            row = cursor.fetchone()
            if row and row["image_path"]:
                image_path = row["image_path"]

            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM clipboard_items WHERE id = ?",
                    (item_id,),
                )
            deleted = cursor.rowcount > 0

            # Safe cleanup of image file after database row deletion
            if deleted and image_path:
                try:
                    p = pathlib.Path(image_path)
                    if p.exists():
                        p.unlink()
                except OSError as e:
                    logger.warning("Failed to remove image file %s: %s", image_path, e)

            return deleted
        except sqlite3.Error as e:
            logger.error("Database error deleting item %d: %s", item_id, e)
            return False

    def clear_history(self) -> int:
        """Deletes all unpinned clipboard items and their image files. Pinned items are preserved."""
        if self._conn is None:
            logger.error("Database is not initialized")
            return 0

        try:
            cursor = self._conn.execute(
                "SELECT image_path FROM clipboard_items WHERE is_pinned = 0 AND image_path IS NOT NULL"
            )
            image_paths = [r["image_path"] for r in cursor.fetchall() if r["image_path"]]

            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM clipboard_items WHERE is_pinned = 0"
                )
            deleted_count = cursor.rowcount

            # Safe cleanup of image files for unpinned records
            for img_p in image_paths:
                try:
                    p = pathlib.Path(img_p)
                    if p.exists():
                        p.unlink()
                except OSError as e:
                    logger.warning("Failed to remove unpinned image file %s: %s", img_p, e)

            logger.info("Cleared %d unpinned clipboard items from database", deleted_count)
            return deleted_count
        except sqlite3.Error as e:
            logger.error("Database error clearing history: %s", e)
            return 0

    def cleanup_orphaned_images(self) -> int:
        """Removes any application-owned image files not referenced by any database record."""
        if self._conn is None or not self.images_dir.exists():
            return 0

        try:
            cursor = self._conn.execute(
                "SELECT image_path FROM clipboard_items WHERE image_path IS NOT NULL"
            )
            referenced_paths = {
                pathlib.Path(r["image_path"]).resolve()
                for r in cursor.fetchall()
                if r["image_path"]
            }

            orphans_cleaned = 0
            for file_path in self.images_dir.glob("*.png"):
                if file_path.resolve() not in referenced_paths:
                    try:
                        file_path.unlink()
                        orphans_cleaned += 1
                        logger.info("Cleaned up orphaned image file: %s", file_path)
                    except OSError as e:
                        logger.warning("Failed to clean up orphan %s: %s", file_path, e)

            return orphans_cleaned
        except Exception as e:
            logger.error("Error during orphan image cleanup: %s", e)
            return 0

    def close(self) -> None:
        """Closes the SQLite database connection safely."""
        if self._conn:
            try:
                self._conn.close()
                logger.info("Database connection closed")
            except sqlite3.Error as e:
                logger.error("Error closing database connection: %s", e)
            finally:
                self._conn = None
