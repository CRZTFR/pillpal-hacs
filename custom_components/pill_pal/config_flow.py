"""Connecting Home Assistant to a Pill Pal lamp.

The lamp is set up in the Bindicator app first. Home Assistant finds it by mDNS or a
typed address, asks to connect, and shows a six-digit code. The person approves the
request in the app after checking the app shows the same code, and the lamp commits a
grant for Home Assistant. No second hold at the lamp (development plan, "Setup order").

The grant key is derived on both sides from an X25519 exchange (crypto.py). It is never
sent, so nothing on the home network sees it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from . import api
from .const import (
    APPROVAL_POLL_SECONDS,
    APPROVAL_TIMEOUT_SECONDS,
    CONF_DEVICE_ID,
    CONF_GENERATION,
    CONF_GRANT_ID,
    CONF_GRANT_KEY,
    DEFAULT_PORT,
    DOMAIN,
    INTEGRATION_NAME,
    SUPPORTED_API,
)
from .crypto import Approval

_LOGGER = logging.getLogger(__name__)


class ApprovalRefused(Exception):
    """The request was declined, expired or replaced before anyone approved it."""

    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state


class PillPalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discovery or an address, then approval from the app."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port = DEFAULT_PORT
        self._device_id: str | None = None
        self._code: str | None = None
        self._approval_task: asyncio.Task | None = None
        self._approved: dict[str, Any] | None = None
        self._refused: str | None = None

    async def _identify(self, host: str, port: int) -> str:
        info = await api.hello(async_get_clientsession(self.hass), host, port)
        device_id = info.get("deviceId")
        if not isinstance(device_id, str) or not device_id:
            raise api.PillPalError("no device id")
        return device_id

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            try:
                device_id = await self._identify(host, port)
            except api.PillPalError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
                self._host, self._port, self._device_id = host, port, device_id
                return await self.async_step_pair()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        device_id = discovery_info.properties.get("device")
        if not device_id:
            return self.async_abort(reason="not_pill_pal")
        if discovery_info.properties.get("api", SUPPORTED_API) != SUPPORTED_API:
            return self.async_abort(reason="unsupported_api")
        await self.async_set_unique_id(device_id)
        # A lamp already set up that moved address is followed, not offered again.
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.host, CONF_PORT: discovery_info.port}
        )
        self._host = discovery_info.host
        self._port = discovery_info.port or DEFAULT_PORT
        self._device_id = device_id
        self.context["title_placeholders"] = {"name": device_id}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_pair()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._device_id or ""},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The lamp stopped accepting the grant: revoked in the app, or the lamp was reset."""
        self._host = entry_data[CONF_HOST]
        self._port = entry_data.get(CONF_PORT, DEFAULT_PORT)
        self._device_id = entry_data[CONF_DEVICE_ID]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_pair()
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"name": self._device_id or ""},
        )

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._approval_task is None:
            approval = Approval()
            session = async_get_clientsession(self.hass)
            try:
                opened = await api.open_request(
                    session, self._host, self._port, INTEGRATION_NAME, approval.public_key
                )
                request_id = bytes.fromhex(opened["requestId"])
                lamp_key = bytes.fromhex(opened["publicKey"])
            except (api.PillPalError, KeyError, ValueError) as err:
                _LOGGER.debug("Pill Pal would not open a request: %s", err)
                return self.async_abort(reason="cannot_connect")
            grant_key, self._code = approval.derive(self._device_id, request_id, lamp_key)
            self._approval_task = self.hass.async_create_task(
                self._wait_for_approval(opened["requestId"], grant_key)
            )

        if not self._approval_task.done():
            return self.async_show_progress(
                step_id="pair",
                progress_action="wait_for_approval",
                description_placeholders={"code": self._code or "", "name": INTEGRATION_NAME},
                progress_task=self._approval_task,
            )

        try:
            self._approved = self._approval_task.result()
        except ApprovalRefused as refused:
            self._refused = refused.state
            return self.async_show_progress_done(next_step_id="refused")
        except (api.PillPalError, TimeoutError):
            self._refused = "unreachable"
            return self.async_show_progress_done(next_step_id="refused")
        return self.async_show_progress_done(next_step_id="finish")

    async def _wait_for_approval(self, request_id: str, grant_key: bytes) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        async with asyncio.timeout(APPROVAL_TIMEOUT_SECONDS):
            while True:
                answer = await api.poll_request(session, self._host, self._port, request_id)
                state = answer.get("state")
                if state == "approved":
                    return {
                        CONF_GRANT_ID: int(answer["grantId"]),
                        CONF_GENERATION: int(answer["ownershipGeneration"]),
                        CONF_GRANT_KEY: grant_key.hex(),
                    }
                if state != "pending":
                    raise ApprovalRefused(str(state))
                await asyncio.sleep(APPROVAL_POLL_SECONDS)

    async def async_step_refused(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        reason = {
            "declined": "declined",
            "expired": "expired",
            "unreachable": "cannot_connect",
        }.get(self._refused or "", "expired")
        return self.async_abort(reason=reason)

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_DEVICE_ID: self._device_id,
            **(self._approved or {}),
        }
        if self.source == "reauth":
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        return self.async_create_entry(title=f"Pill Pal {self._device_id}", data=data)
