# LookAtSketch – a Fusion add-in

When you start a new sketch on a face, Fusion's built-in "Auto look at sketch" turns the
view face-on but centers it on the origin.
If your part sits far from its component's origin, the camera flies
away from the face you just clicked.

This add-in replaces that behavior: when a **new** sketch opens, it turns the camera
face-on to the sketch plane and centers on the **face you picked** (optionally zooming to
fit it). It does the same when you edit an existing sketch.

## Download

The .zip file can be downloaded from the releases page, or by clicking this [link]().

## Install

1. Unzip. You get a folder called `LookAtSketch`.
2. In Fusion, press **Shift+S** (Utilities → Scripts and Add-Ins) and open the **Add-Ins** tab.
3. Click **+** → **Script or add-in from device** and select the `LookAtSketch` folder.
   - Alternatively, copy the folder into Fusion's add-in folder:
     - **macOS:** `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`
     - **Windows:** `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`
4. Select **LookAtSketch** in the list and click **Run**. Tick **Run on Startup** if it
   isn't already ticked, so it starts with Fusion every time.
5. **Important:** for this add-in to work correctly, you must disable Fusion's own auto look
   feature: **Preferences → General → Design → Auto look at sketch** → off.

## Settings

In Fusion, go to the **Utilities** tab → **Add-Ins** panel → **LookAtSketch Settings**.
Changes apply as soon as you click **Save**, with no restart.

| Setting | Default | What it does |
|---|---|---|
| Enabled | on | Master switch. Turn off to pause the add-in without stopping it. |
| Animate camera | on | Smooth camera animation. Off jumps to the face instantly. |
| Snap to nearest axis | on | Keeps your current view rotation, snapped to the nearest axis, so the view doesn't spin to put a fixed axis up. Off always puts the sketch's Y axis up. |
| On sketch edit | on | Also turns the view when you edit an existing sketch. |
| Auto zoom | off | Zoom to fit the picked face. Off keeps your current zoom level. |
| Zoom margins | 1.3 | Extra room around the face when zooming to fit (1.0 = tight, up to 3.0). |

## Notes and limitations

- Centering uses the face outline that Fusion projects into a new sketch
  (**Preferences → General → Design → "Auto project edges on reference"**, on by default).
  If that is off, the add-in centers on the point of the sketch plane in the middle of the
  screen instead, and keeps your zoom.
- Sketches on construction planes have no outline, so they get the same fallback.
- Nothing in your design is changed; the add-in only moves the camera.
- Errors, if any, are written to Fusion's **Text Commands** window
  (View → Show Text Commands), prefixed with `LookAtSketch:`.

## Uninstall

Shift+S → Add-Ins → select **LookAtSketch** → **Stop** (this also removes the settings
button), untick **Run on Startup**, then remove it with the **–** button or delete the folder.

Written for Autodesk Fusion (build 2705), Windows and macOS.
