"""
Script to output puck and gripper positions to the console.
"""

import carb
import time

from pxr import Usd, UsdGeom
import omni.kit.app

try:
    from pymodbus.client import ModbusTcpClient
except Exception:
    ModbusTcpClient = None


MODBUS_HOST = "127.0.0.1"
MODBUS_PORT = 502
MODBUS_SLAVE_ID = 1
MODBUS_BASE_ADDRESS = 0
MODBUS_WRITE_INTERVAL_SEC = 0.1
POSITION_SCALE = 1000.0

_modbus_client = None
_last_modbus_write = 0.0
_modbus_enabled = ModbusTcpClient is not None


def _to_int_register(value):
    """Convert meter value to signed millimeter integer register."""
    scaled = int(round(float(value) * POSITION_SCALE))
    return max(-32768, min(32767, scaled))


def _connect_modbus_if_needed():
    global _modbus_client

    if not _modbus_enabled:
        return False

    if _modbus_client is None:
        _modbus_client = ModbusTcpClient(host=MODBUS_HOST, port=MODBUS_PORT)

    try:
        if not _modbus_client.connected:
            return _modbus_client.connect()
        return True
    except Exception as exc:
        carb.log_warn(f"Modbus connect failed: {exc}")
        return False


def _write_modbus_registers(registers):
    """Write holding registers with compatibility for pymodbus v2/v3 args."""
    try:
        _modbus_client.write_registers(MODBUS_BASE_ADDRESS, registers, slave=MODBUS_SLAVE_ID)
    except TypeError:
        _modbus_client.write_registers(MODBUS_BASE_ADDRESS, registers, unit=MODBUS_SLAVE_ID)

def update(dt):
    """Update callback to log positions every frame."""
    global _last_modbus_write

    # Get the stage
    from omni.usd import get_context
    stage = get_context().get_stage()
    
    if not stage:
        return
    
    # Get the prims
    gripper_prim = stage.GetPrimAtPath("/World/PlugBot/Robotiq_2F_85_edit/Robotiq_2F_85_edit/Robotiq_2F_85/base_link")
    object_prim = stage.GetPrimAtPath("/Paper_Plug")
    
    if not gripper_prim.IsValid():
        carb.log_error("Gripper prim not valid")
        return
    
    if not object_prim.IsValid():
        carb.log_error("Object prim not valid")
        return
    
    # Get gripper's world position and rotation
    gripper_xform = UsdGeom.Xformable(gripper_prim)
    gripper_world_transform = gripper_xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    gripper_pos = gripper_world_transform.ExtractTranslation()
    
    # Set puck to gripper's position and rotation
    object_xform = UsdGeom.Xformable(object_prim)
    object_xform.SetLocalTransform(gripper_world_transform)
    
    # Log to console
    carb.log_info(f"Puck Position: {gripper_pos}")

    now = time.time()
    if now - _last_modbus_write < MODBUS_WRITE_INTERVAL_SEC:
        return

    _last_modbus_write = now
    if not _connect_modbus_if_needed():
        return

    # Registers 0-2: gripper X/Y/Z in millimeters (signed 16-bit)
    registers = [
        _to_int_register(gripper_pos[0]),
        _to_int_register(gripper_pos[1]),
        _to_int_register(gripper_pos[2]),
    ]

    try:
        _write_modbus_registers(registers)
    except Exception as exc:
        carb.log_warn(f"Modbus write failed: {exc}")



# Register update callback
carb.log_info("Registering position monitoring callback")
if not _modbus_enabled:
    carb.log_warn("pymodbus not available. Install pymodbus to enable Modbus output.")
else:
    carb.log_info(
        f"Modbus enabled -> {MODBUS_HOST}:{MODBUS_PORT}, slave={MODBUS_SLAVE_ID}, base={MODBUS_BASE_ADDRESS}"
    )
omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(update)
