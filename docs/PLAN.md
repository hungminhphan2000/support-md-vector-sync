# Remaining take-home plan

Part 1 scrape/export is in place. This document plans the remaining work. The SCIO brief is Brief A; see `docs/SCIO_SLICE_PLAN.md`. The one-file check script is `check_one_file.py`. Live API uploads have already succeeded into store `vs_6af032a615b88191a363b0ae464d4677` (one-file check, then batch upload of 101 articles); see the findings below.

## What already satisfies the assignment

The scrape section asks for at least 30 Help Center articles as clean Markdown, with headings, code, and relative links kept and nav/ads removed. File names may be any scheme.

Current code:

- `src/articles.py` loads the public Zendesk list (`per_page=100`), keeps published articles, validates `id`, `title`, `body`, `html_url`, and `updated_at`, and stops after the first page once 30 published articles are in hand. Page 1 currently returns 100 published articles, so one list call fills the quota. Article `360051014713` (How to Use YouTube with OptiSigns) is not on page 1 today. The fetcher loads it from `/articles/360051014713.json` when the page does not contain it.
- `src/normalize.py` converts one article with markdownify. Output starts with the title and an `Article URL:` line. Scripts, styles, and nav are removed. Headings, nested lists, tables, relative links, inline code, fenced code, and fragment targets (`name` and `id`) are kept.
- `export_articles.py` writes UTF-8 files to `data/articles/<article-id>.md`. Last run: fetched 101, saved 101, failed 0.
- Tests cover malformed records, repeated pagination URLs, formatting, and fragment targets. `requirements.txt` declares `markdownify`.

The Help Center has about 396 articles. Fetching the rest is optional unless the one-file check shows that the YouTube article alone cannot answer the sample question.

## What is still required

Part 1, in assignment order:

1. Warm-up that only a person can do: an optisigns.com trial and a short chat with OptiBot, plus an OpenAI API key that can create a vector store.
2. A Playground Chat (Responses) setup with the File search tool, using this system prompt verbatim. The Assistants API was sunset on 26 August 2026, so this check does not create an assistant or call `/v1/assistants`.

   > You are OptiBot, the customer-support bot for OptiSigns.com.
   > • Tone: helpful, factual, concise.
   > • Only answer using the uploaded docs.
   > • Max 5 bullet points; else link to the doc.
   > • Cite up to 3 "Article URL:" lines per reply.

3. A Python upload into the vector store. UI drag-and-drop does not count. Chunking is our choice and must be explained in the README. The assignment also asks for a chunk count. That requirement stays pending. The published objects have no indexed chunk-count field. `chunking_strategy` values such as `max_chunk_size_tokens` and `chunk_overlap_tokens` are configuration, and `check_one_file.py` prints them under `chunking_strategy_settings`, not as `count_fields`. Log `chunks_embedded` only if a live run prints `indexed_chunk_count_field` as a real count outside that strategy object.
4. A screenshot of the assistant answering “How do I add a YouTube video?” with a correct answer and citations.
5. `main.py` as the scraper-uploader entrypoint, plus a `Dockerfile`. The container runs once and exits 0. Local proof:

   ```bash
   docker build -t optibot-job .
   docker run --rm \
     -e API_KEY \
     -e VECTOR_STORE_ID \
     optibot-job
   ```

   `API_KEY` and `VECTOR_STORE_ID` are required. The image name is `optibot-job`. The image `CMD` is `python main.py`, so the run command does not repeat the script name. Both variables are passed in at run time. The store id points at the store created during the one-file check, so later runs update that index instead of creating a new empty one.
6. A daily job on a public host (DigitalOcean, Railway, Render, Fly.io, AWS, or GCP). Each run re-scrapes, detects new and updated articles, uploads only that delta, and logs added, updated, and skipped counts. The README links to the job logs or a last-run artefact.
7. A GitHub repo whose name does not contain “optisigns”, clear commits, no hardcoded keys, and `.env.sample`. README is at most one page: setup, local run, log link, screenshot.

Pass bar is 70/100. Remaining points: vector upload 20, daily job and logs 15, clarity and README 10. Tests are +5, not required.

Part 2 is a separate planning document, about 10 hours, no code. Pick Brief A (assets, playlists, schedules, screens) or Brief B (team, roles, permissions, assets, screens), say why, and plan that slice only after using app.optisigns.com. That document is not this file.

## How store filenames track updates

No database. The vector store file list is the only record of what was ingested. Each uploaded object uses one filename:

```text
<article-id>-<hash>.md
```

`<hash>` is the first 16 hex characters of the SHA-256 of the exact UTF-8 Markdown bytes we upload. Listing the store and splitting the filename on the last hyphen gives the article id and the hash that was sent. `VECTOR_STORE_ID` is the only extra configuration, because the store itself has to survive between runs.

OpenAI reports each vector-store file as `in_progress`, `completed`, `failed`, or `cancelled`. Those statuses are in the current vector-store file schema. An `in_progress` or `failed` file is not counted as embedded. The store’s `file_counts` object counts files (`cancelled`, `completed`, `failed`, `in_progress`, `total`). `usage_bytes` is on both the store and the file. `chunking_strategy` reports the configured token size and overlap, which defaults to 800 and 400. That strategy is not a count of chunks produced.

For one article id, the run groups every listed file:

| What the list shows | What this run does |
|---|---|
| No file for this id | Upload `<id>-<current-hash>.md`. Count **added**. Leave it `in_progress` until the status poll finishes. |
| `completed` file whose hash equals the current Markdown | Count **skipped**. Do not upload. |
| `in_progress` file whose hash equals the current Markdown | Do not upload a second copy. Poll that file. Count **added** or **updated** only after it reaches `completed`. If it is still `in_progress` when the poll budget ends, exit non-zero and leave the file in place. |
| `failed` or `cancelled` file whose hash equals the current Markdown | This is a retry, not a skip. Delete that failed file, upload the same filename again, and poll. The previous `completed` file for another hash stays until the retry reaches `completed`. |
| `completed` file with an older hash, and no file yet for the current hash | Upload the new filename first. Poll it. Delete the old-hash file only after the new file is `completed`. If the upload or the poll ends `failed`, keep the old `completed` file and exit non-zero. |
| `in_progress` new hash plus `completed` old hash (previous run died mid-replace) | Do not upload again. Poll the new file. Delete the old file only after the new one is `completed`. |
| `completed` current hash plus any older files for the same id (previous run died after success, before delete) | Delete the older files. Count **skipped**, and log `removed_old`. |

Retrying a run is the same code path. The desired filename is a pure function of the article id and the Markdown, so a second run sees the file it already created:

- Still `in_progress` with the same hash: poll, do not upload again.
- `failed` with the same hash: delete and upload that filename again.
- `completed` with the same hash: skip.
- New file `completed` and old file still present: delete the old file now.

The old version stays searchable until the replacement has status `completed`. A failed replacement never removes the last good file.

## How articles stay fresh when page 1 changes

Zendesk page 1 is a moving window. An article ingested today can be absent from page 1 tomorrow. The job still refreshes it, because the store list remembers the id:

1. Fetch the current first page with `fetch_published_articles()`, which also backfills `360051014713` when that id is off the page.
2. List vector-store filenames and parse every article id already stored.
3. The refresh set is the union of current-page ids, stored ids, and `360051014713`.
4. Ids already present in the page payload use that payload. Every other id in the refresh set is loaded from `/articles/{id}.json`, the same endpoint the fetcher already uses for the YouTube article.
5. Convert with `article_to_markdown()` and apply the filename rules above.

An article that has left page 1 is therefore updated when its Markdown hash changes, and skipped when the hash matches the `completed` filename. A single-article response that is unpublished, missing, or invalid is logged and does not delete the `completed` file. Removing articles that disappear from the Help Center is outside the assignment.

Worked example: `360051014713` is off page 1 today. After the feasibility upload, a later daily run will not see it in the list payload. Step 3 still includes it because the filename `360051014713-<hash>.md` is in the store. Step 4 GETs `/articles/360051014713.json`. The same will happen to any page-1 article that scrolls off the page after it has been ingested once.

## What the one-file check learned

