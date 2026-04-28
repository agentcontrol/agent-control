"""Built-in :class:`RequestAuthorizer` implementations."""

from .header import HeaderAuthProvider, OssAccessLevel
from .http_upstream import HttpUpstreamAuthProvider

__all__ = [
    "HeaderAuthProvider",
    "HttpUpstreamAuthProvider",
    "OssAccessLevel",
]
