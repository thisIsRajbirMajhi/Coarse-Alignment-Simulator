# Control Deck — New UI Design Specification

## Scope

This redesign covers the following existing application areas shown in the supplied references:

- **Live Dashboard**
- **Remote Terminal**
- **Local Terminal**
- **Environment**
  - World / render size
  - Seed / reproducibility
  - Atmosphere / gradient / haze
  - Starfield / clutter
- **Disturbances & Noise**
  - Air & Light
  - Camera Motion
  - Sensor Noise

The redesign keeps the existing simulation controls and semantics, but reorganizes them into a clearer control system with stronger hierarchy, less empty space, better value visibility, and a more professional technical-console appearance.

> **Design principle:** expose the parameters users change frequently; move diagnostic and fine-tuning parameters into compact Advanced sections.

---

# 1. Design Direction

## Visual language

Use a **dark technical-control UI** rather than the current large white form layout.

| Token | Recommendation |
|---|---|
| App background | `#0B0F14` |
| Surface | `#111720` |
| Elevated surface | `#151C26` |
| Border | `#283341` |
| Primary text | `#E8EDF3` |
| Secondary text | `#8F9CAB` |
| Muted text | `#647182` |
| Accent | `#61D6FF` |
| Accent strong | `#2BB9EA` |
| Success | `#57D38C` |
| Warning | `#F2B84B` |
| Danger | `#F06D7A` |
| Disabled | `#3B4653` |

The interface should feel closer to a professional simulation / optical instrumentation console than a generic settings form.

## Typography

- UI font: **Inter**, **Geist**, or equivalent system sans.
- Page title: `20–24px / 700`.
- Section title: `14–15px / 650`.
- Control label: `12–13px / 550`.
- Supporting text: `11–12px / 400`.
- Numeric values: use a tabular/monospaced font such as `JetBrains Mono` or `SFMono-Regular`.

## Density

Use a compact density without making controls cramped:

- Header: `56–64px`
- Main navigation: `44–48px`
- Card padding: `16–20px`
- Control row height: `36–42px`
- Slider track: `4px`
- Slider thumb: `14px`
- Card gap: `12–16px`
- Major section gap: `20–24px`

---

# 2. Global Control Deck Shell

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  OPTICAL CONTROL DECK                         ● LIVE     Randomize   ⛶   ×   │
│  Local Terminal / Remote Terminal / Environment / Disturbances               │
├──────────────────────────────────────────────────────────────────────────────┤
│  LOCAL  REMOTE  ENVIRONMENT  DISTURBANCES                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Page title                                      [Preset ▾] [Reset]            │
│  Small contextual description                                                │
│                                                                              │
│  ┌──────────────────────────────┐  ┌─────────────────────────────────────┐   │
│  │ Primary control card         │  │ Primary control card                │   │
│  └──────────────────────────────┘  └─────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Header behavior

**Left**
- Compact product mark: `OPTICAL CONTROL DECK`.
- Optional breadcrumb / context.

**Right**
- Live state indicator.
- `Randomize` primary action.
- `Fullscreen` icon button.
- `Close` icon button.

### Navigation

Replace the tiny browser-like tabs with a proper segmented navigation bar:

```text
[ Local Terminal ] [ Remote Terminal ] [ Environment ] [ Disturbances ]
```

Active item:
- Accent text.
- Accent bottom/side indicator.
- Slightly elevated surface.

Inactive items remain readable without heavy borders.

---

# 3. Environment — New Layout

## Page structure

```text
ENVIRONMENT
Scene generation, atmosphere and star distribution

[ Preset ▾ ] [ Randomize Environment ]                         Seed: 42

┌────────────────────────────────────────────────────────────────────────────┐
│ WORLD                                                                       │
│ Render dimensions                                                          │
│                                                                            │
│ Width                         Height                         Link dimensions │
│ [──────●────────] 2000 px     [──────●────────] 2000 px       [  ]          │
│                                                                            │
│ [ 2K ] [ 3K ] [ 5K ]                                                        │
└────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────┐  ┌─────────────────────────────────────────┐
│ SEED                          │  │ ATMOSPHERE                               │
│                               │  │                                         │
│ [ 42               ]         │  │ BG Top       [────●────────] 12         │
│ [ Randomize ]                │  │ BG Bottom    [────────●────] 22         │
│ Deterministic scene seed      │  │ Vignette     [──●──────────] 0          │
│                               │  │ Haze         [──────●──────] 35         │
└───────────────────────────────┘  └─────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ STARFIELD                                                                    │
│                                                                            │
│ Stars          [────●────────────] 60      Brightness [──────●────] 1.0   │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

                                         [ Reset Environment ]
```

## 3.1 World card

### Header

**WORLD**

Subtitle: `Render dimensions and output scale`

### Width + Height

Each dimension is one control row:

```text
Width       ─────────●────────────       2000 px
Height      ─────────●────────────       2000 px
```

The numeric value should be a real input, not only a badge. Users must be able to click the value and type a precise number.

Recommended behavior:

- Slider controls coarse adjustment.
- Numeric input controls precise adjustment.
- Clamp to `2000–5000` according to current simulation limits.
- Units shown as `px`.

### Preset buttons

Replace large 2K / 3K / 5K buttons with compact segmented chips:

```text
[ 2K ] [ 3K ] [ 5K ]
```

Selected preset gets accent treatment. Custom dimensions automatically switch the state to `Custom`.

### Optional future enhancement

Add a `Lock aspect ratio` icon only if width/height linking is genuinely needed. Do not introduce it merely for visual completeness.

---

# 3.2 Seed card

```text
SEED
Reproduce the exact same scene from the same seed.

Seed
[ 000042                                      ]

[ Generate Random Seed ]

Deterministic: haze, stars and scene placement remain reproducible.
```

### Interaction

- Numeric input should support direct editing.
- `Generate Random Seed` uses a dice icon rather than a large text button.
- Keep the current seed visible even when randomizing.
- If the environment is modified after a seed is set, show a tiny `Modified` indicator rather than replacing the seed.

---

# 3.3 Atmosphere card

Use a **2-column grid** instead of a vertical form.

```text
ATMOSPHERE
Gradient, haze and atmospheric depth

BG TOP                     12
──────────────●────────────

BG BOTTOM                  22
────────────────●─────────

VIGNETTE                    0
────────●──────────────────

HAZE                       35
───────────────●───────────
```

Each slider has:

1. Short label.
2. Optional tooltip.
3. Slider.
4. Right-aligned numeric value.
5. Unit only when relevant.

Avoid placing the value in a separate pill disconnected from the slider.

---

# 3.4 Starfield card

Use one compact card with a visual subsection divider:

```text
STARFIELD

Stars                       60
──────────────●─────────────

Brightness                  1.0×
────────────────●───────────
```

Add a small star icon beside the section title. Keep this card intentionally compact because it contains only two controls.

---

