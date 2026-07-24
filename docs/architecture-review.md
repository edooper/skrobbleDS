# SkrobbleDS — Architecture Review

**Version reviewed:** 0.95.7 (`c3d351e`) · **Date:** 2026-07-24

## Scope

A review of the whole codebase (~5,100 lines: every top-level module and the entire `Upnp/`
package) looking for overcomplication and polish opportunities. The test suite was run and the
event path traced end to end.

No code changes were made. Recommendations are written to be directly executable, with
file:line anchors.

The verdict up front: **the architecture is sound and the recent bug-fix work is high
quality.** There is no structural overcomplication in the producer/consumer core. The real
weight is elsewhere — ~150 lines of UPnP code that runs on every discovery and is never read,
a denormalized `Settings`, and two hand-rolled subsystems (the logger, and the error-marker
protocol) that the standard library already provides.

---

## What's working well

Worth stating plainly, because it constrains what should change:

- **The producer/consumer split is genuinely clean.** `Player` never knows Last.fm exists;
  `Scrobbler` never knows UPnP exists. The EventBus is a thin, justified seam — not
  ceremony. Keep it.
- **Lock discipline is careful and deliberate**, not accidental: listeners copied before
  dispatch (`EventBus.py:47`), observers notified outside the lock
  (`Upnp/Discovery.py:129`, `:326`), `BEGIN IMMEDIATE` for the cross-thread cache pop
  (`Database.py:90`), `'bye'` sentinel enqueued *after* pending work (`Scrobbler.py:51`).
- **The 0.95.2–0.95.7 fixes are well-commented with the *why***, not the what — byte-accurate
  HTTP framing, coalesced-NOTIFY draining, DIDL duration, Uri-driven track change. For code
  this timing-dependent that commentary is the right call and should be preserved verbatim
  through any refactor.
- Zero third-party dependencies beyond Flask/waitress, as advertised.

---

## A. Correctness

### A1. Re-authorising a Last.fm account is a silent no-op — MEDIUM

Two independent defects on the same path, so a revoked or rotated session key cannot be
repaired from the web UI at all:

1. `WebUi.py:146` — `if session and session['name'] not in settings.get_accounts()` skips
   `add_account` entirely when the account already exists. Completing the OAuth flow a
   second time changes nothing.
2. Even if it were called, `Settings.add_account` (`Settings.py:115-122`) updates
   `keys_by_user` but not the *derived* `self.keys[player_name]` written by `add_player`
   (`Settings.py:132`). Already-linked players keep the stale key.

Fix (1) by dropping the membership test — `add_account` is already idempotent for the
account list. Fix (2) by deleting `self.keys` outright (see C1); it exists only as a
denormalization and is the sole reason a stale copy can survive.

### A2. Logger discards queued lines at shutdown — MEDIUM

`Logger.shutdown` (`Logger.py:53-57`) sets `shutdown_flag = True` *then* logs `'ByeBye'`.
`output_loop` (`Logger.py:92`) tests the flag at the top of each iteration, so it prints
whatever message it is currently holding and then exits — dropping everything still queued,
including `'ByeBye'` itself. Because `SkrobbleDs.shutdown()` calls `logger.shutdown()` last
(`SkrobbleDs.py:74-75`), the lines most likely to be lost are the final scrobble results,
i.e. exactly the ones you'd want when diagnosing a shutdown.

`Scrobbler` already solves this exact problem correctly with a sentinel (`Scrobbler.py:51`,
`:81`). Apply the same pattern here — or let it fall out of C4.

### A3. Scrobbler worker threads have no top-level exception guard — MEDIUM

Neither `_scrobble_loop` (`Scrobbler.py:64`) nor `_now_playing_loop` (`:122`) wraps its body
in try/except. Any unexpected exception kills the daemon thread **silently and permanently**:
the process keeps running, the web UI keeps serving, `/health` keeps returning `healthy`, and
scrobbling never happens again. For an unattended background service that is the worst
possible failure mode.

There is a concrete latent path: `Scrobbler.py:86` builds `info_msg` with direct
`info['title']` / `info['artist']` / `info['album']` indexing **before** the `.get()` guard on
`:91` that exists precisely because those keys may be missing. Every current emitter supplies
the keys, so this is latent rather than live — but the ordering is inverted and the loop is
unprotected. Move the guard above the message construction, and wrap each loop body in
`try/except Exception` that logs and continues.

### A4. Startup drains the durable retry cache into RAM — MEDIUM

`Scrobbler.__init__` (`Scrobbler.py:33-39`) pops *every* cached scrobble out of SQLite into an
in-memory queue at boot. The cache's entire purpose is surviving restarts; this hands the
backlog to a process that may be killed before it drains, at which point those scrobbles are
gone for good. The loop already pops on demand at `:75`, so the eager drain buys nothing —
prime a single item and let the existing timeout path do the rest.

### A5. `Upnp/Device.py:156` tests an Element for truthiness — LOW (forward-compat)

