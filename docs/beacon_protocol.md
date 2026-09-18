# Beacon Protocol

> **Scope**: Shared beacon protocol package — frame format, compact payload codec, CRC, OOK encoding, and timing.

---

## 1. Package Location

The beacon protocol is a **shared package** — neither local nor remote terminal owns it:

```
common/
└── protocol/
    └── beacon/
        ├── __init__.py
        ├── payload.py      # BeaconPayload, DecodedPayload, PayloadCodec
        ├── frame.py        # BeaconFrame, BeaconFrameEncoder, BeaconFrameParser
        ├── crc.py          # CRC8, CRCValidator
        └── ook.py          # OOKEncoder, SynchronizationResult, OOKDecodeResult
```

Both the remote terminal encoder and the local terminal decoder import from `common.protocol.beacon`.

---

## 2. Wire Frame Format

Every beacon transmission uses the following deterministic binary frame:

```
┌──────────────────────────────────────────────────────────────────┐
│  PREAMBLE       8 bytes    0xAA 0xAA 0xAA 0xAA 0xAA 0xAA 0xAA 0xAA
│                            alternating 1/0 pattern (10101010…)
│  SYNC           2 bytes    0xEB 0x90
│  PROTOCOL_VER   1 byte     uint8  (default: 1)
│  MESSAGE_TYPE   1 byte     uint8  (BEACON = 0x01)
│  PAYLOAD_LEN    1 byte     uint8  (byte count of PAYLOAD field)
│  PAYLOAD        N bytes    compact binary (see §3)
│  CRC-8          1 byte     CRC-8/MAXIM over all preceding bytes
└──────────────────────────────────────────────────────────────────┘
```

### Field Details

| Field | Size | Description |
|-------|------|-------------|
| `PREAMBLE` | 8 bytes (64 bits) | Alternating 10101010 — enables clock recovery and synchronisation |
| `SYNC` | 2 bytes | `0xEB 0x90` — unique non-preamble pattern marking frame start |
| `PROTOCOL_VERSION` | 1 byte | Current version = 1. Receiver rejects unknown versions. |
| `MESSAGE_TYPE` | 1 byte | `BEACON = 0x01`. Receiver rejects unknown types. |
| `PAYLOAD_LEN` | 1 byte | Length of PAYLOAD in bytes (0–255). Receiver rejects mismatches. |
| `PAYLOAD` | N bytes | Compact binary payload (see §3) |
| `CRC-8` | 1 byte | CRC-8/MAXIM polynomial. Computed over all fields except CRC itself. |

### Rejection Conditions

The frame parser **must** reject and return a structured failure if:

| Condition | Reason Code |
|-----------|-------------|
| Preamble not detected | `INVALID_PREAMBLE` |
| SYNC word mismatch | `INVALID_SYNC` |
| `PROTOCOL_VERSION` ≠ configured | `UNSUPPORTED_VERSION` |
| `MESSAGE_TYPE` not in accepted list | `UNSUPPORTED_MESSAGE_TYPE` |
| `PAYLOAD_LEN` = 0 or > max | `INVALID_LENGTH` |
| Frame shorter than `PAYLOAD_LEN` implies | `TRUNCATED_FRAME` |
| CRC mismatch | `CRC_FAILURE` |
| Payload parse failure | `MALFORMED_PAYLOAD` |

---

## 3. Compact Binary Payload (`payload.py`)

### Default Wire Format

```
┌─────────────────────────────────────────────────────┐
│  tid_len     uint8    length of tid string in bytes  │
│  tid         bytes    UTF-8 terminal ID              │
│  token_len   uint8    length of token string         │
│  token       bytes    UTF-8 authentication token     │
│  wavelength  uint16   wavelength in nm (big-endian)  │
│  sequence    uint32   sequence number (big-endian)   │
└─────────────────────────────────────────────────────┘
```

Example encoding for `tid="RT-001"`, `token="ALPHA-7"`, `wl=1550`, `seq=42`:

```
06 52 54 2D 30 30 31        # tid_len=6, "RT-001"
07 41 4C 50 48 41 2D 37     # token_len=7, "ALPHA-7"
06 0E                        # wavelength=1550  (0x060E)
00 00 00 2A                  # sequence=42
```

Total: 20 bytes + 13 header = 33 bytes per frame.

### Python Dataclasses

```python
@dataclass
class BeaconPayload:
    terminal_id: str       # "RT-001"
    token: str             # "ALPHA-7"
    wavelength_nm: float   # 1550.0
    sequence_number: int   # monotonically increasing

@dataclass
class DecodedPayload:
    terminal_id: str
    token: str
    wavelength_nm: float
    sequence_number: int
```

### PayloadCodec

```python
class PayloadCodec:
    @staticmethod
    def encode(payload: BeaconPayload) -> bytes: ...

    @staticmethod
    def decode(data: bytes) -> DecodedPayload: ...   # raises PayloadDecodeError
```

### Optional JSON Debug Codec

The JSON codec is only used for debugging/logging — never for production simulation:

```python
payload_codec = "json_debug"   # in BeaconConfig
```

---

