"""
OmniGraph Script Node — plug insertion workflow for paper mill simulation.

Pre-creates 10 invisible slot prims in setup() when the stage is stable.
During play, slots are made visible and positioned to follow their roll.
Despawn is triggered by a timeline STOP event subscription (not cleanup(),
which does not fire reliably on sim stop in Isaac Sim).

Lifecycle:
  setup()        — subscribes to timeline stop; creates /World/PlugMill_Inserted/Plug_0..9;
                   hides all slots; resets source puck to spawn.
  compute()      — gripper tracking while enabled=True; on True→False makes the
                   next slot visible at the roll offset and records it for
                   per-tick roll-following. Source puck resets to spawn.
  _on_stop()     — timeline callback: hides all slots when Stop is pressed.
  cleanup()      — unsubscribes; falls back hide in case node is destroyed.

Roll scheme: /factory_01/sushi_0n/paper, n = 1..5
2 insertions per roll (side A then B) = 10 total.

Node inputs:
  enabled               bool   — True = gripper holds puck; False = insert
  gripper_path          string — USD path to gripper prim
  puck_path             string — USD path of the source puck prim
  gripper_offset_x/y/z  double — offset in gripper-local space while held
  side_a_offset_x/y/z   double — roll-local offset for 1st insertion per roll
  side_b_offset_x/y/z   double — roll-local offset for 2nd insertion per roll
  spawn_x/y/z            double — world position where source puck waits
  compute_every_n_ticks  int    — tick throttle (default 6)
"""

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics
import omni.usd
import omni.kit.commands
import omni.timeline

_PUCK_DEFAULT    = "/factory_01/plugdispenser/Paper_Plug/Paper_Plug"
_GRIPPER_DEFAULT = (
    "/World/PlugBot/rs013n_onrobot_rg2/rs013n_onrobot_rg2"
    "/rs013n_onrobot_rg2/Robotiq_2F_85_edit/Robotiq_2F_85_edit"
    "/Robotiq_2F_85/base_link"
)
_CONTAINER    = "/World/PlugMill_Inserted"
_MAX_SLOTS    = 10   # 5 rolls × 2 sides

_tick_counter        = 0
_cached_gripper_prim = None
_cached_puck_prim    = None
_cached_transform_op = None
_cached_gripper_path = ""
_cached_puck_path    = ""
_last_gripper_pos    = None
_motion_threshold    = 0.001
_last_enabled        = False
_insertion_count     = 0
# Each entry: (slot_usd_path, roll_xform_path, ox, oy, oz)
_active_slots        = []
_last_calibrate      = False

# Held reference keeps the subscription alive; set to None to unsubscribe.
_stop_sub = None


# ---------------------------------------------------------------------------
# Timeline stop callback — THE reliable despawn hook
# ---------------------------------------------------------------------------

def _on_stop(event):
    """Fires on every timeline STOP event. Hides all slots and resets session state."""
    if event.type != int(omni.timeline.TimelineEventType.STOP):
        return
    global _active_slots, _insertion_count, _last_enabled
    global _last_gripper_pos, _cached_transform_op, _tick_counter

    stage = omni.usd.get_context().get_stage()
    if stage:
        _hide_all_slots(stage)

    _active_slots        = []
    _insertion_count     = 0
    _last_enabled        = False
    _last_gripper_pos    = None
    _cached_transform_op = None
    _tick_counter        = 0
    _last_calibrate      = False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def setup(db):
    global _tick_counter, _cached_gripper_prim, _cached_puck_prim, _cached_transform_op
    global _cached_gripper_path, _cached_puck_path, _last_gripper_pos
    global _last_enabled, _insertion_count, _active_slots, _stop_sub

    # Subscribe to timeline stop so _on_stop() fires whenever Play is stopped.
    # Guard against double-subscribing across repeated Play/Stop cycles.
    if _stop_sub is None:
        _stop_sub = (
            omni.timeline.get_timeline_interface()
            .get_timeline_event_stream()
            .create_subscription_to_pop(_on_stop, name="plug_mill_cleanup")
        )

    stage = omni.usd.get_context().get_stage()
    if stage:
        puck_path = str(_get_input(db, "puck_path", _PUCK_DEFAULT))
        _ensure_slots(stage, puck_path)
        _hide_all_slots(stage)
        _reset_puck_to_spawn(db, stage, puck_path)
        prim = stage.GetPrimAtPath(puck_path)
        if prim.IsValid():
            _set_collision(prim, False)  # permanently off — puck always tracks something

    _insertion_count     = 0
    _active_slots        = []
    _tick_counter        = 0
    _cached_gripper_prim = None
    _cached_puck_prim    = None
    _cached_transform_op = None
    _cached_gripper_path = ""
    _cached_puck_path    = ""
    _last_gripper_pos    = None
    _last_enabled        = False
    _last_calibrate      = False


