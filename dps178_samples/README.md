# Phase 0 DPS sample archive

This directory holds the raw DPS values captured during Phase 0 of the
room-cleaning feature investigation (see the master plan at
`~/.claude/plans/noble-snuggling-neumann.md` and the per-session plan at
`~/.claude/plans/users-takao-claude-plans-noble-snugglin-goofy-jellyfish.md`).

## Status

**Phase 0 concluded INCONCLUSIVE on 2026-05-02 with FW 7.0.168.**

Room-cleaning data (room IDs, room names, room polygons) does NOT travel over
the local Tuya channel that this integration uses. The Eufy mobile app sends
room selection commands directly to the device via the Tuya cloud / encrypted
P2P channel; the device only echoes a "room mode is on" flag back over the
local LAN (DPS 152 = `AggB`, DPS 153.field1 = `{field1=1}`). The actual room
identifiers are never exposed locally, regardless of which room or how many
rooms are selected (verified across S6, S7, S8, S8b, S8c).

Phases A–D of the master plan are therefore not implementable as designed.
See the master plan §9 final conclusion section for the full reasoning.

## What's here

Raw base64 strings as published by the device, grouped by DPS. Each file is
a single line. Filenames encode `<scenario_id>_<short_description>.b64`.

The samples were captured with `dump_dps` and the diff logger added in commit
`2f6ce00` on the `feature/room-cleaning` branch.

The screenshots that accompany the app-side scenarios (S3, S5, S8, S8b, S8c)
are referenced by the same `<scenario_id>` and would normally live under
`screenshots/`. The user holds the originals on their Mac Desktop; they are
not committed here because they may contain identifying floor-plan detail.

## Decoding tip

Most samples are protobuf wrapped in a 1-byte length prefix. Strip the
leading byte and feed the rest to `protoc --decode_raw`, or use a small
Python varint parser. See the master plan §9 "Phase 0-3 中間メモ" table
for known semantics of each DPS.
