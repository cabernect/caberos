"""MCP client — thin wrapper around the official `mcp` Python SDK.

Supports two transports:
  - stdio: spawn a local process, communicate over stdin/stdout
  - http: connect to a remote server via Streamable HTTP

Usage:
    client = McpClient(transport="stdio", command="uvx", args=["some-mcp-server"])
    await client.connect()
    tools = await client.list_tools()
    result = await client.call_tool("email_read", {"folder": "inbox"})
    await client.disconnect()

The client is per-server-instance. The registry manages a pool of clients
(one per connected MCP server config).

CRITICAL: The MCP SDK uses anyio task groups internally. An AsyncExitStack
that enters a stdio_client or streamablehttp_client context MUST be closed
in the same asyncio task that entered it — otherwise anyio raises
"Attempted to exit cancel scope in a different task". To enforce this,
connect() spawns a dedicated background task that owns the exit stack
lifecycle. disconnect() signals that task to shut down cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
from contextlib import AsyncExitStack
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("agentos.mcp.client")

# Common runtime install directories for stdio command resolution.
# Ordered by preference — Homebrew first, then system, then user-local.
_RUNTIME_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    os.path.expanduser("~/.local/bin"),
]


_KNOWN_RUNTIME_COMMANDS = {"node", "npm", "npx", "uv", "uvx", "git"}

# Windows wraps npm/npx as .cmd shims — a bare `npx` name never resolves
# on that platform, so try executable suffixes too.
_WINDOWS_EXTS = (".exe", ".cmd", ".bat")


def _candidate_names(command: str) -> list[str]:
    if platform.system() == "Windows":
        return [command, *(command + e for e in _WINDOWS_EXTS)]
    return [command]


def _registry_or_none():
    try:
        from ..dependencies import get_dependency_registry

        return get_dependency_registry()
    except Exception:
        return None


def _resolve_stdio_command(
    command: str,
    env: dict[str, str] | None,
) -> tuple[str, dict[str, str]]:
    """Resolve a bare stdio command to a full path and update env.

    The subprocess's PATH is env["PATH"] if set, else the current process's
    PATH (from get_default_environment()). We resolve the command against
    that PATH, falling back to common runtime directories, and prepend the
    resolved directory to the subprocess's PATH so shebang chains (e.g.
    npx re-executing node) resolve correctly.

    Returns (resolved_command, updated_env).
    Raises RuntimeError with an actionable message if not found.
    """
    if not command:
        raise ValueError("stdio transport requires a command")

    env = dict(env or {})

    # If it's already a full path, use it as-is
    if os.path.isabs(command):
        return command, env

    # Caller-provided env PATH takes precedence over everything — an
    # explicit override is the operator's choice.
    caller_path = (env or {}).get("PATH")
    registry = _registry_or_none()
    base_path = caller_path if caller_path else os.environ.get("PATH", "")
    if caller_path:
        for d in [x for x in caller_path.split(os.pathsep) if x]:
            for name in _candidate_names(command):
                candidate = os.path.join(d, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    env["PATH"] = caller_path
                    return candidate, env

    # Health-verified managed/system installs beat a stale default PATH —
    # Node 20 in the global PATH must not shadow a managed Node 24.
    if registry is not None and not os.path.isabs(command):
        verified = registry.resolve(command)
        if verified and os.path.isfile(verified):
            env["PATH"] = registry.child_environment({"PATH": base_path})["PATH"]
            return verified, env

    # Legacy fallback: process PATH + well-known dirs + custom runtime path.
    custom_path = os.environ.get("CABEROS_MCP_RUNTIME_PATH")
    search_dirs = [d for d in base_path.split(os.pathsep) if d]
    for d in [*_RUNTIME_DIRS, *([custom_path] if custom_path else [])]:
        if d not in search_dirs:
            search_dirs.append(d)
    for d in search_dirs:
        for name in _candidate_names(command):
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                env["PATH"] = d + os.pathsep + base_path
                return candidate, env

    raise RuntimeError(
        f"MCP stdio command '{command}' not found. "
        f"Searched: {', '.join(search_dirs)}. "
        "Prepare the required runtime in Settings → General "
        "(Optional Tools & Runtimes) or set CABEROS_MCP_RUNTIME_PATH."
    )


_USER_AGENT = None


async def _ensure_user_agent(request) -> None:
    """Event hook: inject a User-Agent when the SDK didn't set one.

    The MCP SDK builds its OAuth discovery/registration/token requests with
    only an `mcp-protocol-version` header — no client defaults merge, so no
    User-Agent is sent. Some authorization servers (observed: CloudFront in
    front of www.tradingview.com) reject UA-less requests with 403, which
    kills the whole OAuth flow. setdefault keeps any explicitly configured
    header authoritative.
    """
    global _USER_AGENT
    if _USER_AGENT is None:
        from .. import __version__

        _USER_AGENT = f"CaberOS/{__version__}"
    request.headers.setdefault("user-agent", _USER_AGENT)


def _bearer_resource_metadata(challenge: str) -> str | None:
    """Extract resource_metadata= from a Bearer challenge; None otherwise.
    Malformed quoting (unterminated/bare text) is rejected, not salvaged."""
    scheme, _, params = challenge.partition(" ")
    if scheme.lower() != "bearer" or not params:
        return None
    for part in params.split(","):
        key, _, value = part.strip().partition("=")
        if key.lower() == "resource_metadata":
            value = value.strip()
            if value.startswith('"'):
                if len(value) < 2 or not value.endswith('"'):
                    return None
                value = value[1:-1]
            elif '"' in value or not value:
                return None
            return value or None
    return None


def _valid_metadata_url(url: str) -> bool:
    """Absolute http/https URL with a real host and no embedded credentials."""
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


class McpClient:
    """Thin wrapper around the MCP SDK — one instance per server connection.

    Connection lifecycle is managed by a dedicated background task to ensure
    the AsyncExitStack is entered and exited in the same asyncio task.
    """

    def __init__(
        self,
        transport: str = "stdio",
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
        auth: Any = None,
    ) -> None:
        self.transport = transport
        self.command = command
        self.args = args or []
        self.url = url
        self.headers = headers or {}
        self.env = env or {}
        self.timeout = timeout
        self.auth = auth

        self._session: Any = None
        self._exit_stack: AsyncExitStack | None = None
        # Set by the response hook when an undeclared-OAuth HTTP server answers
        # a Bearer resource_metadata challenge — never triggers a fetch or flow.
        self.oauth_required = False
        self._connected = False
        self._lock = asyncio.Lock()
        self._conn_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._connect_event = asyncio.Event()
        self._connect_error: Exception | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Connect to the MCP server and initialize the session.

        Spawns a dedicated background task that owns the AsyncExitStack.
        This ensures the exit stack is entered and exited in the same
        asyncio task, avoiding anyio cancel scope errors.
        """
        if self._connected:
            return

        self.oauth_required = False
        # Spawn the connection task — it owns the exit stack lifecycle
        self._conn_task = asyncio.create_task(self._connection_loop())
        # Wait for the connection to complete (or fail)
        try:
            await asyncio.wait_for(
                asyncio.shield(self._connect_event.wait()), timeout=self.timeout + 5
            )
        except TimeoutError:
            self._connect_error = TimeoutError(
                f"MCP connection timed out after {self.timeout + 5}s"
            )

        if self._connect_error:
            # Clean up the task
            self._shutdown_event.set()
            if self._conn_task and not self._conn_task.done():
                self._conn_task.cancel()
                try:
                    await self._conn_task
                except (asyncio.CancelledError, Exception):
                    pass
            self._conn_task = None
            raise self._connect_error

    @staticmethod
    def _windows_wrapper_argv(
        command: str, resolved: str, args: list[str], registry
    ) -> tuple[str, list[str]]:
        """Fixed launch argv for .cmd/.bat npm/npx wrappers — co-installed
        node.exe + the package's own cli.js inside the same install. Never
        a native .cmd execution. Raises rather than guessing."""
        from pathlib import Path as _P

        wrapper = _P(resolved).resolve()
        wrapper_dir = wrapper.parent
        script = (wrapper_dir / "node_modules" / "npm" / "bin" / f"{command}-cli.js").resolve()
        # Prefer the node.exe co-installed beside the wrapper — the
        # operator's explicit selection stays authoritative.
        co = _P(wrapper_dir / "node.exe")
        coinstalled = co if co.is_file() else None
        node = registry.resolve("node") if registry is not None else None
        node_real = coinstalled or (_P(node).resolve() if node else None)
        # node must live beside the wrapper — a node from another
        # install (or a missing script) fails honestly, never silently.
        if (
            node_real is None
            or node_real.parent != wrapper_dir
            or not script.is_file()
            or not script.is_relative_to(wrapper_dir)
        ):
            raise RuntimeError(
                f"Cannot launch '{command}' safely — the package's "
                f"{command}-cli.js is missing or outside the selected "
                "installation. Prepare the runtime in Settings → General."
            )
        return str(node_real), [str(script), *args]

    async def _connection_loop(self) -> None:
        """Background task that owns the MCP connection lifecycle.

        This task enters the AsyncExitStack, initializes the session,
        and stays alive until disconnect() signals shutdown. This ensures
        the exit stack is closed in the same task that entered it.
        """
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp.client.streamable_http import streamable_http_client
        except ImportError:
            self._connect_error = RuntimeError(
                "mcp package not installed. Install with: pip install mcp"
            )
            self._connect_event.set()
            return

        self._exit_stack = AsyncExitStack()
        try:
            if self.transport == "stdio":
                if not self.command:
                    raise ValueError("stdio transport requires a command")

                # Warm the readiness cache so resolve() can see verified
                # managed installs — only for known bare commands.
                registry = _registry_or_none()
                args = list(self.args)
                known_bare = (
                    not os.path.isabs(self.command) and self.command in _KNOWN_RUNTIME_COMMANDS
                )
                if registry is not None and known_bare:
                    try:
                        await registry.status()
                    except Exception:
                        pass
                    # A cached pointer can outlive its install — ANY
                    # companion runtime (git helpers, uv siblings, node
                    # internals) removed after the health check is stale
                    # too. ONE forced re-check repairs the whole set.
                    _stale = any(
                        p and (not os.path.isfile(p) or not os.access(p, os.X_OK))
                        for p in (registry.resolve(c) for c in _KNOWN_RUNTIME_COMMANDS)
                    )
                    if _stale:
                        registry.clear_cache()
                        try:
                            await registry.status(force=True)
                        except Exception:
                            pass

                # Ready-guard BEFORE the resolver — a stale legacy
                # selection must never reach the SDK: a known bare
                # runtime without a current, executable verified install
                # and no explicit caller PATH reports actionably.
                if registry is not None and known_bare and not (self.env or {}).get("PATH"):
                    _ready = registry.resolve(self.command)
                    if not (_ready and os.path.isfile(_ready) and os.access(_ready, os.X_OK)):
                        raise RuntimeError(
                            f"MCP stdio command '{self.command}' has no verified "
                            "installation. Prepare it in Settings → General "
                            "(Optional Tools & Runtimes)."
                        )

                resolved_command, resolved_env = _resolve_stdio_command(self.command, self.env)

                # Merge ALL verified runtime dirs into the child env — the
                # caller's explicit dirs win, verified dirs follow so
                # companion tools (git helpers, npm internals, uv siblings)
                # resolve without touching the global PATH.
                if registry is not None and known_bare:
                    merged = registry.child_environment(resolved_env)
                    caller_path = (self.env or {}).get("PATH")
                    if caller_path:
                        # Explicit caller dirs first, verified dirs after —
                        # the operator's selection wins, companions follow.
                        extras = [
                            d
                            for d in merged["PATH"].split(os.pathsep)
                            if d and d not in caller_path.split(os.pathsep)
                        ]
                        merged["PATH"] = os.pathsep.join([caller_path, *extras])
                    resolved_env.update(merged)

                # Windows npm/npx .cmd wrappers can't spawn natively —
                # invoke the co-installed node.exe + the package's own
                # cli.js with the original args. Never a shell/COMSPEC.
                if self.command in ("npm", "npx") and resolved_command.lower().endswith(
                    (".cmd", ".bat")
                ):
                    resolved_command, args = self._windows_wrapper_argv(
                        self.command, resolved_command, args, registry
                    )

                params = StdioServerParameters(
                    command=resolved_command,
                    args=args,
                    env=resolved_env if resolved_env else None,
                )
                read, write = await self._exit_stack.enter_async_context(stdio_client(params))

            elif self.transport == "http":
                if not self.url:
                    raise ValueError("http transport requires a url")

                # mcp v2: streamable_http_client takes an httpx2.AsyncClient
                # with auth/headers attached, not auth=/headers= kwargs.
                import httpx2

                http_kwargs: dict = {}
                if self.auth:
                    http_kwargs["auth"] = self.auth
                if self.headers:
                    http_kwargs["headers"] = self.headers

                hooks: dict[str, list] = {"request": [_ensure_user_agent]}
                if self.auth is None:
                    # Undeclared auth: watch for a Bearer resource_metadata
                    # challenge on this server's own URL — flag only, never
                    # fetch metadata, mint a token, or redirect.
                    expected = httpx2.URL(self.url)

                    async def _observe_oauth_challenge(response: httpx2.Response) -> None:
                        try:
                            request = response.request
                            if (
                                response.status_code == 401
                                and request.method == "POST"
                                and request.url == expected
                            ):
                                challenge = response.headers.get("www-authenticate", "")
                                if len(challenge) <= 4096:
                                    meta = _bearer_resource_metadata(challenge)
                                    if meta and _valid_metadata_url(meta):
                                        self.oauth_required = True
                        except Exception:
                            pass

                    hooks["response"] = [_observe_oauth_challenge]
                http_kwargs["event_hooks"] = hooks

                http_client = httpx2.AsyncClient(
                    base_url=self.url,
                    timeout=self.timeout,
                    # No keep-alive: a 401 challenge can be followed by a silent
                    # close; reusing the pooled connection then raises
                    # RemoteProtocolError during OAuth discovery.
                    limits=httpx2.Limits(max_keepalive_connections=0),
                    **http_kwargs,
                )
                result = await self._exit_stack.enter_async_context(
                    streamable_http_client(self.url, http_client=http_client)
                )
                # mcp v2 returns (read, write), v1 returned (read, write, _)
                if len(result) == 3:
                    read, write, _ = result
                else:
                    read, write = result

            else:
                raise ValueError(f"Unknown transport: {self.transport}")

            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=float(self.timeout))
            )
            await self._session.initialize()
            self._connected = True
            log.info("Connected to MCP server (transport=%s)", self.transport)

            # Signal that connection succeeded
            self._connect_event.set()

            # Wait for shutdown signal — this keeps the task alive so the
            # exit stack stays valid until disconnect() is called
            await self._shutdown_event.wait()

        except Exception as e:
            self._connect_error = e
            self._connect_event.set()
            # ConnectionError from the noop callback handler is expected
            # when OAuth tokens expire — log a warning, not a full traceback.
            if isinstance(e, ConnectionError):
                log.warning("MCP connection failed: %s", e)
            else:
                log.exception("MCP connection failed (transport=%s)", self.transport)
        finally:
            # Clean up the exit stack in the SAME task that entered it
            self._connected = False
            if self._exit_stack:
                try:
                    await self._exit_stack.aclose()
                except BaseExceptionGroup as eg:
                    # The MCP SDK wraps OAuth ConnectionError in an
                    # ExceptionGroup during aclose(). If all sub-exceptions
                    # are ConnectionErrors, suppress the traceback.
                    if all(isinstance(e, ConnectionError) for e in eg.exceptions):
                        log.debug("MCP exit stack closed after OAuth error")
                    else:
                        log.exception("Error closing MCP client exit stack")
                except ConnectionError:
                    log.debug("MCP exit stack closed after connection error")
                except Exception:
                    log.exception("Error closing MCP client exit stack")
            self._exit_stack = None
            self._session = None

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover tools exposed by the MCP server.

        Returns a list of dicts with: name, description, inputSchema.
        """
        if not self._connected or self._session is None:
            raise RuntimeError("Not connected")

        async with self._lock:
            result = await self._session.list_tools()

        tools = []
        for tool in result.tools:
            annotations = getattr(tool, "annotations", None)
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": getattr(tool, "inputSchema", None)
                    or tool.input_schema
                    or {"type": "object", "properties": {}},
                    # MCP ToolAnnotations (readOnlyHint, destructiveHint, ...)
                    # inform the trusted effect classification (v0.2).
                    "annotations": (
                        annotations.model_dump(exclude_none=True)
                        if annotations is not None and hasattr(annotations, "model_dump")
                        else None
                    ),
                }
            )
        return tools

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server.

        Returns {"content": [...], "isError": bool}.
        """
        if not self._connected or self._session is None:
            raise RuntimeError("Not connected")

        async with self._lock:
            result = await self._session.call_tool(name, args)

        content_parts = []
        for part in result.content:
            if hasattr(part, "text"):
                content_parts.append({"type": "text", "text": part.text})
            elif hasattr(part, "data"):
                content_parts.append(
                    {"type": "image", "data": part.data, "mimeType": getattr(part, "mimeType", "")}
                )
            else:
                content_parts.append({"type": "unknown", "repr": repr(part)})

        return {
            "content": content_parts,
            "isError": result.isError if hasattr(result, "isError") else False,
        }

    async def disconnect(self) -> None:
        """Disconnect and clean up.

        Signals the background connection task to shut down, which closes
        the AsyncExitStack in the correct task context.
        """
        self._connected = False
        self._shutdown_event.set()

        if self._conn_task and not self._conn_task.done():
            # Give the task a few seconds to shut down cleanly
            try:
                await asyncio.wait_for(asyncio.shield(self._conn_task), timeout=10.0)
            except (TimeoutError, asyncio.CancelledError, Exception):
                # Force cancel if it doesn't shut down in time
                self._conn_task.cancel()
                try:
                    await self._conn_task
                except (asyncio.CancelledError, Exception):
                    pass

        self._conn_task = None
        self._exit_stack = None
        self._session = None
        log.info("Disconnected from MCP server")


class MockMcpClient:
    """Mock MCP client for testing — no real process or network.

    Returns a fixed set of tools and echoes call args back as the result.
    """

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        call_results: dict[str, Any] | None = None,
    ) -> None:
        self._tools = tools or [
            {
                "name": "echo",
                "description": "Echo the input back",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            }
        ]
        self._call_results = call_results or {}
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._connected:
            raise RuntimeError("Not connected")
        return list(self._tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            raise RuntimeError("Not connected")
        if name in self._call_results:
            return self._call_results[name]
        return {
            "content": [{"type": "text", "text": f"Mock result for {name}: {args}"}],
            "isError": False,
        }

    async def disconnect(self) -> None:
        self._connected = False
