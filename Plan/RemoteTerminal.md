# TASK: Build a Simplified, Realistic 2D FSOC Remote Terminal

You are the implementation agent working inside the existing `Coarse-Alignment-Simulator` repository.

Your task is to redesign and implement the **Remote Terminal subsystem only**.

The resulting Remote Terminal must be:

* Simple.
* Cleanly structured.
* Physically meaningful.
* Suitable for a 2D FSOC/PAT simulation.
* Cooperative.
* Configurable through a GUI.
* Capable of transmitting its **last-known location in its optical beacon payload**.
* Easy to extend later.
* Independent and self-contained.

Do not implement or redesign any other terminal subsystem.

---

# 1. Core Design Philosophy

The Remote Terminal represents a simulated optical communication terminal that:

1. Moves through a 2D environment.
2. Can operate alone or as part of a formation.
3. Has an identity.
4. Produces an optical beacon.
5. Emits optical power according to configuration.
6. Uses a configurable wavelength.
7. Uses a configurable modulation.
8. Produces a beam with configurable angular spot size/divergence.
9. Maintains a simple internal operational state.
10. Includes its latest sampled position in the beacon payload.
11. Uses realistic but simplified 2D geometry.

Do NOT turn the Remote Terminal into a complex autonomous system.

The Remote Terminal must NOT contain:

```text
AI
Computer vision
Image processing
Candidate detection
Target classification
Candidate discrimination
Target selection
Complex tracking
Kalman filtering
Search algorithms
Reacquisition algorithms
Detailed spacecraft attitude dynamics
Detailed laser physics
Detailed receiver-camera simulation
Complex communications PHY
```

The Remote Terminal is fundamentally:

```text
Motion
   ↓
Position
   ↓
Geometry
   ↓
Beam
   ↓
Beacon
   ↓
Optical Emission
```

---

# 2. High-Level Architecture

Use this architecture:

```text
                         REMOTE TERMINAL SYSTEM
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
              Scenario Config             Terminal Config
                    │                           │
                    ▼                           ▼
             Formation Manager          Remote Terminal
                    │                           │
                    │                  ┌────────┼─────────┐
                    │                  │        │         │
                    ▼                  ▼        ▼         ▼
             Formation Positions     Motion   Beacon   Optical
                                       │        │       Model
                                       │        │         │
                                       └────┬───┴─────────┘
                                            │
                                            ▼
                                      Geometry Engine
                                            │
                                            ▼
                                       Beam Geometry
                                            │
                                            ▼
                                     Optical Emission
```

The main architectural principle is:

> **Configuration → state → derived geometry → optical emission**

Do not mix configuration values with runtime state.

---

# 3. User-Configurable Parameters

The GUI must expose only these primary parameters.

## 3.1 Formation and Motion

```text
Terminal Count
Formation Shape
Motion Profile
Terminal Spacing
Speed
Heading
```

Use these exact choices.

### Formation Shape

```text
Single
Line
Circle
Arc
Grid
Rectangle
V Formation
```

### Motion Profile

```text
Rest
Constant Velocity
Linear
Circular
Sinusoidal
Figure-8
Random
```

Correct spelling internally:

```text
SINUSOIDAL
```

but the GUI should display:

```text
Sinusoidal
```

---

# 4. Terminal Parameters

Each terminal must support:

```text
Terminal ID

Power
Beacon

Operational State

Optical Power
Wavelength
Modulation
Spot Size
```

GUI representation:

```text
Power:
    ON / OFF

Beacon:
    ON / OFF

Operational State:
    OFF
    STANDBY
    BEACONING
    LINKED
    FAULT
```

---

# 5. Optical Parameters

Configurable optical properties:

```text
Optical Power (W)
Wavelength (nm)
Modulation
Spot Size (mrad)
```

Supported modulation:

```text
CW
OOK
PPM
```

Default:

```text
OOK
```

Do not implement additional modulation types unless already required by the existing repository.

---

# 6. Spot Size Definition

Define:

> `Spot Size (mrad)` = full angular beam width/divergence.

This definition must be documented in code and GUI metadata.

Internal conversion:

```python
beam_width_rad = spot_size_mrad * 1e-3
```

Approximate beam footprint at range `R`:

```python
beam_diameter_m = R * beam_width_rad
```

Example:

```text
Spot Size = 1 mrad
Range     = 10,000 m

Beam diameter ≈ 10 m
```

Do not ambiguously interpret this parameter as FWHM, radius, or half-angle.

---

# 7. Coordinate System

Use a 2D Cartesian world.

```text
+Y
 ^
 |
 |
 +------------> +X
(0,0)
```

Define:

```text
0°   = +X
90°  = +Y
180° = -X
-90° = -Y
```

Angles are degrees in the GUI.

Use radians internally where appropriate.

Distances are metres.

Velocity is metres/second.

Time is seconds internally.

---

# 8. Main Enumerations

Create:

```python
from enum import Enum


class FormationShape(str, Enum):
    SINGLE = "single"
    LINE = "line"
    CIRCLE = "circle"
    ARC = "arc"
    GRID = "grid"
    RECTANGLE = "rectangle"
    V_FORMATION = "v_formation"


class MotionProfile(str, Enum):
    REST = "rest"
    CONSTANT_VELOCITY = "constant_velocity"
    LINEAR = "linear"
    CIRCULAR = "circular"
    SINUSOIDAL = "sinusoidal"
    FIGURE_8 = "figure_8"
    RANDOM = "random"


class OperationalState(str, Enum):
    OFF = "off"
    STANDBY = "standby"
    BEACONING = "beaconing"
    LINKED = "linked"
    FAULT = "fault"


class ModulationType(str, Enum):
    CW = "cw"
    OOK = "ook"
    PPM = "ppm"
```

---

# 9. Configuration Data Models

Separate scenario-level configuration from individual terminal configuration.

## 9.1 Vector2

```python
@dataclass
class Vector2:
    x: float
    y: float
```

---

# 10. Remote Formation Configuration

Implement:

```python
@dataclass
class RemoteFormationConfig:
    terminal_count: int = 1

    formation_shape: FormationShape = (
        FormationShape.SINGLE
    )

    motion_profile: MotionProfile = (
        MotionProfile.CONSTANT_VELOCITY
    )

    terminal_spacing_m: float = 100.0

    speed_mps: float = 10.0

    heading_deg: float = 0.0
```

GUI metadata should provide:

```text
terminal_count
    integer
    min = 1

formation_shape
    dropdown

motion_profile
    dropdown

terminal_spacing_m
    float
    unit = m

speed_mps
    float
    unit = m/s

heading_deg
    float
    unit = deg
    range = [-180, 180]
```

---

# 11. Remote Terminal Configuration

Implement:

```python
@dataclass
class RemoteTerminalConfig:
    terminal_id: str = "RT-001"

    power_enabled: bool = True

    beacon_enabled: bool = True

    operational_state: OperationalState = (
        OperationalState.BEACONING
    )

    optical_power_w: float = 0.5

    wavelength_nm: float = 1550.0

    modulation: ModulationType = (
        ModulationType.OOK
    )

    spot_size_mrad: float = 1.0
```

---

# 12. Complete Scenario Configuration

Implement:

```python
@dataclass
class RemoteScenarioConfig:
    formation: RemoteFormationConfig

    terminals: list[RemoteTerminalConfig]
```

The GUI should edit this configuration.

The simulation runtime should never directly depend on GUI widgets.

---

# 13. Configuration Validation

Implement a central validation system.

Validate:

```text
Terminal Count >= 1

Number of terminal configs == Terminal Count

Terminal IDs are unique

Speed >= 0

Spacing >= 0

Optical Power >= 0

Spot Size > 0

Wavelength is within supported simulator range

Heading ∈ [-180°, 180°]

SINGLE formation requires exactly one terminal
```

Example validation errors:

```text
Terminal count is 5 but 4 terminal configurations exist.

Terminal ID 'RT-002' is duplicated.

Speed cannot be negative.

Terminal spacing cannot be negative.

Optical power cannot be negative.

Spot size must be greater than zero.

SINGLE formation requires exactly one terminal.
```

Do not silently correct invalid user input.

---

# 14. Runtime Data Models

Do not store runtime state in the GUI configuration objects.

Create a separate runtime model.

```python
@dataclass
class RemoteTerminalRuntime:
    terminal_id: str

    position_m: Vector2

    velocity_mps: Vector2

    range_m: float

    los_angle_deg: float

    beam_angle_deg: float

    pointing_error_deg: float

    beam_width_rad: float

    beam_diameter_m: float

    effective_emission_enabled: bool

    instantaneous_power_w: float

    beacon_sequence: int

    operational_state: OperationalState
```

---

# 15. Scenario Runtime

Create:

```python
@dataclass
class RemoteScenarioRuntime:
    simulation_time_s: float

    formation_center_m: Vector2

    terminals: list[RemoteTerminalRuntime]
```

This contains the live simulation state.

---

# 16. Truth State vs Beacon State

This distinction is mandatory.

The Remote Terminal has an internal:

```text
TRUE STATE
```

and separately creates:

```text
BEACON NAVIGATION STATE
```

The beacon must NOT simply reference live mutable position data.

At frame generation, sample the state.

Example:

```text
Simulation time:
10.000 s

Position:
X = 1000 m
Y = 500 m
```

The beacon contains:

```text
timestamp = 10.000 s
X = 1000 m
Y = 500 m
```

The terminal may move immediately afterward.

The already-generated beacon must still contain:

```text
1000, 500
```

This is the definition of **last-known location**.

---

# 17. Navigation State Data Model

Create:

```python
@dataclass
class NavigationState2D:
    timestamp_ms: int
    position_x_m: float
    position_y_m: float
```

Keep the first implementation intentionally small.

Do NOT add:

```text
velocity
acceleration
heading
covariance
attitude
```

to the first navigation payload unless necessary for compatibility.

The future architecture should allow these to be added later.

---

# 18. Last-Known-Location Beacon

The beacon must include:

```text
Terminal ID
Sequence
Timestamp
Position X
Position Y
```