# 4. Disturbances & Noise — New Layout

## Page structure

```text
DISTURBANCES & NOISE
Model atmospheric, optical, camera and sensor imperfections.

[ ON ]   Scenario: [ Custom ▾ ]                    [ Reset ]

ACTIVE DISTURBANCES
┌─────────────────────────────────────────────────────────────────────────────┐
│ AIR & LIGHT     ● Enabled      Camera Motion   ● Off      Sensor Noise ● Off│
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│ Active module content                                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Master disturbance control

The current large checkbox should become a modern **master toggle**:

```text
Disturbances     [ ● ON ]
```

When off:
- Keep settings visible but visually muted.
- Do not destroy user-entered values.
- Display `Disabled` in the status area.

### Scenario selector

Use a compact select/combobox:

```text
Scenario   [ Custom ▾ ]
```

Possible current presets should be retained. If a preset is selected and the user changes one parameter, the label should become `Custom` automatically.

---

# 5. Disturbance Module Navigation

Replace the tiny tabs with **module cards / segmented tabs**:

```text
┌────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│ Air & Light    │ │ Camera Motion    │ │ Sensor Noise    │
│ ● Enabled      │ │ ○ Off            │ │ ○ Off           │
└────────────────┘ └──────────────────┘ └─────────────────┘
```

Each tab should show status without opening the tab:

- `●` = enabled.
- `○` = disabled.
- Optional small value summary underneath.

Example:

```text
Air & Light
Fog · 100% · Turbulence 4
```

This lets the operator understand the entire disturbance configuration at a glance.

---

# 6. Air & Light — New UI

## Proposed layout

```text
AIR & LIGHT
Atmospheric conditions, optical turbulence and beam distortion.

Condition
[ Fog ▾ ]

┌────────────────────────────────────────────────────────────────────────────┐
│ WEATHER                                                                     │
│                                                                            │
│ Severity       ───────────────────●──────────────       100%               │
│ Contrast       ─────────────●────────────────────        38%               │
│ Brightness     ─────●────────────────────────────        22%               │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ TURBULENCE                                                                  │
│ Beam distortion / shimmer                                                  │
│                                                                            │
│ Strength       ──────────────●───────────────────         4                │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ BEAM DETAILS                                     [ Advanced ▾ ]              │
└────────────────────────────────────────────────────────────────────────────┘
```

## Weather controls

### Condition

Use a select with enough width for the complete label. Do not truncate `Fog`, `Rain`, etc. inside a tiny control.

### Severity, contrast, brightness

Use standard full-width sliders with right-aligned values.

For percentage values:

```text
Severity                                    100%
Contrast                                     38%
Brightness                                   22%
```

### Context summary

Put the currently selected weather state under the card header:

```text
Fog · severity 100% · contrast 38% · brightness 22%
```

This can be shown only when the module is collapsed or not active.

---

# 7. Air & Light — Turbulence

Make turbulence a separate visual block because it affects beam behavior rather than weather state.

```text
TURBULENCE
Beam distortion

Strength          ─────────────●───────────────       4

Shimmer intensity controls beam wobble and twinkle.
```

If `Enable Channel` exists in the simulation, present it as:

```text
Optical channel                       [ ON ]
```

rather than an old-style checkbox.

---

# 8. Air & Light — Advanced Beam Details

The current screenshot exposes four secondary controls permanently. Hide these by default behind an Advanced disclosure.

```text
BEAM DETAILS                                          [ Advanced ↑ ]

Attenuation     [ Atmospheric ▾ ]   ─────────●─────  1.00
Wander                           ─────●────────────  1.00×
Spread                           ─────●────────────  1.00×
Twinkle                          ─────●────────────  1.00×
```

### Recommended behavior

- `Advanced` remembers its expanded/collapsed state.
- Controls remain live; no Apply button is required.
- Tooltips explain physical meaning, not implementation details.

Example tooltip:

> **Wander:** changes the lateral path variation of the optical beam.

---

# 9. Camera Motion — New UI

## Proposed layout

```text
CAMERA MOTION
Frame-to-frame camera displacement and platform drift.

┌────────────────────────────────────────────────────────────────────────────┐
│ CAMERA SHAKE                                             [ ON ]             │
│                                                                            │
│ Amount             ───────────────●────────────────     0.0 px              │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ PLATFORM MOTION                                      [ ON ]                │
│                                                                            │
│ Path              [ Linear ▾ ]                                             │
│ Speed             ────●───────────────────────────     0.0 px/frame        │
└────────────────────────────────────────────────────────────────────────────┘

MOTION DETAILS                                         [ Advanced ▾ ]
```

## Camera shake

Use the module toggle in the section header.

```text
Camera Shake                                      [ ON ]
Amount          ───────────────●────────────────  0.0 px
```

The `px/frame` or `px` unit should always be visible in the value.

---

# 10. Platform Motion

### Path selector

Retain the existing path choices, but use a normal select:

```text
Path   [ Linear ▾ ]
```

If the simulation supports multiple paths, show a small path glyph next to each option where practical:

- Linear
- Random
- Figure 8

### Speed

```text
Speed          ─────────●──────────────────────  0.0 px/frame
```

Show a helper line only when necessary:

> Controls how quickly the platform moves between frames.

Avoid long descriptive paragraphs under every slider.

---

# 11. Camera Motion — Advanced Details

Move the current amplitude/direction controls into a collapsible advanced card.

```text
MOTION DETAILS                                          [ Advanced ↑ ]

Amplitude X     ────────────────●────────────     110 px
Amplitude Y     ────────────────●────────────     110 px
Direction       ─────────────●────────────────      0°
```

A tiny directional indicator can improve comprehension:

```text
                 ↑ 90°
                 │
        180° ─── ● ─── 0°
                 │
                ↓ 270°
```

Use the indicator only if it does not consume excessive space.

---

# 12. Sensor Noise — New UI

The current version places three independent noise types in large horizontal sections. Replace this with a **noise stack**.

```text
SENSOR NOISE
Select one or more noise models.

