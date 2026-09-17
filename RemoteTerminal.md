Remote Terminal (Replacement of existing Target System):

RemoteTerminal 
¦
+-- identity
¦   +-- id
¦   +-- name
¦   +-- type
¦   +-- platform
¦       +-- platformId
¦
+-- state
¦   +-- operationalState
¦   +-- powerState
¦   +-- beaconState
¦   +-- communicationState
¦
+-- position
¦   +-- position
¦   ¦   +-- x
¦   ¦   +-- y
¦   ¦   +-- z
¦   ¦   +-- referenceFrame
¦   ¦
¦   +-- orientation
¦       +-- roll
¦       +-- pitch
¦       +-- yaw
¦
+-- beacon
¦   +-- enabled
¦   +-- opticalPower
¦   ¦   +-- value
¦   ¦   +-- unit
¦   ¦
¦   +-- wavelength
¦   ¦   +-- center
¦   ¦   +-- bandwidth
¦   ¦
¦   +-- direction
¦   ¦   +-- azimuth
¦   ¦   +-- elevation
¦   ¦   +-- referenceFrame
¦   ¦
¦   +-- divergence
¦   ¦   +-- horizontal
¦   ¦   +-- vertical
¦   ¦   +-- unit
¦   ¦
¦   +-- modulation
¦   ¦   +-- type
¦   ¦   +-- frequency
¦   ¦   +-- depth
¦   ¦   +-- phase
¦   ¦
¦   +-- pulse
¦   ¦   +-- enabled
¦   ¦   +-- repetitionRate
¦   ¦   +-- width
¦   ¦   +-- dutyCycle
¦   ¦
¦   +-- profile
¦   ¦   +-- type
¦   ¦   +-- width
¦   ¦   +-- height
¦   ¦
¦   +-- polarization
¦       +-- type
¦       +-- angle
¦
+-- communication
¦   +-- terminalId
¦   +-- terminalType
¦   +-- capabilities
¦   +-- protocol
¦
+-- targetSignature
    +-- wavelength
    ¦   +-- value
    ¦   +-- tolerance
    ¦
    +-- modulation
    ¦   +-- type
    ¦   +-- frequency
    ¦
    +-- dutyCycle
    +-- pulseWidth
    ¦
    +-- spatialProfile
    ¦   +-- type
    ¦
    +-- expectedSpotSize
    ¦   +-- value
    ¦   +-- tolerance
    ¦   +-- unit
    ¦
    +-- minimumSNR
    +-- polarization
    +-- code
	
Important Desgin Principle:
1) Identity: What terminal is this/
2) State: What is it doing right now/
3) Position: Where is it and how is it oriented/
4) Beacon: What optical signal is it physically emitting/
5) Communication: What communication interface/capabilities does it have/
6) TargetSignature: What characteristics allow another terminal to recognize that this is the Intended target/

In physical Term:
The remote termial emits:
1) Photons / Optical radiation
2) At a particular wavelength
3) With a particular optical powerState
4) In a particular direction
5) With a particular beam divergence
6) With a particular spatial intensity distribution
7) With a particular polarization
8) With a particular temporal behavior
9) Potentially with modulation carrying Information

Detailed:

1) Identity: The identity section describes the stable identity and classification of the remote terminal.
	--> id: Unique Short Name
	--> name: Complete Name
	--> type: Defines what kind of terminal this object represents.
	--> platform: A reference to the physical platform that carries the terminal.

	Example:
	ID: RT-001
	NAME: Remote Optical Terminal 001
	TYPE: Remote_Terminal / Optical_Terminal / Ground Terminal / Airbone_Terminal / Space _Terminal
	PLATFORM: PaltformID: SAT-001
	
	Important Distinction:
	Platform
    +-- carries
          +-- RemoteTerminal

