"""Redis-backed cross-process runtime status using the stable RESP protocol."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse


class RuntimeRegistry:
    """Store service liveness and latest state with bounded retention.

    Only PING, SET with expiry, and GET are required. Speaking RESP directly
    avoids an otherwise unnecessary runtime dependency while still using the
    real Redis service and its persistence/TTL semantics.
    """

    def __init__(self, url: str, *, namespace: str = "traffic") -> None:
        parsed = urlparse(url)
        if parsed.scheme != "redis" or not parsed.hostname:
            raise ValueError("runtime registry URL must use redis://host[:port]/db")
        self.host = parsed.hostname
        self.port = parsed.port or 6379
        self.database = int((parsed.path or "/0").lstrip("/") or "0")
        self.password = parsed.password
        self.namespace = namespace

    async def ping(self) -> bool:
        """Verify Redis connectivity."""

        response = await self._command("PING")
        return response == "PONG"

    async def heartbeat(
        self,
        role: str,
        instance_id: str,
        payload: Mapping[str, object],
        *,
        ttl_s: int = 15,
    ) -> None:
        """Write one expiring liveness record."""

        await self._set(
            f"{self.namespace}:service:{role}:{instance_id}",
            json.dumps(dict(payload), ensure_ascii=False),
            ttl_s=ttl_s,
        )

    async def set_latest(
        self,
        category: str,
        identifier: str,
        payload: Mapping[str, object],
        *,
        ttl_s: int = 3600,
    ) -> None:
        """Write replaceable runtime state without unbounded key growth."""

        await self._set(
            f"{self.namespace}:latest:{category}:{identifier}",
            json.dumps(dict(payload), ensure_ascii=False),
            ttl_s=ttl_s,
        )

    async def get_latest(
        self,
        category: str,
        identifier: str,
    ) -> dict[str, Any] | None:
        """Read a latest-state record."""

        value = await self._command(
            "GET",
            f"{self.namespace}:latest:{category}:{identifier}",
        )
        if value is None:
            return None
        if not isinstance(value, str):
            raise RuntimeError("Redis GET returned a non-string response")
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise RuntimeError("runtime registry value is not a JSON object")
        return parsed

    async def get_heartbeat(
        self,
        role: str,
        instance_id: str,
    ) -> dict[str, Any] | None:
        """Read one service heartbeat, returning ``None`` after its TTL."""

        value = await self._command(
            "GET",
            f"{self.namespace}:service:{role}:{instance_id}",
        )
        if value is None:
            return None
        if not isinstance(value, str):
            raise RuntimeError("Redis GET returned a non-string response")
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise RuntimeError("runtime heartbeat is not a JSON object")
        return parsed

    async def close(self) -> None:
        """Compatibility hook; each bounded command closes its own connection."""

    async def _set(self, key: str, value: str, *, ttl_s: int) -> None:
        response = await self._command("SET", key, value, "EX", str(ttl_s))
        if response != "OK":
            raise RuntimeError(f"Redis SET failed: {response}")

    async def _command(self, *parts: str) -> str | int | None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=3.0,
        )
        try:
            if self.password:
                writer.write(_encode_command("AUTH", self.password))
                await writer.drain()
                await _read_response(reader)
            if self.database:
                writer.write(_encode_command("SELECT", str(self.database)))
                await writer.drain()
                await _read_response(reader)
            writer.write(_encode_command(*parts))
            await writer.drain()
            return await asyncio.wait_for(_read_response(reader), timeout=3.0)
        finally:
            writer.close()
            await writer.wait_closed()


def _encode_command(*parts: str) -> bytes:
    chunks = [f"*{len(parts)}\r\n".encode("ascii")]
    for part in parts:
        encoded = part.encode("utf-8")
        chunks.extend(
            (
                f"${len(encoded)}\r\n".encode("ascii"),
                encoded,
                b"\r\n",
            )
        )
    return b"".join(chunks)


async def _read_response(reader: asyncio.StreamReader) -> str | int | None:
    prefix = await reader.readexactly(1)
    line = await reader.readline()
    if not line.endswith(b"\r\n"):
        raise RuntimeError("invalid Redis RESP line")
    body = line[:-2]
    if prefix == b"+":
        return body.decode("utf-8")
    if prefix == b":":
        return int(body)
    if prefix == b"-":
        raise RuntimeError(f"Redis error: {body.decode('utf-8', errors='replace')}")
    if prefix == b"$":
        length = int(body)
        if length == -1:
            return None
        payload = await reader.readexactly(length)
        terminator = await reader.readexactly(2)
        if terminator != b"\r\n":
            raise RuntimeError("invalid Redis bulk-string terminator")
        return payload.decode("utf-8")
    raise RuntimeError(f"unsupported Redis RESP prefix: {prefix!r}")