┌────────────────────────────────────────────────────────────────────────────┐
│ Gaussian Noise                                           [ ON ]             │
│ Smooth sensor grain                                                         │
│                                                                            │
│ Strength       ─────────────●──────────────────────       8.0 px            │
│ Max σ          ─────────────────────●─────────────      20.0 px            │
│                                                                            │
│ [ Fine tuning ▾ ]                                                           │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ Salt & Pepper                                           [ ON ]              │
│ Dead / hot pixel simulation                                                │
│                                                                            │
│ Amount         ─────●──────────────────────────────       0.10             │
│ White / Black  ──────────────●─────────────────────       0.50             │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ Poisson Noise                                           [ OFF ]             │
│ Low-light photon noise                                                     │
│                                                                            │
│ Strength       ─────●──────────────────────────────       1.0×             │
│ Peak           ───────────────●────────────────────       100              │
└────────────────────────────────────────────────────────────────────────────┘
```

## Important interaction rule

Allow multiple models to be enabled simultaneously because the existing interface explicitly supports selecting more than one type.

Each card should independently show:

- Enabled / disabled state.
- Short explanation.
- Only the parameters relevant to that noise model.
- Optional Advanced section for specialist tuning.

---

# 13. Sensor Noise — Fine Tuning

The current `Show fine-tuning` checkbox should become a disclosure control.

```text
Fine tuning                                           [ Show ▾ ]
```

When opened:

```text
FINE TUNING
Ceiling        ───────────────●────────────
Balance        ──────────●────────────────
Peak           ─────────────────●─────────
```

Do not display empty advanced fields until requested. This is the primary way to reduce the large unused vertical areas visible in the current UI.

---

# 14. Shared Slider Component

Every slider across Environment and Disturbances should use the same component.

```text
Label                                      38%
───────────────────────●──────────────────────
Optional helper text
```

## Rules

- Numeric value always visible.
- Value is clickable/editable.
- Slider supports keyboard arrows.
- `Home` / `End` jump to min/max where appropriate.
- Show units directly in the value: `px`, `%`, `×`, `°`, `px/frame`.
- Tooltips show min/max and a one-line definition.
- Avoid separate detached value pills unless the design system requires them.

---

# 15. Presets and State

## Scenario presets

The current `Scenario` field should be expanded into a preset workflow:

```text
Scenario      [ Custom ▾ ]

Quick presets:
[ Clear ] [ Fog ] [ Rain ] [ Camera Shake ] [ Low Light ] [ Custom ]
```

Do not imply that a preset is permanent. Once the user edits any parameter:

```text
Scenario      [ Custom • modified ]
```

## Live update

The existing behavior says changes apply live. Make this explicit with a compact status item:

```text
● LIVE PREVIEW
Changes apply immediately
```

No Apply button is necessary unless the underlying simulation requires one.

---

# 16. Randomize UX

The current global `Randomize All` button is useful but visually dominant.

Recommended hierarchy:

```text
[ Randomize ]   [ Reset ]
```

Use an overflow menu for scope selection:

```text
Randomize ▾
├─ Everything
├─ Environment
├─ Disturbances
├─ Optical parameters
└─ Seed only
```

This prevents a destructive-looking global action from being the only visible option.

Before changing values, show a lightweight confirmation only for `Everything` if a user could lose a carefully tuned configuration.

---

# 17. Footer / Status Bar

Remove the long sentence currently stretched across the bottom.

Use a compact status bar:

```text
● LIVE   |   Seed 42   |   2000 × 2000   |   Fog 100%   |   Turbulence 4
```

When the interface is too narrow, collapse it to:

```text
● LIVE   |   Seed 42   |   Custom
```

---

# 18. Responsive Behavior

## Desktop ≥ 1200px

- Environment: 2-column cards where useful.
- Disturbances: 3 module cards across the top; active content below.
- Sliders can use full card width.

## Tablet 768–1199px

- Two cards per row.
- Disturbance module navigation becomes horizontally scrollable.
- Advanced sections remain collapsed by default.

## Narrow desktop / laptop < 900px

- Use a single content column.
- Keep sticky header and navigation.
- Collapse descriptive text aggressively.

## Minimum interaction target

All interactive controls should remain at least approximately `36×36px`, with primary touch targets preferably `40–44px`.

---

# 19. Accessibility

The redesign should support keyboard and assistive-technology use from the start.

- Every slider has an accessible label and current value.
- Every toggle exposes `on/off` state.
- Do not communicate enabled state with color alone.
- Focus ring must remain visible against dark surfaces.
- Minimum body text contrast should meet WCAG AA where applicable.
- Tooltips must also be accessible by keyboard focus.
- Do not rely on hover to reveal essential information.
- Numeric inputs accept direct keyboard editing.

---

# 20. Interaction States

Every component needs explicit states:

### Toggle

```text
OFF  [ ○ ]
ON   [ ● ]
```

### Slider

```text
Default      ───────●────────
Hover        ───────●────────  + subtle glow
Focus        ───────●────────  + visible focus ring
Disabled     ───────○────────  muted
```

### Card

- Default: low-contrast border.
- Active: accent border or accent top edge.
- Disabled: reduce contrast, but keep text readable.

### Preset

- Selected: filled accent surface.
- Available: outlined surface.
- Modified: small dot indicator.

---

# 21. Component Architecture

Suggested reusable component tree:

```text
ControlDeck
├── AppHeader
│   ├── LiveStatus
│   ├── RandomizeMenu
│   ├── FullscreenButton
│   └── CloseButton
│
├── PrimaryNav
│
├── EnvironmentPage
│   ├── PageHeader
│   ├── WorldCard
│   │   ├── NumericSlider
│   │   ├── NumericSlider
│   │   └── PresetSegment
│   ├── SeedCard
│   ├── AtmosphereCard
│   │   └── NumericSlider × 4
│   └── StarfieldCard
│       └── NumericSlider × 2
│
└── DisturbancesPage
    ├── DisturbanceHeader
    │   ├── MasterToggle
    │   └── ScenarioSelect
    ├── ModuleNav
    ├── AirLightPanel
    │   ├── ConditionSelect
    │   ├── NumericSlider × 4
    │   └── Disclosure / BeamDetails
    ├── CameraMotionPanel
    │   ├── Toggle
    │   ├── NumericSlider
    │   ├── PathSelect
    │   ├── NumericSlider
    │   └── Disclosure / MotionDetails
    └── SensorNoisePanel
        ├── NoiseCard / Gaussian
        ├── NoiseCard / SaltPepper
        ├── NoiseCard / Poisson
        └── Disclosure / FineTuning
```

---

# 22. Data Binding Rules

The UI should be a direct projection of the simulation state.

Each control should declare:

```text
id
label
value
min
max
step
unit
enabled
advanced
help
```

Example:

```json
{
  "id": "atmosphere.haze",
  "label": "Haze",
  "value": 35,
  "min": 0,
  "max": 100,
  "step": 1,
  "unit": "%",
  "enabled": true,
  "advanced": false
}
```

This enables the same slider component to be reused across Environment, Air & Light, Camera Motion, and Sensor Noise.

---

# 23. Recommended Information Hierarchy

The redesigned interface should make this hierarchy visually obvious:

```text
APPLICATION
  └─ PAGE
      └─ MODULE
          └─ CONTROL GROUP
              └─ PARAMETER
                  └─ VALUE
```

For example:

```text
DISTURBANCES & NOISE
  └─ Air & Light
      └─ Weather
          └─ Severity
              └─ 100%
