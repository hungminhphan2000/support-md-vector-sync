# OptiBot scrape-and-index job

Daily job that scrapes OptiSigns Help Center articles, converts them to Markdown, and uploads only new or changed files into an OpenAI vector store for File search.

## Setup

1. Create an OpenAI API key and a vector store (or reuse an existing store id).
2. Copy `.env.sample` to `.env`, then fill in `API_KEY` and `VECTOR_STORE_ID`:

   ```bash
   cp .env.sample .env
   ```

3. For the GitHub Actions daily run, add the same values as repository secrets: `API_KEY`, `VECTOR_STORE_ID`.

## Local Docker run

```bash
docker build -t optibot-job .
docker run --rm --env-file .env optibot-job
```

The container runs `main.py` once and exits `0` on success. It re-scrapes Help Center articles, refreshes ids already in the store, uploads the delta, and prints `added`, `updated`, and `skipped`.

## Chunking

Uploads use the vector-store default static chunking strategy:

- `max_chunk_size_tokens=800`
- `chunk_overlap_tokens=400`

Live API responses expose `usage_bytes` and `file_counts.*`. They do **not** expose an indexed chunk count (`indexed_chunk_count_field=absent`), so embedded chunk totals cannot be logged from the published API.

## Daily run log

Latest successful Actions summary: [docs/last-run.txt](docs/last-run.txt)  
(pending until the first scheduled or manual workflow run commits real counts).

## Screenshot

Playground File search answer to “How do I add a YouTube video?”:

![YouTube File search answer](docs/screenshots/youtube-file-search.png)