2) State: The state section describes what the remote terminal is doing now.

	Example:
		Identity:
			RT-001

		State:
			ACTIVE
			ON
			EMITTING
			CONNECTED
			
	Note: The identity remains the same even when the state changes.
	
	a) OperationalState: OFF / INITIALIZING / STANDBY / ACTIVE / FAULT / MAINTENANCE
	b) powerState: OFF / ON / LOW POWER / FAULT
	
	Note: Why separate this from operationalState?
	Because a terminal might technically exist and be configured but not currently powered.
	
	Example:
	operationalState = STANDBY
	powerState       = ON
	
	c) beaconState: Describes the state of the optical beacon.
	-> OFF / READY / EMITTING / FAULT
	Note: This is not the beacon configuration itself.
	
	The distinction is:
	
	beacon
    = WHAT the beacon emits

	beaconState
    = WHETHER it is currently emitting
	
	d) communicationState: Describes the communication/link state.
	-> NO LINK / DETECTING / OPTICAL LOCK / HANDSHAKE / CONNECTED / ERROR
	
	A useful state progression is:
	NO LINK -> DETECTING -> OPTICAL LOCK -> HANDSHAKE -> CONNECTED
	
	Note: 
	-> Detecting the beacon does not necessarily mean that communication has been established.
	-> A receiving terminal might detect optical energy but still have no usable communication link.
	
3) position: The position section describes the terminal's physical location and orientation.
		
		position: x, y, z
		Example:
		{
		  "x": 1200.5,
		  "y": -450.2,
		  "z": 820.7
		}
		The meaning of these coordinates depends on the referenceFrame.
		For example they could be:
		ECEF / ECI / LOCAL / PLATFORM / ENU / NED
		A robust model should therefore associate the position with a reference frame.
		
		position
		+-- x
		+-- y
		+-- z
		+-- referenceFrame
		
		Example:
		{
		  "x": 1200.5,
		  "y": -450.2,
		  "z": 820.7,
		  "referenceFrame": "ECI"
		}
		
		orientation: The orientation describes which way the terminal is physically pointing.
		It can be represented using Euler angles:
		orientation
		+-- roll
		+-- pitch
		+-- yaw
		
		or, preferably for many simulation/attitude applications, a quaternion:
		orientation
		+-- x
		+-- y
		+-- z
		+-- w
		
		Example: 
		{
		  "roll": 0.0,
		  "pitch": 10.0,
		  "yaw": 45.0
		}
		
		Why orientation matters?
		The terminal's orientation determines the direction in which its optical system can point.
		
		Conceptually:
		Platform position/orientation + Terminal mounting orientation + Beacon pointing direction = Actual beam direction
		
4) beacon: The beacon section describes the actual optical emission characteristics of the remote terminal.
This is the most important section when the receiving terminal is trying to detect the remote terminal optically.

	beacon
	+-- enabled
	+-- opticalPower
	+-- wavelength
	+-- direction
	+-- divergence
	+-- modulation
	+-- pulse
	+-- profile
	+-- polarization
	
	a) enabled: Whether the beacon is configured to emit. true/false

	Note the distinction:
	
	enabled = configuration
	beaconState = current operational state
	
	or
	
	enabled = true
	beaconState = FAULT
	
	meaning the beacon is intended to be enabled but is not currently operating correctly.
	
	b) opticalPower: Defines the emitted optical power
	Example:
	{
	  "value": 1.0,
	  "unit": "W"
	}
	
	It answers how much optical energy is the terminal emitting?
	
	c) wavelength: Defines the optical wavelength of the emitted light.
	Example:
	{
	  "center": 1550e-9,
	  "bandwidth": 1e-9,
	  "unit": "nm"
	}
	This tells the receiving sensor which portion of the electromagnetic spectrum it should be sensitive to.
	
	Example: center wavelength = 1550 nm
	The bandwidth represents the spectral width around that center.
	
	d) direction: Defines where the beacon is pointed.
	Example:
	{
	  "azimuth": 30.0,
	  "elevation": 15.0,
	  "referenceFrame": "PLATFORM"
	}
	
	Note: This is not the terminal's physical orientation.
	
	There are two different concepts:
	orientation = how much the terminal/platform itself is oriented/
	direction = where the optical beam is pointing relative to that frame
	
	e) divergence: Describes how quickly the optical beam spreads as it travels.
	Example:
	{
	  "horizontal": 0.001,
	  "vertical": 0.001,
	  "unit": "rad"
	}
	
	A smaller divergence generally means a narrower beam; a larger divergence means a wider beam.
	This affects the illuminated/observable spot at the receiver.
	
	f) modulation: Describes how the optical signal varies over time to carry a signal or beacon pattern.
	Example:
	{
	  "type": "AM",
	  "frequency": 10000,
	  "depth": 1.0,
	  "phase": 0.0
	}
	
	Possible modulation types depend on the actual system:
	NONE / AM / PM / OOK / PPM / CustomEvent
	
	The important point is that modulation describes the temporal information impressed on the optical emission.
	
	g) pulse: This describes pulsed operation.
	Example:
	{
	  "enabled": true,
	  "repetitionRate": 10000,
	  "width": 50e-6,
	  "dutyCycle": 0.5
	}
	
	Meaning: 
	(eanbled): Whether the optical signal is pulsed.
	(repetitionRate): How frequently pulses occur.
	(width): Duration of an individual pulse.
	(dutyCycle): The fraction of time the signal is active.
	
	For a continuous-wave beacon, this could instead be: enabled = false
	
	h) profile: Describes the spatial distribution of optical intensity across the beam.
	Example: 
	
	GAUSSIAN
	TOP_HAT
	CUSTOM
	
	{
	  "type": "GAUSSIAN",
	  "width": 0.001,
	  "height": 0.001
	}
	
	A GAUSSIAN beam does not have uniform intensity across its cross section.
	A TOP_HAT pofile is much closer to uniform intensity inside its defined region.
	This becomes important when modelling:
	+ spot size
	+ received power
	+ detector response
	+ beam overlap
	
	i) polarization: Deines the polarization state of the optical emission.
	UNPOLARIZED / LINEAR / CIRCULAR / ELLIPTICAL
	
	Example:
	{
	  "type": "LINEAR",
	  "angle": 45.0
	}
	
	j) Communication: The communication section describes the terminal's communication identity, interface, protocol and capabilities.
	
	This should not be confused with communicationState.
	communication
    = WHAT communication capabilities the terminal has

	communicationState
    = WHAT the link is doing right now
	
	terminalID: The communication-level identifier of the terminal.
	termialType: Defines the communication endpoint type. 
	Remote_Terminal / LOCAL_TERMINAL / RELAY / GROUND_STATION
	
	capabilities: Describes what the terminal is capable of doing.
	Example:
	[
	  "BEACON",
	  "OPTICAL_RX",
	  "OPTICAL_TX",
	  "BIDIRECTIONAL_LINK",
	  "TRACKING"
	]
	This is a capability declaration, not an instantaneous state.
	
	capabilities = ["OPTICAL_TX", "OPTICAL_RX"]
	This does not mean both are currently active. It means terminal supports them.
	
	protocol: Defiens the communication protocol used by the terminal
	Example:
	{
	  "name": "OPTICAL_LINK",
	  "version": "1.0"
	}
	
