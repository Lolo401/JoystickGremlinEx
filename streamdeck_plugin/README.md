# Stream Deck plugin for Joystick Gremlin Ex

Two-way bridge between **Elgato Stream Deck software** and **Joystick Gremlin Ex**.
Stream Deck software keeps USB ownership (Wave Link / multi-deck safe). Companion/OSC is not required for these keys.

## Install the plugin

Requires **Stream Deck software 6.0+**. The plugin backend is classic HTML/JS (`app.html` → `app.js`); Stream Deck hosts it and injects the WebSocket registration call.

1. Quit Stream Deck software.
2. Copy the folder `com.joystickgremlin.ex.sdPlugin` into the Stream Deck plugins directory, typically:

   `%appdata%\Elgato\StreamDeck\Plugins\`

3. Start Stream Deck software. You should see **Joystick Gremlin Ex** actions: **JG Ex Button** and **JG Ex Dial**.

Optional: zip the `.sdPlugin` folder contents and rename to `.streamDeckPlugin` for double-click install (Elgato packaging).

If the Property Inspector stays on **Connecting…** and Stream Deck's log shows `The plugin has no attached client`, re-copy the folder (ensure `manifest.json` has `"CodePath": "app.html"`) and fully quit/restart Stream Deck.

## Configure GremlinEx

1. Open **Options → OSC/MIDI**.
2. Enable **Stream Deck bridge**.
3. Bridge port default: **9020** (`ws://127.0.0.1:9020`).
4. Restart tabs / reload if prompted so each **connected Stream Deck** gets its own device tab (e.g. Stream Deck XL, Stream Deck +).

## Map buttons (Button ID)

1. In Stream Deck software, drop **JG Ex Button** on a key (or use a seeded JG Ex profile).
2. Keep customizing **icon** and **title** in Stream Deck as usual — those are visual only.
3. Property Inspector: editable **Button ID** (unique name on this deck). New buttons get an auto default such as `btn-a1b2c3`; rename to whatever you want (`Gear`, etc.). There is no Row/Column/Page field.
4. Use **Open Plugin Configuration** for GEX host/port (not inline on every button).
5. In GEX, click **Refresh** on that deck’s tab — inputs appear sorted alphabetically by Button ID. There is no auto-refresh.

The plugin ships one JG Ex profile per device class (XL, +, Mini, Neo, classic). Change Page targets that profile’s pages for the selected device — not one profile per page. Change Page is unrelated to Button ID identity.

## Dials (Stream Deck+)

Use **JG Ex Dial**. Rotate pulses INC/DEC-style inputs with autorelease; push sends dial press/release.

## Two-way control from GEX

Add action **Map to Stream Deck**:

1. Select a **connected Stream Deck** from the dropdown (Refresh if the list is empty).
2. Choose a **Function** — currently **Change Page**.
3. For Change Page, set the **Page** number as shown in Stream Deck software (1 = first page).

| Function | Effect |
|----------|--------|
| Change Page | Sends Elgato `switchToProfile` with a 0-based `page` index for the selected device |

### SDK notes

Elgato’s public API for navigation is `switchToProfile` (optional profile name + optional page). Close the Stream Deck **editor** window for switches to apply. Profile/page switching can be limited by Stream Deck software and profile type; test on your setup.

## Multi-deck / Wave Link

Because Stream Deck software owns the hardware, you can use one deck for Wave Link (or other plugins) and another for JG Ex Button actions on the same PC. GEX never opens USB HID on the deck.

## Coexistence with Companion / OSC

Existing OSC + Companion support is unchanged. Prefer either Companion buttons **or** JG Ex Button on a given key, not both.

## Bridge protocol (JSON over WebSocket)

Plugin → GEX: `hello`, `device`, `willAppear`, `willDisappear`, `keyDown`, `keyUp`, `dialRotate`, `dialDown`, `dialUp`  
GEX → Plugin: `hello_ack`, `status`, `command` (`changePage`, plus legacy `setTitle` / `setImage` / `setState` / `showOk` / `showAlert` / `switchToProfile`)
