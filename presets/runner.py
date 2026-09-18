# presets/runner.py - Apply presets to sessions + headless pass/fail runs (Qt-free).
from __future__ import annotations


def apply_to_session(session, preset_id: str):
    """Auto-configure ALL modules of a session from a preset.

    Works with gui.application.session.SimulationSession (apply_* API) and
    with simulation.headless.HeadlessSimulation (attribute swap + reset).
    Returns the preset.
    """
    from presets.presets import build_configs

    env, lt, scen, dist, preset = build_configs(preset_id)

    if hasattr(session, "apply_environment_config"):
        # GUI session: environment rebuilds, rest apply live.
        session.apply_environment_config(env)
        session.apply_local_terminal_config(lt)
        session.apply_terminal_config(scen)
        session.apply_disturbance_config(dist)
    else:
        session.env_config = env
        session.local_terminal_config = lt
        session.camera_config = lt
        session.scenario_config = scen
        session.disturbance_config = dist
        if hasattr(session, "reset"):
            try:
                session.reset(seed=preset.seed)
            except TypeError:
                session.reset()
    return preset


def evaluate_telemetry(telemetry: dict, expect: dict) -> tuple[bool, str]:
    """Check final local-terminal telemetry against preset expectation."""
    state = (telemetry.get("state") or {}) if isinstance(telemetry, dict) else {}
    autonomy = (telemetry.get("autonomy") or {}) if isinstance(telemetry, dict) else {}
    kind = expect.get("kind", "lock")

    det = state.get("detection_state", "")
    trk = state.get("tracking_state", "")
    active = autonomy.get("active_target_id")

    if kind == "lock":
        ok = det == "TARGET_CONFIRMED" and trk == "TRACKING"
        want_active = expect.get("active")
        if ok and want_active and active != want_active:
            return False, f"locked wrong target {active!r}, expected {want_active!r}"
        return ok, f"detection={det} tracking={trk} active={active}"
    if kind == "acquire":
        ok = trk == "TRACKING" and det == "TARGET_CONFIRMED"
        return ok, f"detection={det} tracking={trk} active={active}"
    if kind == "no_lock":
        bad = trk == "TRACKING" and det == "TARGET_CONFIRMED"
        return (not bad), f"detection={det} tracking={trk} active={active} (must stay unconfirmed)"
    if kind == "degraded":
        ok = det in ("TARGET_CONFIRMED", "DISCRIMINATING", "DETECTING")
        return ok, f"detection={det} tracking={trk} (degraded channel)"
    if kind == "relock":
        ok = det == "TARGET_CONFIRMED" and trk == "TRACKING"
        return ok, f"detection={det} tracking={trk} active={active} (after blink)"
    if kind == "ever_locked":
        ok = bool(expect.get("saw_tracking"))
        return ok, f"{'caught the target mid-run' if ok else 'never caught the target'} (final {det}/{trk})"
    return False, f"unknown expectation kind {kind!r}"


def run_headless(preset_id: str, steps: int | None = None, seed: int | None = None) -> dict:
    """Run a preset headless (no Qt) and return pass/fail + telemetry.

    Result: {"preset_id", "name", "passed", "reason", "steps",
             "final_detection", "final_tracking", "active_target",
             "saw_reacquiring" (relock only), "telemetry"}.
    """
    from simulation.headless import HeadlessSimulation
    from presets.presets import build_configs

    env, lt, scen, dist, preset = build_configs(preset_id)
    n_steps = int(steps or preset.steps)
    run_seed = int(seed if seed is not None else preset.seed)

    sim = HeadlessSimulation(
        seed=run_seed, env_config=env, local_terminal_config=lt,
        disturbance_config=dist, scenario_config=scen,
    )
    sim.reset(seed=run_seed)

    saw_reacquiring = False
    saw_tracking = False

    def _note_progress() -> None:
        nonlocal saw_reacquiring, saw_tracking
        try:
            st = sim.local_terminal.config.state
            if st.tracking_state == "REACQUIRING":
                saw_reacquiring = True
            if st.tracking_state == "TRACKING" and st.detection_state == "TARGET_CONFIRMED":
                saw_tracking = True
        except Exception:
            pass

    if preset.expect.get("kind") == "relock":
        # Phase 1: lock (up to 1/3 of steps). Phase 2: beacon cut.
        phase1 = max(30, n_steps // 4)
        for _ in range(phase1):
            obs, *_ = sim.step(None)
        for t in sim.terminal_scenario.terminals:
            try:
                t.set_beacon_enabled(False)
            except Exception:
                try:
                    t.config.beacon.enabled = False
                except Exception:
                    pass
        # Phase 2: observe coast (up to 60 steps).
        for _ in range(60):
            obs, *_ = sim.step(None)
            _note_progress()
        for t in sim.terminal_scenario.terminals:
            try:
                t.set_beacon_enabled(True)
            except Exception:
                try:
                    t.config.beacon.enabled = True
                except Exception:
                    pass
        # Phase 3: relock with remaining steps.
        for _ in range(max(60, n_steps - phase1 - 60)):
            obs, *_ = sim.step(None)
            _note_progress()
    else:
        for _ in range(n_steps):
            obs, *_ = sim.step(None)
            _note_progress()

    try:
        telemetry = sim.local_terminal.get_telemetry()
    except Exception:
        telemetry = {}
    expect = dict(preset.expect)
    expect["saw_tracking"] = saw_tracking
    passed, reason = evaluate_telemetry(telemetry, expect)
    if preset.expect.get("kind") == "relock" and passed and not saw_reacquiring:
        passed, reason = False, reason + " (never saw REACQUIRING coast)"
    state = (telemetry.get("state") or {})
    return {
        "preset_id": preset_id,
        "name": preset.name,
        "passed": bool(passed),
        "reason": reason,
        "steps": n_steps,
        "final_detection": state.get("detection_state"),
        "final_tracking": state.get("tracking_state"),
        "active_target": (telemetry.get("autonomy") or {}).get("active_target_id"),
        "saw_reacquiring": saw_reacquiring,
        "saw_tracking": saw_tracking,
        "telemetry": telemetry,
    }


def _cli() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Run simulator testing presets headless.")
    p.add_argument("--list", action="store_true", help="list presets and exit")
    p.add_argument("--preset", default=None, help="preset id (default: run ALL)")
    p.add_argument("--steps", type=int, default=None, help="override step count")
    p.add_argument("--seed", type=int, default=None, help="override seed")
    args = p.parse_args()

    from presets.presets import PRESETS, list_presets

    if args.list:
        for item in list_presets():
            print(f"{item['id']:20s} [{item['category']}] {item['name']} - {item['description']}")
        return 0

    targets = [args.preset] if args.preset else [p.preset_id for p in PRESETS]
    failures = 0
    for pid in targets:
        res = run_headless(pid, steps=args.steps, seed=args.seed)
        mark = "PASS" if res["passed"] else "FAIL"
        print(f"[{mark}] {pid}: {res['reason']}")
        failures += 0 if res["passed"] else 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
