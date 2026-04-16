import time

import carb.input
import omni.appwindow
import omni.usd
from pxr import Gf, UsdGeom


# Module-level state for this Script Node instance.
_STATE = {
    "current_index": 0,
    "desired_index": 0,
    "is_moving": False,
    "move_speed": 0.30,
    "epsilon": 0.01,
    "keyboard": None,
    "keyboard_sub": None,
    "last_time": None,
    "did_warn_no_prim": False,
    "did_log_first_compute": False,
    "last_heartbeat": 0.0,
}

# Default robot stops from your original gantry robot behavior.
_DEFAULT_ROBOT_POSITIONS = [
    Gf.Vec3d(3.00, 0.80, 4.00),   # J
    Gf.Vec3d(3.00, 0.00, 4.00),   # K
    Gf.Vec3d(3.00, -1.30, 4.00),  # L
    Gf.Vec3d(3.00, -2.20, 4.00),  # ;
]


def _get_input(db, name, default):
    try:
        value = getattr(db.inputs, name)
        return default if value is None else value
    except Exception:
        return default


def _as_vec3(value, default):
    if isinstance(value, Gf.Vec3d):
        return value
    if isinstance(value, Gf.Vec3f):
        return Gf.Vec3d(float(value[0]), float(value[1]), float(value[2]))
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return Gf.Vec3d(float(value[0]), float(value[1]), float(value[2]))
    return default


def _get_location(prim):
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        op_name = op.GetOpName()
        if op_name == "xformOp:translate":
            return op.Get()
        if op_name == "xformOp:transform":
            transform_matrix = op.Get()
            return Gf.Transform(transform_matrix).GetTranslation()

    translate_op = xformable.AddXformOp(UsdGeom.XformOp.TypeTranslate, UsdGeom.XformOp.PrecisionDouble)
    default_translation = Gf.Vec3d(0.0, 0.0, 0.0)
    translate_op.Set(default_translation)
    return default_translation


def _set_location(prim, location):
    xformable = UsdGeom.Xformable(prim)
    for op in xformable.GetOrderedXformOps():
        op_name = op.GetOpName()
        if op_name == "xformOp:translate":
            op.Set(location)
            return True
        if op_name == "xformOp:transform":
            transform_matrix = op.Get()
            transform = Gf.Transform(transform_matrix)
            transform.SetTranslation(location)
            op.Set(transform.GetMatrix())
            return True

    return False


def _resolve_positions(db):
    use_custom = bool(_get_input(db, "useCustomPositions", False))
    if not use_custom:
        return _DEFAULT_ROBOT_POSITIONS

    return [
        _as_vec3(_get_input(db, "positionJ", _DEFAULT_ROBOT_POSITIONS[0]), _DEFAULT_ROBOT_POSITIONS[0]),
        _as_vec3(_get_input(db, "positionK", _DEFAULT_ROBOT_POSITIONS[1]), _DEFAULT_ROBOT_POSITIONS[1]),
        _as_vec3(_get_input(db, "positionL", _DEFAULT_ROBOT_POSITIONS[2]), _DEFAULT_ROBOT_POSITIONS[2]),
        _as_vec3(_get_input(db, "positionSemicolon", _DEFAULT_ROBOT_POSITIONS[3]), _DEFAULT_ROBOT_POSITIONS[3]),
    ]


def _resolve_target_prim(db, stage, default_path):
    candidate_paths = []

    prim_path_input = str(_get_input(db, "primPath", default_path))
    if prim_path_input:
        candidate_paths.append(prim_path_input)

    try:
        selected = omni.usd.get_context().get_selection().get_selected_prim_paths()
        candidate_paths.extend(selected)
    except Exception:
        pass

    seen = set()
    for path in candidate_paths:
        if not path or path in seen:
            continue
        seen.add(path)

        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid() and prim.IsA(UsdGeom.Xformable):
            return prim, path

    return None, prim_path_input


def _on_keyboard_event(event, *args, **kwargs):
    if event.type != carb.input.KeyboardEventType.KEY_PRESS:
        return True

    if event.input == carb.input.KeyboardInput.J:
        _STATE["desired_index"] = 0
    elif event.input == carb.input.KeyboardInput.K:
        _STATE["desired_index"] = 1
    elif event.input == carb.input.KeyboardInput.L:
        _STATE["desired_index"] = 2
    elif event.input == carb.input.KeyboardInput.SEMICOLON:
        _STATE["desired_index"] = 3
    else:
        return True

    if _STATE["desired_index"] != _STATE["current_index"]:
        _STATE["is_moving"] = True
        carb.log_info(
            f"[scriptnode_gantry_robot] key press -> desired_index={_STATE['desired_index']} "
            f"from current_index={_STATE['current_index']}"
        )

    return True