def cleanup(db):
    """Unsubscribe and hide slots (fires on node/graph destruction, not Stop)."""
    global _stop_sub, _active_slots
    _stop_sub = None
    stage = omni.usd.get_context().get_stage()
    if stage:
        _hide_all_slots(stage)
    _active_slots = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_input(db, name, default_value):
    try:
        return getattr(db.inputs, name)
    except Exception:
        return default_value


def _slot_path(index):
    return f"{_CONTAINER}/Plug_{index}"


def _ensure_slots(stage, puck_path):
    """Create the container and all 10 slot prims if they don't already exist."""
    if not stage.GetPrimAtPath(_CONTAINER).IsValid():
        UsdGeom.Xform.Define(stage, _CONTAINER)

    for i in range(_MAX_SLOTS):
        path = _slot_path(i)
        if stage.GetPrimAtPath(path).IsValid():
            continue
        try:
            omni.kit.commands.execute("CopyPrimCommand",
                path_from=puck_path, path_to=path)
        except Exception:
            Sdf.CopySpec(stage.GetRootLayer(), Sdf.Path(puck_path),
                         stage.GetRootLayer(), Sdf.Path(path))
        prim = stage.GetPrimAtPath(path)
        if prim.IsValid():
            _disable_physics(prim)
            _set_collision(prim, False)
            UsdGeom.Imageable(prim).MakeInvisible()


def _hide_all_slots(stage):
    """Make every slot invisible — the reliable despawn."""
    container = stage.GetPrimAtPath(_CONTAINER)
    if not container.IsValid():
        return
    for i in range(_MAX_SLOTS):
        prim = stage.GetPrimAtPath(_slot_path(i))
        if prim.IsValid():
            UsdGeom.Imageable(prim).MakeInvisible()


def _set_collision(prim, enabled):
    for p in Usd.PrimRange(prim):
        attr = p.GetAttribute("physics:collisionEnabled")
        if attr.IsValid():
            attr.Set(enabled)


def _disable_physics(prim):
    for p in Usd.PrimRange(prim):
        attr = p.GetAttribute("physics:rigidBodyEnabled")
        if attr.IsValid():
            attr.Set(False)


def _xform_ancestor(stage, prim_path):
    prim = stage.GetPrimAtPath(prim_path)
    while prim.IsValid() and prim.IsA(UsdGeom.Gprim):
        prim = prim.GetParent()
    return str(prim.GetPath()) if prim.IsValid() else prim_path


def _current_roll_path():
    roll_num = (_insertion_count // 2) + 1
    if roll_num > 5:
        return ""
    return f"/factory_01/sushi_0{roll_num}/paper"


def _current_side_offset(db):
    if _insertion_count % 2 == 0:
        return (float(_get_input(db, "side_a_offset_x", 0.0)),
                float(_get_input(db, "side_a_offset_y", 0.0)),
                float(_get_input(db, "side_a_offset_z", 0.635)))
    return (float(_get_input(db, "side_b_offset_x", 0.0)),
            float(_get_input(db, "side_b_offset_y", 0.0)),
            float(_get_input(db, "side_b_offset_z", 0.0)))


def _current_side_rotation(db):
    """Returns (rx, ry, rz) in degrees for the current insertion side."""
    if _insertion_count % 2 == 0:
        return (float(_get_input(db, "side_a_rot_x", 0.0)),
                float(_get_input(db, "side_a_rot_y", 180.0)),
                float(_get_input(db, "side_a_rot_z", 0.0)))
    return (float(_get_input(db, "side_b_rot_x", 0.0)),
            float(_get_input(db, "side_b_rot_y", 0.0)),
            float(_get_input(db, "side_b_rot_z", 0.0)))


def _reset_puck_to_spawn(db, stage, puck_path):
    prim = stage.GetPrimAtPath(puck_path)
    if not prim.IsValid():
        return
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(
        float(_get_input(db, "spawn_x", 0.23901)),
        float(_get_input(db, "spawn_y", 0.0)),
        float(_get_input(db, "spawn_z", -0.85654)),
    ))
    xform.AddRotateXOp().Set(180.0)


