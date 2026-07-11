"""Constants for grubstation."""

from logging import Logger, getLogger
from typing import Final

LOGGER: Logger = getLogger(__package__)

DOMAIN: Final[str] = "grubstation"
ATTRIBUTION: Final[str] = "Data provided by GrubStation"

ATTR_OS: Final[str] = "os"
ATTR_SERVICE_MANAGER: Final[str] = "service_manager"
ATTR_VERSION: Final[str] = "version"

CONF_ADVANCED_OPTIONS: Final[str] = "advanced_options"
CONF_BOOT_OPTIONS: Final[str] = "boot_options"
CONF_DAEMONLESS: Final[str] = "daemonless"
CONF_HA_DAEMON_URL: Final[str] = "ha_daemon_url"
CONF_HA_GRUB_URL: Final[str] = "ha_grub_url"
CONF_HOSTNAME: Final[str] = "hostname"
CONF_TURN_OFF_ACTION: Final[str] = "turn_off_action"
CONF_UPDATE_GRUB: Final[str] = "update_grub"
CONF_DAEMON_TOKEN: Final[str] = "daemon_token"
CONF_WOL_BROADCAST: Final[str] = "wol_broadcast"
CONF_WOL_PORT: Final[str] = "wol_port"

DEFAULT_AGENT_PORT: Final[int] = 8081
DEFAULT_BOOT_OPTION: Final[str] = "default"
DEFAULT_DAEMONLESS: Final[bool] = False
DEFAULT_SERVER_PORT: Final[int] = 8123
DEFAULT_WOL_BROADCAST: Final[str] = "255.255.255.255"
DEFAULT_WOL_PORT: Final[int] = 9

API_TIMEOUT_SECONDS: Final[int] = 10
API_KEY_LENGTH: Final[int] = 32
