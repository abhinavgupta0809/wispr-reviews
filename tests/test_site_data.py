from copy import deepcopy
import csv
from datetime import timedelta
import json
from pathlib import Path

import pytest

from pipeline import build_site_data as site, config
from pipeline.annotate import ANNOTATION_COLUMNS
from pipeline.annotation_support import load_taxonomy
from pipeline.common import ScrapeError, dt

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MATCH_COUNTS = {
    'c_reliability': 626,
    'c_regression': 292,
    'c_substantive': 4801,
    'c_before_use': 498,
    'i_fails': 626,
    'i_nothing': 90,
    'i_paste': 80,
    'i_regressed': 138,
    'i_bubble': 265,
    'i_bubble_gone': 83,
    'i_banking': 53,
    'i_switch': 76,
    'i_keyboard': 58,
    'i_mic_on': 19,
    'i_ipad': 45,
    'i_word_limit': 120,
    'i_limit_surprise': 34,
    'i_pricing': 252,
    'i_login': 140,
    'i_setup': 174,
    'i_perm_stuck': 75,
    'i_privacy': 196,
    'i_accuracy': 410,
    'i_first_words': 18,
    'i_added_words': 32,
    'i_overedit': 26,
    'i_language': 258,
    'i_wrong_lang': 81,
    'i_parity': 106,
    'i_battery': 53,
    'i_billing': 84,
    'i_ads': 52,
    'f_keyboard': 89,
    'f_parity': 62,
    'f_language': 57,
    'f_ui': 59,
    'f_editing': 43,
    'f_pricing': 45,
    'f_history': 22,
    'f_accuracy': 80,
    's_accuracy': 980,
    's_time': 870,
    's_vs_native': 207,
    's_editing': 464,
    's_language': 246,
    's_use': 550,
    's_ai': 138,
    's_health': 96,
    's_devices': 167,
    's_ease': 379,
}


@pytest.fixture
def taxonomy():
    return load_taxonomy(ROOT / 'tests/fixtures/taxonomy.json')


@pytest.fixture
def rows(taxonomy):
    # Saved, identity-free base row; six explicitly hand-worked observations.
    base = json.loads((ROOT / 'tests/fixtures/normalized_reviews.json').read_text())[0]
    specs = [
        ('android', '2026-07-12', 5, 2, 'Specific Praise', ['Answer Accuracy', 'Search & Sources'], 'fast answers'),
        ('android', '2026-07-13', 1, 1, 'Specific Complaint', ['Answer Accuracy'], 'wrong answers'),
        ('ios', '2026-07-19', 2, 2, 'Specific Complaint', ['Answer Accuracy', 'Speed'], 'wrong answers'),
        ('ios', '2026-07-20', 4, 4, 'Feature Request', ['Speed'], 'voice control'),
        ('android', '2026-08-02', 3, 3, 'Generic Good', [], ''),
        ('ios', '2026-08-03', 5, 5, 'Nonsense', [], ''),
    ]
    result = []
    for i, (platform, date, rating, sentiment, label, categories, topic) in enumerate(specs):
        row = dict(base)
        row.update(review_id=f'{"play" if platform == "android" else "ios"}_fixture-{i}', platform=platform,
                   country='' if platform == 'android' else 'us', store_lang='en' if platform == 'android' else '',
                   timestamp=date+'T12:00:00Z', date_utc=date, rating=rating, sentiment_rating=sentiment,
                   title='ALPHA' if i == 1 else '', review_text='sample text', app_version='1.2', thumbs_up=i,
                   labels=[label], categories=categories, topic=topic, language='es' if i == 0 else 'en',
                   english_translation='translated needle' if i == 0 else '', competitors=['ChatGPT'] if i == 1 else [],
                   regression_claim=i == 1, rating_mismatch=i == 0, is_truncated=False)
        result.append(row)
    return result


