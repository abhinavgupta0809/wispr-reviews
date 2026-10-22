"""Build deterministic, offline dashboard data from the reviewed corpus."""
import argparse
from collections import Counter
import csv
from datetime import timedelta
import gzip
import io
import json
import os
from pathlib import Path
import re

from . import config
from .annotate import ANNOTATION_COLUMNS, ROOT
from .annotation_support import load_taxonomy
from .common import ScrapeError, atomic_text, cli, dt, read_json, validate_row

SCOPES = ('all', 'android', 'ios')
GROUPS = ('callouts', 'improvements', 'feature_requests', 'strengths')
MATCH_KEYS = {'labels_any', 'categories_any', 'categories_all', 'pattern', 'regression_claim', 'competitors_any', 'platform'}
TOKENS = {'count', 'pct_low_star', 'avg_rating', 'ios_count', 'android_count', 'pct_of_substantive'}
REVIEW_COLUMNS = ('review_id', 'platform', 'timestamp', 'date_utc', 'rating', 'title', 'review_text', 'app_version', 'thumbs_up', 'labels', 'categories', 'sentiment_rating', 'language', 'english_translation', 'topic', 'competitors', 'regression_claim', 'rating_mismatch', 'is_truncated')


def mean(values):
    return sum(values) / len(values) if values else None


def percent(numerator, denominator):
    return numerator * 100 / denominator if denominator else None