Conceptually:

```text
┌──────────────────────────┐
│ Terminal ID              │
├──────────────────────────┤
│ Sequence Number          │
├──────────────────────────┤
│ Existing Beacon Fields   │
├──────────────────────────┤
│ Navigation Extension     │
│   Timestamp              │
│   Position X             │
│   Position Y             │
├──────────────────────────┤
│ CRC                      │
└──────────────────────────┘
```

Do not create a completely separate beacon protocol.

Extend the existing shared beacon payload.

---

# 19. Protocol Extension

Inspect:

```text
common/protocol/beacon/
```

before modifying anything.

Use the existing:

```text
frame.py
payload.py
ook.py
crc.py
```

architecture.

Add an optional navigation extension to the existing payload.

Recommended capability:

```text
CAP_NAVIGATION_STATE
```

Use the first currently-unused capability bit.

Do not reuse an existing capability flag.

---

# 20. Navigation Payload Encoding

Encode:

```text
timestamp_ms : uint32
position_x_m : float32
position_y_m : float32
```

Use:

```text
big-endian
IEEE-754
```

Total:

```text
12 bytes
```

Do not use JSON.

Do not use pickle.

Do not encode values as textual strings.

Use compact deterministic binary serialization.

---

# 21. Navigation Serialization API

Create clear helpers:

```python
encode_navigation_state(
    state: NavigationState2D
) -> bytes
```

and:

```python
decode_navigation_state(
    data: bytes
) -> NavigationState2D
```

They must:

* validate input length
* handle malformed data safely
* preserve deterministic encoding
* round-trip within floating-point tolerance

---

# 22. Backward Compatibility

Existing payloads without navigation state must continue to decode.

Expected behavior:

```text
Old payload
    ↓
Decode
    ↓
navigation_state = None
```

New payload:

```text
New payload
    ↓
Decode
    ↓
navigation_state = populated
```

Do not make the navigation extension mandatory.

---

# 23. Decoded Payload Model

Extend the existing decoded payload model with:

```python
navigation_state: NavigationState2D | None
```

Do not create a separate decoded-payload class.

---

# 24. Beacon Frame Generation

The remote beacon-generation process should be:

```text
Terminal Runtime
      │
      ▼
Sample Current Position
      │
      ▼
NavigationState2D
      │
      ├───────────────┐
      │               │
      ▼               ▼
 Timestamp         X / Y
      │               │
      └───────┬───────┘
              ▼
       Beacon Payload
              │
              ▼
             CRC
              │
              ▼
          Frame Encoder
              │
              ▼
             OOK
              │
              ▼
        Optical Emission
```

---

# 25. Important Beacon Sampling Rule

The navigation state is sampled **once per beacon frame**.

Correct:

```text
FRAME START
    ↓
sample timestamp
sample X
sample Y
    ↓
encode complete frame
    ↓
transmit bits
```

Incorrect:

```text
every OOK chip
    ↓
read current position
```

The latter would make the payload internally inconsistent.

---

# 26. Sequence Number

Maintain:

```python
beacon_sequence: int
```

Every new beacon frame increments it.

Expected:

```text
253
254
255
0
1
2
...
```

Handle wrap correctly.

Do not use naive integer ordering such as:

```python
new_sequence > old_sequence
```

when determining sequence freshness.

---

# 27. Motion Architecture

Create:

```text
MotionModel
```

responsible only for motion.

Input:

```text
speed
heading
motion_profile
simulation_time
dt
```

Output:

```text
position
velocity
```

Do not put optical logic inside the motion model.

---

# 28. Motion Profile: REST

Definition:

```text
velocity = 0
```

Position remains fixed.

Example:

```text
t=0    → (100,200)
t=5    → (100,200)
t=20   → (100,200)
```

---

# 29. Motion Profile: CONSTANT VELOCITY

Use:

```python
vx = speed * cos(heading)
vy = speed * sin(heading)
```

Then:

```python
x += vx * dt
y += vy * dt
```

Example:

```text
Speed   = 50 m/s
Heading = 30°

Vx ≈ 43.30 m/s
Vy = 25.00 m/s
```

This derived velocity must be visible as telemetry but not independently editable.

---

# 30. Motion Profile: LINEAR

Interpret `LINEAR` as a deterministic straight-line motion profile with a simple speed transition.

Use the configured heading.

For example:

```text
initial speed = 0
speed ramps to configured speed
then continues linearly
```

Use a fixed internal ramp duration.

Do NOT add another GUI field unless explicitly required.

The exact internal ramp duration should be a constant in the motion model.

---

# 31. Motion Profile: CIRCULAR

Move around a circular path.

Internally derive a radius from a reasonable simulator default.

The heading determines the initial tangent direction.

Example:

```text
             ●
        ●         ●
      ●      RT     ●
        ●         ●
             ●
```

The terminal continuously follows the path.

Do not add radius/angular velocity as new user-facing parameters for this task.

Use reasonable internal constants and document them.

---

# 32. Motion Profile: SINUSOIDAL

Use a deterministic oscillating trajectory.

Recommended conceptual model:

```python
x(t) = x0 + vx * t

y(t) = y0 + A * sin(omega * t)
```

The terminal generally moves along the heading direction while oscillating perpendicular to it.

Use internal:

```text
amplitude
frequency
```

constants.

Do not expose them in the GUI yet.

---

# 33. Motion Profile: FIGURE-8

Implement a smooth 2D figure-eight trajectory.

A suitable parametric form is:

```python
x = A * sin(theta)
y = B * sin(theta) * cos(theta)
```

where:

```python
theta = omega * t
```

Rotate the resulting trajectory according to `heading_deg`.

Use internal default amplitude/frequency values.

Do not expose them as GUI parameters in the first implementation.

---

# 34. Motion Profile: RANDOM

Implement deterministic, bounded random motion.

Important requirements:

* Use a seeded random generator.
* Same seed + same scenario → same trajectory.
* Do not use uncontrolled global randomness.
* Avoid instantaneous teleportation.
* Maintain continuous position.
* Maintain bounded velocity.
* Avoid unrealistic discontinuous heading jumps.

A simple implementation can generate smooth random acceleration or heading perturbations.

Use an internal seed.

Do not initially expose random-motion amplitude parameters through the GUI.

---

# 35. Formation Manager

Create:

```text
FormationManager
```

It generates terminal offsets relative to the formation center.

Supported shapes:

```text
Single
Line
Circle
Arc
Grid
Rectangle
V Formation
```

---

# 36. SINGLE Formation

Requirement:

```text
terminal_count == 1
```

Offset:

```text
(0, 0)
```

---

# 37. LINE Formation

Place terminals evenly along one axis.

Example with 5:

```text
RT-001    RT-002    RT-003    RT-004    RT-005
  ●---------●---------●---------●---------●
```

Spacing:

```text
terminal_spacing_m
```

Center the complete formation around the formation origin.

---

# 38. CIRCLE Formation

Distribute terminals around a circle.

Even angular spacing:

```text
angle_i = 2πi / N
```

Derive a radius from the configured spacing.

Center the formation at the origin.

---

# 39. ARC Formation

Distribute terminals along a circular arc.

Use an internal default arc angle.

For example:

```text
        ●
     ●     ●
   ●         ●
```

Center the arc around the formation origin.

Use terminal spacing as the approximate neighboring distance.

Do not introduce a GUI parameter for arc angle in this initial version.

Use a documented internal constant.

---

# 40. GRID Formation

Generate a roughly square grid.

Example:

```text
●──●──●
│  │  │
●──●──●
│  │  │
●──●──●
```

Use terminal spacing for horizontal and vertical spacing.

For a non-square terminal count:

```text
N = 7
```

generate:

```text
3 × 3 grid
```

and populate seven positions.

Center the occupied positions.

---

# 41. RECTANGLE Formation

Use terminals along the perimeter of a rectangle.

Example:

```text
●──────●──────●
│             │
●             ●
│             │
●──────●──────●
```

Use terminal spacing as the approximate spacing between neighboring terminals.

For too few terminals, gracefully degrade to the closest sensible perimeter arrangement.

---

# 42. V FORMATION

Use a leader at the front:

```text
              RT-001
                ●
               / \
              /   \
          RT-002   RT-003
             ●       ●
            /         \
        RT-004        RT-005
           ●             ●
```

Spacing controls adjacent terminal separation.

Center the complete formation.

---

# 43. Formation Heading

After generating local formation coordinates, rotate the entire formation:

```python
world_offset = rotation(heading_deg) @ local_offset
```

Then:

```python
terminal_position =
    formation_center +
    world_offset
```

Heading therefore controls the orientation of the entire formation.

---

# 44. Formation + Motion Interaction

Formation geometry and motion must remain separate.

Think:

```text
FORMATION
    ↓
relative positions

MOTION
    ↓
formation-center movement

FINAL TERMINAL POSITION
    =
formation center
+
rotated formation offset
```

This is important.

For example:

```text
formation center → moves east

V formation → remains V-shaped

heading → rotates the entire formation
```

Do not make each terminal independently drift away from the formation unless the selected motion profile explicitly requires it.

---

# 45. Formation Motion Model

Use a formation center trajectory.

Conceptually:

```text
                 Formation
                     │
                     ▼
              Formation Center
                     │
                     ▼
              Motion Profile
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
     Center Position       Center Velocity
          │                     │
          └──────────┬──────────┘
                     ▼
             Formation Offsets
                     │
                     ▼
             Terminal Positions
```

This keeps formations coherent.

---

# 46. Geometry Engine

Create a small:

```text
GeometryEngine
```

with functions for:

```text
range
LOS angle
relative vector
```

For two points:

```python
dx = target_x - source_x
dy = target_y - source_y

range_m = sqrt(dx**2 + dy**2)

los_angle_deg = degrees(
    atan2(dy, dx)
)
```

Do not put beam rendering or beacon encoding here.

---

# 47. Pointing Model

Create a very small pointing model.

The primary beam direction should follow the nominal LOS toward the intended reference point.

For the simplified 2D model:

```python
beam_angle = los_angle + pointing_error
```