```

The current screenshots flatten too many of these levels into the same visual weight. The redesign restores hierarchy through typography, spacing, card surfaces, and disclosure states.

---

# 24. Visual Comparison — Current → Proposed

| Current issue | Proposed treatment |
|---|---|
| Very large white areas | Compact card-based layout |
| Tiny/uneven tab labels | Proper segmented navigation |
| Checkbox-heavy controls | Toggle components |
| Values detached from sliders | Right-aligned inline values |
| Advanced settings always visible | Collapsible Advanced sections |
| Long helper sentences | One-line contextual help / tooltip |
| Huge randomize button emphasis | Action menu with scoped randomization |
| Weak active-state indication | Accent state + status dot |
| Numeric values hard to edit precisely | Editable numeric fields beside sliders |
| Large horizontal forms | Responsive grids and grouped cards |
| Poor scanability across modules | Status summaries for each module |

---

# 25. Final Screen Blueprint

## Environment

```text
┌──────────────────────────────────────────────────────────────────────┐
│ OPTICAL CONTROL DECK                         ● LIVE  Randomize  ×    │
├──────────────────────────────────────────────────────────────────────┤
│ Local   Remote   [ Environment ]   Disturbances                     │
├──────────────────────────────────────────────────────────────────────┤
│ ENVIRONMENT                                      [ Preset ▾ ] [Reset]│
│ Scene generation, atmosphere and star distribution                  │
│                                                                      │
│ ┌─────────────────────────────┐  ┌────────────────────────────────┐ │
│ │ WORLD                       │  │ SEED                           │ │
│ │ Width     ───●──── 2000 px │  │ [000042] [Generate]            │ │
│ │ Height    ───●──── 2000 px │  │ Deterministic scene            │ │
│ │ [2K] [3K] [5K]             │  │                                │ │
│ └─────────────────────────────┘  └────────────────────────────────┘ │
│                                                                      │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ ATMOSPHERE                                                       │ │
│ │ BG Top     ─────●──── 12      BG Bottom ─────●──── 22            │ │
│ │ Vignette   ─●──────── 0       Haze       ─────●──── 35            │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ STARFIELD                                                        │ │
│ │ Stars      ─────●──── 60      Brightness ─────●── 1.0×           │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                   [Reset Environment]│
└──────────────────────────────────────────────────────────────────────┘
```

## Disturbances & Noise

```text
┌──────────────────────────────────────────────────────────────────────┐
│ OPTICAL CONTROL DECK                         ● LIVE  Randomize  ×    │
├──────────────────────────────────────────────────────────────────────┤
│ Local   Remote   Environment   [ Disturbances ]                     │
├──────────────────────────────────────────────────────────────────────┤
│ DISTURBANCES & NOISE                         [ ON ]  [ Custom ▾ ]    │
│ Atmospheric, optical, camera and sensor imperfections               │
│                                                                      │
│ [ Air & Light ● ] [ Camera Motion ○ ] [ Sensor Noise ● ]            │
│                                                                      │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ AIR & LIGHT                                                     │ │
│ │ Condition [ Fog ▾ ]                                             │ │
│ │ Severity   ─────────────●──────────── 100%                      │ │
│ │ Contrast   ───────●─────────────────  38%                      │ │
│ │ Brightness ─────●────────────────────  22%                      │ │
│ │                                                                  │ │
│ │ TURBULENCE                                                       │ │
│ │ Strength   ─────────●───────────────   4                       │ │
│ │                                                                  │ │
│ │ Beam Details                                         [Advanced]  │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 26. Implementation Priority

### Phase 1 — Core visual redesign

1. New dark shell and navigation.
2. Card-based Environment page.
3. Card/segment-based Disturbances page.
4. Shared slider + numeric-input component.
5. Toggle and select components.

### Phase 2 — Interaction quality

1. Advanced disclosures.
2. Preset / Custom state tracking.
3. Module status summaries.
4. Randomize scope menu.
5. Keyboard accessibility.

### Phase 3 — Polish

1. Micro-interactions.
2. Direction/path visualizations.
3. Better tooltips.
4. Saved UI expansion state.
5. Compact status bar.

---

# 27. Acceptance Criteria

The redesign is complete when:

- Every existing parameter shown in the supplied screenshots remains accessible.
- Users can edit numeric values directly as well as with sliders.
- Environment controls fit into a compact, scan-friendly layout without large unused areas.
- Disturbance modules clearly expose enabled/disabled state before opening them.
- Advanced controls are collapsed by default.
- Multiple sensor-noise models can remain enabled simultaneously.
- Scenario selection automatically changes to `Custom` after a parameter is manually edited.
- Live-update behavior remains intact.
- Randomization does not obscure the current state or destroy settings without clear user action.
- The interface remains usable on laptop-sized screens without requiring browser zoom.

---

# 28. One-Sentence Design Summary

**Turn the current form-heavy control surface into a compact dark technical console with strong module hierarchy, reusable parameter controls, visible state summaries, and advanced settings hidden until needed.**


---

# 29. Live Dashboard — New UI

## Purpose

The Live Dashboard is the operator's **at-a-glance telemetry surface**. It should answer three questions immediately:

1. Is the simulation running?
2. What is the current optical-tracking performance?
3. Are there active timing, acquisition, detection, or tracking issues?

The current screen presents metrics as isolated gray/green pills separated by very large vertical whitespace. Replace it with a structured telemetry dashboard using hierarchy, grouping, trend indicators, and compact metric cards.

## Proposed page

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ LIVE DASHBOARD                                  ● RUNNING   [ Fullscreen ]  × │
│ Real-time optical terminal telemetry                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ SYSTEM STATE                                                                  │
│                                                                              │
│  ● RUNNING        Duration 00:11        FPS 32.9        Jitter 1 ms          │
│  Simulation      [██████████████████]  Performance     [███████████]        │
├──────────────────────────────────────────────────────────────────────────────┤
│ PERFORMANCE                                                                   │
│                                                                              │
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌──────────────┐ │
│ │ FPS             │ │ JITTER          │ │ RMS ERROR       │ │ RMSE         │ │
│ │ 32.9            │ │ 1 ms            │ │ — px            │ │ — mrad       │ │
│ │ ▲ live          │ │ stable          │ │ waiting         │ │ waiting      │ │
│ └─────────────────┘ └─────────────────┘ └─────────────────┘ └──────────────┘ │
│                                                                              │
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌──────────────┐ │
│ │ SEARCHING       │ │ ACQUISITION     │ │ RE-ACQUISITION │ │ DETECTION    │ │
│ │ 3.6 s           │ │ —               │ │ —               │ │ 97%          │ │
│ └─────────────────┘ └─────────────────┘ └─────────────────┘ └──────────────┘ │
│                                                                              │
│ TRACKING                                                                     │
│ ┌───────────────────────────────┐ ┌────────────────────────────────────────┐ │
│ │ Retention Rate                │ │ Center Hit Rate                         │ │
│ │ —                             │ │ —                                      │ │
│ └───────────────────────────────┘ └────────────────────────────────────────┘ │
│                                                                              │
│ ERROR / LOSS                                                                  │
│ ┌───────────────────────────────┐ ┌────────────────────────────────────────┐ │
│ │ Avg Tracking Error            │ │ Average Loss Rate                       │ │
│ │ — px / mrad                   │ │ 0.00 / min                             │ │
│ └───────────────────────────────┘ └────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 29.1 Top status bar

