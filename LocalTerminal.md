Local Terminal Architecture:

LocalTerminal
├── identity
├── state
├── position
├── camera
├── ptz
├── display
├── angularModel
├── realism
├── acquisition
├── detection
├── tracking
└── communication

The first five sections correspond directly to your current PTZ configuration. The remaining sections represent the operational behavior needed for the Local Terminal to interact with the Remote Terminal.

Complete Architecture:

LocalTerminal
│
├── identity
│   ├── id
│   ├── name
│   ├── type
│   └── platformId
│
├── state
│   ├── operationalState
│   ├── powerState
│   ├── ptzState
│   ├── acquisitionState
│   ├── detectionState
│   ├── trackingState
│   └── linkState
│
├── position
│   ├── x
│   ├── y
│   ├── z
│   └── referenceFrame
│
├── camera
│   ├── type
│   ├── sensorType
│   ├── resolution
│   │   ├── width
│   │   └── height
│   └── fieldOfView
│       ├── x
│       └── y
│
├── ptz
│   ├── pan
│   │   ├── min
│   │   ├── max
│   │   ├── home
│   │   ├── speed
│   │   └── resolution
│   │
│   ├── tilt
│   │   ├── min
│   │   ├── max
│   │   ├── home
│   │   ├── speed
│   │   └── resolution
│   │
│   ├── latency
│   ├── updateRate
│   └── controlMode
│
├── display
│   ├── cameraScreen
│   │   ├── width
│   │   └── height
│   
│
├── angularModel
│   ├── pixelToAngleX
│   ├── pixelToAngleY
│   ├── angleToPixelX
│   └── angleToPixelY
│
├── realism
│   ├── maxAcceleration
│   ├── backlash
│   ├── encoderSigma
│   └── latencyJitter
│
├── acquisition
│   ├── mode
│   ├── searchPattern
│   ├── searchRegion
│   ├── searchSpeed
│   └── timeout
│
├── detection
│   ├── wavelength
│   ├── bandwidth
│   ├── intensityThreshold
│   ├── minimumSNR
│   ├── expectedSpotSize
│   ├── modulation
│   └── confidenceThreshold
│
├── tracking
│   ├── mode
│   ├── algorithm
│   ├── updateRate
│   ├── prediction
│   ├── smoothing
│   └── lostTargetBehavior
│
└── communication
    ├── terminalId
    ├── protocol
    ├── capabilities
    └── linkState

1) Identity:

Recommended Default (Fixed No Change):
{
  "id": "LT-001",
  "name": "Local PTZ Camera 01",
  "type": "LOCAL_OPTICAL_TERMINAL",
  "platformId": "PLATFORM-001"
}

2) State: State is runtime information, not configuration.

state
├── operationalState
├── powerState
├── ptzState
├── acquisitionState
├── detectionState
├── trackingState
└── linkState

Recommended Values:
operationalState:
    OFF
    INITIALIZING
    STANDBY
    ACTIVE
    FAULT

powerState:
    OFF
    ON

ptzState:
    IDLE
    MOVING
    AT_POSITION
    LIMIT_REACHED
    FAULT

acquisitionState:
    IDLE
    SEARCHING
    ACQUIRING
    ACQUIRED

detectionState:
    NO_TARGET
    DETECTING
    TARGET_CONFIRMED

trackingState:
    OFF
    TRACKING
    LOST
    REACQUIRING

linkState:
    NO_LINK
    OPTICAL_LOCK
    HANDSHAKE
    CONNECTED
	
Note: The control deck should display these rather than allow arbitrary editing.

4) Position: This represents where the Local Terminal physically exists.
Example: 
{
  "x": 1000.0,
  "y": 500.0,
  "z": 100.0,
  "referenceFrame": "WORLD"
}

Note: This is separate from PTZ pan/tilt.

position
    = where the camera is

ptz.pan / ptz.tilt
    = where the camera is looking

5) Camera: 
camera
├── type
├── sensorType
├── resolution
│   ├── width
│   └── height
└── fieldOfView
    ├── x
    └── y
	
Defaults:
Camera Type:          Monochrome
Sensor Type:          Focal Plane Array

Resolution W:         640 px
Resolution H:         480 px

FOV X:                4.0 deg
FOV Y:                3.0 deg

6) PTZ: 
ptz
├── pan
│   ├── min
│   ├── max
│   ├── home
│   ├── speed
│   └── resolution
│
├── tilt
│   ├── min
│   ├── max
│   ├── home
│   ├── speed
│   └── resolution
│
├── latency
├── updateRate
└── controlMode

Defaults:
Pan Min:              0
Pan Max:              0

