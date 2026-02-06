from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LookupStatus(Enum):
    PENDING = "pending"
    GRAPH_API_MISS = "graph_api_miss"  # Not found via Graph API, awaiting Instaloader
    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


@dataclass
class Follower:
    username: str
    followed_at: Optional[int] = None  # Unix timestamp
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    full_name: Optional[str] = None
    is_verified: Optional[bool] = None
    is_private: Optional[bool] = None
    lookup_status: LookupStatus = LookupStatus.PENDING
    lookup_source: Optional[str] = None  # "graph_api" or "instaloader"
    error_message: Optional[str] = None
    retry_count: int = 0
