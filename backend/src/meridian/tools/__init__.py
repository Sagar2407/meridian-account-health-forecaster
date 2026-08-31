"""The read-only, role-allowlisted tool layer (plan section 12).

Business logic is ordinary typed Python in `services`; `registry` adds the
per-role allowlist, validation, timeout, retry, and audit record; `server` and
`client` expose the same services over MCP without protocol objects reaching
any caller.
"""

from meridian.tools.contracts import RequesterRole
from meridian.tools.services import ToolServices, ToolUnavailableError

__all__ = ["RequesterRole", "ToolServices", "ToolUnavailableError"]