The pointing-error model should provide:

```text
small bias
small jitter
```

internally.

Do not expose these in the GUI during this task.

If a suitable pointing-error utility already exists in the repository, reuse it.

Do not create duplicate disturbance models.

---

# 48. Optical Beam Model

Create:

```text
BeamModel
```

Inputs:

```text
optical power
wavelength
modulation
spot size
beam angle
range
```

Outputs:

```text
OpticalEmission
```

Model the beam approximately as an angular Gaussian or similarly smooth beam profile.

No detailed electromagnetic simulation is required.

---

# 49. Optical Emission Data Model

Use:

```python
@dataclass
class OpticalEmission:
    active: bool

    wavelength_nm: float

    instantaneous_power_w: float

    modulation: ModulationType

    beam_center_angle_deg: float

    beam_width_rad: float
```

This object is what the environment/propagation layer consumes.

---

# 50. Emission Logic

Implement:

```python
def is_emitting(config) -> bool:
    if not config.power_enabled:
        return False

    if not config.beacon_enabled:
        return False

    if config.operational_state in {
        OperationalState.OFF,
        OperationalState.STANDBY,
        OperationalState.FAULT,
    }:
        return False

    return True
```

Result:

```text
Power OFF
    → no emission

Beacon OFF
    → no beacon

OFF
    → no emission

STANDBY
    → no emission

BEACONING
    → beacon emission

LINKED
    → beacon/optical emission

FAULT
    → no emission
```

---

# 51. Beacon Generation

Reuse the existing beacon encoder where possible.

The beacon generator is responsible for:

```text
creating payload
adding terminal identity
adding sequence
adding navigation state
creating protocol frame
modulating frame
```

It must NOT calculate:

```text
formation
trajectory
range
beam footprint
```

Those belong elsewhere.

---

# 52. Beacon Generation Timing

A new beacon frame should be generated according to the existing beacon timing/chip-rate architecture.

At the beginning of a new frame:

```text
sample navigation state
encode payload
increment sequence appropriately
frame payload
generate modulation
```

Then transmit that fixed frame until completion.

Do not continuously rebuild the frame using the current position.

---

# 53. Operational State Behavior

The operational state should control whether optical activity is allowed.

Use:

```text
OFF
STANDBY
BEACONING
LINKED
FAULT
```

Keep automatic state transitions minimal.

For the first implementation, configuration may directly select the state.

Do not implement complicated autonomous transitions.

---

# 54. GUI Design

The GUI should have two levels.

## Formation/Motion Panel

```text
REMOTE TERMINAL SCENARIO
────────────────────────────────────

FORMATION

Terminal Count       [ 5          ]
Formation Shape      [ V Formation ▼]
Terminal Spacing     [ 100.0 ] m


MOTION

Motion Profile       [ Constant Velocity ▼]
Speed                [ 50.0 ] m/s
Heading              [ 30.0 ] deg
```

Do not make velocity independently editable.

Show derived velocity as read-only telemetry.

---

# 55. Terminal Configuration Panel

For every terminal:

```text
RT-001
────────────────────────────────────

IDENTITY
Terminal ID          [ RT-001 ]

EMISSION
Power                [ ON ]
Beacon               [ ON ]
Operational State    [ BEACONING ▼ ]

OPTICAL
Optical Power        [ 0.50 ] W
Wavelength           [ 1550 ] nm
Modulation           [ OOK ▼ ]
Spot Size            [ 1.00 ] mrad
```

---

# 56. GUI Read-Only Runtime Telemetry

The GUI may display derived values:

```text
POSITION
X
Y

VELOCITY
Vx
Vy

GEOMETRY
Range
LOS Angle

BEAM
Beam Angle
Pointing Error
Beam Width
Beam Diameter

BEACON
Sequence
Navigation Timestamp

EMISSION
Effective Emission
Instantaneous Optical Power
```

These must not be editable through the normal parameter editor.

---

# 57. GUI Field Metadata

Use a metadata/schema system so that the GUI does not hard-code the configuration structure.

Each parameter should contain:

```text
label
control type
unit
minimum
maximum
step
group
description
```

Example:

```python
{
    "speed_mps": {
        "label": "Speed",
        "control": "float",
        "unit": "m/s",
        "min": 0.0,
        "max": 10000.0,
        "step": 0.1,
        "group": "Motion",
    }
}
```

Do this consistently.

---

# 58. Recommended Folder Structure

Keep the implementation compact.

```text
remote_terminal/
│
├── __init__.py
│
├── config.py
├── models.py
├── formation.py
├── motion.py
├── geometry.py
├── pointing.py
├── beacon_encoder.py
├── optics.py
├── terminal.py
└── scenario.py
```

Responsibilities:

```text
config.py
    Enums
    GUI-facing configuration models
    Validation

models.py
    Vector2
    NavigationState2D
    Runtime state
    OpticalEmission

formation.py
    FormationManager

motion.py
    MotionModel

geometry.py
    GeometryEngine

pointing.py
    PointingModel

beacon_encoder.py
    Beacon generation
    Navigation payload integration

optics.py
    BeamModel
    Optical emission

terminal.py
    One RemoteTerminal orchestration

scenario.py
    RemoteTerminalManager
    Scenario update
```