6) Target Signature:
	The targetSignature is different from the beacon.
	This is one of the most important distinctions in the model.
	
	Beacon: Describes what the remote terminal is actually emitting.
	Target Signature: Desribes what another terminal expects to observe in order to identity this remote terminal.
	So:
	Remote Terminal
      ¦
      +-- beacon --> actual emitted optical characteristics
      ¦      
      ¦  
      ¦
      +-- targetSignature --> identification criteria
	
    The signature can be used by the receiving terminal for detection and target discrimination.
	
	a) wavelength: Defines the expected wavelength signature.
	Example:
	{
	  "value": 1550e-9,
	  "tolerance": 2e-9
	}
	
	The receiver can interpret this as:
	Expected ˜ 1550 nm
	Acceptable range ˜ 1548–1552 nm
	
	b) modulation: Defines modulation characteristics that identify the terminal.
	Example:
	{
	  "type": "AM",
	  "frequency": 10000
	}
	The receiving system can look for that modulation pattern rather than merely detecting arbitrary optical energy.
	
	c) dutyCycle: Expected fraction of time that the signal is active.
	Example: dutyCycle = 0.5
	Means approx 50% active time
	
	d) pulseWidth: Expected width of an optical pulse.
	Example: 50 µs
	For pulsed systems this can be part of the target's recognition signature.
	
	e) spatialProfile: Describes the expected shape/distribution of the observed beam.
	Example: Gaussian
	This is useful when the receiver uses the spatial characteristics of the detected spot as part of target identification.
	
	f) expectedSpotSize: Defines how large the optical spot is expected to appear at the receiver under the relevant geometry.
	{
	  "value": 3.0,
	  "tolerance": 0.5,
	  "unit": "mrad"
	}
	
	The exact interpretation depends on whether the system defines spot size as:
	+ angular diameter
	+ angular radius
	+ physical diameter at a defined range
	+ FWHM
	+ another beam-width convention

	The model should explicitly document which convention is being used.

	g) minimumSNR: The minimum signal-to-noise ratio considered sufficient for accepting the signature.
	Example: 8 db
	Conceptually: 
	detected SNR < threshold
    --> insufficient confidence

	detected SNR >= threshold
    -->  signature may be accepted
	
	This is particularly useful when the optical environment contains noise or other sources.
	
	h) polarization: Defines the expected polarization characteristic of the target.
	Example: LINEAR or UNPOLARIZED
	A receiver can Potentially use this as another disriminator
	
	i) code: Optional string / binary sequence
	An optional identifying code embedded in the beacon/modulation.
	Example: RT001 or a binary/pseudo-random sequence.
	This allows multiple terminals that have similar optical properties to be distinguished.
	
	Example:
	Terminal A:
    wavelength = 1550 nm
    modulation = 10 kHz
    code = A7F2

	Terminal B:
    wavelength = 1550 nm
    modulation = 10 kHz
    code = B91C
	
	The optical characteristics are similar, but the code distinguishes the terminals.
	

