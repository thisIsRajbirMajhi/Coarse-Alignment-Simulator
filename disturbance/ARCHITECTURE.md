# Disturbance Architecture

```text
                         DisturbanceContext
                                |
              +-----------------+-----------------+
              v                 v                 v
        Environment          Target             Camera
              |                 |                 |
              +-----------------+-----------------+
                                v
                           Optical Path
                                |
                                v
                              Sensor
                                |
                                v
                               Frame
```

## Ownership

- `core`: per-run context, timestep, RNG, configuration, reset, and orchestration.
- `environment`: atmospheric conditions and future world-level clutter effects.
- `target`: target-local motion, photometry, and dropout behavior.
- `camera`: platform motion, vibration, jitter, and pointing drift.
- `optical`: propagation and turbulence effects on an image.
- `sensor`: detector noise, image defects, exposure, and persistent defect state.

The normal frame order is camera pose disturbance, optical effects, then sensor
effects. `DisturbancePipeline` delegates to the three subsystem owners; it does
not implement their mathematics.

## State and RNG

Each simulation creates one `DisturbanceContext` and one pipeline. Subsystems
own their temporal state, and the context owns the seeded generator and
simulation time. Calling `reset()` clears subsystem state and returns time to
zero. Legacy function calls still work, but their module-level state is only a
compatibility path and is not used by the simulation pipeline.

## Compatibility and extension

`disturbance.legacy` and `disturbance.disturbances` preserve the old public
functions. New disturbance models should be added to the physical owner,
exposed through that owner's subsystem, and then connected to
`DisturbancePipeline` only as orchestration. GUI and simulation ticks should
depend on subsystem interfaces rather than model functions.

The importable global package is `disturbance.global_`; `global` is retained as
a filesystem compatibility path because it is a Python keyword.