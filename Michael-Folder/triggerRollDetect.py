"""
Trigger script for the roll detection zone.
Point both 'On Enter Script' and 'On Leave Script' to this file.
"""

import builtins
import carb

carb.log_warn("[RollTrigger] script loaded")


def on_trigger_enter(triggerPrimPath, otherPrimPath):
    carb.log_warn(f"[RollTrigger] ENTER (v1): trigger={triggerPrimPath}  other={otherPrimPath}")
    builtins._roll_trigger_detected = True


def on_trigger_leave(triggerPrimPath, otherPrimPath):
    carb.log_warn(f"[RollTrigger] LEAVE (v1): trigger={triggerPrimPath}  other={otherPrimPath}")
    builtins._roll_trigger_detected = False


# Alternative signatures Isaac Sim may use
def on_enter(triggerPrimPath, otherPrimPath):
    carb.log_warn(f"[RollTrigger] ENTER (v2): {otherPrimPath}")
    builtins._roll_trigger_detected = True


def on_leave(triggerPrimPath, otherPrimPath):
    carb.log_warn(f"[RollTrigger] LEAVE (v2): {otherPrimPath}")
    builtins._roll_trigger_detected = False


def execute(triggerPrimPath, otherPrimPath):
    carb.log_warn(f"[RollTrigger] ENTER (v3): {otherPrimPath}")
    builtins._roll_trigger_detected = True