def _subscribe_keyboard(db):
    appwindow = omni.appwindow.get_default_app_window()
    if appwindow is None:
        db.log_warning("No default app window available; keyboard control disabled.")
        return

    input_interface = carb.input.acquire_input_interface()
    keyboard = appwindow.get_keyboard()

    _STATE["keyboard"] = keyboard
    _STATE["keyboard_sub"] = input_interface.subscribe_to_keyboard_events(keyboard, _on_keyboard_event)


def _unsubscribe_keyboard():
    if _STATE["keyboard_sub"] is None:
        return

    input_interface = carb.input.acquire_input_interface()
    input_interface.unsubscribe_to_keyboard_events(_STATE["keyboard"], _STATE["keyboard_sub"])
    _STATE["keyboard_sub"] = None
    _STATE["keyboard"] = None


def setup(db):
    _STATE["current_index"] = 0
    _STATE["desired_index"] = 0
    _STATE["is_moving"] = False
    _STATE["move_speed"] = float(_get_input(db, "moveSpeed", 0.30))
    _STATE["epsilon"] = float(_get_input(db, "arrivalThreshold", 0.01))
    _STATE["last_time"] = time.monotonic()
    _STATE["did_warn_no_prim"] = False
    _STATE["did_log_first_compute"] = False
    _STATE["last_heartbeat"] = 0.0

    db.log_warning("[scriptnode_gantry_robot] setup() executed. Waiting for compute ticks.")

    _subscribe_keyboard(db)


def cleanup(db):
    _unsubscribe_keyboard()
    _STATE["is_moving"] = False


def compute(db):
    now = time.monotonic()

    if not _STATE["did_log_first_compute"]:
        db.log_warning("[scriptnode_gantry_robot] compute() is running.")
        _STATE["did_log_first_compute"] = True

    debug_heartbeat = bool(_get_input(db, "debugHeartbeat", False))
    if debug_heartbeat and (now - _STATE["last_heartbeat"]) >= 1.0:
        carb.log_info(
            f"[scriptnode_gantry_robot] heartbeat: current_index={_STATE['current_index']} "
            f"desired_index={_STATE['desired_index']} is_moving={_STATE['is_moving']}"
        )
        _STATE["last_heartbeat"] = now

    enabled = bool(_get_input(db, "enabled", True))
    if not enabled:
        return True

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        db.log_warning("USD stage is not available.")
        return True

    prim, resolved_path = _resolve_target_prim(db, stage, "/World/Robot")
    if prim is None:
        if not _STATE["did_warn_no_prim"]:
            db.log_warning(
                f"No valid Xformable target prim found. primPath='{resolved_path}'. "
                "Set db.inputs.primPath to your robot prim path or select a prim in the stage."
            )
            _STATE["did_warn_no_prim"] = True
        return True
    _STATE["did_warn_no_prim"] = False

    positions = _resolve_positions(db)

    input_target_index = int(_get_input(db, "targetIndex", -1))
    if 0 <= input_target_index < len(positions):
        _STATE["desired_index"] = input_target_index
        if _STATE["desired_index"] != _STATE["current_index"]:
            _STATE["is_moving"] = True

    if not _STATE["is_moving"]:
        return True

    delta_time = float(_get_input(db, "deltaTime", 0.0))
    if delta_time <= 0.0:
        if _STATE["last_time"] is None:
            _STATE["last_time"] = now
            return True
        delta_time = now - _STATE["last_time"]
    _STATE["last_time"] = now

    target = positions[_STATE["desired_index"]]
    current = _get_location(prim)
    direction = target - current
    distance = direction.GetLength()

    if distance <= _STATE["epsilon"]:
        _set_location(prim, target)
        _STATE["current_index"] = _STATE["desired_index"]
        _STATE["is_moving"] = False
        return True

    direction.Normalize()
    step = min(_STATE["move_speed"] * max(delta_time, 0.0), distance)
    new_pos = current + direction * step
    _set_location(prim, new_pos)

    return True
