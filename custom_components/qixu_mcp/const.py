"""Constants for the Qixu MCP integration."""

DOMAIN = "qixu_mcp"
TITLE = "Qixu MCP"

CONF_ENDPOINT = "endpoint"
CONF_TOKEN = "token"
CONF_HOME_ID = "home_id"
CONF_CONFIRM_KEYWORDS = "confirm_keywords"

DEFAULT_CONFIRM_KEYWORDS = "门锁,开锁,开门,出车,撤防"

RECONNECT_SECONDS = 20
HEARTBEAT_SECONDS = 50
CONFIRM_TTL_SECONDS = 30

CONFIRM_TOOL_NAME = "QixuConfirmAction"

# Older entries may still carry this API id.
STATELESS_LLM_API = "stateless_assist"
