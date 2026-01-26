"""Event ingestion layer for observability.

This module provides the EventIngestor protocol and implementations
for processing control execution events.
"""

from .base import EventIngestor, IngestResult
from .direct import DirectEventIngestor

__all__ = ["EventIngestor", "IngestResult", "DirectEventIngestor"]