def test_match_fields_alone_and_combined(rows, taxonomy):
    cases = [({'labels_any': ['Specific Complaint']}, [1, 2]),
             ({'categories_any': ['Search & Sources', 'Speed']}, [0, 2, 3]),
             ({'categories_all': ['Answer Accuracy', 'Speed']}, [2]),
             ({'pattern': 'ALPHA|NEEDLE|voice'}, [0, 1, 3]),
             ({'regression_claim': True}, [1]), ({'regression_claim': False}, [0, 2, 3, 4, 5]),
             ({'competitors_any': ['ChatGPT']}, [1]), ({'platform': 'ios'}, [2, 3, 5]),
             ({'labels_any': ['Specific Complaint'], 'categories_all': ['Answer Accuracy'],
               'categories_any': ['Answer Accuracy'], 'pattern': 'alpha', 'regression_claim': True,
               'competitors_any': ['ChatGPT'], 'platform': 'android'}, [1])]
    for match, indices in cases:
        matcher = site.compile_match(match, taxonomy)
        assert [r['review_id'] for r in rows if matcher(r)] == [rows[i]['review_id'] for i in indices]


@pytest.mark.parametrize('match,message', [({'unknown': True}, 'Unknown match key'), ({'pattern': '['}, 'Invalid match regex'),
    ({'labels_any': ['bad']}, 'Unknown labels'), ({'categories_any': ['bad']}, 'Unknown categories'),
    ({'categories_all': ['bad']}, 'Unknown categories'), ({'competitors_any': ['bad']}, 'Unknown competitors'),
    ({'platform': 'desktop'}, 'Unknown match platform'), ({'regression_claim': 'TRUE'}, 'boolean')])
def test_bad_match_rejected(match, message, taxonomy):
    with pytest.raises(ScrapeError, match=message):
        site.compile_match(match, taxonomy)


def insights_source():
    return {'evidence_note': 'Evidence note', 'label_takeaways': {}, 'category_notes': {},
            'callouts': [{'id': 'hand', 'title': '{{count}} / {{avg_rating}}',
                          'text': '{{pct_low_star}} {{android_count}} {{ios_count}} {{pct_of_substantive}}',
                          'desc': 'Matched {{count}}', 'match': {'labels_any': ['Specific Complaint']}}],
            'improvements': [], 'feature_requests': [], 'strengths': []}


def test_tokens_scope_nulls_and_zero_match(rows, taxonomy):
    result = site.resolve_insights(insights_source(), rows, taxonomy)['callouts'][0]['scopes']
    # Two complaint rows, stars 1 and 2: mean 1.5, both low; one each platform.
    # Four substantive rows overall, so matched/substantive = 2/4.
    assert result['all']['title'] == '2 / 1.50'
    assert result['all']['text'] == '100% 1 1 50%'
    assert result['all']['desc'] == 'Matched 2'
    assert result['android']['title'] == '1 / 1.00'
    assert result['ios']['title'] == '1 / 2.00'
    source = insights_source()
    source['callouts'][0]['match']['platform'] = 'android'
    empty = site.resolve_insights(source, rows, taxonomy)['callouts'][0]['scopes']['ios']
    assert empty['stats']['count'] == 0 and empty['stats']['avg_rating'] is None
    assert empty['title'] == '0 / n/a' and empty['stats']['pct_low_star'] is None
    source['callouts'][0]['match'] = {'pattern': 'not-in-saved-fixture'}
    with pytest.raises(ScrapeError, match='matches zero reviews'):
        site.resolve_insights(source, rows, taxonomy)
    with pytest.raises(ScrapeError, match='Unknown insight token'):
        site.fill_tokens('{{invented}}', result['all']['stats'])
    assert site.fill_tokens('{{count}}', {'count': 1200}) == '1,200'


def test_complete_weeks_both_edges_and_midnight(rows):
    manifest = {'run_time_utc': '2026-08-03T12:00:00Z', 'settings': {'window_days': 22}}
    weeks, first, last = site.complete_weeks(rows, manifest)
    assert first == '2026-07-13' and last == '2026-08-02'
    assert weeks == ['2026-07-13', '2026-07-20', '2026-07-27']
    # A Monday cutoff at noon excludes that Monday; next complete week starts Jul 20.
    manifest['settings']['window_days'] = 21
    assert site.complete_weeks(rows, manifest)[0] == ['2026-07-20', '2026-07-27']
    # A midnight Monday cutoff includes the Monday; final partial day is still excluded.
    manifest['run_time_utc'] = '2026-08-03T00:00:00Z'
    assert site.complete_weeks(rows, manifest)[0] == ['2026-07-13', '2026-07-20', '2026-07-27']


