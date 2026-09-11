# Overlay

The Overlay tab draws live physical, vJoy, and GEX state inputs on either a chromakey (or image) window for OBS, or a transparent on-screen HUD. It replaces a Touch OSC + OSC round-trip when you only need a joystick overlay.

## Enable it on a profile

Open the **Overlay** tab (next to Settings and Plugins). Each GEX profile has its own overlay; switching profiles loads that profile’s layout. The tab title shows the active profile name.

Layouts are stored in the profile’s companion JSON (`<profile>.json`, key `obs_overlay`). An optional `<profile>.overlay.json` sidecar is also written so you can import/export layouts. Saving the GEX profile saves the overlay with it.

A user plugin is **not** required. [`user_plugins/obs_overlay.py`](../user_plugins/obs_overlay.py) only adds a Plugins-tab button that jumps to Overlay.

## Background modes

### Chroma / image (OBS)

1. Set **Background** to **chroma** or **image**.
2. Click **Show overlay** (window title `GEX Overlay`).
3. In OBS, add a **Window Capture** source for `GEX Overlay`.
4. For chroma, add a **Chroma Key** filter. The default key color is `#00FF00`.
5. Hide the overlay drag bar (right-click the overlay, or uncheck **Overlay drag bar**) before going live.

A background **image** can be used instead of chroma if you want a static HUD plate.

### On-screen HUD

1. Set **Background** to **on-screen**.
2. Pick the **Monitor**. The canvas width and height update to that monitor’s resolution.
3. Click **Show overlay** (or enable **Show at profile start**). The overlay covers that monitor, stays on top, and is click-through so games keep mouse and keyboard focus.

Use **Hide overlay** on the Overlay tab to close an on-screen HUD (it does not accept clicks).

## Profile start

Check **Show at profile start** on the Overlay tab. Activating the profile opens the overlay automatically and hides it when the profile stops.

**Toggle overlay** (Canvas) assigns a physical, vJoy, or GEX state input the same way widget bindings do: pick a device or click **Listen...**, then choose axis, button, or hat. While the profile is running, a press (or an axis crossing 0.5) shows or hides the overlay. This works whether or not Show at profile start is on.

## Designer

- **Palette:** click to add a widget at the center of the current canvas view. If a widget is already selected, the click changes it to this type and keeps compatible settings (geometry, colors, fonts, and bindings when they still apply).
- **Templates:** dual-stick HUD, Xbox-style gamepad, throttle pair. **Save template** stores the current widgets globally under the GEX data folder (`overlay_templates/`), not in the profile. An empty canvas is the default for a new profile. Built-in templates are click-to-apply only. Right-click a **saved** template to overwrite it with the current widgets and properties, or to delete it.
- Drag, resize, snap-to-grid, Shift+click multi-select. Right-click selected widgets to duplicate, delete, bring forward, send backward, group, or ungroup. Delete, Ctrl+D, Ctrl+G / Ctrl+Shift+G, Ctrl+Z, and arrow-key nudge still work. Widgets that sit outside a smaller canvas (after a resize or leaving on-screen mode) stay visible in the dark overflow area and can be dragged back; the live overlay still only shows what is on the canvas.
- Inspector **Geometry** includes **Scale font with size**. Appearance groups **Grid** (show, color, line width, fade at border) and **Crosshairs** (show + color) for X/Y widgets. Grids reach the widget border; **Fade at border** tapers them toward the edge.
- **Shape** replaces Panel: rectangle, circle, triangle, diamond, line, or freeform. Freeform points are added by double-clicking the outline; drag a point, then drag its yellow handles to Bézier-curve that corner. Uncheck **Closed** for an open path.
- **Image** is a separate palette widget. Browse to a PNG, WebP, GIF, JPEG, or BMP. Formats with an alpha channel keep their transparency; Fill is only a backdrop behind those pixels. **Keep aspect ratio** (on by default) fits the picture in the widget instead of stretching it.
- Inspector: size, colors, fonts, line/dot sizes, labels (including fill and border), invert, deadzone, and binding. Selecting a **group** (or multiple widgets) shows only shared properties; edits apply to every selected widget. With **Scale font with size** on, Font size shows the size currently drawn and updates while you resize the widget.
- **Guides** (Canvas): add vertical and/or horizontal lines, set a color, drag them on the canvas, or type a percent of width/height. Moving or resizing a widget snaps its left/right/center (or top/bottom/center) to nearby guides.
- **Color palettes** sit at the top of Appearance as two rows: built-in defaults (click to apply) and user palettes. They are per widget type and stored globally (`overlay_color_palettes.json` in the GEX data folder), not in the profile. **+** saves the current colors as a user square. Right-click a user square to overwrite it or delete it. Default palettes cannot be changed. Transparent fills show as a square with a cross. Built-in squares: default, Touch OSC (red), transparent green.

Widget mapping (Touch OSC-style names in the palette):

| Palette | What it is |
|---|---|
| Bar | 1D pad with a moving dot (horizontal or vertical), same language as the X/Y square |
| Radio | Stepped cells along one axis |
| Fader | Ladder track, fill below the thumb, and a sliding thumb |
| Radial | 270° arc with ticks |
| Encoder | Full donut with ticks and one moving highlighted wedge |
| X/Y | 2D square pad; optional lines through the dot, circle/square dot, shadow |
| Radar | Concentric rings, a beam from the center, and a circle through the current position; optional 15/30/45° angle lines |
| Circular | Round 2D pad; optional angle lines |
| Shape | Rectangle, circle, triangle, diamond, line, or freeform Bézier path |
| Image | Custom picture; PNG/WebP/GIF keep transparency |

## Bindings

Each widget (except labels, shapes, and images) can bind to:

- a **physical** device axis, button, or hat (use **Listen...** or pick from the lists)
- a **vJoy** axis, button, or hat
- a named GEX **state**

2D sticks and the radar widget have **two independent bindings** (Axis X and Axis Y). Each axis has its own device and axis picker (or Listen). You can mix devices — for example physical X on a stick and vJoy Y on another device.

## Notes

- For OBS, capture **GEX Overlay**, not the Overlay tab.
- Layouts are per profile. Saving the layout or the GEX profile writes the overlay into that profile’s config (and a sidecar JSON). **Load layout...** imports a JSON file into the current profile.
- Axis labels (N/S/E/W) have their own font, size, weight, and color in the inspector.
- **Deadzone display** is overlay-only. Axis values inside that range around center are drawn as zero; it does not change GEX mappings.
- Photoreal HOTAS meshes, DJ decks, and an OBS Browser Source path are not in this version.
