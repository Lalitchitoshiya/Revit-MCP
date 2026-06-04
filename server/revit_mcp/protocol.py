"""Wire protocol constants shared with the C# add-in (docs/05-addin-protocol.md)."""

from __future__ import annotations

PROTOCOL_VERSION = "1.0"

# Default bounded timeouts (NFR-7). Commits get a larger ceiling in later phases.
CONNECT_TIMEOUT_S = 5.0
REQUEST_TIMEOUT_S = 30.0


class ErrorCodes:
    BAD_TOKEN = "BAD_TOKEN"
    VERSION_INCOMPATIBLE = "VERSION_INCOMPATIBLE"
    NO_ACTIVE_DOCUMENT = "NO_ACTIVE_DOCUMENT"
    REVIT_BUSY_TIMEOUT = "REVIT_BUSY_TIMEOUT"
    UNKNOWN_METHOD = "UNKNOWN_METHOD"
    INVALID_PARAMS = "INVALID_PARAMS"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Client-side (this server) codes:
    REVIT_NOT_REACHABLE = "REVIT_NOT_REACHABLE"
    NO_SESSION_FILE = "NO_SESSION_FILE"


def major(version: str) -> str:
    return version.split(".", 1)[0]


def is_compatible(server_version: str, our_version: str = PROTOCOL_VERSION) -> bool:
    return bool(server_version) and major(server_version) == major(our_version)
