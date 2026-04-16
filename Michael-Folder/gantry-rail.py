# SPDX-FileCopyrightText: Copyright (c) 2024-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import random
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


class LocationRandomizer(BehaviorScript):
    """
    Behavior script that randomizes the location of prims within specified bounds.
    The behavior can be applied to multiple prims at once.
    """

    BEHAVIOR_NS = "locationRandomizer"
    VARIABLES_TO_EXPOSE = [
        {
            "attr_name": "range:minPosition",
            "attr_type": Sdf.ValueTypeNames.Vector3d,
            "default_value": Gf.Vec3d(-1.0, -1.0, -1.0),
            "doc": "The minimum position for the randomization.",
        },
        {
            "attr_name": "range:maxPosition",
            "attr_type": Sdf.ValueTypeNames.Vector3d,
            "default_value": Gf.Vec3d(1.0, 1.0, 1.0),
            "doc": "The maximum position for the randomization.",
        },
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
            "default_value": True,
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
        """Called when the script is assigned to a prim."""
        self._min_position = Gf.Vec3d(-1.0, -1.0, -1.0)
        self._max_position = Gf.Vec3d(1.0, 1.0, 1.0)
        self._use_relative_frame = False
        self._target_prim = None
        #self._targets = [Gf.Vec3d(-237, 140, 561), Gf.Vec3d(-237, 100, 561)]
        self._rail_positions = [
            Gf.Vec3d(-237, -160, 561),  # J
            Gf.Vec3d(-237, -80, 561),   # K
            Gf.Vec3d(-237, 45, 561),   # L
            Gf.Vec3d(-237, 140, 561),  # ;
        ]
        self._current_index = 0
        self._desired_index = 0
        self._is_moving = False
        self._move_speed = 30.0  # units per second
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
        """Called when the script is unassigned from a prim."""
        self._reset()
        # Exposed variables should be removed if the script is no longer assigned to the prim
        if check_if_exposed_variables_should_be_removed(self.prim, __file__):
            remove_exposed_variables(self.prim, EXPOSED_ATTR_NS, self.BEHAVIOR_NS, self.VARIABLES_TO_EXPOSE)
            omni.kit.window.property.get_window().request_rebuild()

    def on_play(self):
        """Called when `play` is pressed."""
        self._setup()
        # Make sure the initial behavior is applied if the interval is larger than 0
        #if self._interval > 0:
            #self._apply_behavior()

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

        # Set initial position to default (J)
        #self._move_to_index(self._current_index)

    def on_stop(self):
        """Called when `stop` is pressed."""
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

        #self._move_to_index(self._current_index)

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
        """Called on per frame update events that occur when `playing`."""
        #if delta_time <= 0:
            #return
        #if self._interval <= 0:
            #self._apply_behavior()
        #else:
            #self._update_counter += 1
            #if self._update_counter >= self._interval:
                #self._apply_behavior()
                #self._update_counter = 0

        if not self._is_moving or delta_time <= 0:
            return

        target_pos = self._rail_positions[self._desired_index]

        for prim in self._valid_prims:
            current = self._get_location(prim)

            # Direction vector
            direction = target_pos - current
            distance = direction.GetLength()

            if distance < 0.01:
                # Close enough — snap and stop
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
        # Fetch the exposed attributes
        self._min_position = self._get_exposed_variable("range:minPosition")
        self._max_position = self._get_exposed_variable("range:maxPosition")
        self._use_relative_frame = self._get_exposed_variable("frame:useRelativeFrame")
        target_prim_path = self._get_exposed_variable("frame:targetPrimPath")
        include_children = self._get_exposed_variable("includeChildren")
        self._interval = self._get_exposed_variable("interval")

        # Get the prims to apply the behavior to
        if include_children:
            self._valid_prims = [prim for prim in Usd.PrimRange(self.prim) if prim.IsA(UsdGeom.Xformable)]
        elif self.prim.IsA(UsdGeom.Xformable):
            self._valid_prims = [self.prim]
        else:
            self._valid_prims = []
            carb.log_warn(f"[{self.prim_path}] No valid prims found.")

        # Check if the randomization should be relative to a target prim
        if target_prim_path:
            if not self.stage:
                carb.log_warn(f"[{self.prim_path}] Stage is not valid to access target prim '{target_prim_path}'.")
                self._target_prim = None
            else:  # Stage is valid
                fetched_prim = self.stage.GetPrimAtPath(Sdf.Path(target_prim_path))
                if fetched_prim and fetched_prim.IsValid() and fetched_prim.IsA(UsdGeom.Xformable):
                    self._target_prim = fetched_prim
                else:
                    self._target_prim = None
                    carb.log_warn(
                        f"[{self.prim_path}] Target prim '{target_prim_path}' not found, not valid, or not Xformable."
                    )

        # Save the initial locations (and relative offsets) of the prims
        for prim in self._valid_prims:
            self._initial_locations[prim] = self._get_location(prim)
            if self._target_prim:
                self._target_offsets[prim] = self._initial_locations[prim] - get_world_location(self._target_prim)

    def _reset(self):
        # Set prims back to their initial locations
        for prim, location in self._initial_locations.items():
            self._set_location(prim, location)
        # Clear cached values
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
                #time.sleep(0.5)

    def _get_exposed_variable(self, attr_name):
        full_attr_name = f"{EXPOSED_ATTR_NS}:{self.BEHAVIOR_NS}:{attr_name}"
        return get_exposed_variable(self.prim, full_attr_name)

    def _get_location(self, prim):
        # Get the location of the prim based on the available xformOps, create a default translation if none exists
        xformable = UsdGeom.Xformable(prim)
        xform_ops = xformable.GetOrderedXformOps()

        for op in xform_ops:
            op_name = op.GetOpName()
            if op_name == "xformOp:translate":
                return op.Get()
            elif op_name == "xformOp:transform":
                transform_matrix = op.Get()
                return Gf.Transform(transform_matrix).GetTranslation()

        # If no translation op exists, create one with a default translation
        translate_op = xformable.AddXformOp(UsdGeom.XformOp.TypeTranslate, UsdGeom.XformOp.PrecisionDouble)
        default_translation = Gf.Vec3d(0.0, 0.0, 0.0)
        translate_op.Set(default_translation)
        return default_translation

    def _set_location(self, prim, location: Gf.Vec3d):
        # Set the location of the prim based on the available xformOps
        xformable = UsdGeom.Xformable(prim)
        xform_ops = xformable.GetOrderedXformOps()

        # Look for a valid translation op to set the new rotation
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

    def _randomize_location(self, prim):
        # Generate a random offset within the bounds
        random_offset = Gf.Vec3d(
            random.uniform(self._min_position[0], self._max_position[0]),
            random.uniform(self._min_position[1], self._max_position[1] + 50),
            random.uniform(self._min_position[2], self._max_position[2]),
        )

        # Initialize location
        loc = random_offset

        # Handle the target prim if specified
        if self._target_prim:
            target_loc = get_world_location(self._target_prim)

            if self._use_relative_frame:
                # Maintain the offset from the target prim
                loc = target_loc + self._target_offsets[prim] + random_offset
            else:
                # Move the prim to the randomized location relative to the target prim
                loc = target_loc + random_offset
        else:
            if self._use_relative_frame:
                # Add the initial location if using the relative frame
                loc += self._initial_locations[prim]

        # Set the randomized location to the prim
        self._set_location(prim, loc)

    def set_location(self, prim):
        # start_pos = -237, -43, 561
        offset = Gf.Vec3d(-237, 300, 561)
        loc = offset
        if self._target_prim:
            target_loc = get_world_location(self._target_prim)
            carb.log_info(f"WORLD LOC: {target_loc}")

            # if self._use_relative_frame:
            #     loc = target_loc + self._target_offsets[prim] + offset
            # else:
            #     loc = target_loc + offset
            loc = target_loc + offset
        # else:
        #     if self._use_relative_frame:
        #         loc += self._initial_locations[prim]

        self._set_location(prim, loc)
