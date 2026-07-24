# Design: Uri-driven track-change detection (fix missing first album track)

## Problem

The first track of a newly-started album is frequently missed (recorded with a
blank title, so no now-playing and no scrobble), in normal use — not just under
rapid skipping.

Confirmed against a live Linn Selekt DSM with `gupnp-event-dumper`: when a new
album starts, the Linn's Info service fires **two `TrackCount` events in quick
succession** (e.g. 132 then 133, ~2.7s apart, both duration 239s — i.e. the same
first track counted twice). The real `Metadata` (title/artist) is delivered
*after* the first `TrackCount`, as a separate event. The second `TrackCount`
sometimes re-sends `Metadata`, sometimes does not — a race.

`Player._on_info_event` treats **every** `TrackCount` change as a track boundary:
it emits a scrobble for the outgoing track and resets `self.current`/`self.meta`.
So the second, spurious `TrackCount` wipes the first track's just-delivered
metadata, and when no fresh `Metadata` follows, the track plays out blank.

Event order observed per real track: `TrackCount` → `Uri` → `Metadata` →
`Duration`. The spurious second `TrackCount` is **not** accompanied by a new
`Uri` (it repeats the same track's Uri, or sends none).

## Approach (surgical)

Trigger track-boundary handling off the **`Uri`** state variable instead of
`TrackCount`. The Uri is the reliable per-track identity (Tidal
`tidal://track?trackId=…`, local file path, radio stream URL); a genuine track
change is a new, different, non-empty Uri. The duplicate/spurious `TrackCount`
carries the same Uri (or none), so it becomes a no-op and can no longer wipe
good metadata.

This keeps the existing structure (scrobble-outgoing → reset → debounced
`_update_meta`); only the *trigger* moves from `TrackCount` to `Uri`.

## Changes (`Player.py`)

- Add `self.current_uri = ''` to `__init__`.
- In `_on_info_event`, add an `elif name == 'Uri':` branch:
  - If `value` is non-empty and `value != self.current_uri`:
    - set `self.current_uri = value`
    - run the existing track-boundary block (cancel timers; append stopped;
      emit `scrobble` for the outgoing `self.current` **iff** it has title+artist;
      reset `self.current`, `self.meta`, `self.duration`; append the
      playing/stopped timestamp; start the `update_meta_timer`).
  - Otherwise (empty or unchanged Uri): do nothing.
- Remove the track-boundary body from the `TrackCount` branch. `TrackCount` is
  no longer a reset trigger. (Drop the branch, or keep it only as a debug log.)
- `Metadata`, `Duration`, `TransportState` handling, the `_update_meta` /
  resync logic, `_on_stopped`, and the blank-scrobble guard are unchanged.

## Behavior / edge cases

- **New album's first track**: first `Uri` (real) triggers the change and
  populates metadata; the duplicate second `TrackCount` has the same Uri → no-op
  → metadata preserved. Fixed.
- **Normal mid-album change**: new Uri each track → triggers as before.
- **Rapid skipping**: each landed track has a distinct Uri → resolves to that
  track; transitional bursts without a new Uri are ignored.
- **Last track of a queue/album**: no following Uri change; still scrobbled by
  the existing Stopped → `_on_stopped` timer path.
- **Same track on repeat**: same Uri → not re-detected (rare; accepted).
- **Source with no Uri**: track changes wouldn't be detected — not a case for
  the supported players (Tidal/local/radio all send a Uri).

## Verification

- Unit tests (extend `tests/test_player_track_change.py`):
  - A new non-empty Uri triggers a scrobble of the outgoing track and resets.
  - A repeated/identical Uri does **not** trigger (metadata preserved) — the
    album-boundary duplicate-TrackCount regression.
  - A `TrackCount` change alone (no Uri change) does **not** reset/scrobble.
  - Empty Uri is ignored.
- Live validation against the device + `gupnp-event-dumper` on faust: start a
  new album from track 1 and confirm the first track's title populates, now-
  playing is sent, and it scrobbles when it ends — cross-checked against the
  wire stream.
