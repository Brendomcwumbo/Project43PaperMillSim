import time

import carb.input
import omni.appwindow

import omni.kit.window.property
from isaacsim.replicator.behavior.global_variables import EXPOSED_ATTR_NS
from isaacsim.replicator.behavior.utils.behavior_utils import (
    check_if_exposed_variables_should_be_removed,
    create_exposed_variables,
    get_exposed_variable,
    remove_exposed_variables,
)
from isaacsim.replicator.behavior.utils.scene_utils import get_world_location
from omni.kit.scripting import BehaviorScript
from pxr import Gf, Sdf, Usd, UsdGeom


class GantryRobot(BehaviorScript):
    BEHAVIOR_NS = "GantryRobot"
    VARIABLES_TO_EXPOSE = [
        {
            "attr_name": "frame:useRelativeFrame",
            "attr_type": Sdf.ValueTypeNames.Bool,
            "default_value": True,
            "doc": "Use relative frame for randomization.",
        },
        {
            "attr_name": "frame:targetPrimPath",
            "attr_type": Sdf.ValueTypeNames.String,
            "default_value": "",
            "doc": "Path to the target prim for relative randomization.",
        },
        {
            "attr_name": "includeChildren",
            "attr_type": Sdf.ValueTypeNames.Bool,
            "default_value": False,
            "doc": "Include valid prim children to the behavior.",
        },
        {
            "attr_name": "interval",
            "attr_type": Sdf.ValueTypeNames.UInt,
            "default_value": 0,
            "doc": "Interval for updating the behavior. Value 0 means every frame.",
        },
    ]

    def on_init(self):
        self._min_position = Gf.Vec3d(-1.0, -1.0, -1.0)
        self._max_position = Gf.Vec3d(1.0, 1.0, 1.0)
        self._use_relative_frame = False
        self._target_prim = None
        self._rail_positions = [
            Gf.Vec3d(3.00, 0.80, 4.00),   # J
            Gf.Vec3d(3.00, 0.00, 4.00),   # K
            Gf.Vec3d(3.00, -1.30, 4.00),  # L
            Gf.Vec3d(3.00, -2.20, 4.00),  # ;
        ]
        self._current_index = 0
        self._desired_index = 0
        self._is_moving = False
        self._move_speed = 0.30  # units per second
        self._keyboard_sub = None

        self._update_counter = 0
        self._interval = 0
        self._valid_prims = []
        self._initial_locations = {}
        self._target_offsets = {}

        # Expose the variables as USD attributes
        create_exposed_variables(self.prim, EXPOSED_ATTR_NS, self.BEHAVIOR_NS, self.VARIABLES_TO_EXPOSE)

        # Refresh the property windows to show the exposed variables
        omni.kit.window.property.get_window().request_rebuild()

    def on_destroy(self):
        self._reset()
        # Exposed variables should be removed if the script is no longer assigned to the prim
        if check_if_exposed_variables_should_be_removed(self.prim, __file__):
            remove_exposed_variables(self.prim, EXPOSED_ATTR_NS, self.BEHAVIOR_NS, self.VARIABLES_TO_EXPOSE)
            omni.kit.window.property.get_window().request_rebuild()

    def on_play(self):
        self._setup()
        self._current_index = 0
        self._desired_index = 0
        self._is_moving = False

        appwindow = omni.appwindow.get_default_app_window()
        input_interface = carb.input.acquire_input_interface()
        self._keyboard = appwindow.get_keyboard()

        self._keyboard_sub = input_interface.subscribe_to_keyboard_events(
            self._keyboard,
            self._on_keyboard_event
        )

    def on_stop(self):
        self._reset()

        if self._keyboard_sub:
            carb.input.acquire_input_interface().unsubscribe_to_keyboard_events(
                self._keyboard,
                self._keyboard_sub
            )
            self._keyboard_sub = None

    def _on_keyboard_event(self, event, *args, **kwargs):
        if event.type != carb.input.KeyboardEventType.KEY_PRESS:
            return True

        if event.input == carb.input.KeyboardInput.J:
            self._desired_index = 0
        elif event.input == carb.input.KeyboardInput.K:
            self._desired_index = 1
        elif event.input == carb.input.KeyboardInput.L:
            self._desired_index = 2
        elif event.input == carb.input.KeyboardInput.SEMICOLON:
            self._desired_index = 3
        else:
            return True

        if self._desired_index != self._current_index:
            self._is_moving = True

        return True

    def _move_to_index(self, index):
        if not self._valid_prims:
            return

        target_pos = self._rail_positions[index]
        for prim in self._valid_prims:
            self._set_location(prim, target_pos)

        carb.log_info(f"Gantry moved to index {index} → {target_pos}")


    def on_update(self, current_time: float, delta_time: float):
        if not self._is_moving or delta_time <= 0:
            return

        target_pos = self._rail_positions[self._desired_index]
        for prim in self._valid_prims:
            current = self._get_location(prim)

            direction = target_pos - current
            distance = direction.GetLength()

            if distance < 0.01:
                self._set_location(prim, target_pos)
                self._current_index = self._desired_index
                self._is_moving = False
                return

            direction.Normalize()

            # Move at constant speed (frame-rate independent)
            step = self._move_speed * delta_time
            step = min(step, distance)

            new_pos = current + direction * step
            self._set_location(prim, new_pos)

    def _setup(self):
        self._use_relative_frame = self._get_exposed_variable("frame:useRelativeFrame")
        target_prim_path = self._get_exposed_variable("frame:targetPrimPath")
        include_children = self._get_exposed_variable("includeChildren")
        self._interval = self._get_exposed_variable("interval")

        if include_children:
            self._valid_prims = [prim for prim in Usd.PrimRange(self.prim) if prim.IsA(UsdGeom.Xformable)]
        elif self.prim.IsA(UsdGeom.Xformable):
            self._valid_prims = [self.prim]
        else:
            self._valid_prims = []
            carb.log_warn(f"[{self.prim_path}] No valid prims found.")

        if target_prim_path:
            if not self.stage:
                carb.log_warn(f"[{self.prim_path}] Stage is not valid to access target prim '{target_prim_path}'.")
                self._target_prim = None
            else:
                fetched_prim = self.stage.GetPrimAtPath(Sdf.Path(target_prim_path))
                if fetched_prim and fetched_prim.IsValid() and fetched_prim.IsA(UsdGeom.Xformable):
                    self._target_prim = fetched_prim
                else:
                    self._target_prim = None
                    carb.log_warn(
                        f"[{self.prim_path}] Target prim '{target_prim_path}' not found, not valid, or not Xformable."
                    )

        for prim in self._valid_prims:
            self._initial_locations[prim] = self._get_location(prim)
            if self._target_prim:
                self._target_offsets[prim] = self._initial_locations[prim] - get_world_location(self._target_prim)

    def _reset(self):
        for prim, location in self._initial_locations.items():
            self._set_location(prim, location)

        self._valid_prims.clear()
        self._initial_locations.clear()
        self._target_offsets.clear()
        self._target_prim = None
        self._interval = 0
        self._update_counter = 0

    def _apply_behavior(self):
        for prim in self._valid_prims:
            current = self._get_location(prim)
            if hasattr(self, "_targets") and self._targets:
                t = 0.05
                for target in enumerate(self._targets):
                    new_pos = Gf.Vec3d(
                        Gf.Lerp(t, current[0], self._targets[0][0]),
                        Gf.Lerp(t, current[1], self._targets[0][1]),
                        Gf.Lerp(t, current[2], self._targets[0][2])
                    )
                    self._set_location(prim, new_pos)

    def _get_exposed_variable(self, attr_name):
        full_attr_name = f"{EXPOSED_ATTR_NS}:{self.BEHAVIOR_NS}:{attr_name}"
        return get_exposed_variable(self.prim, full_attr_name)

    def _get_location(self, prim):
        xformable = UsdGeom.Xformable(prim)
        xform_ops = xformable.GetOrderedXformOps()

        for op in xform_ops:
            op_name = op.GetOpName()
            if op_name == "xformOp:translate":
                return op.Get()
            elif op_name == "xformOp:transform":
                transform_matrix = op.Get()
                return Gf.Transform(transform_matrix).GetTranslation()

        translate_op = xformable.AddXformOp(UsdGeom.XformOp.TypeTranslate, UsdGeom.XformOp.PrecisionDouble)
        default_translation = Gf.Vec3d(0.0, 0.0, 0.0)
        translate_op.Set(default_translation)
        return default_translation

    def _set_location(self, prim, location: Gf.Vec3d):
        xformable = UsdGeom.Xformable(prim)
        xform_ops = xformable.GetOrderedXformOps()

        for op in xform_ops:
            op_name = op.GetOpName()
            if op_name == "xformOp:translate":
                op.Set(location)
                return
            elif op_name == "xformOp:transform":
                transform_matrix = op.Get()
                transform = Gf.Transform(transform_matrix)
                transform.SetTranslation(location)
                op.Set(transform.GetMatrix())
                return

        carb.log_warn(f"No valid location op found on {prim.GetPath()}")

    def set_location(self, prim):
        offset = Gf.Vec3d(-237, 300, 561)
        loc = offset
        if self._target_prim:
            target_loc = get_world_location(self._target_prim)
            carb.log_info(f"WORLD LOC: {target_loc}")
            loc = target_loc + offset
        self._set_location(prim, loc)