Do not create unnecessary additional files.

---

# 59. Shared Beacon Protocol

Modify only the existing common protocol implementation.

Expected location:

```text
common/protocol/beacon/
```

Primary file:

```text
payload.py
```

Potentially update:

```text
frame.py
```

only if required by payload sizing/serialization.

Reuse:

```text
ook.py
crc.py
```

Do not duplicate them under `remote_terminal/`.

---

# 60. Suggested Shared Protocol Model

Extend the existing payload model with:

```python
@dataclass
class NavigationState2D:
    timestamp_ms: int
    position_x_m: float
    position_y_m: float
```

Then:

```python
@dataclass
class DecodedPayload:
    ...
    navigation_state: NavigationState2D | None = None
```

Use the repository's existing structures rather than replacing them wholesale.

---

# 61. Navigation Capability

Add:

```text
CAP_NAVIGATION_STATE
```

using an unused capability bit.

The presence of the capability means:

```text
navigation extension exists
```

Absence means:

```text
navigation extension should not be assumed
```

This preserves protocol extensibility.

---

# 62. Beacon Example

For a terminal:

```text
Terminal ID       = RT-001
Sequence          = 152
Simulation time   = 12.500 s
X                 = 10342.5 m
Y                 = -2410.75 m
```

The decoded payload should conceptually expose:

```python
DecodedPayload(
    terminal_id="RT-001",
    sequence=152,
    navigation_state=NavigationState2D(
        timestamp_ms=12500,
        position_x_m=10342.5,
        position_y_m=-2410.75,
    ),
)
```

---

# 63. Last-Known-Location Example

At:

```text
t = 10.000 s
position = (1000, 500)
```

a beacon frame is created.

Then at:

```text
t = 10.500 s
position = (1050, 500)
```

the original beacon must still contain:

```text
timestamp = 10.000 s
position = (1000, 500)
```

Do not modify an already-encoded beacon frame.

---

# 64. Formation Example

Configuration:

```text
Terminal Count = 5
Shape = V Formation
Spacing = 100 m
Speed = 50 m/s
Heading = 30°
Motion Profile = Constant Velocity
```

The formation center moves with:

```text
Vx ≈ 43.30 m/s
Vy = 25.00 m/s
```

while the terminal relative offsets preserve the V shape.

---

# 65. Circle Example

```text
Terminal Count = 8
Shape = Circle
Spacing = 100 m
Heading = 45°
```

Expected conceptual geometry:

```text
                 ●

          ●             ●


       ●        CENTER       ●


          ●             ●

                 ●
```

The entire formation is rotated by 45°.

---

# 66. Motion Examples

## Rest

```text
RT position:
(100, 200)

after 10 s:
(100, 200)
```

## Constant Velocity

```text
speed = 10 m/s
heading = 0°

after 10 s:

x = x0 + 100
y = y0
```

## Circular

```text
terminal moves continuously
around a defined circular trajectory
```

## Sinusoidal

```text
forward motion
+
cross-track oscillation
```

## Figure-8

```text
       ╭───╮
      /     \
      \     /
       ╰─╮ ╭╯
         ╰─╯
```

## Random

```text
smoothly varying
bounded trajectory
```

---

# 67. Deterministic Random Motion

Random motion must be reproducible.

Use:

```python
random.Random(seed)
```

not global random calls.

The seed may be an internal scenario value rather than a GUI parameter.

Given:

```text
same configuration
same seed
same simulation timestep
```

the trajectory must be reproducible.

This is important for testing.

---

# 68. Runtime Update Flow

Implement the runtime update approximately as:

```text
RemoteScenarioManager.update(dt)
        │
        ▼
Update formation-center motion
        │
        ▼
Calculate formation offsets
        │
        ▼
For each terminal
        │
        ├── update motion state
        │
        ├── calculate position
        │
        ├── calculate velocity
        │
        ├── calculate geometry
        │
        ├── calculate pointing
        │
        ├── update beacon
        │
        └── update optical emission
        │
        ▼
Return RemoteScenarioRuntime
```

---

# 69. RemoteTerminal Update

Each terminal should conceptually execute:

```python
def update(self, dt: float, simulation_time_s: float):
    self.update_motion(dt)
    self.update_geometry()
    self.update_pointing()
    self.update_beacon(simulation_time_s)
    self.update_optical_emission()
```

Keep this orchestration simple.

Do not make `update()` a giant monolithic function.

---

# 70. Important Architectural Rule

Each subsystem should have one responsibility.

```text
FormationManager
    formation geometry only

MotionModel
    trajectory only

GeometryEngine
    LOS/range only

PointingModel
    beam direction only

BeaconGenerator
    protocol/modulation only

BeamModel
    beam/optical emission only

RemoteTerminal
    orchestration only

RemoteTerminalManager
    multi-terminal orchestration only
```

This separation should be enforced.

---

# 71. Tests

Create/update tests for:

## Configuration

