"""
Script to constantly output the robot's position and orientation to the console.
Attach this script to any prim and press play to start monitoring.
Uses the Isaac Sim BehaviorScript framework.
"""

import carb
from omni.kit.scripting import BehaviorScript
from pxr import Gf, Usd, UsdGeom


class RobotPosePrinter(BehaviorScript):
    """
    Behavior script that continuously prints the robot's position and orientation.
    """

    def on_init(self):
        """Called when the script is assigned to a prim."""
        carb.log_info("[Robot Pose Printer] Initialized")
        # Update this path to match your robot's base link
        self.robot_base_path = "/World/PlugBot/Robotiq_2F_85_edit/Robotiq_2F_85_edit/Robotiq_2F_85/base_link"
        self.frame_count = 0

    def on_play(self):
        """Called when `play` is pressed."""
        carb.log_info("[Robot Pose Printer] on_play() called - Starting position monitoring")
        self.frame_count = 0

    def on_stop(self):
        """Called when `stop` is pressed."""
        carb.log_info("[Robot Pose Printer] on_stop() called - Stopping position monitoring")

    def on_update(self, current_time: float, delta_time: float):
        """Called on per frame update when playing."""
        try:
            stage = self.stage
            if not stage:
                carb.log_warn("Stage is not valid")
                return

            # Get the specific prim at the exact path provided
            prim = stage.GetPrimAtPath(self.robot_base_path)
            if not prim.IsValid():
                carb.log_error(f"Prim at {self.robot_base_path} is not valid")
                return

            # Debug: Print what prim we actually got
            actual_path = prim.GetPath()
            carb.log_info(f"Requested path: {self.robot_base_path}")
            carb.log_info(f"Actual prim path: {actual_path}")
            carb.log_info(f"Prim name: {prim.GetName()}")

            # Get the world transform for this specific prim
            xformable = UsdGeom.Xformable(prim)
            world_transform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            position = world_transform.ExtractTranslation()
            rotation = world_transform.ExtractRotation()

            # Print every 30 frames to avoid console spam (adjust as needed)
            self.frame_count += 1
            if self.frame_count % 30 == 0:
                print(f"\n========== Robot Pose (Time: {current_time:.2f}s) ==========")
                print(f"Requested: {self.robot_base_path}")
                print(f"Got prim: {actual_path}")
                print(f"Position: X={position[0]:.4f}, Y={position[1]:.4f}, Z={position[2]:.4f}")
                print(f"Rotation: {rotation}")
                print("=" * 50)

                # Also log to carb for Isaac Sim console
                carb.log_info(f"Position: X={position[0]:.4f}, Y={position[1]:.4f}, Z={position[2]:.4f}")
                carb.log_info(f"Rotation: {rotation}")
        except Exception as e:
            carb.log_error(f"Error getting world pose: {str(e)}")
            import traceback
            carb.log_error(traceback.format_exc())
