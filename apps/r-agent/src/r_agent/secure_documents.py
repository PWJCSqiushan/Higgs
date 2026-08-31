"""Public secure-document boundary used by read-only tools."""

from r_agent.safe_tools import (
    AttachmentHandleStore,
    DocumentReader,
    DocumentSecurityError,
    DownloadIsolation,
    DownloadSandbox,
    ResponseTooLargeError,
    SafeReadOnlyTools,
)

__all__ = [
    "AttachmentHandleStore",
    "DocumentReader",
    "DocumentSecurityError",
    "DownloadIsolation",
    "DownloadSandbox",
    "ResponseTooLargeError",
    "SafeReadOnlyTools",
]