def _calibrate(db, stage):
    """Log the puck's current position in roll-local space for offset tuning."""
    t = Usd.TimeCode.Default()
    puck_path = str(_get_input(db, "puck_path", _PUCK_DEFAULT))
    roll_path = _current_roll_path() or "/factory_01/sushi_01/paper"

    puck_prim = stage.GetPrimAtPath(puck_path)
    roll_prim = stage.GetPrimAtPath(roll_path)

    if not puck_prim.IsValid() or not roll_prim.IsValid():
        db.log_warn(f"[CALIBRATE] puck or roll prim not found — puck={puck_path}  roll={roll_path}")
        return

    puck_world = UsdGeom.Xformable(puck_prim).ComputeLocalToWorldTransform(t)
    roll_world = UsdGeom.Xformable(roll_prim).ComputeLocalToWorldTransform(t)
    offset = (puck_world * roll_world.GetInverse()).ExtractTranslation()

    side = "side_a" if _insertion_count % 2 == 0 else "side_b"
    db.log_warn(
        f"[CALIBRATE] roll={roll_path}  {side}: "
        f"x={offset[0]:.5f}  y={offset[1]:.5f}  z={offset[2]:.5f}"
    )


def _activate_slot(db, stage, puck_path):
    """Make the next slot visible at the current roll offset, record for tracking."""
    global _insertion_count, _active_slots, _cached_transform_op

    if _insertion_count >= _MAX_SLOTS:
        return

    roll_path  = _current_roll_path()
    if not roll_path:
        return

    offset = _current_side_offset(db)
    rot    = _current_side_rotation(db)
    path   = _slot_path(_insertion_count)
    prim   = stage.GetPrimAtPath(path)

    if prim and prim.IsValid():
        UsdGeom.Imageable(prim).MakeVisible()
        _active_slots.append((path, roll_path,
                               offset[0], offset[1], offset[2],
                               rot[0], rot[1], rot[2]))

    _reset_puck_to_spawn(db, stage, puck_path)
    _cached_transform_op = None
    _insertion_count    += 1


def _update_active_slots(stage):
    """Reposition each visible slot to stay at its roll offset."""
    t = Usd.TimeCode.Default()
    for (path, roll_xform_path, ox, oy, oz, rx, ry, rz) in _active_slots:
        slot_prim = stage.GetPrimAtPath(path)
        roll_prim = stage.GetPrimAtPath(roll_xform_path)
        if not slot_prim.IsValid() or not roll_prim.IsValid():
            continue
        roll_world = UsdGeom.Xformable(roll_prim).ComputeLocalToWorldTransform(t)
        rot = (Gf.Rotation(Gf.Vec3d(1, 0, 0), rx)
               * Gf.Rotation(Gf.Vec3d(0, 1, 0), ry)
               * Gf.Rotation(Gf.Vec3d(0, 0, 1), rz))
        offset_mat = Gf.Matrix4d(rot, Gf.Vec3d(ox, oy, oz))
        target_world = offset_mat * roll_world

        # Convert world transform to local space relative to the container prim
        parent = slot_prim.GetParent()
        if parent.IsValid() and parent.GetPath().pathString != "/":
            parent_world = UsdGeom.Xformable(parent).ComputeLocalToWorldTransform(t)
            target = target_world * parent_world.GetInverse()
        else:
            target = target_world

        xform = UsdGeom.Xformable(slot_prim)
        ops   = xform.GetOrderedXformOps()
        if ops and ops[0].GetOpType() == UsdGeom.XformOp.TypeTransform:
            ops[0].Set(target)
        else:
            xform.ClearXformOpOrder()
            xform.AddTransformOp().Set(target)


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------

