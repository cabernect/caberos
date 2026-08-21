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
from contextlib import AsyncExitStack
from typing import Any

log = logging.getLogger("agentos.mcp.client")


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

                params = StdioServerParameters(
                    command=self.command,
                    args=self.args,
                    env=self.env if self.env else None,
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

                http_client = httpx2.AsyncClient(
                    base_url=self.url,
                    timeout=30.0,
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
                    if all(
                        isinstance(e, ConnectionError) for e in eg.exceptions
                    ):
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
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": getattr(tool, "inputSchema", None)
                    or tool.input_schema
                    or {"type": "object", "properties": {}},
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
