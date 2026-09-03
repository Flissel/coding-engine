"""Package marker for mcp_plugins.servers.grpc_host.

Required so this directory resolves as a regular package rather than an
implicit PEP 420 namespace package. Without it, Python's import machinery
prefers the sibling script ``mcp_plugins/servers/grpc_host.py`` over this
directory for any qualified import (``mcp_plugins.servers.grpc_host.<mod>``),
which breaks every such import in the codebase. Existing call sites only
survived this via ``try/except ImportError`` fallbacks; adding this file
makes those imports actually work instead of silently degrading.
"""