def test_hand_worked_aggregates(rows, taxonomy):
    daily = [{'platform': 'android', 'date_utc': '2026-07-13', 'count': 10},
             {'platform': 'ios', 'date_utc': '2026-07-19', 'count': 11}]
    result = site.scope_summary(rows, daily, 'all', ['2026-07-13', '2026-07-20', '2026-07-27'], taxonomy)
    # Stars: 5+1+2+4+3+5 = 20; sentiment excludes standalone Nonsense: 2+1+2+4+3 = 12.
    assert result['stats']['count'] == 6 and result['stats']['avg_rating'] == 20/6
    assert result['stats']['avg_sentiment'] == 12/5 and result['stats']['sentiment_n'] == 5
    assert result['stats']['nonsense_count'] == 1
    assert result['stats']['substantive'] == 4 and result['stats']['pct_substantive'] == 400/6
    assert result['stats']['pct_mismatch'] == 100/6 and result['stats']['pct_non_english'] == 100/6
    accuracy = result['categories']['Answer Accuracy']
    assert accuracy['count'] == 3 and accuracy['avg_rating'] == 8/3
    assert accuracy['avg_sentiment'] == 5/3 and accuracy['pct_low_star'] == 200/3
    assert accuracy['topics'] == [{'topic': 'wrong answers', 'count': 2}, {'topic': 'fast answers', 'count': 1}]
    assert result['categories']['Speed']['count'] == 2 # Multi-category row counted in both.
    assert result['categories']['Model Choice']['avg_rating'] is None
    assert result['categories']['Model Choice']['avg_sentiment'] is None
    assert result['labels']['Specific Complaint']['count'] == 2
    assert result['labels']['Specific Complaint']['avg_rating'] == 1.5
    assert result['stats']['weekly_n'] == 4 and result['stats']['weekly_sentiment_n'] == 4
    assert result['stats']['weekly_volume_n'] == 21
    assert result['stats']['pain_n'] == 3 and result['stats']['request_n'] == 1
    assert result['weekly'][0]['volume'] == 21 # Daily true counts, NOT two annotated rows.
    assert result['weekly'][0]['n'] == 2 and result['weekly'][0]['regression'] == 1
    assert result['weekly'][1]['n'] == 1 and result['weekly'][1]['avg_rating'] == 4
    assert result['weekly'][2]['n'] == 1 and result['weekly'][2]['avg_rating'] == 3
    android = site.scope_summary(rows, daily, 'android', ['2026-07-13'], taxonomy)
    ios = site.scope_summary(rows, daily, 'ios', ['2026-07-13'], taxonomy)
    assert android['stats']['count'] == ios['stats']['count'] == 3
    assert android['stats']['avg_rating'] == 9/3 and ios['stats']['avg_rating'] == 11/3
    assert android['stats']['nonsense_count'] == 0 and ios['stats']['nonsense_count'] == 1
    assert android['weekly'][0]['volume'] == 10 and ios['weekly'][0]['volume'] == 11
    assert android['labels']['Feature Request']['avg_rating'] is None
    assert result['pain'][0]['count'] == 2 and result['pain'][0]['pct_low_star'] == 100


