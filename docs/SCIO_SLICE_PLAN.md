# SCIO slice plan — Brief A

I chose **Brief A: uploaded assets, playlists, schedules, and screens**. It is the part of SCIO I could follow from beginning to end in the trial: put content in the library, arrange it, decide when it plays, and connect it to a screen. Brief B would have required a different investigation of teams and permissions, which I did not do deeply enough to base a plan on.

My proposed first release takes **8 weeks with three people (24 person-weeks)**. It covers one account, a web CMS, an API with file processing, and one browser-based player. The path I want to prove is simple: **upload two images → make a playlist → schedule it → pair a screen → see the images play**. This is a new build, so the estimate includes login, storage, deployment, and player work. If those already existed, the estimate would be shorter.

## What I learned by using SCIO

I used the trial on 8–9 November 2026. These observations shaped the plan:

- Uploading a file reported that it was being processed. That makes upload a small pipeline, not just a form that saves a URL.
- I put two images in a `Lobby demo` playlist. Each item had its own duration, and the editor enforced a **4-second minimum**. The asset menu also offered duplicate, tags, folders, and trash, but none of those were needed to get content playing.
- I created a one-time event in `Lobby demo schedule` for 8:43–9:13 PM. A second overlapping event produced a warning: the last updated item would win during the overlap. The UI let me adjust the times or save anyway. I did not see a timezone label in that event form.
- `Screen 1` was assigned to that schedule. Its later offline status made it a poor device for further testing. I then paired a fresh **Web Player** through Add Screen, assigned the existing playlist directly, and watched both images appear in turn. I removed that temporary screen afterward. This verified pairing and direct playlist playback; it did **not** verify scheduled playback on the new screen.
- I also uploaded a six-second video and a one-page PDF to learn how SCIO treats them. Both previewed successfully. The video took its native six-second duration in a temporary playlist; the PDF took the account's 20-second default. I moved those temporary files and the playlist to Trash. Their playback on a player remains untested.