Note: Not every signature field has to be present.
	

Complete Example:
{
  "id": "remote-terminal-001",
  "name": "Remote Optical Terminal 001",
  "type": "REMOTE_TERMINAL",

  "platform": {
    "platformId": "platform-001",
    "position": {
      "x": 0.0,
      "y": 0.0,
      "z": 0.0
    },
    "orientation": {
      "roll": 0.0,
      "pitch": 0.0,
      "yaw": 0.0
    }
  },

  "state": {
    "operationalState": "ACTIVE",
    "powerState": "ON",
    "beaconState": "EMITTING",
    "communicationState": "NO_LINK"
  },

  "beacon": {
    "enabled": true,

    "opticalPower": {
      "value": 1.0,
      "unit": "W"
    },

    "direction": {
      "azimuth": 0.0,
      "elevation": 0.0,
      "referenceFrame": "PLATFORM"
    },

    "divergence": {
      "horizontal": 0.001,
      "vertical": 0.001,
      "unit": "rad"
    },

    "wavelength": {
      "center": 1550e-9,
      "bandwidth": 1e-9,
      "unit": "m"
    },

    "modulation": {
      "type": "AM",
      "frequency": 10000.0,
      "depth": 1.0
    },

    "pulse": {
      "enabled": false,
      "repetitionRate": 0.0,
      "width": 0.0,
      "dutyCycle": 0.0
    },

    "profile": {
      "type": "GAUSSIAN",
      "width": 0.001,
      "height": 0.001,
      "unit": "rad"
    },

    "polarization": {
      "type": "UNPOLARIZED"
    }
  },

  "communication": {
    "terminalId": "RT-001",
    "terminalType": "REMOTE_TERMINAL",
    "capabilities": [],
    "protocol": "OPTICAL_LINK"
  },

  "targetSignature": {
    "wavelength": {
      "value": 1550e-9,
      "tolerance": 2e-9
    },

    "modulation": {
      "type": "AM",
      "frequency": 10000.0
    },

    "dutyCycle": 0.5,
    "pulseWidth": 50e-6,

    "spatialProfile": {
      "type": "GAUSSIAN"
    },

    "expectedSpotSize": {
      "value": 3.0,
      "tolerance": 0.5,
      "unit": "mrad"
    },

    "minimumSNR": 8.0,

    "polarization": "UNPOLARIZED",

    "code": null
  }
}


Remote Terminal Control Deck Design Section:
1) Six cards/panels matching the data model
+-------------------------------------------------------------+
¦ REMOTE TERMINAL                                             ¦
¦ RT-001     ACTIVE     BEACON: ON     LINK: NO LINK          ¦
+-------------------------------------------------------------¦
¦ 1. Identity      ¦ 2. Position      ¦ 3. Operational State  ¦
+------------------+------------------+-----------------------¦
¦ 4. Beacon        ¦ 5. Communication ¦ 6. Target Signature   ¦
¦                  ¦                  ¦                       ¦
+-------------------------------------------------------------+

But the Beacon panel should receive the most screen space because it contains the parameters that directly affect the emitted optical signal.
	
2) Identity Panel: Most of this should be configurable during setup, but not continuously during operation.
| Parameter     | UI control         |  Editable? |
| ------------- | ------------------ | ---------: |
| Terminal ID   | Text / ID field    | Setup only |
| Terminal Name | Text field         |        Yes |
| Terminal Type | Dropdown           | Setup only |
| Platform      | Dropdown/reference | Setup only |

Example:
IDENTITY
------------------------
Terminal ID       RT-001
Name              Remote Terminal 01
Type              Remote Optical Terminal
Platform          Platform-01

