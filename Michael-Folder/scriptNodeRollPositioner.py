"""
OmniGraph Script Node — two-stage paper roll locking for paper mill simulation.

Locking is done via a post-update callback (order=9999) that runs AFTER the
conveyor has set transforms for the frame.

compute()    — reads beam inputs and enabled, drives state transitions
_on_update() — registered post-update, overwrites transform when locked

State machine:
  beam_1 rising edge  → FIRST_LOCKED  (snap to position 1)
  enabled True→False  → MOVING        (release, conveyor resumes)
  beam_2 rising edge  → SECOND_LOCKED (snap to position 2)
  enabled True→False  → advance to next roll, back to TRACKING

Roll scheme: /factory_01/sushi_0N/paper, N = 1..5

Node inputs:
  beam_1   bool — IR beam at position 1; True = roll present
  beam_2   bool — IR beam at position 2; True = roll present
  enabled  bool — True→False edge drives release transitions
"""

from pxr import Gf, Usd, UsdGeom
import omni.usd
import omni.timeline
import omni.kit.app
import carb

_TRACKING      = 0
_FIRST_LOCKED  = 1
_MOVING        = 2
_SECOND_LOCKED = 3

_MAX_ROLLS = 5

_LOCK_X_1 = 2.866
_LOCK_X_2 = 4.64
_LOCK_Y   = -6.0
_LOCK_Z   =  2.366
_LOCK_RX  = 160.33
_LOCK_RY  =   0.0
_LOCK_RZ  =   0.0

_roll_index       = 0
_state            = _TRACKING
_last_enabled     = False
_last_beam_1      = False
_last_beam_2      = False
_locked_world_mat = None
_stop_sub         = None
_update_sub       = None


def _roll_path(index):
    return f"/factory_01/sushi_0{index + 1}/paper"


def _make_lock_mat(x, y, z):
    rot = (Gf.Rotation(Gf.Vec3d(1, 0, 0), _LOCK_RX)
           * Gf.Rotation(Gf.Vec3d(0, 1, 0), _LOCK_RY)
           * Gf.Rotation(Gf.Vec3d(0, 0, 1), _LOCK_RZ))
    return Gf.Matrix4d(rot, Gf.Vec3d(x, y, z))


def _pin_to_world_mat(stage, prim, world_mat):
    parent = prim.GetParent()
    if parent.IsValid() and parent.GetPath().pathString != "/":
        parent_world = UsdGeom.Xformable(parent).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default()
        )
        local_mat = world_mat * parent_world.GetInverse()
    else:
        local_mat = world_mat
    xform = UsdGeom.Xformable(prim)
    ops = xform.GetOrderedXformOps()
    if ops and ops[0].GetOpType() == UsdGeom.XformOp.TypeTransform:
        ops[0].Set(local_mat)
    else:
        xform.ClearXformOpOrder()
        xform.AddTransformOp().Set(local_mat)


def _on_update(event):
    if _state not in (_FIRST_LOCKED, _SECOND_LOCKED):
        return
    if _locked_world_mat is None:
        return
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return
    prim = stage.GetPrimAtPath(_roll_path(_roll_index))
    if prim.IsValid():
        _pin_to_world_mat(stage, prim, _locked_world_mat)


def _on_stop(event):
    if event.type != int(omni.timeline.TimelineEventType.STOP):
        return
    global _roll_index, _state, _last_enabled, _last_beam_1, _last_beam_2, _locked_world_mat
    _roll_index       = 0
    _state            = _TRACKING
    _last_enabled     = False
    _last_beam_1      = False
    _last_beam_2      = False
    _locked_world_mat = None


def setup(db):
    global _roll_index, _state, _last_enabled, _last_beam_1, _last_beam_2
    global _locked_world_mat, _stop_sub, _update_sub

    if _stop_sub is None:
        _stop_sub = (
            omni.timeline.get_timeline_interface()
            .get_timeline_event_stream()
            .create_subscription_to_pop(_on_stop, name="roll_positioner_reset")
        )
    if _update_sub is None:
        _update_sub = (
            omni.kit.app.get_app()
            .get_update_event_stream()
            .create_subscription_to_pop(_on_update, name="roll_positioner_pin", order=9999)
        )

    _roll_index       = 0
    _state            = _TRACKING
    _last_enabled     = False
    _last_beam_1      = False
    _last_beam_2      = False
    _locked_world_mat = None
    carb.log_warn(f"[RollPositioner] setup() — tracking {_roll_path(0)}")


def cleanup(db):
    global _stop_sub, _update_sub
    _stop_sub   = None
    _update_sub = None


def _get_input(db, name, default):
    try:
        return getattr(db.inputs, name)
    except Exception:
        return default


def compute(db):
    try:
        return _compute_inner(db)
    except Exception as e:
        carb.log_warn(f"[RollPositioner] ERROR in compute: {e}")
        return True


def _compute_inner(db):
    global _state, _last_enabled, _last_beam_1, _last_beam_2
    global _locked_world_mat, _roll_index

    if _roll_index >= _MAX_ROLLS:
        return True

    enabled  = bool(_get_input(db, "enabled", False))
    beam_1   = bool(_get_input(db, "beam_1",  False))
    beam_2   = bool(_get_input(db, "beam_2",  False))

    just_fell   = not enabled and _last_enabled
    beam_1_rose = beam_1 and not _last_beam_1
    beam_2_rose = beam_2 and not _last_beam_2

    _last_enabled = enabled
    _last_beam_1  = beam_1
    _last_beam_2  = beam_2

    if _state == _TRACKING:
        if beam_1_rose:
            _locked_world_mat = _make_lock_mat(_LOCK_X_1, _LOCK_Y, _LOCK_Z)
            _state = _FIRST_LOCKED
            carb.log_warn(f"[RollPositioner] Roll {_roll_index + 1} beam_1 → FIRST_LOCKED")

    elif _state == _FIRST_LOCKED:
        if just_fell:
            _locked_world_mat = None
            _state = _MOVING
            carb.log_warn(f"[RollPositioner] Roll {_roll_index + 1} released → MOVING")

    elif _state == _MOVING:
        if beam_2_rose:
            _locked_world_mat = _make_lock_mat(_LOCK_X_2, _LOCK_Y, _LOCK_Z)
            _state = _SECOND_LOCKED
            carb.log_warn(f"[RollPositioner] Roll {_roll_index + 1} beam_2 → SECOND_LOCKED")

    elif _state == _SECOND_LOCKED:
        if just_fell:
            _locked_world_mat = None
            _roll_index += 1
            _state = _TRACKING
            carb.log_warn(
                f"[RollPositioner] Roll {_roll_index} done. "
                f"Tracking roll {_roll_index + 1}"
            )

    return True
