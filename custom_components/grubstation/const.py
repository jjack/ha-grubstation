"""Constants for grubstation."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "grubstation"
ATTRIBUTION = "Data provided by http://jsonplaceholder.typicode.com/"

ATTR_OS = "os"
ATTR_VERSION = "version"
ATTR_SERVICE_MANAGER = "service_manager"

CONF_BOOT_OPTIONS = "boot_options"
CONF_DAEMONLESS = "daemonless"
CONF_HA_DAEMON_URL = "ha_daemon_url"
CONF_HA_GRUB_URL = "ha_grub_url"
CONF_UPDATE_GRUB = "update_grub"
CONF_TURN_OFF_ACTION = "turn_off_action"

DEFAULT_AGENT_PORT = 8081
DEFAULT_DAEMONLESS = False
SERVER_PORT = 8123