Note: Don't put UUID-style internal identifiers prominently in the operational deck. Show a human-readable terminal name and ID.

3. State / Operational panel: This should be a control + status panel, but only expose legitimate state transitions.
User Controls:
POWER
[ ON ] [ OFF ]

OPERATING MODE
[ STANDBY ? ]

BEACON
[ ON ] [ OFF ]

Depending on your state machine:
Operational Mode
------------------------
X OFF
X STANDBY
* ACTIVE
X MAINTENANCE

Read-only status:
STATUS
----------------------
Power             ON
Operational       ACTIVE
Beacon            EMITTING
Communication     NO LINK
Fault             NONE

I would not let a user directly type communicationState = CONNECTED.
Instead, the software derives it:
NO LINK -> DETECTING -> OPTICAL LOCK -> HANDSHAKE -> CONNECTED
	
The operator controls the causes; the system reports the resulting state.

4. Position / Pointing panel:
This should be one of the most important interactive areas.
There are actually two different things to expose:

A. Terminal/platform pose
POSITION
------------------------
X       [ 1200.5 ]
Y       [ -450.2 ]
Z       [  820.7 ]

Reference Frame [ ECI ? ]

AND

ORIENTATION
------------------------
Roll     [ 0.0° ]
Pitch    [ 0.0° ]
Yaw      [ 45.0° ]

B. Optical pointing
Do not make the operator infer beam direction from platform orientation.
Give the beam its own controls:
BEAM POINTING
------------------------
Azimuth       [ 30.0° ]
Elevation     [ 15.0° ]

Reference     [ PLATFORM ? ]

             [ POINT AT TARGET ]
             [ TRACK TARGET    ]

For an actual control deck, I would also include a visual pointing indicator:
              ELEVATION   
                 ¦
        <--------+--------> AZIMUTH
                 ¦
                 .
              BORESIGHT
			  
If your simulation has target tracking, add:
Pointing Mode
[ Manual ? ]

Manual
Track Target
Track Coordinates
	
5. Beacon panel — the main configuration area
5.1 Enable / emission

At the top:

BEACON
------------------------
Beacon              [ ON ]

Emission Mode       [ CONTINUOUS ? ]

Possible emission modes:

CONTINUOUS
PULSED
MODULATED

Though internally, modulation and pulse configuration can remain separate.

5.2 Optical power
OPTICAL POWER

Power       [------?----] 1.00 W
Maximum                      2.00 W

For precise configuration:

Power [ 1.000 ] W

A slider is useful for interactive simulation, while the numeric entry provides precision.

I would show both:

Power
[------?--------]
1.000 W
6. Wavelength

This is something I would expose directly because it materially changes what the receiver can detect.

WAVELENGTH
------------------------
Center wavelength
[ 1550.0 ] nm

Bandwidth
[ 1.0 ] nm

If you have a discrete hardware-like system, use a dropdown:

Wavelength
[ 850 nm ? ]
[ 1064 nm ]
[ 1310 nm ]
[ 1550 nm ]

If you're simulating a configurable optical terminal, numeric input may be more appropriate.

7. Beam divergence

Expose the beam geometry explicitly.

BEAM DIVERGENCE
------------------------
Horizontal     [ 1.00 ] mrad
Vertical       [ 1.00 ] mrad

Optionally:

? Symmetric

Horizontal    1.00 mrad
Vertical      1.00 mrad

When symmetric is enabled, one control can drive both values.

8. Beam profile

This should be a compact subsection.

BEAM PROFILE
------------------------
Profile       [ Gaussian ? ]

Width         [ 1.00 ] mrad
Height        [ 1.00 ] mrad

Possible profiles:

Gaussian
Top-Hat
Custom

If the profile has no meaningful width/height parameters for a particular type, disable those fields rather than displaying irrelevant controls.

9. Modulation

This deserves its own card inside Beacon because it may determine target recognition.

MODULATION
------------------------
Type          [ AM ? ]

Frequency     [ 10.000 ] kHz
Depth         [ 100 ] %
Phase         [ 0.0 ] °

For different modulation types, dynamically change the available controls.

For example:

Type = NONE

Frequency       disabled
Depth           disabled
Phase           disabled

Whereas:

Type = AM

Frequency       enabled
Depth           enabled
Phase           enabled

This makes the UI much cleaner.

10. Pulse configuration

Only show this when pulsed operation is selected.

PULSE
------------------------
Pulse Enabled       [ ON ]

