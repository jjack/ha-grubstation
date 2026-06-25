"""Sample API Client."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import aiohttp


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


def _verify_response_or_raise(response: aiohttp.ClientResponse) -> None:
    """Verify that the response is valid."""
    if response.status in (401, 403):
        msg = "Invalid credentials"
        raise GrubStationApiClientAuthenticationError(
            msg,
        )
    response.raise_for_status()


class GrubStationApiClient:
    """Sample API Client."""

    def __init__(
        self,
        host: str,
        port: int,
        mac: str | None,
        daemonless: bool,
        webhook_id: str | None,
        api_key: str | None,
        ha_daemon_url: str | None,
        ha_grub_url: str | None,
        apply_config: bool,
        session: aiohttp.ClientSession,
    ) -> None:
        """Sample API Client."""
        self._host = host
        self._port = port
        self._mac = mac
        self._daemonless = daemonless
        self._webhook_id = webhook_id
        self._api_key = api_key
        self._ha_daemon_url = ha_daemon_url
        self._ha_grub_url = ha_grub_url
        self._apply_config = apply_config
        self._session = session

    async def async_pair(self) -> Any:
        """Pair the integration with the GrubStation device."""
        pairing_payload = {
            "paired": True,
            "webhook_id": self._webhook_id,
            "api_key": self._api_key,
            "ha_daemon_url": self._ha_daemon_url,
            "ha_grub_url": self._ha_grub_url,
            "apply_config": self._apply_config,
        }
        return await self._api_wrapper(
            method="post",
            url=f"http://{self._host}:{self._port}/pair",
            data=pairing_payload,
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
                _verify_response_or_raise(response)
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
        except Exception as exception:  # pylint: disable=broad-except
            msg = f"Something really wrong happened! - {exception}"
            raise GrubStationApiClientError(
                msg,
            ) from exception
