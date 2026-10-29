"""Constants for the instnt hub integration."""

DOMAIN = "instnt_hub"

# Options: which entity plays which role.
CONF_CONSOLE_POWER = "console_power"
CONF_CONSOLE_PLAYING = "console_playing"
CONF_CONSOLE_ART = "console_art"
CONF_COVERS = "covers"
CONF_DAY_POSITION = "day_position"
CONF_NIGHT_POSITION = "night_position"
CONF_SOUNDBAR_TOGGLE = "soundbar_toggle"
CONF_TV = "tv"
CONF_KEEP_ON = "keep_on"
CONF_GUIDE = "guide"
CONF_GUIDE_URL = "guide_url"
CONF_GUIDE_CHANNELS = "guide_channels"

# Off by default, so they don't run alongside automations the user already has.
CONF_AUTO_COVERS = "auto_covers"
CONF_AUTO_SOUNDBAR = "auto_soundbar"
CONF_AUTO_TV = "auto_tv"

DEFAULT_DAY_POSITION = 0
DEFAULT_NIGHT_POSITION = 50

# A switch (ps5-mqtt) reports on/off, a media player (PlayStation Network)
# playing/idle/off. Anything else, such as "unavailable" while the console is
# in rest mode, is not a transition.
ON_STATES = {"on", "playing", "paused", "idle", "buffering"}
OFF_STATES = {"off", "standby"}

SIGNAL_UPDATE = f"{DOMAIN}_update"
