from dataclasses import dataclass
from typing import Optional


@dataclass
class ClipboardItem:
    id: int
    content: Optional[str]
    content_type: str
    created_at: str
    is_pinned: bool = False
    image_path: Optional[str] = None
    image_hash: Optional[str] = None
