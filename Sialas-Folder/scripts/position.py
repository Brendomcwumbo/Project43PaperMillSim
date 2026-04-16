"""
OmniGraph Script Node for optionally clipping a plug to a gripper.

Expected node pins:
- Inputs:
    - enabled: bool
    - gripper_path: string
    - plug_path: string
    - offset_z: double
    - compute_every_n_ticks: int
"""

from pxr import Gf, Usd, UsdGeom
import omni.usd

_tick_counter = 0
_cached_gripper_prim = None
_cached_plug_prim = None
_cached_transform_op = None
_cached_gripper_path = ""
_cached_plug_path = ""
_last_gripper_pos = None
_motion_threshold = 0.001


def setup(db):
    """Called once when the Script Node is created or reset."""
    global _tick_counter, _cached_gripper_prim, _cached_plug_prim, _cached_transform_op, _last_gripper_pos
    _tick_counter = 0
    _cached_gripper_prim = None
    _cached_plug_prim = None
    _cached_transform_op = None
    _last_gripper_pos = None


def cleanup(db):
    """Called when the Script Node is destroyed."""
    pass


def _get_input(db, name, default_value):
    try:
        return getattr(db.inputs, name)
    except Exception:
        return default_value


def compute(db):
    """Called every evaluation tick."""
    global _tick_counter, _cached_gripper_prim, _cached_plug_prim, _cached_transform_op
    global _cached_gripper_path, _cached_plug_path, _last_gripper_pos, _motion_threshold

    enabled = bool(_get_input(db, "enabled", True))
    gripper_path = str(_get_input(db, "gripper_path", "/World/PlugBot/rs013n_onrobot_rg2/rs013n_onrobot_rg2/rs013n_onrobot_rg2/Robotiq_2F_85_edit/Robotiq_2F_85_edit/Robotiq_2F_85/right_inner_finger"))
    plug_path = str(_get_input(db, "plug_path", "/factory_01/plugdispenser/Paper_Plug/Paper_Plug"))
    offset_z = float(_get_input(db, "offset_z", 5.0))
    compute_every_n_ticks = max(1, int(_get_input(db, "compute_every_n_ticks", 6)))

    _tick_counter += 1
    if _tick_counter % compute_every_n_ticks != 0:
        return True

    if not enabled:
        return True

    stage = omni.usd.get_context().get_stage()
    if not stage:
        db.log_warn("Stage is not valid.")
        return True

    # Cache prim lookups; re-fetch only if path changed
    if gripper_path != _cached_gripper_path or _cached_gripper_prim is None:
        _cached_gripper_prim = stage.GetPrimAtPath(gripper_path)
        _cached_gripper_path = gripper_path
    gripper_prim = _cached_gripper_prim
    if not gripper_prim.IsValid():
        db.log_warn(f"Gripper prim not valid: {gripper_path}")
        return True
    if not gripper_prim.IsA(UsdGeom.Xformable):
        db.log_warn(f"Gripper prim is not xformable: {gripper_path}")
        return True

    gripper_xform = UsdGeom.Xformable(gripper_prim)
    gripper_world_transform = gripper_xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    gripper_pos = gripper_world_transform.ExtractTranslation()

    # Check if gripper has moved significantly
    if _last_gripper_pos is not None:
        delta = (gripper_pos - _last_gripper_pos).GetLength()
        if delta < _motion_threshold:
            return True
    _last_gripper_pos = gripper_pos

    if plug_path != _cached_plug_path or _cached_plug_prim is None:
        _cached_plug_prim = stage.GetPrimAtPath(plug_path)
        _cached_plug_path = plug_path
    plug_prim = _cached_plug_prim
    if not plug_prim.IsValid():
        db.log_warn(f"Plug prim not valid: {plug_path}")
        return True
    if not plug_prim.IsA(UsdGeom.Xformable):
        db.log_warn(f"Plug prim is not xformable: {plug_path}")
        return True

    gripper_xform = UsdGeom.Xformable(gripper_prim)
    gripper_world_transform = gripper_xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())

    offset_transform = Gf.Matrix4d(1.0)
    offset_transform.SetTranslate(Gf.Vec3d(0.0, 0.0, offset_z))
    target_world_transform = gripper_world_transform * offset_transform

    parent_prim = plug_prim.GetParent()
    if parent_prim and parent_prim.IsValid() and parent_prim.GetPath().pathString != "/":
        parent_xform = UsdGeom.Xformable(parent_prim)
        parent_world_transform = parent_xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        plug_target_transform = target_world_transform * parent_world_transform.GetInverse()
    else:
        plug_target_transform = target_world_transform

    plug_xform = UsdGeom.Xformable(plug_prim)
    # Cache and reuse the transform op instead of recreating it every frame
    if _cached_transform_op is None:
        plug_xform.ClearXformOpOrder()
        _cached_transform_op = plug_xform.AddTransformOp()
    _cached_transform_op.Set(plug_target_transform)

    db.log_info(f"Plug clipped to gripper: plug={plug_path}, gripper={gripper_path}")

    return True