`if deviceList:` is already semantically wrong — an empty `<deviceList/>` is falsy, so its
absence and its emptiness are conflated — and Python 3.12+ deprecates Element truthiness with
a stated intent to raise. Line `:149` does it correctly with `is not None`; make `:156` match.

### A6. Regex built from a network-supplied string — LOW

`Upnp/Discovery.py:251` does `re.match('^' + newPkt.TypeString() + '$', self.iSearchType)`,
where `TypeString()` comes from the NT header of any NOTIFY on the LAN. Metacharacters raise
`re.error`, which `Ssdp.run` swallows at `Upnp/Ssdp.py:133` — so the packet is silently
dropped rather than crashing the discovery thread. Low severity, but `DoMsearch` already does
the right thing with `!=` at `Discovery.py:207`; the two paths should agree.

---

## B. Dead code and unused surface

### B1. The SCPD fetch-and-parse pipeline is unused *and* actively harmful — HIGH VALUE

`DescriptionRetriever.RetrieveServiceDescs` (`Upnp/Device.py:54-59`) performs a serial HTTP
GET **per service, per device**, feeding each response to `Service.ParseXmlDesc`
(`Upnp/Service.py:76-140`), which constructs `StateVariable` / `Action` / `Argument` object
graphs.

Nothing ever reads them. `StateVarList()` and `ActionList()` have no callers outside the file
that defines them; `Player` uses only `service.Type()` and `service.EventSubUrl()`, both of
which come from the *device* description that has already been fetched.

Two costs, one of them real:

- A Linn DS Source device exposes many services, so this adds N serial HTTP round-trips to
  every discovery.
- `DescriptionRetriever.run` wraps the whole sequence in a single try/except
  (`Upnp/Device.py:61-78`), so **one failed or slow SCPD fetch aborts the entire device
  description** and the player is never discovered at all.

Deleting the SCPD retrieval plus the `Action` / `Argument` / `StateVariable` classes removes
~150 lines and eliminates that failure mode. `Service` shrinks to what's actually used: type,
id, control URL, event-sub URL, and the relative-URL resolution.

### B2. Unused API surface, reachable from nothing

`Discovery.WaitForDiscover` / `LockDeviceList` / `UnlockDeviceList` and the `iSearchDone`
Event; `Ssdp.DumpPackets` / `iDumpPackets`; `EventSub.Timeout` / `Clear` /
`SetRequestTimeout` / `ActualTimeout` / `iTimedOut`; `Device.PresentationUrl`;
`HttpPacket.SetBody`; `LastFm.auth_get_token` (the UI uses the redirect flow, not getToken).

### B3. `Msearch` is a Thread subclass that calls one method

`Upnp/Discovery.py:28-36` exists solely to invoke `DoMsearch`. That's
`Thread(target=self.DoMsearch, daemon=True).start()`.

### B4. Python 2 leftovers

`EventSession.Append`'s str-encoding branch (`Upnp/EventServer.py:50-52`), `data = ''` where
bytes are expected on the OSError path (`:229`), and `HttpConnection`'s accepted-and-ignored
`strict` parameter (`Upnp/HttpConnection.py:7`).

---

## C. Simplification

### C1. Settings keeps 5 fields for 2 mappings

`accounts` is the key set of `keys_by_user`; `players` is the key set of `users`; and `keys`
is a pure denormalization of `keys_by_user[users[player]]` — the one that causes A1's second
half.

Collapse to two dicts:

```python
self.accounts = {}   # user -> session_key
self.players  = {}   # player_name -> user
```

`get_session_key` becomes `self.accounts.get(self.players.get(name))`. Dicts preserve
insertion order, so `get_accounts()` / `get_players()` keep returning lists in the same order
and `_save_settings` is unchanged in shape. `_remove_player_no_save` collapses to one `pop`.
The stale-key bug becomes unrepresentable.

### C2. WebUi passes every dependency twice

`create_app` receives `settings`, `players`, `shutdown_callback`, `version`, `db`, `logger` as
arguments, then stores all six *again* in `app.config['SK_*']` (`WebUi.py:47-52`) — and the
routes read them back out of `current_app.config`, shadowing the in-scope closure names
(`settings` and `players` in `index`, `shutdown_cb` in `exit_app`). One mechanism is enough;
the closure is already there. Deleting the `SK_*` layer removes ~15 lines and the shadowing.

Two smaller ones in the same file: `verify_account` binds a local `session` over the imported
Flask `session` (`WebUi.py:145`), and `datetimeformat_filter` imports `datetime` inside the
function body (`:71`).

### C3. Scrobbler hard-constructs its LastFm client

`Scrobbler.py:22` does `self.lastfm = LastFm.LastFm(logger)` while settings, logger, and db
are all injected. This isn't hypothetical: it's why
`tests/test_scrobbler.py::test_shutdown_drains_pending_scrobbles` currently fails in a
checkout whose `config/config.json` has no `api_key` — merely constructing a `Scrobbler`
reads real on-disk config. Accept the client as a constructor argument defaulting to `None`.

