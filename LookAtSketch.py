# LookAtSketch - Fusion add-in
# When a NEW sketch opens, turn the camera face-on to the sketch plane and center it on
# the face you picked (its auto-projected outline), ignoring the far-away sketch origin.
#
# Settings: Utilities > Add-Ins > "LookAtSketch Settings" (saved to settings.json next to
# this file). Turn OFF Preferences > General > Design > "Auto look at sketch" so the two
# don't fight.

import adsk.core, adsk.fusion, traceback, threading, math, json, os

ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(ADDIN_DIR, 'settings.json')
RESOURCES_DIR = os.path.join(ADDIN_DIR, 'resources')

# ---- user settings (edit them in Fusion, not here) ---------------------------
DEFAULTS = {
    'enabled': True,          # master on/off switch
    'animate': True,          # smooth camera animation (False = jump instantly)
    'snap_axis': True,        # keep the current view rotation, snapped to the nearest axis
                              # (False = always put the sketch's Y axis up)
    'fit_to_face': False,     # zoom to fit the picked face (False = keep current zoom)
    'margin': 1.3,            # extra room around the face when fitting (1.0 - 3.0)
    'look_at_on_edit': True,  # also look at existing sketches when you edit them
}
S = dict(DEFAULTS)

# ---- internal ----------------------------------------------------------------
POLL_SECONDS = 0.15      # how often to check whether a sketch has opened
SETTLE_TICKS = 2         # wait a moment so Fusion can finish projecting the face edges
MARGIN_MIN, MARGIN_MAX = 1.0, 3.0

EVENT_ID = 'LookAtSketch_Tick'
CMD_ID = 'LookAtSketch_Settings'
WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID = 'SolidScriptsAddinsPanel'

app = None
_handlers = []
_stop = None
_seen = {}          # document -> tokens of sketches that existed before
_pending = None     # [token, ticks] for a sketch waiting to settle
_handled = None     # token of the sketch already handled in this edit session
_logged = False


def _log(msg):
    try:
        app.log('LookAtSketch: ' + msg)
    except Exception:
        pass


# ---- settings file -----------------------------------------------------------

def _load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except Exception:
        _log('could not read settings.json, using defaults')
        return
    for key, default in DEFAULTS.items():
        if key not in data:
            continue
        val = data[key]
        if isinstance(default, bool):
            if isinstance(val, bool):
                S[key] = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            S[key] = min(MARGIN_MAX, max(MARGIN_MIN, float(val)))


def _save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(S, f, indent=2)
        return True
    except Exception:
        _log('could not save settings.json: ' + traceback.format_exc())
        return False


# ---- camera ------------------------------------------------------------------

def _token(sk):
    nat = sk.nativeObject if sk.assemblyContext else sk
    return nat.entityToken


def _known(design):
    doc = app.activeDocument
    key = doc.creationId if doc else 'none'
    if key not in _seen:
        s = set()
        for comp in design.allComponents:
            for sk in comp.sketches:
                s.add(sk.entityToken)
        _seen[key] = s
    return _seen[key]


def _curve_extents(sk):
    """World-space bounding box of the sketch curves (the projected face outline)."""
    mn = [1e30, 1e30, 1e30]
    mx = [-1e30, -1e30, -1e30]
    found = False
    for c in sk.sketchCurves:
        try:
            g = c.worldGeometry
            ev = g.evaluator
            ok, p0, p1 = ev.getParameterExtents()
            if not ok:
                continue
            params = [p0 + (p1 - p0) * i / 16.0 for i in range(17)]
            ok, pts = ev.getPointsAtParameters(params)
            if not ok:
                continue
            for p in pts:
                a = (p.x, p.y, p.z)
                for k in range(3):
                    mn[k] = min(mn[k], a[k])
                    mx[k] = max(mx[k], a[k])
                found = True
        except Exception:
            continue
    return (mn, mx) if found else None


def _snapped_up(cam, x, y, n):
    """Screen 'up' after the smallest rotation that turns the current view face-on to the
    plane (normal n), snapped to the nearest of the sketch's axis directions +-x / +-y."""
    view = cam.eye.vectorTo(cam.target)
    view.normalize()
    to = n.copy(); to.scaleBy(-1.0)            # the camera will look along -n
    up = cam.upVector.copy(); up.normalize()
    k = view.crossProduct(to)
    s = k.length
    c = view.dotProduct(to)
    if s > 1e-9:
        # rotate 'up' by the same rotation that takes 'view' onto 'to' (Rodrigues)
        k.scaleBy(1.0 / s)
        kdu = k.dotProduct(up)
        r = up.copy(); r.scaleBy(c)
        t = k.crossProduct(up); t.scaleBy(s); r.add(t)
        t = k.copy(); t.scaleBy(kdu * (1.0 - c)); r.add(t)
        up = r
    # drop any component along the normal, then snap
    t = n.copy(); t.scaleBy(up.dotProduct(n)); up.subtract(t)
    if up.length < 1e-6:
        return y.copy()
    best, best_dot = y.copy(), -2.0
    for axis in (x, y):
        for sign in (1.0, -1.0):
            d = up.dotProduct(axis) * sign
            if d > best_dot:
                best_dot = d
                best = axis.copy(); best.scaleBy(sign)
    return best


