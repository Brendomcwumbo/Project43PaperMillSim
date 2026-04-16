"""
Script to make the puck follow the gripper in real time.
Attach this script to a prim and press 'P' when playing to start/stop following.
Uses the Isaac Sim BehaviorScript framework for proper lifecycle management.
"""

import carb.input
import omni.appwindow
from omni.kit.scripting import BehaviorScript
from pxr import Gf, Usd, UsdGeom, UsdPhysics


class PuckFollower(BehaviorScript):
    """
    Behavior script that makes the puck follow the gripper when 'P' is pressed.
    """

    def on_init(self):
        """Called when the script is assigned to a prim."""
        carb.log_info("[Puck Script] on_init() called")
        self._keyboard_sub = None
        self._keyboard = None
        self.puck_path = "/Paper_Plug"
        self.gripper_path = "/World/Robotiq_2F_85_edit/Robotiq_2F_85/base_link"
        self._fallback_gripper_paths = [
            "/World/PlugBot/Robotiq_2F_85_edit/Robotiq_2F_85_edit/Robotiq_2F_85/base_link",
            "/World/PlugBot/Robotiq_2F_85_edit/Robotiq_2F_85/base_link",
        ]
        self._is_following = False
        self._captured_relative_transform = None
        carb.log_info(f"[Puck Script] Initialized - Puck: {self.puck_path}, Gripper: {self.gripper_path}")

    def on_destroy(self):
        """Called when the script is unassigned from a prim."""
        self._cleanup_keyboard()

    def on_play(self):
        """Called when `play` is pressed."""
        carb.log_info("[Puck Script] on_play() called - setting up keyboard listener")
        
        # Set up keyboard listener
        appwindow = omni.appwindow.get_default_app_window()
        carb.log_info(f"[Puck Script] Got app window: {appwindow}")
        
        input_interface = carb.input.acquire_input_interface()
        carb.log_info(f"[Puck Script] Got input interface: {input_interface}")
        
        self._keyboard = appwindow.get_keyboard()
        carb.log_info(f"[Puck Script] Got keyboard: {self._keyboard}")

        self._keyboard_sub = input_interface.subscribe_to_keyboard_events(
            self._keyboard,
            self._on_keyboard_event
        )
        carb.log_info(f"[Puck Script] Subscribed to keyboard events: {self._keyboard_sub}")
        carb.log_info("Keyboard listener active - Press 'Z' to toggle puck following")
        self._is_following = False
        self._captured_relative_transform = None

    def on_stop(self):
        """Called when `stop` is pressed."""
        self._cleanup_keyboard()
        self._is_following = False
        self._captured_relative_transform = None

    def on_update(self, current_time: float, delta_time: float):
        """Called on per frame update when playing."""
        if not self._is_following:
            return

        stage = self.stage
        if not stage:
            carb.log_warn("Stage is not valid")
            return

        # Get the prims
        puck_prim = stage.GetPrimAtPath(self.puck_path)
        gripper_prim = self._get_gripper_prim(stage)

        if not puck_prim.IsValid():
            carb.log_error(f"Puck prim at {self.puck_path} is not valid")
            return

        if not gripper_prim.IsValid():
            carb.log_error(f"Gripper prim at {self.gripper_path} is not valid")
            return

        carb.log_info(f"[Puck Following] Updating positions...")

        if self._captured_relative_transform is None:
            carb.log_warn("No captured relative transform. Press 'Z' again to capture follow offset.")
            return

        # Get the gripper's world transform
        gripper_xform = UsdGeom.Xformable(gripper_prim)
        gripper_world_transform = gripper_xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        # Rebuild puck world transform from the captured relative transform.
        target_world_transform = self._captured_relative_transform * gripper_world_transform

        # Convert world target into the puck's parent local space.
        parent_prim = puck_prim.GetParent()
        if parent_prim and parent_prim.IsValid() and parent_prim.GetPath().pathString != "/":
            parent_world = UsdGeom.Xformable(parent_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            target_transform = target_world_transform * parent_world.GetInverse()
        else:
            target_transform = target_world_transform

        # Clear and set up xform ops for puck - use a single Transform op
        puck_xform = UsdGeom.Xformable(puck_prim)
        puck_xform.ClearXformOpOrder()
        transform_op = puck_xform.AddTransformOp()
        transform_op.Set(target_transform)
        carb.log_info("  Puck transform updated from captured relative offset")

    def _capture_relative_transform(self):
        """Capture puck transform relative to gripper at the moment follow starts."""
        stage = self.stage
        if not stage:
            carb.log_warn("Stage is not valid")
            return False

        puck_prim = stage.GetPrimAtPath(self.puck_path)
        gripper_prim = self._get_gripper_prim(stage)

        if not puck_prim.IsValid():
            carb.log_error(f"Puck prim at {self.puck_path} is not valid")
            return False

        if not gripper_prim.IsValid():
            carb.log_error(f"Gripper prim at {self.gripper_path} is not valid")
            return False

        puck_world = UsdGeom.Xformable(puck_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        gripper_world = UsdGeom.Xformable(gripper_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())

        # USD transforms compose as local * parent, so relative = puck_world * inverse(gripper_world).
        self._captured_relative_transform = puck_world * gripper_world.GetInverse()
        return True

    def _get_gripper_prim(self, stage):
        """Resolve gripper prim, with fallbacks for different robot parenting layouts."""
        gripper_prim = stage.GetPrimAtPath(self.gripper_path)
        if gripper_prim.IsValid():
            return gripper_prim

        for fallback_path in self._fallback_gripper_paths:
            fallback_prim = stage.GetPrimAtPath(fallback_path)
            if fallback_prim.IsValid():
                if self.gripper_path != fallback_path:
                    self.gripper_path = fallback_path
                    carb.log_info(f"[Puck Script] Updated gripper path to: {self.gripper_path}")
                return fallback_prim

        return gripper_prim

    def _set_puck_collision_enabled(self, enabled):
        """Set the puck's Collision Enabled property."""
        stage = self.stage
        if not stage:
            carb.log_warn("Stage is not valid")
            return False

        puck_prim = stage.GetPrimAtPath(self.puck_path)
        if not puck_prim.IsValid():
            carb.log_error(f"Puck prim at {self.puck_path} is not valid")
            return False

        collision_api = UsdPhysics.CollisionAPI.Get(stage, puck_prim.GetPath())
        if not collision_api:
            collision_api = UsdPhysics.CollisionAPI.Apply(puck_prim)

        collision_enabled_attr = collision_api.GetCollisionEnabledAttr()
        if not collision_enabled_attr:
            collision_enabled_attr = collision_api.CreateCollisionEnabledAttr()

        collision_enabled_attr.Set(enabled)
        carb.log_info(f"[Puck Script] Collision Enabled set to: {enabled}")
        return True

    def _cleanup_keyboard(self):
        """Clean up the keyboard event listener."""
        if self._keyboard_sub:
            carb.input.acquire_input_interface().unsubscribe_to_keyboard_events(
                self._keyboard,
                self._keyboard_sub
            )
            self._keyboard_sub = None
            self._keyboard = None

    def _on_keyboard_event(self, event, *args, **kwargs):
        """Handle keyboard events."""
        carb.log_info(f"[Puck Script] Key event received: type={event.type}, input={event.input}")
        
        if event.type != carb.input.KeyboardEventType.KEY_PRESS:
            carb.log_info(f"[Puck Script] Not a key press, skipping")
            return True

        carb.log_info(f"[Puck Script] Key press detected, input value: {event.input}")
        carb.log_info(f"[Puck Script] Checking if Z key (Z={carb.input.KeyboardInput.Z})")

        # Check for 'Z' key
        if event.input == carb.input.KeyboardInput.Z:
            carb.log_info(f"[Puck Script] Z KEY PRESSED!")
            if self._is_following:
                self._is_following = False
                self._captured_relative_transform = None
            else:
                if self._capture_relative_transform():
                    self._set_puck_collision_enabled(False)
                    self._is_following = True
                    carb.log_info("[Puck Script] Captured puck offset from current pose")
                else:
                    self._is_following = False
            status = "ON" if self._is_following else "OFF"
            carb.log_info(f"[Puck Script] Puck following: {status}")
        else:
            carb.log_info(f"[Puck Script] Key pressed but not Z")

        return True
