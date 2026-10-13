# Wispr Flow app reviews

An independent, unofficial dashboard of public Google Play and App Store reviews of the Wispr Flow
mobile apps: 7,007 reviews from May 23, 2025 to Oct 11, 2026, each labeled by an LLM and browsable.
Run 4 of a series (Perplexity, Indeed, Claude, Wispr Flow). Not affiliated with Wispr.

- Site: `site/` (static HTML, CSS, JavaScript; no build step)
- Findings: `analysis/insights.json`; taxonomy: `docs/TAXONOMY.md`; prompt: `docs/annotation_prompt.md`
- Label check against 120 hand-labeled reviews: `docs/handover/02-eval.md` (94.17% first label, 90.22% first category)
- Scrape volume and coverage: `data/volume_report.md`

Things specific to this run:

- **All time, not 90 days.** Wispr Flow has about 3,400 reviews in four months, so the window is
  600 days (`WINDOW_DAYS` in `pipeline/config.py`), which reaches past the oldest review either
  store serves. Android starts at its Feb 13, 2026 launch.
- **Mobile only.** The Mac and Windows apps are sold directly and have no store reviews.
- **50 App Store storefronts.** Apple's feed returns at most 500 reviews per country, so breadth is
  the only way to add iOS volume. US iOS reaches back only to Aug 2026.
- **Six Play languages left out** (ur, bn, ta, mr, ms, te): Play returned no reviews for them and
  the pinned scraper library raises on a fully empty stream.
- **Weekly series start at the first review**, and weekly averages are left blank on the site for
  weeks with fewer than 30 reviews.
- Labeling ran as four shards split by a hash of the review text, then the caches were merged.
  Cost about USD 1.30 at public rates for 6,844 distinct texts.

## Review collection