def _look_at(sk):
    x = sk.xDirection.copy(); x.normalize()
    y = sk.yDirection.copy(); y.normalize()
    n = x.crossProduct(y); n.normalize()
    origin = sk.origin
    vp = app.activeViewport
    cam = vp.camera
    up_vec = _snapped_up(cam, x, y, n) if S['snap_axis'] else y
    ext = _curve_extents(sk)
    size = 0.0
    if ext:
        mn, mx = ext
        center = adsk.core.Point3D.create((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2)
        # size of the outline measured along the sketch axes
        corners = []
        for cx in (mn[0], mx[0]):
            for cy in (mn[1], mx[1]):
                for cz in (mn[2], mx[2]):
                    v = origin.vectorTo(adsk.core.Point3D.create(cx, cy, cz))
                    corners.append((v.dotProduct(x), v.dotProduct(y)))
        w = max(c[0] for c in corners) - min(c[0] for c in corners)
        h = max(c[1] for c in corners) - min(c[1] for c in corners)
        size = max(w, h)
    else:
        # no outline: use the point of the plane at the centre of the screen
        d = cam.eye.vectorTo(cam.target)
        denom = d.dotProduct(n)
        if abs(denom) > 1e-9:
            t = cam.eye.vectorTo(origin).dotProduct(n) / denom
            d.scaleBy(t)
            center = cam.eye.copy(); center.translateBy(d)
        else:
            v = origin.vectorTo(cam.target)
            center = cam.target.copy()
            back = n.copy(); back.scaleBy(-v.dotProduct(n)); center.translateBy(back)
    dist = cam.eye.distanceTo(cam.target)
    if S['fit_to_face'] and size > 0:
        span = size * S['margin']
        cam.viewExtents = span
        if cam.cameraType != adsk.core.CameraTypes.OrthographicCameraType:
            ang = cam.perspectiveAngle if cam.perspectiveAngle > 0 else math.radians(30)
            dist = max((span / 2.0) / math.tan(ang / 2.0), span)
    eye = center.copy()
    off = n.copy(); off.scaleBy(dist)
    eye.translateBy(off)
    cam.target = center
    cam.eye = eye
    cam.upVector = up_vec
    cam.isFitView = False
    cam.isSmoothTransition = S['animate']
    vp.camera = cam
    vp.refresh()


class _TickHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        global _pending, _handled, _logged
        try:
            if not S['enabled']:
                _pending = None
                return
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                return
            known = _known(design)
            sk = adsk.fusion.Sketch.cast(app.activeEditObject)
            if not sk:
                _pending = None
                _handled = None
                return
            tok = _token(sk)
            if tok == _handled:
                return
            if tok in known and not S['look_at_on_edit']:
                _handled = tok
                return
            if _pending is None or _pending[0] != tok:
                _pending = [tok, 0]
                return
            _pending[1] += 1
            if _pending[1] < SETTLE_TICKS:
                return
            _look_at(sk)
            known.add(tok)
            _handled = tok
            _pending = None
        except Exception:
            if not _logged:
                _log(traceback.format_exc())
                _logged = True


class _Worker(threading.Thread):
    def __init__(self, stop_event):
        super().__init__(daemon=True)
        self._stop_event = stop_event

    def run(self):
        while not self._stop_event.wait(POLL_SECONDS):
            try:
                app.fireCustomEvent(EVENT_ID, '')
            except Exception:
                pass


# ---- settings dialog ---------------------------------------------------------

def _refresh_inputs(inputs):
    on = inputs.itemById('enabled').value
    fit = inputs.itemById('fit_to_face').value
    inputs.itemById('animate').isEnabled = on
    inputs.itemById('snap_axis').isEnabled = on
    inputs.itemById('fit_to_face').isEnabled = on
    inputs.itemById('margin').isEnabled = on and fit
    inputs.itemById('look_at_on_edit').isEnabled = on


class _SettingsCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = adsk.core.CommandCreatedEventArgs.cast(args).command
            cmd.isExecutedWhenPreEmpted = False
            cmd.okButtonText = 'Save'
            inputs = cmd.commandInputs
            inputs.addBoolValueInput('enabled', 'Enabled', True, '', S['enabled'])
            inputs.addBoolValueInput('animate', 'Animate camera', True, '', S['animate'])
            a = inputs.addBoolValueInput('snap_axis', 'Snap to nearest axis', True, '',
                                         S['snap_axis'])
            a.tooltip = ('Keep your current view rotation, snapped to the nearest axis. '
                         'Off always puts the sketch\'s Y axis up.')
            e = inputs.addBoolValueInput('look_at_on_edit', 'On sketch edit', True, '',
                                         S['look_at_on_edit'])
            e.tooltip = 'Also look at existing sketches when you edit them.'
            z = inputs.addBoolValueInput('fit_to_face', 'Auto zoom', True, '', S['fit_to_face'])
            z.tooltip = 'Zoom to fit the picked face. Off keeps your current zoom level.'
            m = inputs.addFloatSpinnerCommandInput('margin', 'Zoom margins', '',
                                                   MARGIN_MIN, MARGIN_MAX, 0.1, S['margin'])
            m.tooltip = 'Extra room around the face when zooming to fit. 1.0 = tight.'
            note = inputs.addTextBoxCommandInput(
                'note', '',
                '<b>Important:</b> for this add-in to work correctly, you must disable '
                'Fusion\'s auto look feature. Turn off the setting at '
                '<b>Preferences &gt; General &gt; Design &gt; Auto look at sketch</b>.', 4, True)
            note.isFullWidth = True
            _refresh_inputs(inputs)

            on_change = _SettingsChanged()
            cmd.inputChanged.add(on_change)
            _handlers.append(on_change)
            on_exec = _SettingsExecute()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
        except Exception:
            _log(traceback.format_exc())


class _SettingsChanged(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            ev = adsk.core.InputChangedEventArgs.cast(args)
            if ev.input.id in ('enabled', 'fit_to_face'):
                _refresh_inputs(ev.inputs)
        except Exception:
            _log(traceback.format_exc())


class _SettingsExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            for key in ('enabled', 'animate', 'snap_axis', 'fit_to_face', 'look_at_on_edit'):
                S[key] = bool(inputs.itemById(key).value)
            S['margin'] = min(MARGIN_MAX, max(MARGIN_MIN, float(inputs.itemById('margin').value)))
            if _save_settings():
                _log('settings saved')
        except Exception:
            _log(traceback.format_exc())


def _add_ui():
    ui = app.userInterface
    old = ui.commandDefinitions.itemById(CMD_ID)
    if old:
        old.deleteMe()
    res = RESOURCES_DIR if os.path.isdir(RESOURCES_DIR) else ''
    cd = ui.commandDefinitions.addButtonDefinition(
        CMD_ID, 'LookAtSketch Settings',
        'Settings for the LookAtSketch add-in: on/off, animation, sketch edit and auto zoom.',
        res)
    h = _SettingsCreated()
    cd.commandCreated.add(h)
    _handlers.append(h)
    ws = ui.workspaces.itemById(WORKSPACE_ID)
    panel = ws.toolbarPanels.itemById(PANEL_ID) if ws else None
    if panel:
        ctrl = panel.controls.itemById(CMD_ID)
        if ctrl:
            ctrl.deleteMe()
        ctrl = panel.controls.addCommand(cd)
        ctrl.isPromoted = True


def _remove_ui():
    ui = app.userInterface
    ws = ui.workspaces.itemById(WORKSPACE_ID)
    panel = ws.toolbarPanels.itemById(PANEL_ID) if ws else None
    if panel:
        ctrl = panel.controls.itemById(CMD_ID)
        if ctrl:
            ctrl.deleteMe()
    cd = ui.commandDefinitions.itemById(CMD_ID)
    if cd:
        cd.deleteMe()


# ---- add-in entry points -----------------------------------------------------

def run(context):
    global app, _stop
    app = adsk.core.Application.get()
    _load_settings()
    try:
        ev = app.registerCustomEvent(EVENT_ID)
        h = _TickHandler()
        ev.add(h)
        _handlers.append(h)
        _stop = threading.Event()
        _Worker(_stop).start()
    except Exception:
        _log(traceback.format_exc())
    try:
        _add_ui()
    except Exception:
        _log('could not add the settings button: ' + traceback.format_exc())
    _log('started')


def stop(context):
    try:
        if _stop:
            _stop.set()
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    try:
        _remove_ui()
    except Exception:
        pass
    _log('stopped')
