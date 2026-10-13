# Local dashboard

From `site/`, run:

```sh
python3 -m http.server
```

Open the localhost URL printed by the server. Chart.js 4.4.1 loads from cdnjs; all dashboard data, reviews, styles, code, and CSV downloads are local. No build step or framework is needed.

Rebuild the data from the repository root with `.venv/bin/python -m pipeline.build_site_data`. JSON is deterministic: generated-at uses the source run timestamp. Changes to the source data, taxonomy, or narrative require rebuilding.
