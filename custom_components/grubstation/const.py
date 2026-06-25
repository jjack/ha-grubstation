"""Constants for grubstation."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "grubstation"
ATTRIBUTION = "Data provided by http://jsonplaceholder.typicode.com/"

CONF_BOOT_OPTIONS = "boot_options"
CONF_DAEMONLESS = "daemonless"

DEFAULT_AGENT_PORT = 8081
DEFAULT_DAEMONLESS = False
