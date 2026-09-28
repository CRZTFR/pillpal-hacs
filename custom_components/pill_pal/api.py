"""The lamp's local API, as an integration sees it.

Unauthenticated: /hello, and the two approval routes, because an integration has no
grant until a phone approves one. Everything else is signed with the grant key
(crypto.py): a read with a nonce the lamp issued, a command over the exact bytes sent.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import aiohttp

from .const import COMMAND_LIFETIME_MS, DEFAULT_PORT
from .crypto import read_tag, tag

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
# SSE stays open. Liveness is judged from the keepalive, not a request timeout.
STREAM_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=10)


class PillPalError(Exception):
    """The lamp could not be reached, or answered with something unusable."""


class PillPalAuthError(PillPalError):
    """The lamp does not accept this grant: revoked, reset, or never approved."""


class PillPalCommandError(PillPalError):
    """The lamp refused a command. `outcome` is the contract's outcome name."""

    def __init__(self, outcome: str, answer: dict[str, Any]) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.answer = answer


def base_url(host: str, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}"


async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        return await response.json(content_type=None)
    except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError) as err:
        raise PillPalError(f"not JSON from {response.url}") from err


async def hello(session: aiohttp.ClientSession, host: str, port: int = DEFAULT_PORT) -> dict:
    """Who the lamp at `host` is. Unauthenticated."""
    try:
        async with session.get(f"{base_url(host, port)}/hello", timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            return await _json(response)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise PillPalError(str(err)) from err


async def open_request(
    session: aiohttp.ClientSession, host: str, port: int, name: str, public_key: bytes
) -> dict[str, Any]:
    """Ask the lamp to connect. Answers requestId, the lamp's publicKey and its expiry."""
    body = {"name": name, "publicKey": public_key.hex()}
    try:
        async with session.post(
            f"{base_url(host, port)}/integrations/request", json=body, timeout=REQUEST_TIMEOUT
        ) as response:
            answer = await _json(response)
            if response.status != 200:
                raise PillPalError(answer.get("error", f"HTTP {response.status}"))
            return answer
    except (aiohttp.ClientError, TimeoutError) as err:
        raise PillPalError(str(err)) from err


async def poll_request(
    session: aiohttp.ClientSession, host: str, port: int, request_id: str
) -> dict[str, Any]:
    """pending, approved (with grantId and ownershipGeneration), declined or expired."""
    try:
        async with session.get(
            f"{base_url(host, port)}/integrations/request/{request_id}", timeout=REQUEST_TIMEOUT
        ) as response:
            response.raise_for_status()
            return await _json(response)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise PillPalError(str(err)) from err


class PillPalClient:
    """One approved grant on one lamp."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        device_id: str,
        grant_id: int,
        key: bytes,
        ownership_generation: int,
    ) -> None:
        self._session = session
        self.host = host
        self.port = port
        self.device_id = device_id
        self.grant_id = grant_id
        self._key = key
        self.ownership_generation = ownership_generation
        self._last_sequence = 0

    @property
    def base_url(self) -> str:
        return base_url(self.host, self.port)

    def _next_sequence(self) -> int:
        # The lamp refuses a sequence it has seen or one far behind the highest (README,
        # "Replay protection"). Milliseconds since the epoch keep rising across a Home
        # Assistant restart without anything to store, and stay far below 2^53.
        self._last_sequence = max(self._last_sequence + 1, int(time.time() * 1000))
        return self._last_sequence

    async def _nonce(self) -> str:
        try:
            async with self._session.get(f"{self.base_url}/nonce", timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                return (await _json(response))["nonce"]
        except (aiohttp.ClientError, TimeoutError, KeyError) as err:
            raise PillPalError(f"no nonce: {err}") from err

    async def read_headers(self, path: str) -> dict[str, str]:
        nonce = await self._nonce()
        return {
            "X-PP-Grant": str(self.grant_id),
            "X-PP-Nonce": nonce,
            "X-PP-Auth": read_tag(self._key, path, self.grant_id, nonce),
        }

    async def state(self) -> dict[str, Any]:
        """The lamp's reported state (README, "Reported state")."""
        headers = await self.read_headers("/state")
        try:
            async with self._session.get(
                f"{self.base_url}/state", headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 401:
                    raise PillPalAuthError("the lamp no longer accepts this grant")
                response.raise_for_status()
                return await _json(response)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PillPalError(str(err)) from err

    async def open_events(self) -> aiohttp.ClientResponse:
        """The event stream. The caller reads it and closes it."""
        headers = await self.read_headers("/events")
        headers["Accept"] = "text/event-stream"
        response = await self._session.get(
            f"{self.base_url}/events", headers=headers, timeout=STREAM_TIMEOUT
        )
        if response.status == 401:
            response.release()
            raise PillPalAuthError("the lamp no longer accepts this grant")
        if response.status != 200:
            response.release()
            raise PillPalError(f"event stream: HTTP {response.status}")
        return response

    async def command(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one transient command and return the lamp's answer.

        Everything an integration may send is transient, so each carries an expiry and
        no configuration revision. Raises PillPalCommandError unless it was applied.
        """
        sequence = self._next_sequence()
        envelope: dict[str, Any] = {
            "protocolVersion": 1,
            "deviceId": self.device_id,
            "ownershipGeneration": self.ownership_generation,
            "grantId": self.grant_id,
            "sequence": sequence,
            "commandId": uuid.uuid4().hex,
            "operation": operation,
            "expiresAt": int(time.time() * 1000) + COMMAND_LIFETIME_MS,
        }
        if payload is not None:
            envelope["payload"] = payload
        # The tag covers these exact bytes, so they are sent as they were signed.
        body = json.dumps(envelope, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            "X-PP-Grant": str(self.grant_id),
            "X-PP-Auth": tag(self._key, body),
        }
        try:
            async with self._session.post(
                f"{self.base_url}/command", data=body, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                answer = await _json(response)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PillPalError(str(err)) from err
        outcome = answer.get("outcome", "malformed")
        if outcome == "duplicate":
            outcome = answer.get("originalOutcome", outcome)
        if outcome in ("unknown_grant", "ownership_mismatch"):
            raise PillPalAuthError(outcome)
        if outcome != "applied":
            raise PillPalCommandError(outcome, answer)
        return answer
