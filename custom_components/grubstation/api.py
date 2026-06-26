"""Sample API Client."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import aiohttp

from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_MAC, CONF_PORT, CONF_WEBHOOK_ID

from .const import CONF_APPLY_CONFIG, CONF_DAEMONLESS, CONF_HA_DAEMON_URL, CONF_HA_GRUB_URL


class GrubStationApiClientError(Exception):
    """Exception to indicate a general API error."""


class GrubStationApiClientCommunicationError(
    GrubStationApiClientError,
):
    """Exception to indicate a communication error."""


class GrubStationApiClientAuthenticationError(
    GrubStationApiClientError,
):
    """Exception to indicate an authentication error."""


class GrubStationApiPinRequiredError(GrubStationApiClientError):
    """Exception to indicate PIN code is required."""


class GrubStationApiInvalidPinError(GrubStationApiClientAuthenticationError):
    """Exception to indicate the entered PIN code is invalid."""


class GrubStationApiConflictError(GrubStationApiClientError):
    """Exception to indicate the host is already paired."""


async def _verify_response_or_raise(response: aiohttp.ClientResponse) -> None:
    """Verify that the response is valid."""
    if response.status == 409:
        raise GrubStationApiConflictError("Conflict: Host already paired")
    if response.status in (401, 403):
        try:
            body = await response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if error == "pin_required":
                    raise GrubStationApiPinRequiredError("PIN is required")
                if error == "invalid_pin":
                    raise GrubStationApiInvalidPinError("Invalid PIN entered")
        except aiohttp.ClientError, ValueError:
            pass
        msg = "Invalid credentials"
        raise GrubStationApiClientAuthenticationError(
            msg,
        )
    response.raise_for_status()


class GrubStationApiClient:
    """Sample API Client."""

    def __init__(
        self,
        config: dict[str, Any],
        session: aiohttp.ClientSession,
    ) -> None:
        """Sample API Client."""
        self._host = config[CONF_HOST]
        self._port = config[CONF_PORT]
        self._mac = config.get(CONF_MAC)
        self._daemonless = config.get(CONF_DAEMONLESS, False)
        self._webhook_id = config.get(CONF_WEBHOOK_ID)
        self._api_key = config.get(CONF_API_KEY)
        self._ha_daemon_url = config.get(CONF_HA_DAEMON_URL)
        self._ha_grub_url = config.get(CONF_HA_GRUB_URL)
        self._apply_config = config.get(CONF_APPLY_CONFIG, True)
        self._session = session

    async def async_pair(self, pin: str | None = None) -> Any:
        """Pair the integration with the GrubStation device."""
        pairing_payload = {
            "paired": True,
            "webhook_id": self._webhook_id,
            "api_key": self._api_key,
            "ha_daemon_url": self._ha_daemon_url,
            "ha_grub_url": self._ha_grub_url,
            "apply_config": self._apply_config,
        }
        headers = {}
        if pin is not None:
            headers["Authorization"] = f"Bearer {pin}"
        return await self._api_wrapper(
            method="post",
            url=f"http://{self._host}:{self._port}/pair",
            data=pairing_payload,
            headers=headers,
        )

    async def async_unpair(self) -> Any:
        """Unpair the integration from the GrubStation device."""
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return await self._api_wrapper(
            method="post",
            url=f"http://{self._host}:{self._port}/unpair",
            headers=headers,
        )

    async def async_get_status(self) -> dict[str, Any]:
        """Check status of the GrubStation device."""
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return await self._api_wrapper(
            method="get",
            url=f"http://{self._host}:{self._port}/status",
            headers=headers,
        )

    async def async_get_data(self) -> Any:
        """Get data from the API."""
        return await self._api_wrapper(
            method="get",
            url="https://jsonplaceholder.typicode.com/posts/1",
        )

    async def async_set_title(self, value: str) -> Any:
        """Get data from the API."""
        return await self._api_wrapper(
            method="patch",
            url="https://jsonplaceholder.typicode.com/posts/1",
            data={"title": value},
            headers={"Content-type": "application/json; charset=UTF-8"},
        )

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
    ) -> Any:
        """Get information from the API."""
        try:
            async with asyncio.timeout(10):
                response = await self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                )
                await _verify_response_or_raise(response)
                return await response.json()

        except TimeoutError as exception:
            msg = f"Timeout error fetching information - {exception}"
            raise GrubStationApiClientCommunicationError(
                msg,
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error fetching information - {exception}"
            raise GrubStationApiClientCommunicationError(
                msg,
            ) from exception
        except GrubStationApiClientError:
            raise
        except Exception as exception:  # pylint: disable=broad-except
            msg = f"Something really wrong happened! - {exception}"
            raise GrubStationApiClientError(
                msg,
            ) from exception
