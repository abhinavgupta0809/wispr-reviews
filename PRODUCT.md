# Product

<!-- impeccable:product-schema 1 -->

Written Oct 12, 2026 from the repo (README, AGENTS.md, docs/DESIGN.md) and Abhinav's redesign
request. Lines marked (inferred) come from the repo, not from a direct answer.

## Platform

web

## Users

- Product people at Wispr who open the link as a work sample from Abhinav Gupta. They scan the
  findings, then check whether the evidence holds. (inferred from the work-sample series)
- Recruiters and other PMs reading it as a portfolio piece. (inferred)

## Product Purpose

An independent, unofficial dashboard of public Google Play and App Store reviews of the Wispr Flow
mobile apps: 7,007 reviews from May 23, 2025 to Oct 11, 2026, each labeled by an LLM. It shows what reviewers praise,
complain about, and ask for, and lets a reader open the reviews behind every number.

## Positioning

Every figure is computed from the review data and links to the reviews it counts. Takeaways state a
conclusion, the evidence, and the next check a PM with internal data would run.

## Operating Context

Read on a laptop from a shared link, usually once, in a few minutes. Four tabs: Overview, Deep Dive,
Opportunities, Reviews. A platform toggle scopes everything to All, Android, or iOS.

## Capabilities and Constraints

- Static site in `site/`: plain HTML, CSS, JavaScript, Chart.js from cdnjs. No build step.
- Nothing typed: site figures come from `site/data/*.json`, built by `pipeline/build_site_data.py`.
- Any subset figure shows its n. Groups under 30 reviews are dimmed.
- Store reviews are self-selected, so findings are signals to investigate, not validated problems.
- The corpus is small (7,007). Many clusters are in the tens.
- No reviewer names, avatars, or profile links anywhere.

## Brand Commitments

- Name: "Wispr Flow app reviews". Byline: Abhinav Gupta, MS Product Management at CMU.
- Abhinav's standing rule (Oct 12, 2026): each dashboard uses the company's colors so a viewer
  recognizes whose product it covers at a glance. Here that is Wispr Flow's palette, read from
  wisprflow.ai's stylesheet.
- No Wispr or Wispr Flow logo or wordmark. The footer says independent, unofficial, not affiliated.
- Color carries meaning in charts: praise, complaint, request, and stars each keep one hue.

## Evidence on Hand

- `site/data/summary.json`, `insights.json`, `reviews.json`; `site/raw_reviews.csv` and
  `annotated_reviews.csv` for download.
- Label check against 120 hand-labeled reviews: `docs/handover/02-eval.md`.

## Product Principles

1. Show the denominator.
2. Signals, not verdicts.
3. Every conclusion links to its chart and its reviews.
4. Say plainly what the data covers: mobile apps only, every review the stores served, small clusters shown with their n.

## Accessibility & Inclusion

Text contrast at 4.5:1 or better. Green and red never carry meaning alone; every chart has value
labels and a table view. Keyboard focus is visible. Reduced motion is honored.