```text
valid configuration
invalid terminal count
duplicate IDs
invalid speed
invalid spacing
invalid optical power
invalid wavelength
invalid spot size
invalid Single configuration
```

## Formation

```text
Single
Line
Circle
Arc
Grid
Rectangle
V Formation
```

Check:

```text
terminal count
spacing
centering
heading rotation
```

## Motion

```text
Rest
Constant Velocity
Linear
Circular
Sinusoidal
Figure-8
Random
```

Verify deterministic expected behavior.

---

# 72. Protocol Tests

Add:

```text
navigation state round-trip
navigation extension absent
navigation extension present
capability bit
malformed navigation extension
old payload compatibility
CRC coverage
sequence behavior
```

---

# 73. Critical Navigation Test

This exact test is required:

```text
t = 10.0
position = (1000, 500)

generate beacon

t = 10.5
position = (1050, 500)

decode original beacon
```

Expected:

```text
timestamp = 10.0
X = 1000
Y = 500
```

not:

```text
X = 1050
```

---

# 74. Emission Tests

Verify:

```text
Power OFF
    → emission inactive

Beacon OFF
    → emission inactive

State OFF
    → emission inactive

State STANDBY
    → emission inactive

State BEACONING
    + Power ON
    + Beacon ON
    → emission active

State LINKED
    + Power ON
    + Beacon ON
    → emission active

State FAULT
    → emission inactive
```

---

# 75. Optical Tests

Verify:

```text
spot_size_mrad
    → correct beam_width_rad

range
    → correct approximate beam diameter

optical power
    → correct instantaneous optical power

wavelength
    → preserved in OpticalEmission

modulation
    → preserved in OpticalEmission
```

---

# 76. Integration Test

Create an end-to-end Remote Terminal test:

```text
Configuration
      ↓
Formation
      ↓
Motion
      ↓
Terminal Position
      ↓
Navigation State
      ↓
Beacon Frame
      ↓
Encoding
      ↓
Decoding
      ↓
Navigation State Verification
      ↓
Optical Emission
```

The test must verify that:

```text
configuration
→ runtime state
→ beacon payload
→ decoded payload
```

remain consistent.

---

# 77. Regression Requirements

Before implementation:

```text
Run existing test suite.
```

After implementation:

```text
Run complete test suite again.
```

Then run the new Remote Terminal tests independently.

Do not claim tests passed unless they were actually executed.

Do not suppress test failures.

Do not weaken tests merely to make them pass.

---

# 78. Error Handling

Do not use:

```python
except Exception:
    pass
```

Use specific exception handling.

Configuration errors should be explicit.

Protocol errors should be contained.

Malformed payloads should not crash the entire simulation.

Invalid user configuration should provide a useful message.

---

# 79. What Must NOT Be Added

Do not add GUI parameters for:

```text
position
velocity vector
initial acceleration
beam angle
pointing bias
pointing jitter
range
beam diameter
beacon sequence
beacon timestamp
navigation payload contents
circular radius
sinusoidal amplitude
sinusoidal frequency
figure-8 amplitude
random-motion amplitude
random seed
```

These are either:

* derived values,
* runtime values,
* internal model parameters,
* or implementation details.

Keep the GUI compact.

---

# 80. Future Extension Points

The architecture should make it possible to later extend the navigation payload from:

```text
timestamp
X
Y
```

to:

```text
timestamp
X
Y
Vx
Vy
uncertainty
```

without replacing the entire beacon protocol.

Likewise, the formation system should allow more shapes later without changing `RemoteTerminal`.

The motion model should allow additional profiles later without changing `FormationManager`.

The optical model should allow more detailed propagation later without changing `MotionModel`.

---

# 81. Final Folder Structure

The desired implementation should look approximately like:

```text
remote_terminal/
│
├── __init__.py
│
├── config.py
│   ├── FormationShape
│   ├── MotionProfile
│   ├── OperationalState
│   ├── ModulationType
│   ├── RemoteFormationConfig
│   ├── RemoteTerminalConfig
│   └── RemoteScenarioConfig
│
├── models.py
│   ├── Vector2
│   ├── NavigationState2D
│   ├── RemoteTerminalRuntime
│   ├── RemoteScenarioRuntime
│   └── OpticalEmission
│
├── formation.py
│   └── FormationManager
│
├── motion.py
│   └── MotionModel
│
├── geometry.py
│   └── GeometryEngine
│
├── pointing.py
│   └── PointingModel
│
├── beacon_encoder.py
│   └── BeaconGenerator
│
├── optics.py
│   └── BeamModel
│
├── terminal.py
│   └── RemoteTerminal
│
└── scenario.py
    └── RemoteTerminalManager
```

Shared protocol:

```text
common/
└── protocol/
    └── beacon/
        ├── frame.py
        ├── payload.py
        ├── ook.py
        └── crc.py
```

---

# 82. Final Architecture Diagram

The final system must conceptually look like this:

```text
                         REMOTE TERMINAL
                               │
                               ▼
                    ┌────────────────────┐
                    │ GUI Configuration  │
                    └─────────┬──────────┘
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
        Formation          Motion           Terminal
         Manager            Model            Config
             │                │                │
             └──────────┬─────┴────────────────┘
                        │
                        ▼
                Terminal Runtime
                        │
             ┌──────────┼───────────┐
             │          │           │
             ▼          ▼           ▼
          Position    Velocity    Identity
             │
             ▼
        Geometry Engine
             │
        ┌────┴────┐
        ▼         ▼
       LOS       Range
        │
        ▼
    Pointing Model
        │
        ▼
      Beam Model
        │
        ├───────────────┐
        │               │
        ▼               ▼
 Optical Power       Beacon
                         │
                 ┌───────┴────────┐
                 │                │
                 ▼                ▼
            Terminal ID      Navigation State
                                  │
                           Timestamp + X + Y
                                  │
                                  ▼
                            Beacon Frame
                                  │
                                  ▼
                             CRC + OOK
                                  │
                                  ▼
                         Optical Emission
```

---

# 83. Final Acceptance Criteria

The task is complete only when:

### GUI

* [ ] Terminal Count works.
* [ ] Formation Shape supports Single, Line, Circle, Arc, Grid, Rectangle, V Formation.
* [ ] Motion Profile supports Rest, Constant Velocity, Linear, Circular, Sinusoidal, Figure-8, Random.
* [ ] Terminal Spacing works.
* [ ] Speed works.
* [ ] Heading works.
* [ ] Terminal ID works.
* [ ] Power ON/OFF works.
* [ ] Beacon ON/OFF works.
* [ ] Operational State works.
* [ ] Optical Power works.
* [ ] Wavelength works.
* [ ] Modulation works.
* [ ] Spot Size works.

### Motion

* [ ] Positions update correctly.
* [ ] Velocity is derived from speed and heading where applicable.
* [ ] Formation geometry is maintained.
* [ ] Formation heading rotates the formation correctly.
* [ ] All requested motion profiles exist.
* [ ] Random motion is reproducible.

### Beacon

* [ ] Terminal identity is transmitted.
* [ ] Sequence number is transmitted.
* [ ] Navigation capability is encoded.
* [ ] Timestamp is transmitted.
* [ ] X position is transmitted.
* [ ] Y position is transmitted.
* [ ] Navigation state is sampled once per frame.
* [ ] CRC covers the extended frame.
* [ ] Old payloads remain decodable.

### Optical

* [ ] Power switch works.
* [ ] Beacon switch works.
* [ ] Operational state affects emission correctly.
* [ ] Wavelength is preserved.
* [ ] Modulation is preserved.
* [ ] Spot size maps to angular beam width.
* [ ] Range produces the expected beam footprint.
* [ ] Pointing contains small realistic internal error/jitter.

### Architecture

* [ ] Configuration is separate from runtime state.
* [ ] Formation logic is separate from motion.
* [ ] Motion is separate from geometry.
* [ ] Geometry is separate from optics.
* [ ] Beacon generation is separate from beam modeling.
* [ ] Existing shared beacon protocol is reused.
* [ ] No duplicate protocol implementation exists.
* [ ] No unrelated subsystem is redesigned.
* [ ] No broad exception swallowing is introduced.

### Testing

* [ ] Existing tests pass.
* [ ] New Remote Terminal tests pass.
* [ ] Navigation round-trip passes.
* [ ] Last-known-location temporal test passes.
* [ ] Formation tests pass.
* [ ] Motion tests pass.
* [ ] Emission tests pass.
* [ ] Optical tests pass.
* [ ] Regression suite passes.

---

# 84. Required Final Report

After implementation, report:

```text
1. Files created
2. Files modified
3. Data models added
4. GUI parameters implemented
5. Formation shapes implemented
6. Motion profiles implemented
7. Beacon protocol changes
8. Navigation payload format
9. Runtime architecture
10. Tests added
11. Tests actually executed
12. Test results
13. Compatibility issues
14. Assumptions
```

Explicitly state the navigation payload format:

```text
timestamp_ms : uint32
position_x_m : float32
position_y_m : float32
```

Explicitly state the units:

```text
Position      = m
Velocity      = m/s
Speed         = m/s
Optical Power = W
Wavelength    = nm
Spot Size     = mrad
Timestamp     = ms
GUI angles    = degrees
```

Do not claim anything was implemented or tested unless you actually performed the work.

---

# 85. Final Principle

Keep the Remote Terminal simple.

The intended architecture is:

```text
USER CONFIG
     ↓
FORMATION
     ↓
MOTION
     ↓
POSITION
     ↓
GEOMETRY
     ↓
BEAM
     ↓
BEACON
     ↓
OPTICAL EMISSION
```

The defining feature of this implementation is:

```text
THE BEACON CARRIES THE REMOTE TERMINAL'S
LAST-KNOWN 2D LOCATION WITH A TIMESTAMP.
```

This information is a **sampled state report**, not an omniscient truth channel.

The implementation must preserve:

```text
TRUE REMOTE STATE
        ≠
BEACON-REPORTED STATE
```

and the architecture must remain compact, deterministic, testable, and suitable for a realistic 2D FSOC/PAT simulation.