Tilt Min:             0
Tilt Max:             0

Home Pan:             1000
Home Tilt:            1000

Pan Speed:            5.0 deg/s
Tilt Speed:           5.0 deg/s

Resolution:           0.10 px

Latency:              12 ms

Update Rate:          30 Hz

One thing to verify:
Preserve the values exactly but the units for PAN MIN / MAX, TILT MIN / MAX HOME PAN / TILT need to be explicitly defined in the app. 1000 is not obviously an angle value, so it may be an internal PTZ/encoder coordinate.
Thta should be settled before Implementing validation.

7) Display: This should be independent from the physical sensor.
display
├── cameraScreen
│   ├── width
│   └── height

Defaults: 
Camera Screen Width:   2000
Camera Screen Height:  2000

8) Angular Model:
This is where I would make a significant architectural improvement.
Do not treat 109 µrad/px as an independent configurable parameter.
it is derived from FOV + Sensor Resolution

For X: FOVx / W
For defaults: 4 deg / 640 = 0.00625 deg / px
Which is approx: 109.08 μrad / px

For Y: FOVy / H
For defaults: 3 deg / 480 = 109.08 μrad / px (Approx)

Therefore:
angularModel
├── pixelToAngleX
├── pixelToAngleY
├── angleToPixelX
└── angleToPixelY

Example:
{
  "angularModel": {
    "pixelToAngleX": 109.083,
    "pixelToAngleY": 109.083,
    "angleToPixelX": 0.009167,
    "angleToPixelY": 0.009167,
    "unit": "urad_per_pixel"
  }
}

These values should be calculated automatically.

9) realism: This section models the difference between an ideal mathematical PTZ and a realistic mechanical PTZ.
realism
├── maxAcceleration
├── backlash
├── encoderSigma
└── latencyJitter

Defaults:
Maximum Acceleration:   20.0 deg/s²
Backlash:               0.25 px
Encoder σ:              0.040 px
Latency Jitter:         1.2 ms

These parameters should be under something like: Advance -> Simulation Realism
rather than occupying the main operational panel.

10) Acquisition:
The Local Terminal has to determine how it searches for the Remote Terminal.
acquisition
├── mode
├── searchPattern
├── searchRegion
├── searchSpeed
└── timeout

Recommended:
mode:
    MANUAL
    SEARCH
    AUTO_ACQUISITION
    TARGET_POINTING

searchPattern:
    RASTER
    SPIRAL
    SECTOR
    GRID
    CUSTOM
	
Example:
{
  "acquisition": {
    "mode": "SEARCH",
    "searchPattern": "RASTER",
    "searchRegion": {
      "panMin": -20,
      "panMax": 20,
      "tiltMin": -10,
      "tiltMax": 10
    },
    "searchSpeed": 15.0,
    "timeout": 30
  }
}

11) Detection:
The Remote Terminal emits the beacon.
The Local Terminal detects that beacon.
Therefore the Local Terminal needs a detection model.

detection
├── wavelength
├── bandwidth
├── intensityThreshold
├── minimumSNR
├── expectedSpotSize
├── modulation
└── confidenceThreshold

Example:
{
  "detection": {
    "wavelength": 1550,
    "bandwidth": 10,
    "intensityThreshold": 0.0,
    "minimumSNR": 8.0,
    "expectedSpotSize": {
      "value": 3.0,
      "tolerance": 0.5,
      "unit": "mrad"
    },
    "modulation": {
      "type": "AM",
      "frequency": 10.0,
      "unit": "kHz"
    },
    "confidenceThreshold": 0.85
  }
}

This is where your Remote Terminal targetSignature gets consumed.

12) tracking: After detection, the Local Terminal can track the target.
tracking
├── mode
├── algorithm
├── updateRate
├── prediction
├── smoothing
└── lostTargetBehavior

Example: 
{
  "tracking": {
    "mode": "OFF",
    "algorithm": "CENTROID",
    "updateRate": 30,
    "prediction": true,
    "predictionHorizon": 0.5,
    "smoothing": 0.2,
    "lostTargetBehavior": "RESUME_SEARCH"
  }
}

This gives:
Search -> Detection -> Target Confirmed -> Tracking -> PTZ Commands

13) Communication: 
Communication should remain separate from camera behavior.

communication
├── terminalId
├── protocol
├── capabilities
└── linkState

Example:
{
  "communication": {
    "terminalId": "LT-001",
    "protocol": "OPTICAL_LINK",
    "capabilities": [
      "OPTICAL_RX",
      "OPTICAL_TX",
      "TRACKING"
    ],
    "linkState": "NO_LINK"
  }
}

