"""Constants for the Qixu MCP integration."""

DOMAIN = "qixu_mcp"
TITLE = "Qixu MCP"

CONF_ENDPOINT = "endpoint"
CONF_TOKEN = "token"
CONF_HOME_ID = "home_id"
CONF_CONFIRM_KEYWORDS = "confirm_keywords"

DEFAULT_CONFIRM_KEYWORDS = "门锁,开锁,开门,出车,撤防"

RECONNECT_MIN_SECONDS = 5
RECONNECT_MAX_SECONDS = 300
# A connection that lived this long resets the backoff.
STABLE_CONNECTION_SECONDS = 60
HEARTBEAT_SECONDS = 50
CONNECT_TIMEOUT_SECONDS = 15
CONFIRM_TTL_SECONDS = 30

CONFIRM_TOOL_NAME = "QixuConfirmAction"

HEADER_HOME = "X-Qixu-Home"
HEADER_PLUGIN_VERSION = "X-Qixu-Plugin-Version"
HEADER_HA_VERSION = "X-HA-Version"

# Older entries may still carry this API id.
STATELESS_LLM_API = "stateless_assist"