def write_csv(path, columns, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_two_builds_byte_identical_and_exact_csv_copies(tmp_path, rows, taxonomy):
    source_rows = []
    for r in rows:
        row = {k: str(r[k]) for k in config.COLUMNS}
        for key in ANNOTATION_COLUMNS:
            value = r.get(key, '')
            row[key] = ', '.join(value) if isinstance(value, list) else 'TRUE' if value is True else 'FALSE' if value is False else str(value)
        row.update(needs_translation='FALSE', is_low_signal='FALSE', is_duplicate_text='FALSE', annotation_error='')
        source_rows.append(row)
    write_csv(tmp_path/'raw.csv', config.COLUMNS, [{k:r[k] for k in config.COLUMNS} for r in source_rows])
    write_csv(tmp_path/'annotated.csv', [*config.COLUMNS, *ANNOTATION_COLUMNS], source_rows)
    write_csv(tmp_path/'daily.csv', ['platform','date_utc','count'], [{'platform':'android','date_utc':'2026-07-13','count':10}])
    (tmp_path/'run.json').write_text(json.dumps({'run_time_utc':'2026-08-03T12:00:00Z','settings':{'window_days':22}}))
    (tmp_path/'insights.json').write_text(json.dumps(insights_source()))
    (tmp_path/'eval.md').write_text('Gold rows: 6\n| Primary label accuracy | 5 | 6 | 83.33% | 85% | FAIL |\n| Primary category agreement | 3 | 4 | 75.00% | 80% | FAIL |\n')
    args=site.arguments(['--site',str(tmp_path/'site'),'--raw',str(tmp_path/'raw.csv'),'--annotated',str(tmp_path/'annotated.csv'),'--daily',str(tmp_path/'daily.csv'),'--run',str(tmp_path/'run.json'),'--insights',str(tmp_path/'insights.json'),'--evaluation',str(tmp_path/'eval.md'),'--taxonomy',str(ROOT/'tests/fixtures/taxonomy.json')])
    result,_=site.build(args)
    before={str(p.relative_to(args.site)):p.read_bytes() for p in args.site.rglob('*') if p.is_file()}
    site.build(args)
    assert before=={str(p.relative_to(args.site)):p.read_bytes() for p in args.site.rglob('*') if p.is_file()}
    assert all(p.stat().st_mode & 0o777 == 0o644 for p in args.site.rglob('*') if p.is_file())
    assert before['raw_reviews.csv']==(tmp_path/'raw.csv').read_bytes()
    assert before['annotated_reviews.csv']==(tmp_path/'annotated.csv').read_bytes()
    assert result['meta']['gold']['n']==6
    assert result['meta']['gold']['primary_category']['n']==4
    # No publication after an unknown token failure.
    bad=insights_source();bad['callouts'][0]['title']='{{unknown}}'
    (tmp_path/'insights.json').write_text(json.dumps(bad))
    with pytest.raises(ScrapeError,match='Unknown insight token'):
        site.build(args)
    assert before=={str(p.relative_to(args.site)):p.read_bytes() for p in args.site.rglob('*') if p.is_file()}


def test_current_corpus_expected_match_counts():
    path=ROOT/'data/annotated_reviews.csv'
    if not path.exists():
        pytest.skip('Real annotated CSV absent; current-corpus matcher regression skipped')
    # The real corpus is labeled with the live taxonomy, not the fixture copy the other tests use.
    taxonomy=json.loads((ROOT/'analysis/taxonomy.json').read_text())
    rows=site.read_reviews(path,taxonomy)
    source=json.loads((ROOT/'analysis/insights.json').read_text())
    actual={item['id']:sum(site.compile_match(item['match'],taxonomy)(r) for r in rows) for group in site.GROUPS for item in source[group]}
    assert actual==EXPECTED_MATCH_COUNTS


def test_top_ten_topics_languages_and_version_cutoff(rows, taxonomy):
    # Twelve topics with explicit frequencies 1 through 12: 78 reviews total.
    topics=[]
    for frequency in range(1,13):
        for _ in range(frequency):
            topics.append(rows[0] | {'topic': f'topic {frequency}'})
    assert site.top_topics(topics) == [
        {'topic':'topic 12','count':12}, {'topic':'topic 11','count':11},
        {'topic':'topic 10','count':10}, {'topic':'topic 9','count':9},
        {'topic':'topic 8','count':8}, {'topic':'topic 7','count':7},
        {'topic':'topic 6','count':6}, {'topic':'topic 5','count':5},
        {'topic':'topic 4','count':4}, {'topic':'topic 3','count':3},
    ]
    version_rows=[rows[0] | {'app_version':v} for v,n in [('1.10',100),('1.9',100),('1.8',99)] for _ in range(n)]
    result=site.scope_summary(version_rows,[], 'android',[],taxonomy)
    assert [(v['name'],v['count'],v['avg_rating']) for v in result['versions']] == [('1.9',100,5),('1.10',100,5)]
    # Nine equally common languages: lexical tie break; the ninth is Other.
    language_rows=[rows[0] | {'language':lang} for lang in ['aa','ab','ac','ad','ae','af','ag','ah','ai']]
    result=site.scope_summary(language_rows,[],'all',[],taxonomy)
    assert result['languages']==[{'name':lang,'count':1} for lang in ['aa','ab','ac','ad','ae','af','ag','ah','Other']]