Use a compact state header rather than a giant green horizontal bar.

```text
● RUNNING   Simulation active        Duration 00:11      FPS 32.9      Jitter 1 ms
```

### State colors

| State | Treatment |
|---|---|
| Running | Green status dot + subdued green background tint |
| Searching | Amber status dot |
| Acquiring | Cyan/blue status dot |
| Tracking | Green status dot |
| Warning | Amber status dot + warning icon |
| Error / Link lost | Red status dot + explicit text |
| Idle / Standby | Neutral gray/blue |

Do not use saturated fills for every metric. Reserve strong color for states that require operator attention.

## 29.2 Metric cards

Replace the current long rounded bars with compact cards. Each metric card should contain:

- Metric name.
- Current value.
- Unit.
- Short state label such as `live`, `waiting`, `stable`, or `unavailable`.
- Optional micro-trend line when historical samples are available.

Example:

```text
FPS
32.9
frames/s
● live
```

### Numeric hierarchy

- Value: `24–30px`, semibold, tabular numerals.
- Label: `11–12px`, muted.
- Unit: `11px`.
- State: `10–11px`.

## 29.3 Group metrics by operator task

Use four groups instead of the current loose grid:

### Runtime

- Duration.
- FPS.
- Jitter.

### Optical quality

- RMS error.
- RMSE.
- Average tracking error.

### Acquisition / detection

- Searching time.
- Acquisition time.
- Re-acquisition time.
- Detection rate.

### Tracking stability

- Retention rate.
- Center hit rate.
- Average loss rate.

This grouping reduces visual scanning time without changing the underlying metrics.

## 29.4 Empty / unavailable states

The current UI uses a plain `—`. Keep the dash, but add semantic status text.

```text
RMS ERROR
—
No tracking sample
```

Avoid presenting an unavailable value as zero.

## 29.5 Live refresh behavior

Metrics should update in-place without causing card reflow.

Recommended:

- Use a 150–250 ms value transition only for rapidly changing values.
- Do not animate labels or container geometry.
- Update a trend trace at a slower cadence than the raw telemetry stream.
- If a metric is stale beyond a configurable threshold, show a muted `STALE` indicator.

## 29.6 Optional diagnostics strip

A thin lower strip can show:

```text
SOURCE: LT-001   TARGET: RT-001   LINK: DETECTING   BEACON: EMITTING   FRAME: 1294
```

This should stay one line high and remain visually secondary to the metric cards.

---

# 30. Remote Terminal — New UI

## Purpose

The Remote Terminal screen is a **terminal configuration + live state surface**. It currently combines quick setup, simulation parameters, motion telemetry, and protocol settings in a single dense form. The redesign should separate these roles without hiding the frequently used controls.

## Proposed page

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ REMOTE TERMINAL                                  RT-001   ● ACTIVE            │
│ Configure terminal formation, beacon emission and link behavior              │
├──────────────────────────────────────────────────────────────────────────────┤
│ ACTIVE TERMINAL  [ RT-001 ▾ ]                      [ Randomize Remote ]       │
│ Scenario 1 / 1   ·  EMITTING   ·   LINK: DETECTING                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ QUICK SETUP                                                                    │
│                                                                              │
│ ┌─────────────────────────────────────┐ ┌──────────────────────────────────┐ │
│ │ FORMATION                           │ │ MOTION                            │ │
│ │ Terminal Count          [──●──] 1   │ │ Formation Shape     [ Circle ▾ ] │ │
│ │ Terminal Spacing       [──●──] 50 m │ │ Motion Profile      [ Constant ] │ │
│ │ Speed                   [──●──] 10m/s│ │ Heading             [──●──] 45° │ │
│ └─────────────────────────────────────┘ └──────────────────────────────────┘ │
│                                                                              │
│ ┌─────────────────────────────────────┐ ┌──────────────────────────────────┐ │
│ │ OPTICAL EMISSION                    │ │ TERMINAL / PROTOCOL               │ │
│ │ Optical Power          [──●──] 1 W  │ │ Terminal ID          [ RT-001 ]  │ │
│ │ Wavelength             [──●──]1550  │ │ State                [ ACTIVE ]  │ │
│ │ Modulation             [ AM ▾ ]     │ │ Auth Token           [ ALPHA-7 ] │ │
│ │ Spot Size              [──●──]1mrad │ │ OOK Chip Rate        [──●──]12Hz│ │
│ └─────────────────────────────────────┘ │ AM Carrier           [──●──]10kHz│ │
│                                         └──────────────────────────────────┘ │
│                                                                              │
│ ADVANCED PARAMETERS                                      [ Expand ▾ ]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 30.1 Identity / state header

The current `Active Remote Terminal` line should become a compact identity strip:

```text
RT-001   REMOTE TERMINAL
● ACTIVE   ·   BEACON: EMITTING   ·   LINK: DETECTING
```

Use semantic state chips instead of one long full-width scenario banner.

## 30.2 Quick Setup cards

The high-frequency controls belong in the initial viewport:

### Formation

- Terminal Count.
- Terminal Spacing.
- Speed.
- Terminal ID.

### Motion

- Formation Shape.
- Motion Profile.
- Heading.
- Operational State.

### Optical emission

- Power & Emission.
- Optical Power.
- Wavelength.
- Modulation.
- Spot Size.

### Link / protocol

- Auth Token.
- OOK Chip Rate.
- AM Carrier.
- Beacon state.

## 30.3 Power / beacon controls

Replace the existing four large rectangular buttons with grouped segmented controls:

```text
POWER
[ ON ] [ OFF ]

BEACON
[ ON ] [ OFF ]
```

Selected state uses accent/success styling; destructive/off states should remain neutral unless turning off the terminal is a critical state transition.

## 30.4 Advanced parameters

The current advanced section should be a collapsible group, but unlike Environment, it should retain rich sub-sections because the parameters are numerous.

Use an accordion navigation row:

```text
Advanced parameters
[A Motion] [B Protocol] [C Geometry] [D Optical] ...
```

Only one or two advanced groups should be expanded at a time on laptop screens.

---

# 31. Remote Terminal — Motion Detail / Live Telemetry

The existing motion telemetry card should be redesigned as a **read-only telemetry panel**.

```text
MOTION TELEMETRY

Acceleration        2.0 m/s²
Simulation Position X     1133.0     Y     1133.0
Link State          DETECTING
Beacon State        EMITTING
```

### Read-only visual language

Read-only values should not look like editable text fields.

Use:

- Dark/neutral value surface.
- Monospaced numeric value.
- Small `READ ONLY` indicator where ambiguity exists.

