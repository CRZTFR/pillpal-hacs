"""The lamp's reported state, and the stream that says when it changed.

State arrives by reading /state. The event stream (integrations.md, "Event stream")
says *that* something changed, not what: a snapshot is several kilobytes and most
changes need none of it, so `changed` triggers a read here, debounced by the
coordinator. `touch` events go straight to the event entity through the dispatcher,
because a tap has to reach an automation in about a second. A slow poll stays under
both in case the stream is down.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PillPalAuthError, PillPalClient, PillPalError
from .const import (
    DOMAIN,
    POLL_INTERVAL_SECONDS,
    SIGNAL_AVAILABILITY,
    SIGNAL_TOUCH,
    STREAM_LIVENESS_SECONDS,
    STREAM_RECONNECT_INITIAL_SECONDS,
    STREAM_RECONNECT_MAX_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class PillPalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the latest snapshot."""

    def __init__(self, hass: HomeAssistant, client: PillPalClient, entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.device_id}",
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
            # A burst of `changed` events becomes one read.
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=0.3, immediate=True),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.state()
        except PillPalAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PillPalError as err:
            raise UpdateFailed(str(err)) from err

    def statuses(self) -> list[dict[str, Any]]:
        return list(((self.data or {}).get("indicators") or {}).get("statuses") or [])

    def own_statuses(self) -> list[dict[str, Any]]:
        """The statuses this integration set, which are the ones it may clear."""
        return [s for s in self.statuses() if s.get("owner") == self.client.grant_id]


class PillPalStream:
    """The long-lived connection to /events, reconnecting with backoff."""

    def __init__(self, hass: HomeAssistant, coordinator: PillPalCoordinator, entry) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._entry = entry
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = self._entry.async_create_background_task(
            self._hass, self._run(), name=f"{DOMAIN}.events.{self._coordinator.client.device_id}"
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if self._connected == value:
            return
        self._connected = value
        async_dispatcher_send(
            self._hass,
            SIGNAL_AVAILABILITY.format(device_id=self._coordinator.client.device_id),
            value,
        )

    async def _run(self) -> None:
        backoff = STREAM_RECONNECT_INITIAL_SECONDS
        while not self._stopping:
            try:
                await self._consume()
                backoff = STREAM_RECONNECT_INITIAL_SECONDS
            except asyncio.CancelledError:
                raise
            except PillPalAuthError:
                # Revoked in the app, or the lamp was reset. Nothing to retry until a
                # person approves Home Assistant again.
                self._set_connected(False)
                self._entry.async_start_reauth(self._hass)
                return
            except (PillPalError, aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Pill Pal event stream: %s; retrying in %ss", err, backoff)
            self._set_connected(False)
            if self._stopping:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, STREAM_RECONNECT_MAX_SECONDS)

    async def _consume(self) -> None:
        response = await self._coordinator.client.open_events()
        try:
            self._set_connected(True)
            name: str | None = None
            data: list[str] = []
            while True:
                try:
                    raw = await asyncio.wait_for(
                        response.content.readline(), timeout=STREAM_LIVENESS_SECONDS
                    )
                except TimeoutError as err:
                    raise PillPalError("no keepalive from the lamp") from err
                if not raw:
                    return
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith(":"):
                    continue
                if line == "":
                    if name is not None:
                        if self._dispatch(name, "\n".join(data)):
                            return
                    name, data = None, []
                elif line.startswith("event:"):
                    name = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data.append(line[len("data:"):].lstrip())
        finally:
            response.release()

    def _dispatch(self, name: str, data: str) -> bool:
        """Handles one event. True when the stream should end."""
        try:
            payload = json.loads(data) if data else {}
        except json.JSONDecodeError:
            _LOGGER.debug("Pill Pal sent an unreadable %s event: %s", name, data)
            return False
        if name == "hello":
            # A new connection may have missed changes: read everything once.
            self._hass.async_create_task(self._coordinator.async_request_refresh())
        elif name == "changed":
            self._hass.async_create_task(self._coordinator.async_request_refresh())
        elif name == "touch":
            async_dispatcher_send(
                self._hass,
                SIGNAL_TOUCH.format(device_id=self._coordinator.client.device_id),
                payload,
            )
        elif name == "revoked":
            raise PillPalAuthError("revoked")
        return False
