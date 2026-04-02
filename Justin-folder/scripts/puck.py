import carb
import omni.kit.window.property
from isaacsim.replicator.behavior.global_variables import EXPOSED_ATTR_NS
from isaacsim.replicator.behavior.utils.behavior_utils import (
    create_exposed_variables,
)
from omni.kit.scripting import BehaviorScript
from pxr import Gf, Sdf, UsdGeom


class PuckRespawner(BehaviorScript):
    """
    Behavior script that respawns a puck at a fixed location every fixed interval.
    The puck prim must already exist in the scene.
    """

    BEHAVIOR_NS = "puckRespawner"
    VARIABLES_TO_EXPOSE = [
        {
            "attr_name": "interval",
            "attr_type": Sdf.ValueTypeNames.Float,
            "default_value": 5.0,
            "doc": "Time interval in seconds to respawn the puck.",
        },
        {
            "attr_name": "spawnLocation",
            "attr_type": Sdf.ValueTypeNames.Vector3d,
            "default_value": Gf.Vec3d(1, 3, 3),
            "doc": "Fixed spawn location for the puck.",
        },
        {
            "attr_name": "puckPrimPath",
            "attr_type": Sdf.ValueTypeNames.String,
            "default_value": "/World/puck",
            "doc": "Path to the puck prim in the stage.",
        },
    ]

    def on_init(self):
        self._puck_prim = None
        self._spawn_location = Gf.Vec3d(0.0, 0.0, 0.0)
        self._interval = 5.0
        self._timer = 0.0

        # Expose the variables
        create_exposed_variables(self.prim, EXPOSED_ATTR_NS, self.BEHAVIOR_NS, self.VARIABLES_TO_EXPOSE)
        omni.kit.window.property.get_window().request_rebuild()

    def on_play(self):
        self._setup()

    def on_update(self, current_time: float, delta_time: float):
        if not self._puck_prim or delta_time <= 0:
            return

        # Increment timer
        self._timer += delta_time

        # Reset puck if timer exceeds interval
        if self._timer >= self._interval:
            self._set_location(self._puck_prim, self._spawn_location)
            carb.log_info(f"Puck respawned at {self._spawn_location}")
            self._timer = 0.0

    def _setup(self):
        # Get exposed variables
        self._interval = self._get_exposed_variable("interval")
        self._spawn_location = self._get_exposed_variable("spawnLocation")
        puck_path = self._get_exposed_variable("puckPrimPath")

        # Fetch puck prim
        if self.stage and puck_path:
            self._puck_prim = self.stage.GetPrimAtPath(Sdf.Path(puck_path))
            if not self._puck_prim or not self._puck_prim.IsValid():
                carb.log_warn(f"Puck prim not found at path: {puck_path}")
                self._puck_prim = None

    def _get_exposed_variable(self, attr_name):
        full_attr_name = f"{EXPOSED_ATTR_NS}:{self.BEHAVIOR_NS}:{attr_name}"
        from isaacsim.replicator.behavior.utils.behavior_utils import get_exposed_variable
        return get_exposed_variable(self.prim, full_attr_name)

    def _get_location(self, prim):
        xformable = UsdGeom.Xformable(prim)
        xform_ops = xformable.GetOrderedXformOps()
        for op in xform_ops:
            if op.GetOpName() == "xformOp:translate":
                return op.Get()
        return Gf.Vec3d(0.0, 0.0, 0.0)

    def _set_location(self, prim, location: Gf.Vec3d):
        xformable = UsdGeom.Xformable(prim)
        xform_ops = xformable.GetOrderedXformOps()
        for op in xform_ops:
            if op.GetOpName() == "xformOp:translate":
                op.Set(location)
                return
        # If no translate op exists, create one
        translate_op = xformable.AddXformOp(UsdGeom.XformOp.TypeTranslate, UsdGeom.XformOp.PrecisionDouble)
        translate_op.Set(location)