Do not use disabled-looking form controls for telemetry.

---

# 32. Remote Terminal — Protocol Panel

The protocol panel should be concise and semantically grouped.

```text
PROTOCOL

Protocol      [ OPTICAL_LINK v1 ]

Capabilities
☐ TX   ☐ RX   ☑ Beacon   ☐ Tracking
```

The capability controls are binary flags, so checkboxes are appropriate here. Keep their label text visible and aligned horizontally.

If capability state is constrained by the selected protocol, unavailable options should be disabled with a tooltip rather than removed.

---

# 33. Local Terminal — New UI

## Purpose

The Local Terminal screen is the **camera / PTZ acquisition and tracking configuration surface**. It contains both operator-facing quick setup values and engineering-level mechanical, optical, detection and control-loop parameters.

The key redesign principle is:

> Keep acquisition and tracking controls above the fold; keep calibration, mechanical imperfections, search limits and PID tuning in structured advanced groups.

## Proposed top-of-page layout

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ LOCAL TERMINAL                                  LT-001   ● STANDBY            │
│ PTZ camera, acquisition and optical tracking                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ ID LT-001     LOCAL PTZ CAMERA 01     PLATFORM-001 / WORLD FRAME             │
│                                                                              │
│ ● POWER ON    ● STANDBY    ● PTZ MOVING    ● SEARCHING                        │
│ ○ DETECTING  ○ TRACK OFF  ● NO LINK      ● AUTO RANDOM SEARCH                 │
├──────────────────────────────────────────────────────────────────────────────┤
│ QUICK SETUP — MAJOR PARAMETERS                                                │
│                                                                              │
│ ┌─────────────────────────────────────┐ ┌──────────────────────────────────┐ │
│ │ OPTICAL                              │ │ SIGNAL / SEARCH                   │ │
│ │ Center Wavelength      [──●──]1550  │ │ Signal / Live        [████ 64%] │ │
│ │ Modulation Type        [ AM ▾ ]      │ │ Modulation Freq       [──●──]10kHz│ │
│ │ Resolution W × H       [640] [480]  │ │ Search Pattern        [ RANDOM ▾ ]│ │
│ │ Optical FOV X × Y      [4°]  [3°]   │ │ Search Scan Speed     [──●──]15° │ │
│ └─────────────────────────────────────┘ └──────────────────────────────────┘ │
│                                                                              │
│ ┌─────────────────────────────────────┐ ┌──────────────────────────────────┐ │
│ │ TERMINAL IDENTITY                    │ │ TRACKING                           │ │
│ │ Expected Terminal ID [ RT-001 ]     │ │ Tracking Mode       [ TRACKING ▾ ]│ │
│ │ Expected Token       [ ALPHA-7 ]    │ │ PTZ Pan Speed       [──●──]8°/s  │ │
│ │ Acquisition Mode     [ AUTO ▾ ]     │ │ PTZ Tilt Speed      [──●──]8°/s  │ │
│ │                                     │ │ Algorithm           [ CENTROID ▾ ]│ │
│ └─────────────────────────────────────┘ └──────────────────────────────────┘ │
│                                                                              │
│ Target discrimination: ...                                                   │
│ Tracking error: Δx +0.0 px · Δy +0.0 px                                      │
│                                                                              │
│ ADVANCED PARAMETERS                                  [ Expand ▾ ]             │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 33.1 State rail

The current two-row status grid should become a **state rail**.

Each state is a compact chip:

```text
POWER   ON
OP      STANDBY
PTZ     MOVING
ACQ     SEARCHING
DET     DETECTING
TRK     OFF
LINK    NO LINK
AUTO    RANDOM SEARCH
```

Use consistent abbreviations in the small label and full state text in the value.

## 33.2 Quick setup organization

Do not split controls only by their original HTML order. Group them by operator task:

| Group | Controls |
|---|---|
| Optical | Wavelength, modulation, resolution, FOV |
| Search | Acquisition mode, pattern, scan speed |
| Identification | Expected terminal ID, token |
| Tracking | Tracking mode, algorithm, pan/tilt speed |
| Signal | Signal/live state, modulation frequency |

## 33.3 Target discrimination and tracking error

These two lines should be status callouts instead of ordinary text below the form.

```text
TARGET DISCRIMINATION
Evaluating 12 visible optical beacons · validating signatures

TRACKING ERROR
Δx +0.0 px (+0.0 µrad) · Δy +0.0 px (+0.0 µrad)
```

Color the value based on state, not on arbitrary emphasis.

---

# 34. Local Terminal — Advanced Parameters Architecture

The current local-terminal page exposes a very long sequence of sections. Replace the continuous scroll wall with a **two-level advanced navigation**.

```text
ADVANCED PARAMETERS

[A Motion] [B Pan/Tilt] [C Viewport] [D Derived] [E Mechanical]
[F Search Region] [G Detection] [H PID / Filter] [I Link]
```

On larger screens, use a two-column advanced grid. On smaller screens, use one column with accordion sections.

Each section should have:

- Section code / icon.
- Title.
- One-line purpose.
- Optional status summary.
- Expand/collapse control.

---

# 35. Local Terminal — Section A: Motion

```text
A — MOTION & LIVE TELEMETRY

Acceleration                     ─────────●────  2.0 m/s²
Simulation Position X            1133.0
Simulation Position Y            1133.0
Telemetry: Link State            DETECTING
Telemetry: Beacon State          EMITTING
```

Use compact telemetry values for X/Y instead of wide input-style fields.

---

# 36. Local Terminal — Section B: Pan-Tilt Mechanics

The current screenshot exposes minimum, maximum, home positions, actuator resolution, update rate, and latency. Present these in paired parameter rows.

```text
B — PAN/TILT MECHANICS

               Minimum                  Maximum
Pan            [───●────] 0 px         [───●────] 0 px
Tilt           [───●────] 0 px         [───●────] 0 px
Home           [──────●─] 1000 px      [──────●─] 1000 px

Actuator resolution     [──●────] 0.10 px
Update rate             [──●────] 30 Hz
Latency                 [──●────] 12 ms
```

Where a parameter is paired, keep both halves visually aligned so the relationship is obvious.

---

# 37. Local Terminal — Section C: Display / Viewport Geometry

Current controls:

- Camera Screen W/H.
- God View W/H.

New layout:

```text
C — DISPLAY / VIEWPORT

Camera Screen
Width   [────────●────] 2000 px
Height  [────────●────] 2000 px

God View
Width   [────────●────] 2000 px
Height  [────────●────] 2000 px
```

Use a 2 × 2 grid rather than four very long horizontal rows spanning the entire window.

---

# 38. Local Terminal — Section D: Derived Pixel ↔ Angle Model

This is computed output and should look visibly different from user-editable controls.

