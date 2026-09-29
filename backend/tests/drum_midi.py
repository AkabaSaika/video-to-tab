"""A tiny Standard MIDI File reader for the tests (the app only writes MIDI)."""

from __future__ import annotations

import struct


def _vlq(data: bytes, i: int) -> tuple[int, int]:
    value = 0
    while True:
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i


def read(data: bytes) -> dict:
    """{"format", "ppq", "tracks": [[(tick, kind, fields...)]]} with absolute ticks.
    Kinds: ("on", channel, key, velocity), ("off", channel, key), ("tempo", usec),
    ("time", num, den), ("name", text), ("end",)."""
    assert data[:4] == b"MThd"
    length, fmt, ntracks, ppq = struct.unpack(">IHHH", data[4:14])
    i = 8 + length
    tracks = []
    for _ in range(ntracks):
        assert data[i : i + 4] == b"MTrk", data[i : i + 4]
        (size,) = struct.unpack(">I", data[i + 4 : i + 8])
        j, end = i + 8, i + 8 + size
        tick, status, events = 0, None, []
        while j < end:
            delta, j = _vlq(data, j)
            tick += delta
            if data[j] & 0x80:
                status = data[j]
                j += 1
            assert status is not None
            if status == 0xFF:
                kind = data[j]
                n, j = _vlq(data, j + 1)
                payload = data[j : j + n]
                j += n
                if kind == 0x51:
                    events.append((tick, "tempo", int.from_bytes(payload, "big")))
                elif kind == 0x58:
                    events.append((tick, "time", payload[0], 2 ** payload[1]))
                elif kind == 0x03:
                    events.append((tick, "name", payload.decode("utf-8")))
                elif kind == 0x2F:
                    events.append((tick, "end"))
                continue
            high, channel = status & 0xF0, (status & 0x0F) + 1
            if high in (0x80, 0x90):
                key, vel = data[j], data[j + 1]
                j += 2
                if high == 0x90 and vel > 0:
                    events.append((tick, "on", channel, key, vel))
                else:
                    events.append((tick, "off", channel, key))
            elif high in (0xC0, 0xD0):
                j += 1
            else:
                j += 2
        assert events and events[-1][1] == "end", "track must end with an end-of-track event"
        tracks.append(events)
        i = end
    return {"format": fmt, "ppq": ppq, "tracks": tracks}