def compute(db):
    global _tick_counter, _cached_gripper_prim, _cached_puck_prim, _cached_transform_op
    global _cached_gripper_path, _cached_puck_path, _last_gripper_pos, _motion_threshold
    global _last_enabled, _last_calibrate

    enabled       = bool(_get_input(db, "enabled", True))
    just_enabled  = enabled and not _last_enabled
    just_disabled = not enabled and _last_enabled
    _last_enabled = enabled

    # Calibrate: rising edge on 'calibrate' input prints roll-local offset to console
    calibrate = bool(_get_input(db, "calibrate", False))
    if calibrate and not _last_calibrate:
        stage = omni.usd.get_context().get_stage()
        if stage:
            _calibrate(db, stage)
    _last_calibrate = calibrate

    if just_enabled:
        _last_gripper_pos = None

    if just_disabled and _insertion_count < _MAX_SLOTS:
        stage = omni.usd.get_context().get_stage()
        puck_path = str(_get_input(db, "puck_path", _PUCK_DEFAULT))
        if stage:
            _calibrate(db, stage)  # log offset at moment of release
            if _cached_puck_prim and _cached_puck_prim.IsValid():
                _activate_slot(db, stage, puck_path)

    if not enabled and not _active_slots:
        return True

    _tick_counter += 1
    if _tick_counter % max(1, int(_get_input(db, "compute_every_n_ticks", 1))) != 0:
        return True

    stage = omni.usd.get_context().get_stage()
    if not stage:
        return True

    if _active_slots:
        _update_active_slots(stage)

    if not enabled or _insertion_count >= _MAX_SLOTS:
        return True

    # --- Gripper tracking ---
    gripper_path = str(_get_input(db, "gripper_path", _GRIPPER_DEFAULT))
    puck_path    = str(_get_input(db, "puck_path",    _PUCK_DEFAULT))
    offset_x     = float(_get_input(db, "gripper_offset_x", 0.0))
    offset_y     = float(_get_input(db, "gripper_offset_y", 0.0))
    offset_z     = float(_get_input(db, "gripper_offset_z", 0.13))

    if gripper_path != _cached_gripper_path or _cached_gripper_prim is None:
        _cached_gripper_prim = stage.GetPrimAtPath(gripper_path)
        _cached_gripper_path = gripper_path
    gripper_prim = _cached_gripper_prim

    if not gripper_prim.IsValid() or not gripper_prim.IsA(UsdGeom.Xformable):
        db.log_warn(f"Gripper prim not valid: {gripper_path}")
        return True

    gripper_world_xf = (
        UsdGeom.Xformable(gripper_prim)
        .ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    )
    gripper_pos = gripper_world_xf.ExtractTranslation()

    if _last_gripper_pos is not None:
        if (gripper_pos - _last_gripper_pos).GetLength() < _motion_threshold:
            return True
    _last_gripper_pos = gripper_pos

    if puck_path != _cached_puck_path or _cached_puck_prim is None:
        _cached_puck_prim = stage.GetPrimAtPath(puck_path)
        _cached_puck_path = puck_path
        _cached_transform_op = None
    puck_prim = _cached_puck_prim

    if not puck_prim.IsValid() or not puck_prim.IsA(UsdGeom.Xformable):
        db.log_warn(f"Puck prim not found at '{puck_path}'. "
                    f"Check puck_path in the Stage panel.")
        return True

    offset_matrix = Gf.Matrix4d(1.0)
    offset_matrix.SetTranslate(Gf.Vec3d(offset_x, offset_y, offset_z))
    target_world = offset_matrix * gripper_world_xf

    parent_prim = puck_prim.GetParent()
    if parent_prim and parent_prim.IsValid() and parent_prim.GetPath().pathString != "/":
        parent_world = (
            UsdGeom.Xformable(parent_prim)
            .ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        )
        puck_target = target_world * parent_world.GetInverse()
    else:
        puck_target = target_world

    puck_xform = UsdGeom.Xformable(puck_prim)
    if _cached_transform_op is None:
        puck_xform.ClearXformOpOrder()
        _cached_transform_op = puck_xform.AddTransformOp()
    _cached_transform_op.Set(puck_target)

    return True