## 4. CRC-8 (`crc.py`)

### Polynomial

CRC-8/MAXIM (Dallas/Maxim):
- Polynomial: `0x31` (x⁸ + x⁵ + x⁴ + 1)
- Initial value: `0x00`
- Input/output reflection: Yes
- XOR out: `0x00`

```python
class CRC8:
    def compute(self, data: bytes) -> int: ...

class CRCValidator:
    def validate(self, frame_bytes: bytes) -> bool: ...
    # frame_bytes includes the CRC byte as the last element
```

---

## 5. OOK Encoding (`ook.py`)

### Encoding Rule (NRZ — Non-Return-to-Zero)

```
bit = 1  →  chip = HIGH  (intensity ON)
bit = 0  →  chip = LOW   (intensity OFF)
```

Each bit maps to exactly one chip at the configured `chip_rate_hz`.

### Frame to Chip Count

```
n_chips = n_bits_in_frame = (preamble_bytes + sync_bytes + header_bytes
                              + payload_len + crc_bytes) × 8
```

With compact payload of 20 bytes:
```
n_chips = (8 + 2 + 3 + 20 + 1) × 8 = 272 chips
```

### Chip Duration

```
chip_duration_s = 1 / chip_rate_hz
frame_duration_s = n_chips × chip_duration_s
```

Example at `chip_rate_hz = 12.0`:
```
frame_duration_s = 272 / 12.0 ≈ 22.7 s
```

### OOKEncoder

```python
class OOKEncoder:
    def encode_frame(self, frame_bytes: bytes) -> list[int]:
        """Returns list of chip values {0, 1}."""
        bits = bytes_to_bits(frame_bytes)
        return bits   # NRZ: bit value == chip value

    def chips_to_intensity(
        self,
        chips: list[int],
        on_intensity: float,
        off_intensity: float,
    ) -> list[float]: ...
```

---

## 6. BeaconFrameEncoder (`frame.py`)

Assembles a complete wire frame:

```python
class BeaconFrameEncoder:
    def encode(self, payload: BeaconPayload, codec: PayloadCodec) -> bytes:
        body = codec.encode(payload)
        frame = (
            PREAMBLE_BYTES
            + SYNC_BYTES
            + bytes([PROTOCOL_VERSION, MESSAGE_TYPE, len(body)])
            + body
        )
        crc = CRC8().compute(frame)
        return frame + bytes([crc])
```

---

## 7. BeaconFrameParser (`frame.py`)

Parses a recovered byte sequence from the demodulator:

```python
@dataclass
class BeaconDecodeResult:
    frame_detected: bool
    synchronized: bool
    valid_crc: bool
    protocol_version: int | None
    message_type: int | None
    payload_length: int | None
    payload_bytes: bytes | None
    decode_confidence: float          # 0–1
    reason: str
    is_new_frame: bool                # MANDATORY — False for duplicate sequences

class BeaconFrameParser:
    def parse(self, recovered_bytes: bytes) -> BeaconDecodeResult: ...
```

---

## 8. Timing Configuration and Validation

### Coherence Requirement

```
receiver_history_duration > 2 × frame_duration_s × safety_factor

where:
  frame_duration_s = n_frame_bits / chip_rate_hz
  safety_factor ≥ 1.5
```

### Validation Logic

```python
def validate_timing_config(
    chip_rate_hz: float,
    camera_fps: float,
    history_samples: int,
    safety_factor: float = 1.5,
) -> TimingValidationResult:

    frame_bits = compute_frame_bits()         # from protocol constants
    frame_duration_s = frame_bits / chip_rate_hz
    required_duration_s = 2 * frame_duration_s * safety_factor
    required_samples = ceil(required_duration_s * camera_fps)
    ok = history_samples >= required_samples

    return TimingValidationResult(
        ok=ok,
        frame_duration_s=frame_duration_s,
        required_samples=required_samples,
        actual_samples=history_samples,
        message=... if not ok else "OK",
    )
```

### Recommended Configuration

| Parameter | Default |
|-----------|---------|
| `chip_rate_hz` | 12.0 |
| `camera_fps` | 30.0 |
| `compact_payload_bytes` | ~20 |
| `frame_bits` | ~272 |
| `frame_duration_s` | ~22.7 |
| `required_history_s` | ~68.1 (×1.5 safety, ×2 frames) |
| `required_camera_samples` | ~2043 |

> This means the default configuration requires tracking a candidate for ~68 seconds before a first identity decode. To speed this up, increase `chip_rate_hz` or reduce payload size.

---

## 9. SynchronizationResult

The OOK decoder produces:

```python
@dataclass
class SynchronizationResult:
    synchronized: bool
    frame_start_sample: int       # index into signal history
    estimated_chip_rate_hz: float
    confidence: float             # 0–1, quality of synchronisation
    reason: str
```

---

## 10. Protocol Versioning

| Version | Status | Description |
|---------|--------|-------------|
| 1 | Current | Compact binary payload, CRC-8/MAXIM, NRZ OOK |

Future versions use a different `PROTOCOL_VERSION` byte. The receiver rejects all unknown versions.