Checked against the official docs on 8 November 2026: the [Assistants migration guide](https://developers.openai.com/api/docs/assistants/migration), the [file search guide](https://developers.openai.com/api/docs/guides/tools-file-search), and the [vector store](https://developers.openai.com/api/reference/resources/vector_stores/methods/create) and [files](https://developers.openai.com/api/reference/resources/files/methods/create) reference.

| Question | Result |
|---|---|
| Which API to call | `POST /v1/vector_stores`, `POST /v1/files`, `POST /v1/vector_stores/{id}/files`, then `GET` the vector-store file until it leaves `in_progress`. File search itself is a tool on `POST /v1/responses`. |
| Assistants API | Sunset on 26 August 2026. Do not send `OpenAI-Beta: assistants=v2` and do not create an assistant. |
| Upload purpose | `user_data`. The `assistants` purpose belongs to the retired API. |
| Indexed chunk count | Still pending. Live run confirmed `indexed_chunk_count_field=absent`. `max_chunk_size_tokens=800` and `chunk_overlap_tokens=400` appeared only under `chunking_strategy_settings`. Count fields that did appear: `usage_bytes` and `file_counts.*`. |
| Live call | Passed. Exit code 0. Article `360051014713` uploaded as `360051014713-599d0a98e6285548.md`, attached, and indexed. |

Live run (key omitted):

```text
article_id=360051014713
upload_filename=360051014713-599d0a98e6285548.md
vector_store_id=vs_6af032a615b88191a363b0ae464d4677
vector_store_created=True
file_id=file-PLEB3eALfHXtvk4Jmhbsyd
vector_store_file_status=completed
vector_store_status=completed
last_error_code=None
count_fields:
  vector_store_file.usage_bytes=23021
  vector_store.usage_bytes=23021
  vector_store.file_counts.in_progress=0
  vector_store.file_counts.completed=1
  vector_store.file_counts.failed=0
  vector_store.file_counts.cancelled=0
  vector_store.file_counts.total=1
chunking_strategy_settings:
  chunking_strategy.static.max_chunk_size_tokens=800
  chunking_strategy.static.chunk_overlap_tokens=400
indexed_chunk_count_field=absent
```

Reuse that store for later work:

```bash
export VECTOR_STORE_ID=vs_6af032a615b88191a363b0ae464d4677
```

### Manual Playground steps

Completed UI check. The assignment’s “create the assistant” wording maps to Playground Chat with File search, not the retired Assistants view. The store above is already filled by the API; do not upload the Markdown again in the UI.

1. Sign in at [platform.openai.com](https://platform.openai.com).
2. Open **Playground → Chat**. Stay off any Assistants / Assistants playground link.
3. Pick a current chat model that lists the **File search** tool.
4. Turn **File search** on. Attach vector store `vs_6af032a615b88191a363b0ae464d4677`. Confirm the attached file name looks like `360051014713-599d0a98e6285548.md`.
5. Paste this into the system / instructions field, unchanged:

   ```text
   You are OptiBot, the customer-support bot for OptiSigns.com.
   • Tone: helpful, factual, concise.
   • Only answer using the uploaded docs.
   • Max 5 bullet points; else link to the doc.
   • Cite up to 3 "Article URL:" lines per reply.
   ```

6. Send exactly one user message: `How do I add a YouTube video?`
7. Stop after that reply. A second turn in the same Playground chat can fail because the UI does not expose the Responses `store` flag.
8. Check the reply before screenshotting:
   - It is about adding a YouTube video or Short in OptiSigns.
   - At most five bullets, or a link to the doc.
   - It cites the relevant source article; the citation may render as a source link. Check the target when preparing final evidence.
   - File search annotations may also show the uploaded filename.
9. Save the actual UI response as evidence and mention it from the README later. The user confirmed the original question was above the visible crop. The image shows a correct three-step answer and a link titled “How to Use YouTube with OptiSigns”; the literal URL target cannot be read from pixels alone. The malformed filecite marker is visible but did not prevent the source link from rendering. Confirm the source link target before final submission if the UI makes it accessible.

## Work checklist

Roughly 5 hours remain for Part 1 after the scrape work. Stop when a checkbox’s expected result fails, and record the actual API payload in this file before changing approach.

### 0. One-file feasibility — about 45 minutes

Use `data/articles/360051014713.md` only. Do this before writing the batch uploader, the delta loop, or Docker.

- [x] Confirm the current API from the official docs, and add `check_one_file.py`. **Result:** Assistants is retired. The script uses Files plus Vector Stores only. See the findings table.
- [x] Export `API_KEY` and run `.venv/bin/python check_one_file.py`. **Live API:** exit 0. Store `vs_6af032a615b88191a363b0ae464d4677`, file `file-PLEB3eALfHXtvk4Jmhbsyd`, status `completed`, `file_counts.completed=1`, `usage_bytes=23021`.
- [x] Treat `chunking_strategy` sizes as configuration. **Mocked:** `tests/test_check_one_file.py` passes. **Live API:** settings were `800` / `400` and were not treated as chunk counts.
- [x] Record the live status, `count_fields`, and `chunking_strategy_settings` in this plan. Key omitted.
- [ ] Log how many chunks were embedded. **Pending.** Live blocker confirmed: `indexed_chunk_count_field=absent`. Do not substitute `max_chunk_size_tokens`, `chunk_overlap_tokens`, or `usage_bytes`.
- [x] Run the Playground question and save `docs/screenshots/youtube-file-search.png`. **UI evidence:** correct three-step answer and source link shown; user confirms the original question is above the visible crop. Link destination remains to be checked for final submission.

### 1. Batch upload of the current export — about 1 hour

Depends on the live one-file store above. The Playground response now demonstrates retrieval from that store.

- [x] Add `src/vector_store.py` and `upload_articles.py`. Reuses Files + Vector Stores (not Assistants). Skips completed same-hash files, polls same-hash `in_progress` files instead of uploading duplicates, retries `failed`/`cancelled`. Reports `added`, `skipped`, `failed`, and store `file_counts`.
- [x] Focused mocked tests for filename parsing, skip/upload/retry, and a restarted run with `in_progress`. **Mocked:** `tests/test_upload_articles.py` in the full suite.
- [x] Live batch upload into `VECTOR_STORE_ID=vs_6af032a615b88191a363b0ae464d4677`. **Live API:**

  ```text
  local_articles=101
  added=82
  skipped=19
  failed=0
  completed_file_count=101
  in_progress_file_count=0
  failed_file_count=0
  total_file_count=101
  indexed_chunk_count_field=absent
  ```

  `skipped=19` includes prior completed hashes (the one-file YouTube upload plus files already present from an interrupted earlier attempt). Embedded-chunk-count stays pending.
- [x] Immediate rerun. **Live API:**

  ```text
  added=0
  skipped=101
  failed=0
  completed_file_count=101
  ```

- [x] Read-only store check after the rerun. **Live API:** planner result `to_upload=0`, `to_poll=0`, `skipped=101`. No further uploads needed for the current export.

### 2. Delta, refresh, and `main.py` — about 90 minutes

- [x] Pure delta classifier in `src/vector_store.py`: `decide_delta` / `decide_deltas` return `new`, `unchanged`, `changed`, `in_progress`, or `failed`. `plan_uploads` maps those onto upload / poll / skip. **Mocked:** `tests/test_delta.py`.
- [x] Refresh collection in `main.py`: `collect_refresh_articles` unions page ids ∪ stored ids ∪ `360051014713`, GETs missing ids via `fetch_article_by_id`, converts valid published articles to Markdown `LocalArticle`s, and skips unpublished/invalid single-article responses. **Mocked:** `tests/test_main_refresh.py` (stored id absent from page; required id backfill; skip invalid).
- [x] Wire delta decisions into `main.py`: load `.env`, list store, collect refresh set, apply `decide_deltas`, poll new files, delete old completed files only after replacement `completed`, log `added`/`updated`/`skipped`/`removed_old` and store `file_counts`, exit non-zero on failures. `delete_store_file` added in `src/vector_store.py`. **Mocked:** `tests/test_main_job.py` (new→added, changed→delete-after-complete, failed replace keeps old, unchanged removes stale old, failed-hash retry deletes before reupload).
- [x] Live refresh check: `.venv/bin/python -B main.py` exited 0. The log showed `fetch_article_by_id article_id=360051014713`, confirming the off-page YouTube article was fetched. Results: `refresh_articles=101`, `added=0`, `updated=0`, `skipped=101`, `failed=0`, `removed_old=0`, `completed_file_count=101`, `in_progress_file_count=0`, `failed_file_count=0`, `total_file_count=101`, and `indexed_chunk_count_field=absent`.
- [ ] Live replace check: upload a one-off Markdown change for a single id (or a temporary local hash override), then run again. **Expect** the new filename to reach `completed` while the old filename still exists, then **expect** the old filename to be gone and exactly one `completed` file to remain for that id. Restore the real Markdown on the next run and **expect** the same hand-off back to the original hash.

### 3. Docker — about 45 minutes

- [x] `Dockerfile` installs `requirements.txt` and sets `CMD ["python", "main.py"]`; `.dockerignore` excludes `.env`, `.venv`, and local-only files. The locally built `optibot-job` image was inspected successfully; its command is `[python main.py]`.
- [x] Run the built image locally with runtime credentials:

  ```bash
  docker build -t optibot-job .
  docker run --rm --env-file .env optibot-job
  ```

  **Live result:** `fetch_article_by_id article_id=360051014713`, `refresh_articles=101`, `added=0`, `updated=0`, `skipped=101`, `failed=0`, `removed_old=0`, `completed_file_count=101`, `in_progress_file_count=0`, `failed_file_count=0`, `total_file_count=101`, and `indexed_chunk_count_field=absent`. The preceding local `main.py` run had the same zero-delta result, so the container run also verified repeatability. `.env` is supplied only at runtime and is excluded from the image.
- [x] Run the image with either variable omitted. Both local checks exited 1 before any API call: without `API_KEY`, the error named `API_KEY`; with a dummy key and no `VECTOR_STORE_ID`, the error named `VECTOR_STORE_ID`.

### 4. Daily job — about 1 hour

- [x] GitHub Actions workflow `.github/workflows/daily-optibot.yml` prepared: daily cron (`0 6 * * *` UTC) plus `workflow_dispatch`. Builds `optibot-job`, runs it with repo secrets `API_KEY` and `VECTOR_STORE_ID`, writes only `ran_at` plus count lines to `docs/last-run.txt`, and commits that file after a successful run. **Local validation:** `actionlint .github/workflows/daily-optibot.yml` exited 0.
- [ ] Complete the first hosted daily run. The public repo and repository secrets are ready. `docs/last-run.txt` currently contains the verified local Docker counts with `source=local_docker`; verify a successful hosted run before treating it as scheduled evidence.
- [x] README links relatively to `docs/last-run.txt`, which shows the verified local Docker counts and clearly labels their source. After the first successful Actions run, the workflow replaces it with `source=github_actions`, a timestamp, and fresh counts.

### 5. README and repo — about 30 minutes

- [x] README is one page: setup, Docker run, chunking (`800` / `400`), unavailable indexed chunk count, screenshot, and relative link to `docs/last-run.txt`.
- [x] `.env.sample` lists empty `API_KEY` and `VECTOR_STORE_ID` only (no `OPENAI_API_KEY`, no store id value).
- [x] Public GitHub repo: `https://github.com/phanmhung/support-md-vector-sync`. The name omits “optisigns”; remote `HEAD` matches the local commit `e00c10e`.

## Part 2

About 10 hours. Product exploration can proceed while Part 1 hosted-run evidence is pending. The assignment prefers a partial submission that says what was cut.

Observed in the SCIO trial on 8 November 2026: upload reported that files were uploaded and being processed; the asset menu exposed actions including Duplicate Asset, Edit Tags, Organize, Playlists, and Move to Trash. The `Lobby demo` playlist contains two image assets, and the user found a 4-second minimum item duration. A one-time `Lobby demo schedule` event selected that playlist for 8:43–9:13 PM. When another event overlapped it, SCIO warned that the last updated schedule item would take priority and offered `Adjust Times` or `Save Anyway`. No timezone label is visible in the captured event dialog. The screen editor shows `Screen 1` assigned to `Lobby demo schedule`, and the user reports that the player displayed the content. Video duration remains unobserved.

- [x] Explore the core Brief A path in the SCIO trial: uploaded files → playlist with item durations → one-time schedule and overlap warning → schedule assigned to a screen with playback reported. Reviewed official Help Center articles for these features. Video and document asset behavior remain follow-up topics.
- [x] Choose Brief A or Brief B and write that choice, with the reason, at the top of the planning document. **Result:** Brief A in `docs/SCIO_SLICE_PLAN.md` because the trial already covered upload → playlist → schedule overlap → screen playback; Brief B was not exercised.
- [x] Finalize the Brief A plan. **Result:** `docs/SCIO_SLICE_PLAN.md` adds a from-scratch foundations section. Auth, storage/processing, expiring one-time pairing codes, player refresh/offline, deploy, and QA are mapped onto the three roles and four phases. **5 weeks / 15 person-weeks was not realistic** without assuming those layers already existed; v1 is **8 weeks / 24 person-weeks** (3 + 1 + 1.5 + 2.5).

## Cut line

If time runs out, finish from the top of the checklist and say which boxes were left open:

1. One-file API upload, the count fields the API actually returns, and the YouTube screenshot.
2. `main.py` delta counts, including refresh of ids already in the store.
3. `docker run --rm -e API_KEY -e VECTOR_STORE_ID optibot-job` exits 0.
4. Daily schedule and a log link.
5. One-page README.
6. Part 2.

A full-catalog crawl, a database, delete-sync for articles removed from the Help Center, and a custom chat UI stay out of scope unless the one-file check fails.