Repetition Rate     [ 10.0 ] kHz
Pulse Width         [ 50.0 ] µs
Duty Cycle          [ 50.0 ] %

I would avoid allowing the operator to independently enter all three of:

repetition rate
pulse width
duty cycle

because they are mathematically related.

For example, if:

$$ D = f \times T $$

then changing two determines the third.

So the UI should make one of them calculated:

Repetition Rate    [ 10.0 ] kHz
Pulse Width        [ 50.0 ] µs
Duty Cycle         50.0 %   ? calculated

This avoids inconsistent configurations.

11. Polarization

Keep this simple.

POLARIZATION
------------------------
Type        [ Linear ? ]

Angle       [ 45.0 ] °

When:

Type = Unpolarized

disable the angle control.

When:

Type = Circular

the UI could replace angle with:

Handedness [ Right ? ]

depending on how detailed your simulation is.

12. Communication panel

The communication panel should be more about protocol and capability configuration than the physical optical emission.

COMMUNICATION
------------------------

Terminal ID
[ RT-001 ]

Protocol
[ Optical Link v1.0 ? ]

Capabilities

? Optical TX
? Optical RX
? Beacon
? Tracking
? Bidirectional Link

Then show current link information separately:

LINK STATUS
------------------------
State             NO LINK
Remote detected   NO
Optical lock      NO
Handshake         IDLE

I would make capabilities mostly setup-time configuration rather than frequently changed controls.

13. Target Signature panel

This is where I would be careful with terminology.

The signature should represent how the terminal is identified, not another copy of every beacon field.

A good control deck could show:

TARGET SIGNATURE
--------------------------------

Identification Mode    [ Signature ? ]

Expected Wavelength
Value                  [ 1550.0 ] nm
Tolerance              [ ±2.0 ] nm

Modulation
Type                   [ AM ? ]
Frequency              [ 10.0 ] kHz

Expected Spot
Size                   [ 3.0 ] mrad
Tolerance              [ 0.5 ] mrad

Minimum SNR            [ 8.0 ] dB

Polarization           [ Unpolarized ? ]

Identification Code    [ RT001 ]
14. What should actually be user-configurable?

I would divide all parameters into three categories.

A. Operator controls

These are the parameters the user should normally be able to change:

Beacon ON/OFF
Optical Power
Wavelength
Beam Azimuth
Beam Elevation
Beam Divergence
Beam Profile
Modulation Type
Modulation Frequency
Modulation Depth
Pulse Enable
Pulse Rate
Pulse Width
Polarization
Polarization Angle
Operating Mode
Tracking Mode

These are the core controls.

B. Setup/configuration parameters

These can be editable, but should not usually be changed during normal operation:

Terminal ID
Terminal Type
Platform Association
Communication Protocol
Capabilities
Target Signature
Reference Frames
Hardware limits

I would put these behind an Advanced / Configuration section.

C. Read-only telemetry

These should generally not be editable:

Current Operational State
Current Power State
Current Beacon State
Current Communication State
Actual Position
Actual Orientation
Actual Beam Direction
Fault State
Detected Target
Optical Lock
Link State

This separation is important.

A control deck becomes confusing when every field is treated as a command.
	

Final UI:
+---------------------------------------------------------------------+
¦ REMOTE TERMINAL: RT-001                         ACTIVE ?            ¦
¦ Beacon: ON ?      Link: NO LINK      Fault: NONE                    ¦
+---------------------------------------------------------------------¦
¦ OPERATION              ¦ BEAM POINTING                              ¦
¦                        ¦                                            ¦
¦ Power       [ ON ]     ¦ Mode       [ MANUAL ? ]                    ¦
¦ Mode        [ACTIVE]   ¦ Azimuth    [ 30.00° ]                      ¦
¦ Beacon      [ ON ]     ¦ Elevation  [ 15.00° ]                      ¦
¦                        ¦ [ POINT AT TARGET ] [ TRACK ]              ¦
+-----------------------+---------------------------------------------¦
¦ OPTICAL BEACON         ¦ COMMUNICATION                              ¦
¦                        ¦                                            ¦
¦ Power     1.00 W       ¦ Protocol    Optical Link v1.0              ¦
¦ ?         1550 nm      ¦ Capabilities                               ¦
¦ BW        1 nm         ¦ [TX] [RX] [Beacon] [Tracking]              ¦
¦ Divergence 1.0 mrad    ¦                                            ¦
¦ Profile   Gaussian     ¦ Link State: NO LINK                        ¦
¦ Polariz.  Unpolarized  ¦                                            ¦
+-----------------------+---------------------------------------------¦
¦ MODULATION / PULSE     ¦ TARGET SIGNATURE                           ¦
¦                        ¦                                            ¦
¦ Type      AM           ¦ ?        1550 ± 2 nm                       ¦
¦ Freq      10 kHz       ¦ Mod      AM / 10 kHz                       ¦
¦ Depth     100 %        ¦ Spot     3.0 ± 0.5 mrad                    ¦
¦                        ¦ Min SNR  8 dB                              ¦
¦ Pulse     OFF          ¦ Code     RT001                             ¦
+---------------------------------------------------------------------+
		

