# AGENTS.md

Standing rules for any coding agent working in this repo.

## What this is

A static dashboard of Wispr Flow mobile app reviews (Google Play + Apple App Store), labeled by an LLM,
modeled on https://perplexity-reviews-site.vercel.app/. Pipeline in Python, site in plain HTML/CSS/JS.

## Roles

- **Claude** owns planning, taxonomy, the annotation prompt, analysis, site design, and code review.
- **Codex** writes the code. Work only from the current file in `docs/handover/`. Each handover is
  one phase. Stop when its "Done when" list is met and write the report it asks for.
- **Abhinav** runs both, approves spend, and deploys.

## Rules

- Do the phase you were handed. Don't start the next one, and don't redesign earlier ones.
- Files Claude owns, read-only for you: `docs/TAXONOMY.md`, `docs/annotation_prompt.md`,
  `docs/DESIGN.md`, `docs/handover/*` (except your own `NN-report.md` and generated `NN-eval.md`),
  `analysis/taxonomy.json`, `analysis/gold_set.csv`, `analysis/insights.json`.
  If one of them looks wrong, say so in your report instead of editing it.
- Never hard-code a number that can be computed from the data. Site figures come from
  `pipeline/build_site_data.py`, nothing is typed into HTML or JS.
- No personal data. Drop reviewer names, avatars, and profile links at scrape time. They must never
  reach a CSV, a JSON file, a fixture, or a log.
- Secrets live in `.env` (gitignored). Commit a `.env.example` with names only.
- No paid API call without a `--dry-run` path that prints estimated tokens and cost first. Run the
  full annotation only when the current handover says to, and always with the `--max-cost` guard.
- Python 3.11, a local `.venv`, pinned `requirements.txt`. Keep dependencies few.
- Scripts are idempotent and resumable. Rerunning must not duplicate rows or re-spend on finished work.
- Fail loudly. If a scraper gets zero rows, an unexpected schema, or an HTTP block, exit non-zero
  with a clear message. Never write a partial file that looks complete.
- Tests use saved fixtures. `pytest` must pass offline.
- Don't commit, push, or deploy unless the handover says to.

## Reporting

End every phase by writing `docs/handover/NN-report.md`: what you built, commands you ran with
their real output, what you did not test, anything that surprised you, and open questions.
Report failures as failures. "I didn't run this" is a fine sentence; a guessed result is not.
