# Part 2 — SCIO slice plan (Brief A)

**Choice:** Brief A — uploaded files, playlists, schedules, and screens.

**Why not Brief B:** The 8 November 2026 SCIO trial walked the Brief A path (upload → playlist with durations → one-time schedule with overlap warning → screen assignment → reported playback). Team, roles, and permissions were not exercised.

This document is planning only. No code.

## Team, platforms, depth

| Item | Decision |
|---|---|
| Team | 3 people: CMS web, API/storage, player. The CMS owner also runs the vertical-path QA. |
| Platforms | Web CMS and one player. No mobile app, Designer, Split Screen, or nested playlists. |
| v1 calendar | **8 weeks** |
| v1 effort | **24 person-weeks** (3 people × 8 weeks, all on this slice) |
| Depth | One account. Image files in a playlist, one-time schedule with overlap, pairing-code registration, assign schedule to that screen, playback. |

## Observed (8 Nov 2026 trial)

Facts from SCIO only. Not Help Center copy. Not v1 commitments.

1. Upload reported that files were uploaded and being processed.
2. The asset menu listed Duplicate Asset, Edit Tags, Organize, Playlists, and Move to Trash. Those actions were not used in the walkthrough.
3. Playlist `Lobby demo` held two **image** assets. Item duration had a **4-second minimum**.
4. One-time schedule `Lobby demo schedule` selected that playlist for **8:43–9:13 PM**.
5. An overlapping event warned that the **last updated** schedule item would take priority, with **Adjust Times** or **Save Anyway**.
6. The captured event dialog showed **no timezone label**.
7. Screen editor: `Screen 1` assigned to `Lobby demo schedule`. The player displayed the content.
8. Video duration was not observed. Document assets were not used. Folders were not used. Pairing a new screen was not used (`Screen 1` was already present).

## Help Center (not trial)

Cited where the trial did not show the behavior. These are product facts we design against, not SCIO screenshots.

