# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Project43PaperMillSim** is a multi-developer NVIDIA Isaac Sim simulation of a paper mill factory. This folder (Michael-Folder) contains gantry rail/robot control and puck (paper plug) insertion scripts.

Team members each have their own folder: Michael (gantry/puck), Justin (gantry origin), Sialas (robot/gripper), Brenden (scene/conveyor), Tyler (sandbox).

## Running the Simulation

Scripts are not run directly — they are attached to **OmniGraph Script Node prims** inside Isaac Sim:

1. Open a master USD scene (e.g., `../4-19-master.usd`) in Isaac Sim.
2. Select the OmniGraph Script Node prim for gantry/robot/puck.
3. Set the script node's source to the relevant `.py` file.
4. Press **Play** in Isaac Sim.
5. Use **J / K / L / ;** keys to move gantry positions (4 presets).

## Script Architecture

### Script Node Pattern (production)
`scriptnode_gantry_rail.py`, `scriptnode_gantry_robot.py`, `scriptNodePuckAttach.py` use the OmniGraph Script Node interface:

- Entry points: `setup(db)`, `compute(db)`, `cleanup(db)`
- Per-node state stored in a module-level `_STATE` dict keyed by `id(db)` (OmniGraph nodes are stateless per-frame)
- Inputs accessed via `db.inputs.<name>`, outputs via `db.outputs.<name>`
- Logging via `carb.log_warn()` / `carb.log_info()`

### Behavior Script Pattern (legacy/dev)
`gantry-rail.py`, `gantry-robot.py` extend `omni.kit.scripting.BehaviorScript`:

- Entry points: `on_init()`, `on_play()`, `on_pause()`, `on_stop()`, `on_update(dt)`
- Per-instance state stored as `self.*` attributes
- Used for prototyping; the scriptnode versions are the production equivalents

### Puck Attachment Workflow (`scriptNodePuckAttach.py`)
- Manages 10 pre-created invisible slot prims (`/World/PlugMill_Inserted/slot_0` … `slot_9`)
- While `enabled=True`: slot follows gripper position (with offset)
- On `enabled` going False: slot becomes visible at the roll's insertion point
- Side A vs Side B offsets are configurable per roll
- Timeline STOP event triggers full cleanup (hides slots, respawns puck to spawn position)

## Key USD Paths (defaults)

| Prim | Default Path |
|------|-------------|
| Gantry rail | `/World/Gantry` |
| Robot | `/World/Robot` |
| Paper rolls | `/factory_01/sushi_01` … `sushi_05/paper` |
| Plug slots container | `/World/PlugMill_Inserted` |

## Dependencies

All imports come from the Isaac Sim / Omniverse Python environment — no pip installs needed:

- `pxr` — USD (Gf, Sdf, Usd, UsdGeom, UsdPhysics)
- `omni.usd`, `omni.kit.commands`, `omni.appwindow`, `omni.timeline`, `omni.kit.scripting`
- `carb`, `carb.input` — engine core and keyboard input

## Movement System

Both gantry scripts use frame-rate-independent linear interpolation:

```python
step = move_speed * delta_time
new_pos = current + clamp(target - current, -step, step)  # per-axis
```

Arrival is detected when all axes are within `arrival_threshold` (default 0.5 units). Custom positions can override the 4 hardcoded presets via `db.inputs.useCustomPositions`.
