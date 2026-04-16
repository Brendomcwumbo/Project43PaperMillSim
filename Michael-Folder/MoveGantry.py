from pxr import Gf


def setup(db):
    """Initialize rail positions."""
    db.per_instance_state.rail_positions = [
        Gf.Vec3d(3.00, 0.80, 4.00),   # Position 0
        Gf.Vec3d(3.00, 0.00, 4.00),   # Position 1
        Gf.Vec3d(3.00, -1.30, 4.00),  # Position 2
        Gf.Vec3d(3.00, -2.20, 4.00),  # Position 3
    ]
    db.per_instance_state.last_pos = -1
    print("[MoveGantry] setup() - rail positions initialized", flush=True)


def cleanup(db):
    """Cleanup."""
    print("[MoveGantry] cleanup() called", flush=True)


def compute(db):
    """Output coordinate for the given position index."""
    
    # Read Position input
    try:
        pos_input = db.inputs.Position
        pos_index = int(pos_input)
        print(f"[MoveGantry] compute() - Position input: {pos_input} -> {pos_index}", flush=True)
    except AttributeError:
        pos_index = 0
        print(f"[MoveGantry] compute() - NO Position input, using 0", flush=True)
    except (TypeError, ValueError) as e:
        pos_index = 0
        print(f"[MoveGantry] compute() - Cannot parse Position: {e}, using 0", flush=True)
    
    # Clamp to valid range
    pos_index = max(0, min(pos_index, 3))
    
    # Get coordinate
    coord = db.per_instance_state.rail_positions[pos_index]
    
    # Set output
    try:
        db.outputs.Outputcoords = coord
        if pos_index != db.per_instance_state.last_pos:
            print(f"[MoveGantry] compute() - Output set to position {pos_index}: {coord}", flush=True)
            db.per_instance_state.last_pos = pos_index
    except AttributeError as e:
        print(f"[MoveGantry] compute() - Cannot set Outputcoords: {e}", flush=True)
    
    return True