### C4. Logger duplicates stdlib `logging` — and the error protocol is fragile

The queue + thread + ring buffer is a hand-rolled subset of `logging`. That alone would be a
weak reason to change it. The stronger reason is the **error-banner protocol**: the web UI
decides which lines are failures by substring-matching message text against the five literals
in `Constants.LOG_ERROR_MARKERS` (`Logger.py:82-88`), each of which must be kept in hand-sync
with the exact prefixes written in `LastFm.py:136-180`. Any reworded log message silently
empties the banner, and nothing tests that coupling.

Under stdlib logging this disappears: call sites use `logger.error(...)`, a small
`logging.Handler` subclass holds the deque, and `get_recent_errors` filters on
`record.levelno >= ERROR`. DEBUG filtering — currently done twice, at `Logger.py:66` and again
at `:96` — becomes a level. `LOG_ERROR_MARKERS` is deleted.

### C5. The blank-track dict literal appears three times in Player

`Player.py:33-42`, `:145-154`, `:276-285` — with differing key order between them, which is
how a field gets missed in a future edit. Plus the blank meta dict twice (`:157`, `:172`).
Two module-level helpers, `_blank_track()` and `_blank_meta()`.

### C6. Port-scan bind loops repeated four times, three different styles

`Discovery.py:163-170`, `EventServer.py:165-172` and `:181-188`, `Ssdp.py:103-108`. The Ssdp
one is **unbounded** — no `max_port` — so a pathological environment spins forever instead of
failing. One `NetUtil.bind_in_range(sock, addr, start, count)` covers all four.

### C7. Stale docstrings and a vestigial emit in Player

`_update_meta` (`Player.py:288`) and `_update_play_status` (`:307`) both say "triggered by
TrackCount event" — TrackCount was deliberately abandoned in 0.95.7 in favour of Uri, and the
class comment at `:119-124` now explains at length why it must *not* be used. Also
`shutdown()` emits `now_playing` alongside `scrobble` (`:73`); it's a no-op because the
Scrobbler suppresses it (`stopped[-1] > playing[-1]`), but it reads as an intent to announce
"now playing" while quitting.

### C8. Database connection churn

Every operation opens a fresh `sqlite3.connect`, and `with sqlite3.connect(...)` **commits but
does not close** — connections are left for the GC. Also `add_to_history` re-runs a
full-table pruning subquery on every single insert (`Database.py:131-136`). Neither matters at
this scale, but one connection per thread (or `check_same_thread=False` plus the existing
lock) and pruning every N inserts is strictly less machinery than what's there now.

---

## D. Optional: one shared EventServer

Each `Player` starts its own `EventServer` — a thread plus a listening socket
(`Player.py:83-93`). Since `EventServer` already dispatches by SID
(`Upnp/EventServer.py:243-246`), a single app-wide instance would serve every player, removing
the per-player lifecycle and the device-IP regex at `Player.py:88`.

This is **optional and lower priority**, because it's a genuine behaviour change on
multi-homed hosts: the current code picks the interface per device via
`NetUtil.get_local_ip(host, device_ip)`, and a single shared server must bind one address.
With `network.interface` configured it's equivalent; without it, on a host with players on two
subnets, it isn't. Worth doing only if single-interface operation is guaranteed.

---

## E. Test-suite environment note (not a code defect)

Running plain `pytest` from the repo root — the command CLAUDE.md documents — fails collection
on all test files if any second copy of the repo is reachable from the working tree (e.g. a
symlinked deployment directory), because the test module basenames collide. A `pytest.ini`
with `testpaths = tests` fixes it permanently.

Baseline measured at review time, restricted to `tests/`: **70 passed, 1 failed** — the
failure being C3 above. `tests/test_webui.py` additionally requires Flask to be installed in
the interpreter running pytest.

---

## Recommended sequence

Ordered so each tier is independently shippable and testable:

1. **Correctness** — A1, A2, A3, A4 (+ A5, A6 as trivial riders). Each is small and has a
   clear test.
2. **Deletion** — B1, B2, B3, B4. Pure removal; the existing UPnP tests
   (`test_discovery_packets`, `test_httppacket`, `test_event_server`) cover the surface that
   remains. Verify against a live player, since B1 changes discovery behaviour.
3. **Simplification** — C1, C2, C3, C5, C7 first (contained), then C4 and C6, then C8.
4. **Optional** — D, only if single-interface operation is guaranteed.

Preserve the explanatory comments from the 0.95.2–0.95.7 fixes verbatim wherever the code they
annotate survives — they encode hard-won device behaviour that isn't recoverable from the code.

Verification for any tier: `pytest tests/` (expect 70+ passing), then run
`python3 SkrobbleDs.py` against a live DS and confirm through a full track change, a pause,
a stop, and an album boundary that scrobbles land — the timing paths are not fully covered by
the unit tests.