Also add motion profile, shape, and count:
Remote Terminal Scenario
+-- terminalCount
+-- formation / arrangement
¦   +-- shape
¦   +-- spacing
¦   +-- orientation
¦
+-- motion
    +-- profile
    +-- speed
    +-- direction
    +-- acceleration
    +-- timing
        ¦
        +-- RemoteTerminal[]
             +-- identity
             +-- state
             +-- position
             +-- beacon
             +-- communication
             +-- targetSignature

Data Model:
remoteTerminalScenario
+-- terminalCount: integer

I would not duplicate terminalCount inside every Remote Terminal.
Each individual terminal still has:

identity.id

so the relationship is:

Scenario
    ¦
    +-- terminalCount = 4
    ¦
    +-- terminals[]
          +-- RT-001
          +-- RT-002
          +-- RT-003
          +-- RT-004

2. Shape

If by shape you mean how multiple remote terminals are arranged, then this belongs to the formation/geometry section.

Control
FORMATION
------------------------
Shape       [ Circle ? ]

Possible options:

Single
Line
Circle
Arc
Grid
Rectangle
V-Formation
Custom

For example:

             RT-001
                ?

       RT-004       RT-002
          ?           ?

                RT-003
                   ?
Additional parameters

Shape alone isn't enough. I would expose parameters conditionally:

Shape             Circle
Radius            100 m
Spacing            —
Rotation            0°

For a line:

Shape             Line
Spacing           50 m
Heading           90°

For a grid:

Shape             Grid
Rows              2
Columns           3
Spacing X         50 m
Spacing Y         50 m

So the model becomes:

formation
+-- shape
+-- spacing
+-- radius
+-- rows
+-- columns
+-- rotation
+-- referenceFrame

Not every field needs to be active at the same time.

3. Motion Profile

This is another parameter I would definitely put on the control deck.

But distinguish motion profile from position.

position says:

Where is the terminal now?

motion profile says:

How does the terminal move through the scenario?

UI
MOTION
------------------------
Profile       [ Constant Velocity ? ]

Potential profiles:

Stationary
Constant Velocity
Linear
Circular
Orbital
Waypoint
Sinusoidal
Custom

For a simulation, I would probably start with:

Stationary
Constant Velocity
Circular
Waypoint
Custom

and add more only when the underlying simulation supports them.

4. Speed

Speed belongs underneath the motion configuration.

Speed         [ 10.0 ] m/s

But I would also strongly consider:

Direction     [ 45.0 ] °

because speed without a direction is incomplete for translational motion.

So:

MOTION
------------------------
Profile       Constant Velocity
Speed         10.0 m/s
Direction     45.0°

For 3D motion, you could instead use:

Velocity
+-- vx
+-- vy
+-- vz

The UI should preferably expose the intuitive representation while the simulation internally stores the vector.

For example:

UI:
Speed = 10 m/s
Heading = 45°
Elevation = 5°

Internal:
velocity = Vector3(vx, vy, vz)
5. Acceleration

I would include this even though you didn't explicitly mention it.

Without acceleration, a user changing speed from:

10 m/s ? 100 m/s

causes an instantaneous velocity change unless the simulator handles it specially.

A better control is:

Acceleration     [ 2.0 ] m/s²

Then:

Initial Speed    10 m/s
Target Speed     100 m/s
Acceleration      2 m/s²

This gives you a physically coherent motion model.

6. Motion Shape vs Formation Shape

This is an important terminology distinction.

You potentially have two different meanings of "shape".

Formation shape

The spatial arrangement of multiple terminals:

Circle
Line
Grid
V
Motion path shape

The trajectory followed by a terminal or formation:

Straight
Circular
Arc
Waypoint
Spline

