# Stream Deck plugin for Joystick Gremlin Ex

Two-way bridge between **Elgato Stream Deck software** and **Joystick Gremlin Ex**.
Stream Deck software keeps USB ownership (Wave Link / multi-deck safe). Companion/OSC is not required for these keys.

GEX uses a **Companion-style** model: unlimited virtual pages (banks) live in GremlinEx; the physical deck is a viewport of JG Ex Button / Dial slots that get painted when the active bank changes.

## Install the plugin

Requires **Stream Deck software 6.0+**. The plugin backend is classic HTML/JS (`app.html` → `app.js`); Stream Deck hosts it and injects the WebSocket registration call.

1. Quit Stream Deck software.
2. Copy the folder `com.joystickgremlin.ex.sdPlugin` into the Stream Deck plugins directory, typically:

   `%appdata%\Elgato\StreamDeck\Plugins\`

3. Start Stream Deck software. You should see **Joystick Gremlin Ex** actions: **JG Ex Button** and **JG Ex Dial**.

Optional: zip the `.sdPlugin` folder contents and rename to `.streamDeckPlugin` for double-click install (Elgato packaging).

If the Property Inspector stays on **Connecting…** and Stream Deck's log shows `The plugin has no attached client`, re-copy the folder (ensure `manifest.json` has `"CodePath": "app.html"`) and fully quit/restart Stream Deck.

## Configure GremlinEx

1. Open **Options → Stream Deck**.
2. Enable **Stream Deck bridge** (or use **Install Stream Deck plugin…** first).
3. Bridge port default: **9020** (`ws://127.0.0.1:9020`).
4. Restart tabs / reload if prompted so each **connected Stream Deck** gets its own device tab.

## Map buttons (Companion-style)

1. Fill **one** Elgato profile page with **JG Ex Button** / **Dial** actions (the hardware viewport).
2. In GEX, open that deck’s tab: **pages (left) | grid (center) | actions (right)**.
3. Add unlimited GEX pages; click a grid key to create/edit mappings; use **Map to Stream Deck → Change Page** to switch banks.
4. **Map to Stream Deck → Change Page** switches GEX virtual banks (not limited by Elgato’s ~10 pages).

## Dials (Stream Deck+)

Use **JG Ex Dial**. Rotate pulses INC/DEC-style inputs with autorelease; push sends dial press/release.

## Bridge protocol (summary)

Plugin → GEX: `hello`, `device`, `willAppear` / `willDisappear`, `keyDown` / `keyUp`, dial events.

GEX → Plugin: `hello_ack`, `status`, `command` (`paintPage`, `changePage`, `setTitle`, `setImage`, `setState`, `showOk`, `showAlert`, `syncInputs`).

## Docs

See `docs/streamdeck.md` in the GremlinEx tree.