- **Pairing** ([Getting Started Guide](https://support.optisigns.com/hc/en-us/articles/18823504383891-OptiSigns-Getting-Started-Guide)): player shows a pair code; CMS **New Screen** / **Add Screen** submits it; player then shows Paired.
- **Schedules / timezone** ([Creating and Using Schedules](https://support.optisigns.com/hc/en-us/articles/360016981853-Creating-and-Using-Schedules-with-OptiSigns)): screens play in **their local time zones**, not the computer or portal timezone. A 10–11 AM event plays 10–11 AM EST on an EST device and 10–11 AM PST on a PST device. DST is handled automatically.
- **Playlists / push** ([How to Create & Use Playlists](https://support.optisigns.com/hc/en-us/articles/28295104605843-How-to-Create-Use-Playlists), [Push Contents to Your Screens](https://support.optisigns.com/hc/en-us/articles/18988049363859-Push-Contents-to-your-Screens)): a screen assignment type may be asset, playlist, or schedule; playlist item duration is editable. Direct asset/playlist assignment is later.

## Assumptions (still unverified)

- **Processing:** “being processed” becomes `ready` or `failed`. A failed upload was not watched to completion.
- **Event dialog:** v1 can omit a timezone label in the event form (matching the trial) while still evaluating playback in each screen’s local zone (Help Center).
- Recurring rules, video native duration, and document-as-timed-still were not used in the trial.
- **Pairing TTL:** Help Center shows a code on the player; it does not state expiry. v1 codes are single-use and expire; unused expiry was not observed.
- **Refresh / offline:** the trial reported playback while online. Polling the manifest and playing a cached copy if the network drops are v1 design, not trial evidence.

## v1 versus later

| Area | v1 | Later (see roadmap) |
|---|---|---|
| Image files | Upload, processing `processing` → `ready` \| `failed`, add to playlist | — |
| Video files | Upload returns an **unsupported-file** error (type + “not in v1”). File is not stored as an asset. | Native duration as playlist default |
| Document files | Same **unsupported-file** error. Not stored. | Timed stills, ≥4s floor |
| Folders | Flat asset list | Organize / folder tree |
| Duplicate Asset | Not built | Roadmap |
| Edit Tags | Not built | Roadmap |
| Organize | Not built | Roadmap (with folders) |
| Playlists (asset menu) | Not built | Shortcut into the playlist editor |
| Move to Trash | Not built | Soft-delete / trash |
| Playlist editor | Create, ordered image items, duration ≥ 4s | Nested playlists, apps, web links |
| Schedule | One-time wall-clock events; overlap warning; last-`updated_at` wins; playback in **each assigned screen’s local timezone** | Recurrence, temp takeover, push-to-screens |
| Screen | Pairing-code register, device-reported timezone, name, assign **schedule** | Assign playlist or asset; group edit; unpair |

v1 does not ship disabled buttons for later actions. The CMS asset row has no Duplicate / Tags / Organize / Trash / Playlists menu.

Unsupported files: the API responds `unsupported_file` with the detected kind (`video`, `document`, or other) and a message that only images are accepted in v1. The CMS shows that message. Silent drop is not allowed.

## Data model (v1 only)

Account-scoped. Opaque ids.

**Asset:** `id`, `name`, `kind=image`, `processing_status`. No file-level duration.

**Playlist:** `id`, `name`, `items[]` as `{ asset_id, duration_seconds }` with `duration_seconds >= 4`. Only `ready` images.

**Schedule event:** `{ playlist_id, local_start, local_end, updated_at }`. `local_start` / `local_end` are **civil date-times without a zone** (the 8:43–9:13 PM the editor showed). `local_end > local_start`. Overlap in the CMS is overlap of those wall-clock ranges. After the warning, both events may be saved; the player uses **highest `updated_at`** on the overlap.

**Screen:** `id`, `name`, `pairing_code`, `pairing_code_expires_at`, `paired_at`, `time_zone` (IANA id from the device at pair/heartbeat), `assignment` `{ type: "schedule", id }`. A code is issued to the unpaired player, **expires**, and is **consumed once**. After expiry without a pair, the player shows a new code. Used or expired codes return an explicit error in New Screen.

Playback instant for a screen: interpret `local_start`/`local_end` in **that screen’s `time_zone`**, including DST. The same schedule on two screens at 10 AM is 10 AM local on each, not one shared UTC window. v1 still ships one screen; the data model is already per-screen so a second device would not require a schedule rewrite.

Player: unpaired (show code) → paired idle → assignment → winning event in **this device’s local zone** → playlist loop until local `local_end`.

## Upload → playback (v1)

```text
player shows pairing code (and reports time_zone)
  → CMS New Screen submits the code → player Paired
upload
  → image: processing → ready
  → video/document/other: unsupported_file error, not stored
  → playlist of ready images (each duration ≥ 4s)
  → one-time schedule event (wall-clock start/end)
  → overlap: warn last-updated wins; Adjust Times or Save Anyway
  → assign that schedule to the paired screen
  → player plays the winning event in the screen’s local timezone
```

Overlap is between **events on one schedule**. Pairing is required before assignment; the trial skipped it because `Screen 1` already existed.

## From-scratch foundations and estimate basis

v1 is a **new** CMS, API, worker, and player. The earlier **5 weeks / 15 person-weeks** only counted feature UI after those layers existed. That is not a from-scratch build. The revised total is **8 weeks / 24 person-weeks**. Foundations are not a fifth phase; they sit inside the same four phases and three roles.

| Foundation | v1 meaning | Roles | Phases |
|---|---|---|---|
| Account / auth | One account, email+password (or magic link), session cookie/token. Every row is `account_id`-scoped. One CMS role. No Brief B. The player does **not** log in as a user; it authenticates with the pairing result. | API owns identity and tenancy. CMS owns login/shell. Player unused. | **P1** (week 1). Every later write assumes this. |
| File storage and processing | Signed upload, MIME sniff, `unsupported_file` before persist, object store, worker that marks `processing` → `ready` \| `failed`, one display-sized image derivative. | API/storage owns bucket, queue, worker. CMS owns progress UI. Player only **downloads** `ready` URLs. | **P1** (week 2) to stand up. **P2** refuses non-ready ids. **P4** signed URLs on the manifest. |
| Expiring one-time pairing codes | Player displays a code with TTL. CMS New Screen consumes it once. Expired, already-used, or unknown codes return a distinct error. Unpaired player rotates to a new code after expiry. | API issues/consumes/expires. CMS New Screen. Player shows code, polls, rotates. | **P1** (week 3). **P4** reuses the paired screen token for the manifest. |
| Player refresh / offline | While online: poll/heartbeat for a new manifest (assignment or playlist change). While offline: keep the last **complete** cached playlist and play it through `local_end` in device TZ. No cache: idle, do not invent content. Reconnect: fetch manifest, replace cache. | Player owns poll, disk cache, playback. API owns cheap heartbeat + etag/manifest. CMS unused except last-seen if cheap. | Heartbeat starts **P1** (pairing poll). Cache + offline play **P4**. |
| Deployment | One shared environment: CMS, API, worker, object store, one packaged player. Secrets at runtime. | API/storage owns infra. CMS and player ship into it. | Skeleton **P1**. Production-like path **P4**. |
| QA | Contract tests per API. CMS owner runs the vertical path. Player owner runs pair → cache → play → drop-network. | All three. CMS owner is path QA lead. | A phase check at each exit. Full upload→playback **P4**. |

Cut from v1 foundations (would blow the 8 weeks): SSO, multi-role auth, transcoding farm, CDN design, OTA player auto-update, multi-region.

### Why the phase lengths (not only the order)

**Phase 1 — 3 weeks / 9 pw, not 1.5.** Week 1 is auth + app shells + deploy skeleton (three empty surfaces). Week 2 is storage + worker + `unsupported_file` (the trial’s “being processed” is a pipeline, not an upload form). Week 3 is TTL/single-use pairing plus device `time_zone`. Compressing this into 1.5 weeks assumes those layers already exist.

**Phase 2 — 1 week / 3 pw, unchanged.** Ordered list + duration ≥ 4s is small once `ready` images exist. CMS editor, API CRUD, player fixture playback. No new infra.

**Phase 3 — 1.5 weeks / 4.5 pw, not 1.** Overlap dialog is one day; **civil times vs per-screen TZ and DST** is the rest. CMS overlap is wall-clock; the player/API must not collapse two screens onto one UTC window. Worth extra calendar even with one device in the demo.

**Phase 4 — 2.5 weeks / 7.5 pw, not 1.5.** Live assignment + manifest is about a week. Refresh, disk cache, offline play, reconnect, deploy hardening, and the full QA path need the remaining 1.5. That work was previously omitted, not parallelizable into phase 1.

**Why not 5 weeks:** 15 person-weeks with auth, object storage, a worker, pairing security, offline playback, deploy, and QA would cut either pairing expiry or offline cache, or ship an unauthenticated demo. Those are in scope for a defensible from-scratch v1, so the total moved.

## Phases, calendar, person-weeks (v1)

Three people work **in parallel every week**. CMS/API order: foundations/assets → playlists → schedules → assign. Pairing starts in phase 1; assignment stays last.

| Phase | Calendar | Person-weeks | Why this order | Why this long |
|---|---|---|---|---|
| 1. Foundations, images, pairing | weeks 1–3 | 9 | Playlists need `ready` images. Pairing and `time_zone` do not. | Auth + storage/worker + expiring codes are three sequential infra slices. |
| 2. Playlists | week 4 | 3 | Duration lives on playlist items. | Editor + CRUD only; infra already up. |
| 3. Schedules | next 1.5 weeks (through mid-week 6) | 4.5 | Events point at a playlist. Overlap needs two events. | Wall-clock overlap plus screen-local TZ/DST. |
| 4. Assign, refresh, play, ship | last 2.5 weeks (mid-week 6 through week 8) | 7.5 | Needs a paired screen, TZ, schedule, and cached assets. | Manifest + offline + deploy + path QA. |
| **v1 total** | **8 weeks** | **24** | | 3 × 8. |

### Parallel work (v1)

**CMS web**

1. Login/shell; image upload and processing status; **unsupported-file** message; New Screen (including expired/used code errors). Path-QA checklist started.
2. Playlist create, order, duration (≥4s).
3. One-time wall-clock event editor; overlap dialog (Adjust Times / Save Anyway). No TZ control on the event (trial had none).
4. Assign schedule; run the vertical path on the shared env.

**API / storage**

1. Account/auth and tenancy; signed upload; worker; `unsupported_file`; issue/expire/consume pairing codes; store `time_zone`; heartbeat; deploy skeleton.
2. Playlist CRUD; `unsupported_file` / not-ready if a non-image or non-ready id is added.
3. Persist wall-clock events and `updated_at`; overlap of local ranges; last-updated-wins.
4. Screen assignment; etag manifest (winning playlist + signed image URLs + this screen’s `time_zone`); production-like deploy.

**Player**

1. App shell; show pairing code; rotate on expiry; send device timezone; poll until Paired; idle heartbeat.
2. Play an ordered list of images for given durations (fixture until the API exists).
3. Map wall-clock start/end through **device local TZ** (DST included); last-updated-wins on a fixture schedule.
4. Pull live manifest; disk-cache `ready` images; loop until local end; keep playing from cache if offline; replace cache on reconnect.

**Why not finish screens before playlists:** pairing, code TTL, and timezone reporting can start immediately; **assignment** cannot, because the trial assigned a schedule that already pointed at a playlist.

## Acceptance (v1)

In one account:

1. Launch the player, read the pairing code, submit it in New Screen, see Paired. An expired or reused code fails with an explicit error; a fresh code then pairs.
2. Upload two images; wait until `ready`.
3. Attempt a video or document upload; see the **unsupported-file** error; confirm it is not in the asset list.
4. Put the images in a playlist (durations ≥ 4s).
5. Create a one-time wall-clock window (same shape as 8:43–9:13 PM).
6. Save an overlapping event; see the last-updated warning; Save Anyway.
7. Assign that schedule to the paired screen; see the playlist on the player during that window **in the device’s local time**. After a playlist change, the player picks up the new manifest while online. If the network drops after a successful cache, playback continues from cache until local end.

Not v1 acceptance: video playback, documents, folders, trash, tags, duplicate, timezone label on the event dialog.

## Post-v1 roadmap (after the 24 person-weeks)

Same three people. Sequence follows playback risk, then library UX. Estimates are rough.

| Order | Slice | Calendar | Person-weeks | Why this order |
|---|---|---|---|---|
| 5. Video | Accept video; processing → `ready`; playlist default duration = native length (Help Center; still unverified in trial); player plays video; optional shorten + revert-to-original. | 2 weeks | 6 | Same upload → playlist → schedule → screen path as images. Highest playback risk after stills. |
| 6. Documents | Accept docs; convert or render as timed stills with the **4s minimum** already in the playlist editor. | 1.5 weeks | 4.5 | Reuses image timing and playlist items. Depends on processing, not on folders. |
| 7. Folders | Create/move folders; Organize places an asset in a folder. Flat list remains the default query. | 1 week | 3 | Library UX only. Does not change playback. After file types so folders are not image-only dead ends. |
| 8. Asset actions | Move to Trash (soft-delete; playlist items that point at trashed assets are skipped or blocked). Then Duplicate Asset. Then Edit Tags (metadata only; no screen tag rules). Then asset-menu Playlists shortcut into the editor. | 1.5 weeks | 4.5 | Trash before duplicate so copies do not strand deleted files. Tags and the Playlists shortcut last: observed in the menu, unused in the trial, no playback dependency. |
| **Post-v1 subtotal** | | **6 weeks** | **18** | After v1, not inside it. |

Still later than this roadmap: Brief B, recurrence, nested playlists, content-tag playback rules, push-to-screens variants, unpair / move-account, direct assign of playlist or asset, apps as assets.