Note: The Local Terminal's optical sensor may detect the Remote Terminal even when:
Again detection ad communication should not be conflated.

Complete Example:
{
  "localTerminal": {

    "identity": {
      "id": "LT-001",
      "name": "Local PTZ Camera 01",
      "type": "LOCAL_OPTICAL_TERMINAL",
      "platformId": "PLATFORM-001"
    },

    "state": {
      "operationalState": "STANDBY",
      "powerState": "ON",
      "ptzState": "IDLE",
      "acquisitionState": "IDLE",
      "detectionState": "NO_TARGET",
      "trackingState": "OFF",
      "linkState": "NO_LINK"
    },

    "position": {
      "x": 0.0,
      "y": 0.0,
      "z": 0.0,
      "referenceFrame": "WORLD"
    },

    "camera": {
      "type": "MONOCHROME",
      "sensorType": "FOCAL_PLANE_ARRAY",

      "resolution": {
        "width": 640,
        "height": 480
      },

      "fieldOfView": {
        "x": 4.0,
        "y": 3.0
      }
    },

    "ptz": {

      "pan": {
        "min": 0,
        "max": 0,
        "home": 1000,
        "speed": 5.0,
        "resolution": 0.10
      },

      "tilt": {
        "min": 0,
        "max": 0,
        "home": 1000,
        "speed": 5.0,
        "resolution": 0.10
      },

      "latency": 12,
      "updateRate": 30,
      "controlMode": "MANUAL"
    },

    "display": {

      "cameraScreen": {
        "width": 2000,
        "height": 2000
      },

      "godView": {
        "width": 2000,
        "height": 2000
      },

      "worldSize": 2000.5
    },

    "angularModel": {
      "pixelToAngleX": 109.083,
      "pixelToAngleY": 109.083,
      "unit": "urad_per_pixel"
    },

    "realism": {
      "maxAcceleration": 20.0,
      "backlash": 0.25,
      "encoderSigma": 0.040,
      "latencyJitter": 1.2
    },

    "acquisition": {
      "mode": "SEARCH",
      "searchPattern": "RASTER",
      "searchRegion": {
        "panMin": -20,
        "panMax": 20,
        "tiltMin": -10,
        "tiltMax": 10
      },
      "searchSpeed": 15.0,
      "timeout": 30
    },

    "detection": {
      "wavelength": 1550,
      "bandwidth": 10,
      "intensityThreshold": 0.0,
      "minimumSNR": 8.0,
      "expectedSpotSize": {
        "value": 3.0,
        "tolerance": 0.5,
        "unit": "mrad"
      },
      "modulation": {
        "type": "AM",
        "frequency": 10.0,
        "unit": "kHz"
      },
      "confidenceThreshold": 0.85
    },

    "tracking": {
      "mode": "OFF",
      "algorithm": "CENTROID",
      "updateRate": 30,
      "prediction": true,
      "predictionHorizon": 0.5,
      "smoothing": 0.2,
      "lostTargetBehavior": "RESUME_SEARCH"
    },

    "communication": {
      "terminalId": "LT-001",
      "protocol": "OPTICAL_LINK",
      "capabilities": [
        "OPTICAL_RX",
        "OPTICAL_TX",
        "TRACKING"
      ],
      "linkState": "NO_LINK"
    }
  }
}

Control Deck Designing:

Your existing A–E structure should remain the configuration screen:
A — SENSOR / FOV
B — PAN-TILT MECHANICS
C — DISPLAY / SCREEN
D — PIXEL → ANGLE
E — REALISM / MECHANICAL ERRORS

Then add operational tabs:
F — ACQUISITION
G — DETECTION
H — TRACKING
I — COMMUNICATION

So the final Local Terminal UI becomes:
LOCAL TERMINAL
│
├── CONFIGURATION
│   ├── A Sensor / FOV
│   ├── B Pan-Tilt Mechanics
│   ├── C Display / Screen
│   ├── D Pixel → Angle
│   └── E Realism
│
└── OPERATIONS
    ├── F Acquisition
    ├── G Detection
    ├── H Tracking
    └── I Communication
	
That separation is preferable to putting everything into one large configuration panel.
Most important design rule
The architecture should distinguish configuration, runtime state, derived values, and simulation behavior:

CONFIGURATION
    Camera
    PTZ limits/speeds
    Display
    Realism
          ↓
DERIVED
    Pixel ↔ angle
    FOV-related geometry
          ↓
RUNTIME
    Current pan/tilt
    Detection
    Acquisition
    Tracking
    Link state
          ↓
CONTROL
    PTZ commands
    Search
    Track
    Acquire