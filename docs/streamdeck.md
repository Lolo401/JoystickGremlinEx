# Stream Deck (Elgato plugin bridge)

GremlinEx can use Elgato Stream Deck hardware through a dedicated **Stream Deck plugin** and a localhost WebSocket bridge. Stream Deck software remains running and owns USB, so other decks can still run Wave Link or other plugins on the same PC.

This path does **not** require Bitfocus Companion or OSC for those keys. Companion + OSC remain available for glass surfaces and users who prefer that stack.

## Setup

1. Install the plugin from `streamdeck_plugin/` (see that folder’s README). CodePath must be `app.html` (classic Stream Deck HTML host).
2. In GremlinEx **Options → OSC/MIDI**, enable **Stream Deck bridge** (default port `9020`).
3. Place **JG Ex Button** (or **JG Ex Dial**) actions on Stream Deck keys. Customize icons/titles in Stream Deck software (visual only).
4. Property Inspector status should show **Connected to JG Ex**. Each connected deck gets its own GEX device tab (named from Elgato, e.g. **Stream Deck XL**, **Stream Deck +**) with **Plugin: connected**.
5. Set an editable **Button ID** in the Property Inspector (a unique name on that deck). New buttons get an auto default such as `btn-a1b2c3`. Bridge host/port are under **Open Plugin Configuration**.
6. Click **Refresh** on that deck’s GremlinEx tab to import/update inputs from Stream Deck (there is no auto-refresh).
7. Map the listed inputs (containers / Map to VJoy / etc.).

## Button ID (freeform)

GEX identifies each Stream Deck input as `deviceId : kind : buttonId`.

- **Button ID** is a user-defined opaque string (letters, digits, and `-_.:`). It must be unique on that deck; collisions map to one GEX input.
- Examples: `Gear`, `LandingLights`, `btn-a1b2c3`. Seeded profiles use names like `p1-r1-c1` (plain strings, not a structured schema).
- Only **JG Ex Button** / **JG Ex Dial** actions appear in GEX. Other Stream Deck actions are ignored.
- The list is sorted alphabetically by Button ID (case-insensitive), then kind. Use **Refresh** after programming changes in Stream Deck software.
- Refresh imports **all pages/folders** from the JG Ex Stream Deck profile on disk (ProfilesV3) — every action that has a `buttonId`, regardless of layout.
- Legacy `P1:R1:C1`-style IDs still work as opaque strings (kept as-is).

Stream Deck key **titles/icons** are cosmetic only. Folder/page navigation is unrelated to identity — use different Button IDs for different bindings.

### Companion “Dynamic Page” (investigation)

In Bitfocus’s official Stream Deck plugin, **Dynamic Page** means the button’s page is *not* fixed: Companion is told `page=null` and the action uses the **currently active Companion page** with the configured row/column. Fixed-page mode binds to an explicit Companion page number and needs Satellite “subscriptions” for images.

That feature does **not** apply to JG Ex freeform IDs: Elgato owns profile pages and does not send a page index in SDK events. Identity lives only in the Button ID you set in settings.

## Multi-device

- **One GEX tab per physical Stream Deck** (joystick-like). Inputs for a deck stay under that deck’s stable GUID.
- Tabs appear when the plugin reports the deck connected (`device` / `willAppear`) and hide when it disconnects; profile mappings are kept.
- Old profiles that stored everything under a single **Stream Deck** GUID still show a **Stream Deck (legacy)** tab until those inputs are migrated (happens automatically when that deck reconnects and `device-id` is present).

## Plugin profiles (Change Page)

The plugin ships **one profile per Elgato DeviceType** (pages are pages inside that profile — never one profile per page):

| DeviceType | Profile | Typical hardware |
|---|---|---|
| 2 | `profiles/jgex-xl` | Stream Deck XL |
| 7 | `profiles/jgex-plus` | Stream Deck + |
| 0 | `profiles/jgex` | Classic / MK.2 |
| 1 | `profiles/jgex-mini` | Mini |
| 9 | `profiles/jgex-neo` | Neo |

Stream Deck **+** keys use **JG Ex Button**; encoders use **JG Ex Dial**.

## Two-way control

Use the **Map to Stream Deck** action on any button-like input:

1. **Device** — pick a Stream Deck reported by the connected plugin (Refresh if needed).
2. **Function** — currently **Change Page**.
3. **Page** — page number on that device’s **JG Ex** plugin profile (`1` = first page).
4. Optional **Test** button sends Change Page immediately.

**Important (Elgato SDK):** plugins cannot change pages on arbitrary user profiles (e.g. “Profile 1”). Change Page switches to the bundled JG Ex profile for that device type at the requested page. Close the Stream Deck editor, accept the profile install if prompted, and place your buttons on that profile’s pages.

## Related

- Companion / OSC panel setup: [usage.md](usage.md#osc-device-open-sound-control), [mapping.md](mapping.md), [resources.md](resources.md)
