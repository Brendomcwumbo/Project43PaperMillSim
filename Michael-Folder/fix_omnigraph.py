"""
Paste into Isaac Sim Script Editor and run when On Playback Tick stops firing.
Make sure simulation is STOPPED before running.
"""
import omni.graph.core as og
import carb

count = 0
for g in og.get_all_graphs():
    try:
        g.reload_from_stage()
        carb.log_warn(f"[Fix] reloaded: {g.get_path_to_graph()}")
        count += 1
    except Exception as e:
        carb.log_warn(f"[Fix] failed {g.get_path_to_graph()}: {e}")

carb.log_warn(f"[Fix] done — {count} graph(s) reloaded. Press Play.")
