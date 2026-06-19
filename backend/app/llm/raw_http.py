"""Lightweight async HTTPS client — stdlib only (asyncio + ssl).

Replaces httpx for SSE streaming and simple HTTP GET/POST.
Import time: <1ms vs httpx ~3200ms.

Supports:
  - HTTPS GET / POST
  - Streaming response with chunked transfer-encoding
  - Connection keep-alive (checkout/checkin model)
  - Automatic reconnection on stale connections
  - Redirect following (up to 5 hops)
  - Line-by-line iteration (ideal for SSE parsing)
"""

from __future__ import annotations

import asyncio
import ssl as _ssl


class RawResponse:
    __slots__ = ("status", "headers", "_reader", "_chunked", "_client", "_host", "_port", "_released")

    def __init__(
        self,
        status: int,
        headers: dict[str, str],
        reader: asyncio.StreamReader,
        chunked: bool,
        client: AsyncClient | None = None,
        host: str = "",
        port: int = 443,
    ):
        self.status = status
        self.headers = headers
        self._reader = reader
        self._chunked = chunked
        self._client = client
        self._host = host
        self._port = port
        self._released = False

    def _release(self, discard: bool = False):
        """Return connection to pool, or discard if broken."""
        if self._released or self._client is None:
            return
        self._released = True
        if discard:
            self._client._invalidate(self._host, self._port)
            try:
                self._reader.feed_eof()
            except Exception:
                pass
        else:
            self._client._checkin(self._host, self._port, self._reader)

    async def read(self) -> bytes:
        """Read entire response body."""
        try:
            if self._chunked:
                return await self._read_chunked()
            cl = self.headers.get("content-length")
            if cl:
                return await self._reader.readexactly(int(cl))
            return b""
        except Exception:
            self._release(discard=True)
            raise
        finally:
            if not self._released:
                conn = self.headers.get("connection", "").lower()
                if "close" in conn:
                    self._release(discard=True)
                else:
                    self._release(discard=False)

    async def _read_chunked(self) -> bytes:
        parts: list[bytes] = []
        while True:
            size_line = await self._reader.readline()
            size = int(size_line.strip(), 16)
            if size == 0:
                await self._reader.readline()
                break
            parts.append(await self._reader.readexactly(size))
            await self._reader.readline()
        return b"".join(parts)

    async def aiter_lines(self):
        """Yield decoded text lines from the response body.

        Handles chunked transfer-encoding transparently.
        Lines are decoded as UTF-8 with error replacement.
        """
        try:
            buf = b""
            if self._chunked:
                while True:
                    size_line = await self._reader.readline()
                    if not size_line:
                        break
                    size = int(size_line.strip(), 16)
                    if size == 0:
                        break
                    chunk = await self._reader.readexactly(size)
                    await self._reader.readline()
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        yield line.decode("utf-8", errors="replace")
            else:
                cl = self.headers.get("content-length")
                remaining = int(cl) if cl else -1
                while remaining != 0:
                    line = await self._reader.readline()
                    if not line:
                        break
                    if remaining > 0:
                        remaining -= len(line)
                    yield line.decode("utf-8", errors="replace").rstrip("\r\n")
            remaining_text = buf.rstrip(b"\r\n")
            if remaining_text:
                yield remaining_text.decode("utf-8", errors="replace")
        except Exception:
            self._release(discard=True)
            raise
        else:
            conn = self.headers.get("connection", "").lower()
            if "close" in conn:
                self._release(discard=True)
            else:
                self._release(discard=False)