def read_reviews(path, taxonomy):
    try:
        with Path(path).open(encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != [*config.COLUMNS, *ANNOTATION_COLUMNS]:
                raise ScrapeError('Unexpected annotated CSV columns')
            source = list(reader)
    except OSError:
        raise ScrapeError('Cannot read annotated CSV') from None
    if not source or len({r['review_id'] for r in source}) != len(source):
        raise ScrapeError('Annotated CSV empty or review IDs duplicated')
    rows = []
    for source_row in source:
        validate_row({k: source_row[k] for k in config.COLUMNS})
        if source_row['annotation_error']:
            raise ScrapeError('Annotated CSV has annotation_error rows; site not built')
        row = dict(source_row)
        for key in ('labels', 'categories', 'competitors'):
            row[key] = row[key].split(', ') if row[key] else []
            if any(v not in taxonomy[key] for v in row[key]) or len(set(row[key])) != len(row[key]):
                raise ScrapeError(f'Annotated CSV has unsupported or repeated {key}')
        if not row['labels']:
            raise ScrapeError('Annotated CSV has missing labels')
        for key in ('rating', 'sentiment_rating', 'thumbs_up'):
            try:
                row[key] = int(row[key])
            except (ValueError, TypeError):
                raise ScrapeError(f'Annotated CSV has invalid {key}') from None
        if not taxonomy['sentiment_min'] <= row['sentiment_rating'] <= taxonomy['sentiment_max']:
            raise ScrapeError('Annotated CSV has invalid sentiment')
        for key in ('regression_claim', 'rating_mismatch', 'is_truncated'):
            if row[key] not in ('TRUE', 'FALSE'):
                raise ScrapeError(f'Annotated CSV has invalid {key}')
            row[key] = row[key] == 'TRUE'
        rows.append(row)
    return rows


def compile_match(match, taxonomy):
    if not isinstance(match, dict) or set(match) - MATCH_KEYS:
        raise ScrapeError(f'Unknown match key: {sorted(set(match) - MATCH_KEYS) if isinstance(match, dict) else "invalid match"}')
    for key, enum in (('labels_any', 'labels'), ('categories_any', 'categories'), ('categories_all', 'categories'), ('competitors_any', 'competitors')):
        if key in match and (not isinstance(match[key], list) or not match[key] or any(v not in taxonomy[enum] for v in match[key])):
            raise ScrapeError(f'Unknown {enum} or invalid list in match {key}')
    if 'platform' in match and match['platform'] not in SCOPES[1:]:
        raise ScrapeError('Unknown match platform')
    if 'regression_claim' in match and type(match['regression_claim']) is not bool:
        raise ScrapeError('Match regression_claim must be a boolean')
    pattern = None
    if 'pattern' in match:
        try:
            pattern = re.compile(match['pattern'], re.IGNORECASE)
        except (re.error, TypeError):
            raise ScrapeError('Invalid match regex') from None
    def matches(row):
        if any(key in match and not set(match[key]) & set(row[field]) for key, field in (('labels_any', 'labels'), ('categories_any', 'categories'), ('competitors_any', 'competitors'))):
            return False
        if 'categories_all' in match and not set(match['categories_all']) <= set(row['categories']):
            return False
        if 'platform' in match and row['platform'] != match['platform']:
            return False
        if 'regression_claim' in match and row['regression_claim'] != match['regression_claim']:
            return False
        return pattern is None or pattern.search(' '.join(row[k] for k in ('title', 'review_text', 'english_translation', 'topic')).lower()) is not None
    return matches


def statistics(rows, substantive, taxonomy):
    standalone = set(taxonomy['labels']) - set(taxonomy['specific_labels']) - set(taxonomy['generic_labels'])
    sentiments = [r['sentiment_rating'] for r in rows if not standalone.intersection(r['labels'])]
    count = len(rows)
    return {'count': count, 'avg_rating': mean([r['rating'] for r in rows]), 'avg_sentiment': mean(sentiments),
            'sentiment_n': len(sentiments), 'nonsense_count': sum('Nonsense' in r['labels'] for r in rows),
            'low_star_count': sum(r['rating'] <= 2 for r in rows),
            'star_counts': [sum(r['rating'] == value for r in rows) for value in range(1, 6)],
            'pct_low_star': percent(sum(r['rating'] <= 2 for r in rows), count),
            'mismatch_count': sum(r['rating_mismatch'] for r in rows),
            'pct_mismatch': percent(sum(r['rating_mismatch'] for r in rows), count),
            'android_count': sum(r['platform'] == 'android' for r in rows), 'ios_count': sum(r['platform'] == 'ios' for r in rows),
            'pct_of_substantive': percent(count, substantive)}


def fill_tokens(text, stats):
    if not isinstance(text, str):
        raise ScrapeError('Insight title/text/desc must be strings')
    def replace(match):
        key = match[1].strip()
        if key not in TOKENS:
            raise ScrapeError(f'Unknown insight token: {key}')
        value = stats[key]
        if value is None:
            return 'n/a'
        if key.startswith('pct_'):
            return f'{value:.0f}%'
        if key == 'avg_rating':
            return f'{value:.2f}'
        return f'{value:,}'
    return re.sub(r'\{\{(.*?)\}\}', replace, text)


def resolve_insights(source, rows, taxonomy):
    result = {k: source[k] for k in ('evidence_note', 'label_takeaways', 'category_notes')}
    seen = set()
    for group in GROUPS:
        result[group] = []
        for item in source[group]:
            if item['id'] in seen:
                raise ScrapeError('Duplicate insight ID')
            seen.add(item['id'])
            matcher = compile_match(item['match'], taxonomy)
            matched = [r for r in rows if matcher(r)]
            if not matched:
                raise ScrapeError(f'Insight {item["id"]} matches zero reviews in all scope')
            resolved = {k: v for k, v in item.items() if k not in ('title', 'text', 'desc', 'next')}
            resolved['scopes'] = {}
            for scope in SCOPES:
                subset = [r for r in matched if scope == 'all' or r['platform'] == scope]
                substantive = sum(bool(r['categories']) for r in rows if scope == 'all' or r['platform'] == scope)
                stats = statistics(subset, substantive, taxonomy)
                resolved['scopes'][scope] = {'stats': stats, 'review_ids': [r['review_id'] for r in subset],
                                           **{k: fill_tokens(item[k], stats) for k in ('title', 'text', 'desc', 'next') if k in item}}
            result[group].append(resolved)
    return result


def complete_weeks(rows, manifest):
    run_time = dt(manifest['run_time_utc'])
    cutoff = run_time - timedelta(days=manifest['settings']['window_days'])
    first_full = cutoff.date() + timedelta(days=bool(cutoff.hour or cutoff.minute or cutoff.second or cutoff.microsecond))
    # An all-time window opens long before the first review; start the weeks at the first review instead.
    first_full = max(first_full, min(dt(r['date_utc'] + 'T00:00:00Z').date() for r in rows))
    last_full = max(dt(r['date_utc'] + 'T00:00:00Z').date() for r in rows) - timedelta(days=1)
    monday = first_full + timedelta(days=(-first_full.weekday()) % 7)
    weeks = []
    while monday + timedelta(days=6) <= last_full:
        weeks.append(monday.isoformat())
        monday += timedelta(days=7)
    return weeks, first_full.isoformat(), last_full.isoformat()


def read_daily(path):
    try:
        with Path(path).open(encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ['platform', 'date_utc', 'count']:
                raise ScrapeError('Unexpected daily true-count columns')
            rows = list(reader)
        seen = set()
        for row in rows:
            key = row['platform'], row['date_utc']
            if key in seen or row['platform'] not in SCOPES[1:] or int(row['count']) < 0:
                raise ValueError
            dt(row['date_utc'] + 'T00:00:00Z')
            row['count'] = int(row['count'])
            seen.add(key)
    except (OSError, ValueError):
        raise ScrapeError('Invalid or missing daily true counts') from None
    return rows


def top_topics(rows):
    counts = Counter(r['topic'] for r in rows if r['topic'])
    return [{'topic': k, 'count': v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:10]]


def gold_figures(path):
    try:
        text = Path(path).read_text(encoding='utf-8')
        count = int(re.search(r'Gold rows: (\d+)', text)[1])
        metrics = {}
        for line in text.splitlines():
            cells = [c.strip() for c in line.split('|')][1:-1]
            if len(cells) == 6 and cells[0] in ('Primary label accuracy', 'Primary category agreement'):
                metrics[cells[0]] = {'matches': int(cells[1]), 'n': int(cells[2]), 'pct': float(cells[3].rstrip('%'))}
        if len(metrics) != 2:
            raise ValueError
        return {'n': count, 'primary_label': metrics['Primary label accuracy'], 'primary_category': metrics['Primary category agreement']}
    except (OSError, ValueError, TypeError):
        raise ScrapeError('Cannot parse gold agreement figures from evaluation report') from None


# Cross-cuts behind the Overview insight cards: pairings a reader cannot get from one chart (helpful votes against
# complaint counts, one category against another, a spike against a release, one platform against the other).
# Patterns and thresholds live here so the site never types a number.
PAY_RE = re.compile(r'\bpay|paid|subscri|premium|\$|money|refund|cancel|trial')
OLD_RE = re.compile(r'used to|old version|bring back|went downhill|got worse|since the (last )?update|after (the )?update|downgrade')


def facts(subset, weeks, taxonomy):
    text = lambda r: f"{r.get('title') or ''} {r.get('review_text') or ''} {r.get('english_translation') or ''}".lower()
    votes_of = lambda r: int(r.get('thumbs_up') or 0)
    complaint, praise = taxonomy['specific_labels'][1], taxonomy['specific_labels'][0]
    substantive = [r for r in subset if r['categories']]
    n_sub = len(substantive) or 1
    mentions = Counter(c for r in substantive for c in r['categories'])
    out = {'n_substantive': len(substantive)}
    # Helpful votes (Google Play only) against mention share, per category.
    votes = Counter()
    for r in substantive:
        for c in r['categories']:
            votes[c] += votes_of(r)
    if sum(votes.values()) >= 500:
        total_m, total_v = sum(mentions.values()), sum(votes.values())
        out['votes'] = {'total': total_v, 'by': {c: {'count_pct': mentions[c] / total_m * 100, 'vote_pct': votes[c] / total_v * 100, 'ratio': (votes[c] / total_v) / (mentions[c] / total_m)} for c in mentions if mentions[c] >= 50}}
    # Which platform each category skews to, against the platform mix of all substantive reviews.
    ios_base = sum(r['platform'] == 'ios' for r in substantive) / n_sub * 100
    if 0 < ios_base < 100:
        out['skew'] = {'ios_base_pct': ios_base, 'by': {c: {'ios_pct': sum(r['platform'] == 'ios' for r in substantive if c in r['categories']) / mentions[c] * 100, 'count': mentions[c]} for c in mentions if mentions[c] >= 50}}
    # Complaints that still give five stars, per category.
    comps = [r for r in substantive if r['labels'][0] == complaint]
    if comps:
        base = sum(r['rating'] == 5 for r in comps) / len(comps) * 100
        by = {}
        for c in mentions:
            g = [r for r in comps if c in r['categories']]
            if len(g) >= 40:
                by[c] = {'count': len(g), 'five_pct': sum(r['rating'] == 5 for r in g) / len(g) * 100}
        out['five_star'] = {'base_pct': base, 'by': by}
    # Categories that travel together: lift = observed pairs / expected if independent.
    pairs = Counter()
    for r in substantive:
        cs = sorted(set(r['categories']))
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                pairs[(cs[i], cs[j])] += 1
    lifts = []
    for (a, b), n in pairs.items():
        if n >= 20:
            g = [r for r in substantive if a in r['categories'] and b in r['categories']]
            lifts.append({'a': a, 'b': b, 'count': n, 'lift': n * len(substantive) / (mentions[a] * mentions[b]), 'avg_rating': mean([r['rating'] for r in g]), 'ios_pct': sum(r['platform'] == 'ios' for r in g) / n * 100})
    out['pairs'] = sorted(lifts, key=lambda x: -x['lift'])[:15]
    # Developer replies on Google Play: who gets answered.
    android = [r for r in subset if r['platform'] == 'android']
    replied = lambda r: str(r.get('has_dev_reply')).upper() in ('TRUE', '1')
    if sum(replied(r) for r in android) >= 50:
        by_label = {label: {'count': sum(r['labels'][0] == label for r in android), 'rate': percent(sum(replied(r) for r in android if r['labels'][0] == label), sum(r['labels'][0] == label for r in android))} for label in taxonomy['labels']}
        by_cat = {}
        for c in mentions:
            g = [r for r in android if c in r['categories'] and r['labels'][0] == complaint]
            if len(g) >= 30:
                by_cat[c] = {'count': len(g), 'rate': percent(sum(replied(r) for r in g), len(g))}
        out['replies'] = {'total': sum(replied(r) for r in android), 'by_label': by_label, 'by_category': by_cat}
    # The biggest week for each category against the weeks before it, with the releases it landed on.
    spikes = []
    for c in mentions:
        if mentions[c] < 80:
            continue
        weekly = []
        for start in weeks:
            end = (dt(start + 'T00:00:00Z') + timedelta(days=7)).date().isoformat()
            weekly.append((start, [r for r in substantive if c in r['categories'] and start <= r['date_utc'] < end]))
        if len(weekly) < 6:
            continue
        start, group = max(weekly, key=lambda w: len(w[1]))
        before = [len(g) for s, g in weekly if s < start]
        if not before or len(group) < 25:
            continue
        ratio = len(group) / (mean(before) or 1)
        if ratio >= 2.5:
            versions = Counter((r['platform'], r['app_version']) for r in group if r['app_version']).most_common(2)
            week_all = [r for r in substantive if start <= r['date_utc'] < (dt(start + 'T00:00:00Z') + timedelta(days=7)).date().isoformat()]
            before_all = [r for r in substantive if r['date_utc'] < start and r['date_utc'] >= weeks[0]]
            spikes.append({'category': c, 'week': start, 'count': len(group), 'before_mean': mean(before), 'ratio': ratio,
                           'complaint_pct': percent(sum(r['labels'][0] == complaint for r in group), len(group)),
                           'week_n': len(week_all), 'week_avg_rating': mean([r['rating'] for r in week_all]),
                           'before_week_avg_rating': mean([r['rating'] for r in before_all]) if before_all else None,
                           'before_avg_rating': mean([r['rating'] for s, g in weekly if s < start for r in g]) if any(g for s, g in weekly if s < start) else None,
                           'versions': [{'platform': p, 'version': v, 'count': n} for (p, v), n in versions],
                           'top_topic': (Counter(r['topic'] for r in group if r['topic']).most_common(1) or [('', 0)])[0]})
    out['spikes'] = sorted(spikes, key=lambda x: -x['ratio'])
    # Stars by month and platform, so a platform average can be read as a history.
    months = sorted({r['date_utc'][:7] for r in subset})
    out['monthly'] = [{'month': m, **{p: {'n': len(g), 'avg_rating': mean([r['rating'] for r in g])} for p in ('android', 'ios') for g in [[r for r in subset if r['date_utc'][:7] == m and r['platform'] == p]] if g}} for m in months]
    # Competitors: where each rival is named more than its share.
    base_total = sum(mentions.values()) or 1
    comps_out = {}
    for name in taxonomy.get('competitors', []):
        named = [r for r in subset if name in r['competitors']]
        if len(named) < 20:
            continue
        cats = Counter(c for r in named for c in r['categories'])
        total = sum(cats.values()) or 1
        over = sorted([(c, n, (n / total) / (mentions[c] / base_total)) for c, n in cats.items() if n >= 8 and mentions[c]], key=lambda x: -x[2])
        comps_out[name] = {'count': len(named), 'avg_rating': mean([r['rating'] for r in named]), 'praise': sum(r['labels'][0] == praise for r in named), 'complaints': sum(r['labels'][0] == complaint for r in named), 'over': over[:3]}
    out['competitors'] = comps_out
    # Reviews that mention paying, and reviews that say it got worse.
    pay = [r for r in subset if PAY_RE.search(text(r))]
    old = [r for r in subset if OLD_RE.search(text(r))]
    out['pay'] = {'count': len(pay), 'avg_rating': mean([r['rating'] for r in pay]), 'cats': Counter(c for r in pay for c in r['categories']).most_common(5)}
    out['old'] = {'count': len(old), 'avg_rating': mean([r['rating'] for r in old]), 'cats': Counter(c for r in old for c in r['categories']).most_common(5)}
    return out


def scope_summary(rows, daily, scope, weeks, taxonomy):
    subset = [r for r in rows if scope == 'all' or r['platform'] == scope]
    substantive = sum(bool(r['categories']) for r in subset)
    stats = statistics(subset, substantive, taxonomy)
    stats.update(substantive=substantive, pct_substantive=percent(substantive, len(subset)),
                 non_english=sum(r['language'] not in ('en', 'und') for r in subset))
    stats['pct_non_english'] = percent(stats['non_english'], len(subset))
    def group_stats(group):
        return statistics(group, substantive, taxonomy) | {'topics': top_topics(group)}
    labels = {label: group_stats([r for r in subset if r['labels'][0] == label]) for label in taxonomy['labels']}
    categories = {category: group_stats([r for r in subset if category in r['categories']]) for category in taxonomy['categories']}
    for group in labels.values():
        group['pct_of_scope'] = percent(group['count'], len(subset))
    for name, group in categories.items():
        group['by_label'] = {label: sum(name in r['categories'] and r['labels'][0] == label for r in subset) for label in taxonomy['specific_labels']}
    standalone = set(taxonomy['labels']) - set(taxonomy['specific_labels']) - set(taxonomy['generic_labels'])
    weekly = []
    for start in weeks:
        end = (dt(start + 'T00:00:00Z') + timedelta(days=7)).date().isoformat()
        group = [r for r in subset if start <= r['date_utc'] < end]
        st = statistics(group, substantive, taxonomy)
        weekly.append({'week': start, 'volume': sum(r['count'] for r in daily if start <= r['date_utc'] < end and (scope == 'all' or r['platform'] == scope)),
                       'n': len(group), 'avg_rating': st['avg_rating'], 'avg_sentiment': st['avg_sentiment'], 'sentiment_n': st['sentiment_n'],
                       'regression': sum(r['regression_claim'] for r in group)})
    # Complaints per complete week for each category, so a trend claim on the site is computed, not typed.
    for name, group in categories.items():
        group['weekly_complaints'] = [sum(name in r['categories'] and r['labels'][0] == taxonomy['specific_labels'][1]
                                          and start <= r['date_utc'] < (dt(start + 'T00:00:00Z') + timedelta(days=7)).date().isoformat()
                                          for r in subset) for start in weeks]
    stats.update(weekly_n=sum(w['n'] for w in weekly), weekly_sentiment_n=sum(w['sentiment_n'] for w in weekly),
                 weekly_volume_n=sum(w['volume'] for w in weekly),
                 pain_n=sum(bool(r['categories']) and bool(set(r['labels']) & set(taxonomy['specific_labels'][1:])) for r in subset),
                 request_n=sum(taxonomy['specific_labels'][2] in r['labels'] for r in subset))
    versions = {}
    for row in subset:
        if row['platform'] == 'android' and row['app_version']:
            versions.setdefault(row['app_version'], []).append(row)
    def version_key(version):
        return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in re.split(r'(\d+)', version) if part)
    languages = Counter(r['language'] for r in subset)
    ordered_languages = sorted(languages.items(), key=lambda x: (-x[1], x[0]))
    language_rows = [{'name': k, 'count': n} for k, n in ordered_languages[:8]]
    if len(ordered_languages) > 8:
        language_rows.append({'name': 'Other', 'count': sum(n for _, n in ordered_languages[8:])})
    pain = []
    for name in taxonomy['categories']:
        group = [r for r in subset if name in r['categories'] and set(r['labels']) & {taxonomy['specific_labels'][1], taxonomy['specific_labels'][2]}]
        pain.append({'name': name, 'category_count': categories[name]['count'], **statistics(group, substantive, taxonomy)})
    return {'stats': stats, 'labels': labels, 'categories': categories, 'weekly': weekly,
            'ratings': [{'value': v, 'stars': sum(r['rating'] == v for r in subset),
                         'sentiment': sum(r['sentiment_rating'] == v and not standalone.intersection(r['labels']) for r in subset)}
                        for v in range(taxonomy['sentiment_min'], taxonomy['sentiment_max'] + 1)],
            'versions': [{'name': v, 'count': len(group), 'avg_rating': mean([r['rating'] for r in group])} for v, group in sorted(versions.items(), key=lambda x: version_key(x[0])) if len(group) >= 100],
            'competitors': [{'name': name, **statistics([r for r in subset if name in r['competitors']], substantive, taxonomy)} for name in taxonomy['competitors']],
            'languages': language_rows, 'pain': pain, 'facts': facts(subset, weeks, taxonomy)}


def build(args):
    taxonomy = load_taxonomy(args.taxonomy)
    rows = read_reviews(args.annotated, taxonomy)
    daily, manifest = read_daily(args.daily), read_json(args.run)
    source = read_json(args.insights)
    insights = resolve_insights(source, rows, taxonomy)
    weeks, first_full, last_full = complete_weeks(rows, manifest)
    summary = {scope: scope_summary(rows, daily, scope, weeks, taxonomy) for scope in SCOPES}
    summary['meta'] = {'product': {'name': config.PRODUCT_NAME, 'company': config.PRODUCT_COMPANY, 'label_model': config.ANNOTATION_MODEL},
                       'run_time': manifest['run_time_utc'], 'generated_at': manifest['run_time_utc'],
                       'generated_at_basis': 'Source run timestamp, fixed for deterministic builds',
                       'date_range': {'start': min(r['date_utc'] for r in rows), 'end': max(r['date_utc'] for r in rows)},
                       'first_full_day': first_full, 'last_full_day': last_full, 'weeks': weeks,
                       'gold': gold_figures(args.evaluation), 'platform_totals': {p: summary[p]['stats']['count'] for p in SCOPES[1:]},
                       'taxonomy': {k: taxonomy[k] for k in ('labels', 'categories', 'competitors', 'specific_labels')},
                       'ui': {'zero': 0, 'one': 1, 'two': 2, 'hundred': 100, 'negative_one': -1,
                              'page_reviews': 50, 'page_detail': 25, 'small_category': 30, 'few_reviews': 10,
                              'topic_min_count': 5, 'weekly_rating_min': 3,
                              'rating_min': taxonomy['sentiment_min'], 'rating_max': taxonomy['sentiment_max'],
                              'rating_values': list(range(taxonomy['sentiment_min'], taxonomy['sentiment_max'] + 1)),
                              'rating_digits': 2, 'percent_digits': 0, 'bar_radius': 4, 'line_width': 2,
                              'hover_radius': 4, 'label_padding': 8, 'chart_padding': 56,
                              'bar_row_height': 48, 'label_characters': 22, 'chart_min_height': 220,
                              'mismatch_gap': taxonomy['mismatch_threshold'], 'tab_active': 0, 'tab_inactive': -1}}
    compact = {'columns': list(REVIEW_COLUMNS), 'rows': [[r[k] for k in REVIEW_COLUMNS] for r in rows]}
    # Validate all inputs and prepare all payloads before publishing any files.
    payloads = {name: (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
                for name, value in (('summary.json', summary), ('insights.json', insights), ('reviews.json', compact))}
    try:
        raw = Path(args.raw).read_bytes()
        annotated = Path(args.annotated).read_bytes()
        raw_rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
        if [r['review_id'] for r in raw_rows] != [r['review_id'] for r in rows]:
            raise ScrapeError('Raw and annotated CSV review IDs/order differ')
    except OSError:
        raise ScrapeError('Cannot read CSV copies') from None
    for name, payload in payloads.items():
        with atomic_text(args.site / 'data' / name) as handle:
            handle.write(payload.decode('utf-8'))
            # Set the temporary file's mode before atomic publication; independent of umask.
            os.fchmod(handle.fileno(), 0o644)
    for name, payload in (('raw_reviews.csv', raw), ('annotated_reviews.csv', annotated)):
        target = args.site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy exact CSV bytes, including their original newline format.
        temp = target.with_suffix('.csv.tmp')
        temp.write_bytes(payload)
        temp.chmod(0o644)
        temp.replace(target)
    print(f'Built {len(rows)} reviews; {len(weeks)} complete UTC Monday weeks; scopes: {", ".join(SCOPES)}')
    for group in GROUPS:
        for item in insights[group]:
            print(f'Matcher {item["id"]}: {item["scopes"]["all"]["stats"]["count"]}')
    for name, payload in payloads.items():
        print(f'{name}: raw={len(payload)} bytes; gzip={len(gzip.compress(payload, mtime=0))} bytes')
    for name in ('raw_reviews.csv', 'annotated_reviews.csv'):
        print(f'{name}: {(args.site / name).stat().st_size} bytes')
    return summary, insights


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'site')
    for name, path in (('annotated', config.DATA_DIR / 'annotated_reviews.csv'), ('raw', config.DATA_DIR / 'raw_reviews.csv'), ('daily', config.DATA_DIR / 'daily_true_counts.csv'), ('run', config.DATA_DIR / 'run.json'), ('taxonomy', ROOT / 'analysis/taxonomy.json'), ('insights', ROOT / 'analysis/insights.json'), ('evaluation', ROOT / 'docs/handover/02-eval.md')):
        parser.add_argument('--' + name, type=Path, default=path)
    return parser.parse_args(argv)


def main():
    build(arguments())


if __name__ == '__main__':
    cli(main)