I would therefore not call both simply Shape.

Use:

formation.shape
motion.profile

or:

formation.geometry
trajectory.type

That avoids ambiguity.

7. How I would organize the control deck

I would change the earlier Remote Terminal screen slightly.

Scenario / Formation controls at the top
+--------------------------------------------------------------+
¦ REMOTE TERMINAL SCENARIO                                     ¦
¦                                                              ¦
¦ Count       [ 4 ]       Formation     [ Circle ? ]          ¦
¦ Radius      [ 100 m ]   Spacing       [ — ]                ¦
¦                                                              ¦
¦ Motion      [ Constant Velocity ? ]                         ¦
¦ Speed       [ 10.0 m/s ]                                    ¦
¦ Direction   [ 45° ]                                         ¦
¦ Accel.      [ 2.0 m/s² ]                                    ¦
+--------------------------------------------------------------+

Then below it:

+--------------------------------------------------------------+
¦ REMOTE TERMINAL CONFIGURATION                                ¦
¦                                                              ¦
¦ RT-001   RT-002   RT-003   RT-004                           ¦
¦                                                              ¦
¦ Identity ¦ State ¦ Position ¦ Beacon ¦ Communication ¦ ...  ¦
+--------------------------------------------------------------+

This gives you two levels:

Level 1 — Scenario controls

Controls the group:

Count
Formation
Formation shape
Spacing
Motion profile
Speed
Direction
Acceleration
Trajectory
Level 2 — Terminal controls

Controls an individual terminal:

Identity
State
Position
Orientation
Beacon
Communication
Target Signature
8. What happens when there are multiple terminals?

This is where the model becomes much cleaner.

Suppose:

Count = 4
Formation = Circle
Radius = 100 m
Motion Profile = Circular
Speed = 10 m/s

The scenario engine generates:

Scenario
¦
+-- Formation
¦   +-- shape = CIRCLE
¦   +-- radius = 100 m
¦   +-- terminalCount = 4
¦
+-- Motion
¦   +-- profile = CIRCULAR
¦   +-- speed = 10 m/s
¦
+-- Terminals[]
    +-- RT-001 ? calculated position
    +-- RT-002 ? calculated position
    +-- RT-003 ? calculated position
    +-- RT-004 ? calculated position

The individual terminal's position is then runtime state generated by the motion/formation engine.

That means you don't have to manually edit:

RT-001 position
RT-002 position
RT-003 position
RT-004 position

every frame.

9. What should the operator actually be able to configure?
For the Remote Terminal section, I'd use this hierarchy:
Scenario-level:
| Parameter             | Control      |
| --------------------- | ------------ |
| Remote Terminal Count | Number input |
| Formation Shape       | Dropdown     |
| Formation Size        | Numeric      |
| Terminal Spacing      | Numeric      |
| Formation Rotation    | Angle        |
| Motion Profile        | Dropdown     |
| Speed                 | Numeric      |
| Direction / Heading   | Angle        |
| Elevation             | Angle        |
| Acceleration          | Numeric      |
| Trajectory            | Dropdown     |
| Start Position        | Vector       |
| Start Time            | Time         |


Per terminal:
| Parameter        | Control               |
| ---------------- | --------------------- |
| Terminal ID      | Text                  |
| Name             | Text                  |
| Active/Inactive  | Toggle                |
| Position         | Read-only or advanced |
| Orientation      | Read-only/advanced    |
| Beacon           | Configuration         |
| Optical Power    | Numeric/slider        |
| Wavelength       | Numeric               |
| Divergence       | Numeric               |
| Modulation       | Configuration         |
| Pulse            | Configuration         |
| Polarization     | Configuration         |
| Communication    | Configuration         |
| Target Signature | Configuration         |

10. One architectural change I recommend
Instead of putting this:
RemoteTerminal
+-- identity
+-- state
+-- position
+-- beacon
+-- communication
+-- targetSignature
+-- motionProfile
+-- speed
+-- shape

Use:
RemoteTerminalScenario
+-- count
+-- formation
¦   +-- shape
¦   +-- size
¦   +-- spacing
¦   +-- rotation
¦
+-- motion
¦   +-- profile
¦   +-- speed
¦   +-- direction
¦   +-- acceleration
¦   +-- trajectory
¦
+-- terminals[]
    ¦
    +-- identity
    +-- state
    +-- position
    +-- beacon
    +-- communication
    +-- targetSignature
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