Phase 01 collects free public Google Play and App Store reviews. Python 3.11 is required.
No API key is needed for collection. Phase 02 adds annotation and gold-set evaluation;
the site build and deployment are separate phases.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m pipeline.scrape_play
.venv/bin/python -m pipeline.scrape_appstore
.venv/bin/python -m pipeline.merge
```

`pipeline/config.py` defines application IDs, Play language and iOS storefront order, the review window,
200,000-row cap (never reached in this run), seed, page size, delays, retries, and timeouts. Dependencies,
including transitive dependencies, are pinned in `requirements.txt`.

The first scraper creates `data/run.json` with one UTC run time shared by both
scrapers and the merge. The inclusive interval ends at that time. Completed pages
are atomically checkpointed under `data/interim/.checkpoints/`. Rerunning the same
commands resumes unfinished streams and skips completed streams. Checkpoints hold
only allowlisted review fields and pagination metadata. Source JSONL files are
published only after every configured stream completes successfully; the merge
requires matching completion metadata. A zero-row source, block, unrecognized
schema, repeated page, or exhausted retry exits nonzero. Errors never log response
bodies or reviewer objects. Interruption can refetch the last uncheckpointed page
without duplicating review IDs.

For a new run, use a **fresh** directory consistently for all three commands, e.g.
`--data-dir data/2026-10-10`. Optional `--run-time 2026-10-10T12:00:00Z` sets a
reproducible run time when first creating that directory. The same directory
cannot be reused with a different run time or configuration.

Outputs:

- `data/interim/play.jsonl` and `appstore.jsonl`: normalized, sanitized reviews.
- `data/raw_reviews.csv`: the exact handover columns; review bodies are preserved
  verbatim. Empty/whitespace-only bodies are excluded. Dedupe uses prefixed review
  IDs. Android `country` is empty and `store_lang` records the first Play language
  stream that returned the ID; iOS keeps the first storefront in `country` and has
  empty `store_lang`. Play passes the fixed `PLAY_COUNTRY = "us"` to the library;
  that request parameter is not exported as review geography.
- `data/daily_true_counts.csv`: unique retrieved reviews per platform and UTC day
  **before** capping, with columns `platform,date_utc,count`.
- `data/volume_report.md`: generated counts before/after cap, text statistics,
  language/storefront contributions, feed stop reasons, and hours from run time
  to the newest retrieved review per platform before capping.

If necessary, sampling uses proportional platform/day quotas with largest
remainders, then uniform random sampling inside each group with the fixed seed.
The total is exactly the cap, and each quota differs from its ideal share by less
than one row. Results are stable even if input row order changes.

Coverage is limited to what the configured locale feeds expose. App Store feeds
can stop at a page limit before covering the whole window; an HTTP 400/404 beyond page
one is treated as a page boundary only if the previous page still succeeds.
HTTP 403/429 and server/network failures are never accepted as normal exhaustion.
Daily true counts describe the retrieved corpus, not all reviews on the stores.
Country is an iOS retrieval storefront, not reviewer residence. `store_lang` is
the Play request code, not an inferred review language. No code is replaced when
its stream is empty or duplicates another; overlap counts and identical ID sets
are recorded in the report. No review text is translated. Reviewer identity fields and developer reply text are
discarded at parse time; free-form review bodies are kept as required.

The pinned [google-play-scraper](https://github.com/JoMingyu/google-play-scraper)
suppresses exceptions in its pagination routine. A narrow adapter surfaces fetch
failures through that catch, adds request timeouts/status checks, and uses the
library's newest-first pagination and continuation tokens. Offline tests cover
that adapter so dependency changes cannot silently hide a block.

Interim data, run logs, the preserved `data.run1/`, local environments, and secrets
are gitignored. Final CSVs, the volume report, and `data/run.json` are visible to
Git for a later user-authorized commit. For the 01b configuration change, move
the phase-01 `data/` directory to `data.run1/` before running fresh; keep the backup.
All test
fixtures are synthetic, sanitized examples; pytest disables socket connections
for every test. The public endpoint may change independently of these tests.

## Annotation and evaluation (phase 02)

Copy `.env.example` to `.env` locally and set `ANTHROPIC_API_KEY` before a paid
run. Never commit or print the key. Start with the estimates:

```sh
.venv/bin/python -m pipeline.annotate --gold --dry-run
.venv/bin/python -m pipeline.annotate --dry-run
```

The dry run does not use the API or write files. It reports selected rows,
distinct normalized texts, existing cache hits, approximate tokens, and cost.
The token heuristic is UTF-8 bytes divided by three; output includes an allowance
for translation. The estimate assumes one five-minute prompt-cache write followed
by hits. Retries, cache expiration, additional thinking, and injected schema
tokens can increase actual usage. Dated prices in `pipeline/config.py` are used
only for this estimate. Paid runs fetch the current public pricing table and
print response token usage and its cost at that tariff, excluding account discounts.

```sh
.venv/bin/python -m pipeline.annotate --gold
.venv/bin/python -m pipeline.evaluate
```

Gold mode writes `data/interim/gold_annotations.csv`; the evaluator writes
`docs/handover/02-eval.md` with computed metrics, a confusion matrix, category
counts, and every label/category/low-signal disagreement. Failed annotations count
as misses; sentiment MAE is calculated over scored rows, with missing rows reported.

The prompt is loaded verbatim between the markers in `docs/annotation_prompt.md`.
Taxonomy values and limits are loaded from `analysis/taxonomy.json`. Each distinct
lowercase, whitespace-collapsed title plus body is sent once, using its first
row's star rating. Only `i`, `stars`, `title`, and `text` are sent in the user
message. `--batch-size N` changes the default 25-review request size.

Validated results are appended and flushed to `data/interim/annotations.jsonl`,
keyed by SHA-256 of prompt, model, and normalized text. Cache hits incur no API
calls; changing the prompt or configured model invalidates them. Interrupted
final cache records are discarded on resume; other corruption fails loudly.
A cache lock prevents concurrent runs from spending on the same keys. Validation
failures trigger one whole-batch retry, then one single-review fallback for each
still-invalid result. Final failures remain in the CSV with `annotation_error`;
annotation-dependent fields are empty, while duplicate/truncation flags are still
computed from the source. Authentication or exhausted transport errors stop the
run before publishing a new output, preserving validated cache entries.

`--limit N` annotates the first N uncached keys for a smoke test. The output keeps
every input row in order; uncached keys outside the limit have an explicit
`annotation_error`. All 12 source columns are retained alongside 14 annotation
columns. Gold mode retains only gold rows in source order; duplicate flags always
use the entire raw corpus.

The full run requires `--yes` and prints its estimate before proceeding. Abhinav
runs it after Claude signs off on gold agreement:

```sh
.venv/bin/python -m pipeline.annotate --yes
```

For a large corpus, split `data/raw_reviews.csv` into shards by a hash of the text key, run one
`annotate` per shard with its own `--raw`, `--cache`, and `--output`, concatenate the shard caches
into `data/interim/annotations.jsonl`, then run the main command. It finds everything cached.

## Deploy

The site is the `site/` folder: static HTML, CSS, JavaScript, and generated data, with no build step.
The Vercel project imports this GitHub repository with root directory `site`. A push to `main`
redeploys.
