# instnt hub for Home Assistant

The Home Assistant side of **instnt hub**, an iPad app that sits on the coffee
table all day: photos, clocks, weather, controls for your home, and a
companion screen that appears when the PlayStation or TV turns on.

The app only talks to Home Assistant. This integration translates whatever is
in your house into one fixed shape the app can rely on, so a new source (an
Xbox, another TV brand) is a translation here instead of an app update.

## What it does

- **Contract** (`instnt_hub/contract`, WebSocket): console, room, TV and
  automations in one versioned shape, each with what is still `missing`.
- **Lyrics** (`instnt_hub/lyrics`): synced lyrics from LRCLIB.
- **Queue** (`instnt_hub/queue`): the Sonos queue with cover art, served
  through signed links under `/api/instnt_hub/art/…`.
- **Trophies** (`instnt_hub/trophy_titles`, `instnt_hub/trophy_game`): recent
  games and the trophies of one game, through Home Assistant's own
  PlayStation Network integration. No second token: it borrows that
  integration's client and its rate limit. `console.trophies` in the contract
  says whether it is available.
- **TV guide** (`instnt_hub/tv_guide`): now and next per chosen channel from an
  XMLTV source (by default the free Dutch file from open-epg.com, refreshed
  every six hours), and which channel the TV is on when that can be told. Off
  by default; switch it on in Configure.
- **Soundbar switch**: `switch.<name>_soundbar`, the assumed state of a
  soundbar that only has a toggle; it only presses when the state is wrong.
- **Automations** for blinds, soundbar and TV when the console turns on. They
  are **off** by default, so they never double up with automations you
  already have.

## Install

Via HACS as a custom repository:

1. HACS › three dots › Custom repositories.
2. Add `https://github.com/instnthub/instnthub-HA`,
   type *Integration*.
3. Install **instnt hub**, restart Home Assistant.
4. Settings › Devices & services › Add integration › **instnt hub**, then
   *Configure*. What it detects by itself (PlayStation Network, ps5-mqtt,
   cover art) is filled in already.

Requires Home Assistant 2025.6 or newer.

## Versions

The app and the integration agree on a contract `version`. When the shape
changes, the version goes up, and the app tells you to update the
integration instead of breaking.

## License

MIT, see [LICENSE](LICENSE).