The [OptiSigns schedule guide](https://support.optisigns.com/hc/en-us/articles/360016981853-Creating-and-Using-Schedules-with-OptiSigns) says events run in each screen's local timezone. I use that product behavior in the design below. I did not observe code expiry, offline playback, or failed file processing in the trial; those are design choices to test during the build.

## The first release

I would ship the smallest complete route from an uploaded file to a paired screen. The CMS accepts **images only** at first. It shows `processing`, `ready`, or `failed` for each upload and gives a clear `unsupported_file` message for video or documents. Unsupported files do not enter the library. An image can join a playlist only after it is ready.

A playlist is an ordered list of image items. Each item has a duration of at least four seconds, and the list loops. A schedule contains one-time events that point to a playlist. Users can save overlaps after seeing the same kind of warning I saw in SCIO; the event with the latest update wins for the overlapping minutes. A screen is paired with a one-time code and can be assigned a schedule. The player refreshes its assignment while online and keeps the last complete set of images locally so a brief network loss does not turn the screen black.

I would leave video, documents, folders, duplicate/replace, tags, and trash out of this release. SCIO has all of them, and they belong in Brief A, but each adds another path to process or maintain. Shipping those controls before the basic upload-to-screen route works would spread three people too thin. I would also leave recurrence and direct asset or playlist assignment for later; the release uses schedule assignment so that the full route is exercised.

### Decisions I would settle before coding

**File processing.** The API issues a signed upload, checks the real file type, and stores the original in object storage. A worker creates a display-sized image and moves the asset from `processing` to `ready` or `failed`. The player only receives ready files. The CMS shows the failure so the user can retry rather than leaving a blank playlist item.

**Time and overlaps.** An event stores the wall-clock start and end entered in the CMS, without pretending it belongs to the administrator's timezone. When a screen plays it, the player interprets that window in the screen's reported IANA timezone. This follows the Help Center's per-screen behavior. The API stores `updated_at` so overlap priority is deterministic. I would test daylight-saving transitions explicitly, even though the first demo uses one screen.

**Pairing.** An unpaired player shows a short code. The API gives it an expiry, accepts it once, and returns a device credential after successful pairing. An expired or reused code has a specific error; the player can request a new one. I did not see the expiry behavior in SCIO, so this is a security and recovery decision for our version, not a claim about their implementation.

**Playback when the network drops.** The player downloads a complete playlist before replacing its current cache. If it loses the network, it continues with that complete copy through the scheduled window; with no cached content it stays idle. On reconnect it fetches a fresh assignment. This costs time in the last phase, but it is part of making a screen usable outside a perfect demo connection.

## Build order and estimate

The three people are a **CMS engineer**, an **API/storage engineer**, and a **player engineer**. They work in parallel, but each phase has a path that can be demonstrated before the next one depends on it. The CMS engineer owns the end-to-end QA checklist.

1. **Weeks 1–3: foundations, images, and pairing (9 person-weeks).** Put login and account boundaries in place, deploy the empty CMS/API/player shells, then build image upload and processing. In parallel, the player gets a code and can pair. I would not start the playlist editor until it has ready images to use.
2. **Week 4: playlists (3 person-weeks).** Create and reorder image items, enforce the four-second floor, and loop them on the player. This is intentionally a short phase because upload and the player shell already exist.
3. **The next 1.5 weeks: schedules (4.5 person-weeks).** Add one-time events, the overlap warning, and last-updated priority. Test how those events resolve in the screen's local timezone, including daylight-saving boundaries. Events now have a real playlist to point at.
4. **The final 2.5 weeks: assignment and playback (7.5 person-weeks).** Wire the schedule to a paired screen, refresh and cache content, then test playback through a network interruption. Leave room to run the whole route in the shared environment and fix integration issues.

That totals **8 weeks / 24 person-weeks** with three people working in parallel.

The CMS engineer owns the editor and the visible error states. The API/storage engineer owns account scoping, upload, processing, pairing-code rules, and the content manifest. The player engineer owns code display, playback, timezone handling, and the cache. In weeks 4–5, a fixture playlist or event lets the player work continue while the CMS and API pieces are being connected; the final phase replaces those fixtures with real data.

I would not promise a five-week delivery for this from scratch. That would leave only 15 person-weeks for four surfaces, file processing, pairing, scheduling, and resilient playback. Eight weeks is still tight; it depends on keeping the first release to images and one-time events. Existing auth, storage, or player infrastructure would be the clearest reason to revise the estimate down.

## How I would know it works

The final demo uses one account and one player:

1. Start the player, pair it through the CMS, and see it change from code to paired. Try a reused or expired code and get an understandable error.
2. Upload two images. See processing finish before either is selectable for a playlist. Try a PDF or video and see an explicit unsupported-file message.
3. Create a playlist with different durations. Verify the four-second floor and that both images loop in order.
4. Create a one-time event, then an overlapping event. See the warning, save anyway, and verify the latest updated event wins during the overlap.
5. Assign the schedule to the screen. During the event window, see the playlist play in that screen's local time. Change the playlist and see the player refresh. Disconnect the network after content is cached and see playback continue through the window.

I would automate the API rules for file state, duration, pairing-code reuse, and overlap priority. The CMS engineer would run the visible path at each phase exit. The player engineer would own the pairing, timezone, cache, and reconnect checks. A fixture test is useful early, but the final acceptance needs the actual CMS, API, and player together.

## What comes after

I would add the rest of Brief A in this order, using the same three-person team. These are rough estimates after the first release, not part of its eight weeks:

1. **Video — about 2 weeks.** Add processing and player playback, then use the source video's length as the playlist default. This has the highest new playback risk, so I would tackle it before library conveniences.
2. **Documents — about 1.5 weeks.** Render pages into timed stills and reuse the image display path. The one-page PDF I tested used the 20-second default in a playlist, but I did not test multi-page playback.
3. **Folders — about 1 week.** Add a folder tree and Move To for assets. The flat list can remain available.
4. **Asset actions — about 1.5 weeks.** Add trash, then duplicate/replace, tags, and the shortcut from an asset into playlists. I would define what happens to playlist items when an asset is trashed before shipping that action.

That is roughly **six more weeks / 18 person-weeks**. Recurring schedules, nested playlists, and team permissions would need separate discovery and estimates. The first release deliberately proves the route that makes all of those later features useful.