class AsyncClient:
    """Minimal async HTTPS client with connection reuse.

    Uses checkout/checkin model: _connect() checks out (removes from pool),
    RawResponse._release() checks in (returns to pool) when done.
    Broken connections are discarded, never returned to pool.
    """

    def __init__(self, timeout: float = 60.0, connect_timeout: float = 10.0):
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        # Per-host connection POOL (list of idle connections). Keeping a small
        # pool per host lets concurrent requests (e.g. spawn_agent_group running
        # N agents against the same API host) reuse warm TLS connections instead
        # of every request opening its own.
        self._conns: dict[str, list[tuple[asyncio.StreamReader, asyncio.StreamWriter]]] = {}
        self._pool_size = 4  # max idle connections kept per host
        # Every writer currently checked out (in-flight). aclose() iterates
        # pool + checked-out to guarantee clean shutdown. Connections are
        # removed from here on checkin, so this set stays bounded by the number
        # of concurrent requests.
        self._all_writers: set[asyncio.StreamWriter] = set()
        self._ctx: _ssl.SSLContext | None = None  # Lazy — created on first use

    def _get_ssl_ctx(self) -> _ssl.SSLContext:
        if self._ctx is None:
            self._ctx = _ssl.create_default_context()
        return self._ctx

    @staticmethod
    def _parse_url(url: str) -> tuple[str, int, str]:
        scheme_end = url.find("://")
        if scheme_end != -1:
            url = url[scheme_end + 3 :]
        slash = url.find("/")
        if slash == -1:
            host_port, path = url, "/"
        else:
            host_port, path = url[:slash], url[slash:]
        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 443
        return host, port, path

    def _invalidate(self, host: str, port: int):
        """Discard ALL pooled connections for a host (e.g. on auth failure)."""
        key = f"{host}:{port}"
        pool = self._conns.pop(key, [])
        for _, writer in pool:
            try:
                writer.close()
            except Exception:
                pass

    def _checkin(self, host: str, port: int, reader: asyncio.StreamReader):
        """Return a healthy connection to the pool for reuse."""
        key = f"{host}:{port}"
        pool = self._conns.setdefault(key, [])
        writer = getattr(reader, '_ye_writer', None)
        if writer and not writer.is_closing():
            if len(pool) < self._pool_size:
                pool.append((reader, writer))
            else:
                # Pool full — close the excess connection
                try:
                    writer.close()
                except Exception:
                    pass
        # NOTE: we intentionally do NOT discard from _all_writers here. A
        # writer might fail to be checked in (e.g. on request exception) and
        # end up with no live reference except this tracking set. Keeping it
        # ensures aclose() can still shut it down, preventing the
        # 'Event loop is closed' traceback from StreamWriter.__del__ during
        # teardown. _all_writers is cleared in aclose(), bounding growth to
        # the lifetime of one CLI/server session.

    def _discard_writer(self, host: str, port: int, writer: asyncio.StreamWriter):
        """Close a writer that's no longer needed."""
        try:
            writer.close()
        except Exception:
            pass

    async def _connect(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Check out a connection (from pool or create new).

        Does NOT put new connections in pool — that happens via
        RawResponse._release() when the response is fully consumed.
        """
        key = f"{host}:{port}"
        pool = self._conns.get(key)
        if pool:
            reader, writer = pool.pop()  # Checkout: take from pool
            if not writer.is_closing():
                return reader, writer
            # Stale connection — discard
            try:
                writer.close()
            except Exception:
                pass

        ctx = self._get_ssl_ctx()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx),
            timeout=self._connect_timeout,
        )
        # Stash writer reference on reader so _checkin can find it
        reader._ye_writer = writer  # type: ignore[attr-defined]
        # Track every writer ever created so aclose() can close ALL of them —
        # not just the ones still in the pool. This prevents StreamWriter.__del__
        # from firing on a closed loop during interpreter teardown.
        self._all_writers.add(writer)
        # Do NOT put in pool — will be returned by RawResponse._release()
        return reader, writer

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        _max_redirects: int = 5,
    ) -> RawResponse:
        host, port, path = self._parse_url(url)

        # Try request; if sending on stale connection fails, reconnect once
        resp = None
        last_reader = None
        last_writer = None
        for attempt in range(2):
            # Discard previous attempt's connection if retrying
            if last_writer is not None:
                try:
                    last_writer.close()
                except Exception:
                    pass
                self._invalidate(host, port)

            reader, writer = await self._connect(host, port)
            last_reader = reader
            last_writer = writer

            h: dict[str, str] = {
                "Host": host,
                "Connection": "keep-alive",
                "Accept": "*/*",
            }
            if headers:
                h.update(headers)
            if body is not None and "content-length" not in {k.lower() for k in h}:
                h["Content-Length"] = str(len(body))

            lines = [f"{method} {path} HTTP/1.1"]
            for k, v in h.items():
                lines.append(f"{k}: {v}")
            lines.append("")
            lines.append("")
            raw = "\r\n".join(lines).encode()
            if body:
                raw += body

            try:
                writer.write(raw)
                await writer.drain()
            except (ConnectionError, OSError):
                if attempt == 1:
                    raise
                continue

            try:
                status_line = await asyncio.wait_for(
                    reader.readline(), self._timeout
                )
                if not status_line:
                    raise ConnectionError("empty response")
                decoded_status = status_line.decode().strip()
                parts = decoded_status.split(" ", 2)
                if len(parts) < 2:
                    raise ConnectionError(f"malformed status line: {decoded_status!r}")
            except (ConnectionError, OSError, asyncio.TimeoutError):
                if attempt == 1:
                    raise
                continue

            status = int(parts[1])

            resp_headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), self._timeout)
                decoded = line.decode().strip()
                if not decoded:
                    break
                k, _, v = decoded.partition(":")
                resp_headers[k.strip().lower()] = v.strip()

            chunked = "chunked" in resp_headers.get("transfer-encoding", "").lower()
            resp = RawResponse(status, resp_headers, reader, chunked, client=self, host=host, port=port)
            break

        # Handle redirects
        if resp and resp.status in (301, 302, 303, 307, 308) and _max_redirects > 0:
            location = resp.headers.get("location", "")
            if location:
                # Drain the body so the connection can be reused
                await resp.read()
                if not location.startswith("http"):
                    location = f"https://{host}{location}"
                return await self._request(
                    method, location, headers, body, _max_redirects - 1
                )

        return resp  # type: ignore[return-value]

    async def get(
        self, url: str, headers: dict[str, str] | None = None
    ) -> RawResponse:
        return await self._request("GET", url, headers=headers)

    async def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> RawResponse:
        return await self._request("POST", url, headers=headers, body=body)

    async def warmup(self, url: str) -> None:
        """Pre-establish TCP+TLS connection to a host. Call during preload."""
        host, port, _ = self._parse_url(url)
        try:
            reader, writer = await self._connect(host, port)
            # Return it to pool immediately
            self._checkin(host, port, reader)
        except Exception:
            pass  # Best-effort; failure is non-fatal

    async def aclose(self):
        """Close ALL connections (pooled + checked-out) and wait for shutdown.

        Collects writers from both the idle pool and the in-flight set so no
        SSL transport is left dangling for StreamWriter.__del__ to trip over
        during interpreter teardown.
        """
        writers: set = set(self._all_writers)  # in-flight + ever-created
        for pool in self._conns.values():  # idle in pool
            for _, w in pool:
                writers.add(w)
        self._all_writers.clear()
        self._conns.clear()
        for writer in writers:
            try:
                writer.close()
            except Exception:
                pass
        # Wait for each to finish shutting down so SSL is fully torn down
        # while the loop is still open.
        for writer in writers:
            try:
                await writer.wait_closed()
            except Exception:
                pass