```text
D — DERIVED PIXEL ↔ ANGLE MODEL

┌──────────────────────────────┐   ┌──────────────────────────────┐
│ Pixel → Angle X              │   │ Pixel → Angle Y              │
│ 109.083 µrad/px              │   │ 109.083 µrad/px              │
└──────────────────────────────┘   └──────────────────────────────┘

Angle → Pixel X     0.00917 px/µrad
Angle → Pixel Y     0.00917 px/µrad

Derived automatically from optical geometry.
```

### Visual rule

Use a tinted read-only card. No sliders, inputs, or editable affordances.

---

# 39. Local Terminal — Section E: Actuator Realism / Mechanical Imperfections

```text
E — ACTUATOR REALISM

Max Acceleration     ─────────●──────   20.0 deg/s²
Encoder σ            ─────●──────────    0.040 px
Backlash             ──────●─────────    0.25 px
Latency Jitter       ─────●──────────    1.2 ms
```

Add a subtle `MODEL` label to distinguish simulation-imperfection parameters from hardware telemetry.

---

# 40. Local Terminal — Section F: Fine Spatial Scan Region

The current minimum/maximum controls are visually difficult to pair. Use a compact range-editor pattern.

```text
F — FINE SPATIAL SCAN REGION

PAN RANGE
Min  [──────●────────] -4.2°     Max [──────●────────]  4.2°

TILT RANGE
Min  [──────●────────] -4.8°     Max [──────●────────]  4.8°

Timeout                         [───●────────] 30 s
```

Where technically feasible, show the active range on a small axis visualization:

```text
        -4.2° ├───────────────┤ +4.2°
                scan window
```

---

# 41. Local Terminal — Section G: Fine Optical Detection Tolerances

```text
G — OPTICAL DETECTION

Bandwidth              ─────●────────────  10.0 nm
Minimum SNR            ─────────●────────   8.0 dB
Intensity Threshold    ───●──────────────   0 DN
Expected Spot          ─────●────────────   1.0 mrad
Spot Tolerance         ─────────●────────   1.5 mrad
```

Group parameters in a 2-column grid, ordered by the detection pipeline:

1. Optical bandwidth.
2. Signal threshold.
3. SNR threshold.
4. Expected geometry.
5. Tolerance.

---

# 42. Local Terminal — Section H: Servo PID / Tracking Filter

This section is engineering-facing and should be visually differentiated from basic acquisition settings.

```text
H — SERVO PID / TRACKING FILTER

Update Rate       ───●──────────── 30 Hz       Prediction Horizon ───●── 0.15 s
Smoothing         ────●─────────── 0.20        Lost Target       [ RESUME_SEARCH ]
Kp                ─────●───────── 0.25         Ki                 ───●── 0.050
Kd                ──●──────────── 0.020        Dead Zone          ───●── 0.5 px
```

### Important UI behavior

- Show engineering parameter descriptions on hover/focus.
- Use monospaced values.
- Never hide units inside tooltips when the unit materially changes interpretation.
- Preserve exact decimals entered by the operator.

---

# 43. Local Terminal — Section I: Optical Communication Transceiver Link

The current final full-width form is too visually heavy for two text fields and three capabilities.

New design:

```text
I — OPTICAL COMMUNICATION LINK

Terminal ID      [ LT-001                                      ]
Protocol         [ OPTICAL_LINK                                ]

Capabilities
☐ Optical RX     ☐ Optical TX     ☐ Tracking
```

Use a compact footer card. It should not visually compete with the tracking configuration above.

If capabilities are state flags rather than user-configurable options, convert them to read-only status chips:

```text
RX  ●   TX  ●   TRACKING  ○
```

Choose one pattern based on actual product behavior; do not mix editable checkboxes with read-only states.

---

# 44. Shared Parameter Control System

All screens should use the same control primitives. The current screenshots use multiple visually inconsistent slider/value combinations.

## 44.1 Standard slider row

```text
Label              ───────────────●────────────  12.0 px
```

Rules:

- Label width is stable within a card.
- Slider grows to consume available space.
- Value is fixed-width and right aligned.
- Unit remains attached to the value.
- Clicking the value opens numeric editing without changing the slider position unexpectedly.

## 44.2 Numeric value field

Support three modes:

```text
DISPLAY       12.0 px
HOVER         [ 12.0 px ]  edit icon
EDIT          [ 12.0 ]     [Enter]
```

Enter commits. Escape restores the previous value.

## 44.3 Select / enum

Use a consistent compact combobox:

```text
[ CONSTANT VELOCITY                         ▾ ]
```

Do not use tiny arrows aligned at the extreme edge with large empty fields.

## 44.4 Toggle

```text
Disturbances                         ● ON
```

Recommended dimensions:

- Track: `34 × 18px`.
- Thumb: `14px`.
- Focus ring: `2px`.

## 44.5 Segmented control

Use for mutually exclusive binary or short-option modes:

```text
[ POWER ON ] [ POWER OFF ]
```

Avoid using segmented controls for long option lists.

---

# 45. Shared Status Chip System

Current screens use green, gray, red, and blue bars inconsistently. Standardize status semantics.

```text
● RUNNING
● ACTIVE
● DETECTING
○ OFF
! WARNING
× ERROR
— UNAVAILABLE
```

Use both icon and text. Never communicate state by color alone.

---

# 46. Randomize UX

There are currently multiple randomization actions:

- Randomize All.
- Randomize Remote.
- Randomize Local.
- Environment randomization.

Keep the actions but clarify scope.

### Global button

```text
[ Randomize All ▾ ]
```

Optional menu:

```text
Randomize All
├─ Environment
├─ Remote Terminal
├─ Local Terminal
└─ All
```

### Local button

```text
[ Randomize Local ]
```

The button should never silently alter other modules.

After randomization, display a short non-blocking confirmation:

```text
✓ Local terminal randomized
```

Do not interrupt the operator with a modal confirmation for routine randomization.

---

# 47. Reset UX

Use scoped resets rather than one generic Reset where possible.

```text
[ Reset ]

Environment reset?  This returns environment parameters to defaults.
```

For a destructive reset, prefer an inline confirmation popover rather than a browser alert.

For harmless module resets, allow immediate action and show an undo toast for a few seconds.

---

# 48. Responsive Behavior

The screenshots show a desktop/laptop application. Preserve the high-information-density workflow but make the layout resilient.

## ≥ 1400px

- Two-column card grids.
- Full-width telemetry dashboard.
- Advanced sections can remain expanded.

## 1024–1399px

- Primary cards remain two columns where practical.
- Advanced sections collapse by default.
- Reduce card padding slightly.

## < 1024px

- Single-column cards.
- Tabs remain horizontally scrollable.
- Metric cards use 2-column grid.
- Right-aligned values remain visible.

Do not solve narrow layouts by shrinking text below readable sizes.

---

# 49. Accessibility

## Keyboard

Every interactive element must be keyboard reachable.

Recommended order:

1. Navigation.
2. Page-level actions.
3. Primary controls.
4. Advanced controls.
5. Secondary actions.

## Focus

Use a visible focus ring with sufficient contrast. Avoid changing only border color if that color is easily lost against the dark surface.

## Screen readers

Each slider must expose:

- Name.
- Current value.
- Minimum.
- Maximum.
- Unit where meaningful.

Example:

```text
"Optical power, 1.00 watt, minimum 0, maximum 5"
```

## Color

Do not encode state using color alone. Use icon + text + color.

---

# 50. Interaction Rules Across All Screens

1. **Live values update without losing focus.**
2. **Manual edits override presets and mark the configuration `Custom`.**
3. **Reset is scoped to the current module unless explicitly labeled global.**
4. **Randomize actions clearly indicate their scope.**
5. **Read-only telemetry never resembles editable input.**
6. **Unavailable values show an explanatory state, not zero.**
7. **Advanced parameters persist their open/closed state per screen.**
8. **State changes use a short status transition rather than large animations.**
9. **Units remain visible at the point of value entry.**
10. **Parameter cards do not reflow when a value changes.**

---

# 51. Information Architecture

The final application structure should read as follows:

```text
CONTROL DECK
│
├── Live Dashboard
│   ├── Runtime
│   ├── Optical Quality
│   ├── Acquisition / Detection
│   └── Tracking Stability
│
├── Remote Terminal
│   ├── Identity / State
│   ├── Quick Setup
│   │   ├── Formation
│   │   ├── Motion
│   │   ├── Optical Emission
│   │   └── Protocol
│   └── Advanced
│       ├── Motion Telemetry
│       └── Protocol Details
│
├── Local Terminal
│   ├── Identity / State
│   ├── Quick Setup
│   │   ├── Optical
│   │   ├── Search
│   │   ├── Identification
│   │   └── Tracking
│   └── Advanced
│       ├── Motion
│       ├── Pan/Tilt Mechanics
│       ├── Viewport
│       ├── Derived Geometry
│       ├── Mechanical Imperfections
│       ├── Search Region
│       ├── Detection
│       ├── PID / Tracking Filter
│       └── Optical Communication Link
│
├── Environment
│   ├── World
│   ├── Seed
│   ├── Atmosphere
│   └── Starfield
│
└── Disturbances & Noise
    ├── Master State
    ├── Scenario
    ├── Air & Light
    ├── Camera Motion
    └── Sensor Noise
```

---

# 52. Component Inventory

A reusable implementation should provide these primitives before implementing individual pages.

```text
AppShell
TopBar
PrimaryNav
PageHeader
StatusRail
StatusChip
MetricCard
MetricGroup
ControlCard
SliderField
NumericField
SelectField
Toggle
SegmentedControl
Disclosure
TelemetryValue
ReadOnlyValue
RangeEditor
Toast
Tooltip
PresetSelector
RandomizeMenu
```

This avoids having separate hand-built controls for each screenshot section.

---

# 53. Visual QA Checklist Against the Supplied Screenshots

Use the screenshots as a source-of-truth inventory for parameter coverage, but do not copy their layout geometry.

### Live Dashboard

- Status.
- Duration.
- FPS.
- Jitter.
- RMS.
- RMSE.
- Searching time.
- Acquisition time.
- Re-acquisition time.
- Detection rate.
- Retention rate.
- Center hit rate.
- Average tracking error.
- Average loss rate.

### Remote Terminal

- Terminal count.
- Spacing.
- Speed.
- Formation shape.
- Motion profile.
- Heading.
- Terminal ID.
- Operational state.
- Power.
- Beacon.
- Optical power.
- Wavelength.
- Modulation.
- Spot size.
- Auth token.
- OOK chip rate.
- AM carrier.
- Acceleration.
- Simulation position.
- Telemetry link state.
- Telemetry beacon state.
- Protocol.
- Capabilities.

### Local Terminal

- Power.
- Operation state.
- PTZ state.
- Acquisition state.
- Detection state.
- Tracking state.
- Link state.
- Auto mode.
- Center wavelength.
- Modulation type.
- Modulation frequency.
- Expected terminal ID.
- Expected token.
- Resolution.
- Optical FOV.
- Acquisition mode.
- Search pattern.
- Search scan speed.
- PTZ pan speed.
- PTZ tilt speed.
- Tracking mode.
- Tracking algorithm.
- Target discrimination.
- Tracking error.
- Pan/tilt limits.
- Home positions.
- Actuator resolution.
- Update rate.
- Latency.
- Camera / God View dimensions.
- Pixel/angle derived values.
- Max acceleration.
- Encoder noise.
- Backlash.
- Latency jitter.
- Pan/tilt search bounds.
- Timeout.
- Detection bandwidth.
- Minimum SNR.
- Intensity threshold.
- Expected spot.
- Spot tolerance.
- PID gains.
- Smoothing.
- Prediction horizon.
- Lost-target action.
- Dead zone.
- Optical communication ID/protocol/capabilities.

### Environment and Disturbances

See Sections 3–13 above.

---

# 54. Implementation Priority — Expanded

## Phase 1 — Shared foundation

- App shell.
- Navigation.
- Typography and spacing tokens.
- Slider / numeric field.
- Select / toggle / segmented control.
- Status chips.
- Card system.

## Phase 2 — Operator surfaces

- Live Dashboard.
- Remote Terminal quick setup.
- Local Terminal quick setup.

## Phase 3 — Environment / Disturbances

- Environment cards.
- Disturbance module navigation.
- Air / camera / sensor noise cards.

## Phase 4 — Engineering controls

- Local Terminal advanced groups.
- Remote Terminal advanced groups.
- Read-only derived values.
- Mechanical / PID controls.

## Phase 5 — Polish

- Micro-interactions.
- Telemetry trends.
- Keyboard navigation.
- Persistent expansion state.
- Responsive layout.
- Tooltips and inline help.

---

# 55. Final Design Intent

The four supplied screen families should feel like **one instrument**, not four independently styled forms.

The intended hierarchy is:

```text
GLOBAL SHELL
    ↓
SCREEN / MODULE
    ↓
STATUS + QUICK SETUP
    ↓
PRIMARY PARAMETERS
    ↓
LIVE TELEMETRY / FEEDBACK
    ↓
ADVANCED ENGINEERING PARAMETERS
```

The redesign should preserve the technical depth of the current application while removing the dominant weaknesses visible in the screenshots:

- Excessive empty space.
- Repetitive gray bars.
- Weak grouping.
- Tiny tabs.
- Ambiguous read-only vs editable values.
- Long uninterrupted advanced forms.
- Inconsistent status signaling.
- Poor distinction between operator controls and engineering calibration values.

The resulting UI should read as a **dense, modern optical-simulation control console**: high information density where needed, strong visual grouping, minimal decorative chrome, and immediate visibility of operational state.
