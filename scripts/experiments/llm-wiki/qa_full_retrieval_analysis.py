"""Literal hit regression and source-answer-length coverage, without regrading."""

from collections import Counter
import statistics

from qa_full_evaluation import length_bin, percentile
from regression import matched


def summarize(data):
    questions = data['questions']
    index = {(r['id'], r['variant']): r for r in data['records']}
    expected = {(q['id'], arm) for q in questions for arm in ('main', 'qa_full')}
    if len(index) != len(data['records']) or set(index) != expected:
        raise ValueError('Missing or duplicated regression keys')
    if data['readonly_check']['changed_paths'] or not data['config_unchanged']:
        raise ValueError('Regression lacks read-only verification')
    details, groups, timings = [], {}, {}
    for arm in ('main', 'qa_full'):
        values = [r['retrieval_ms'] for r in data['records'] if r['variant'] == arm]
        timings[arm] = {'median_ms': statistics.median(values), 'p90_ms': percentile(values)}
    covered_qa = set()
    for q in questions:
        row = {'id': q['id'], 'set': q['set'], 'lang': q['lang'], 'noise': q['expect'] is None}
        qa = [] if row['noise'] else [r for r in data['qa_inventory']
            if any(term in r['text'] for term in q['expect'].split('|'))]
        covered_qa.update(r['chunk_id'] for r in qa)
        bins = sorted({length_bin('x' * r['answer_chars']) for r in qa})
        row['qa_target_count'] = len(qa)
        row['qa_answer_bins'] = bins
        row['qa_bin_ambiguous'] = len(bins) > 1
        for arm in ('main', 'qa_full'):
            result = index[q['id'], arm]['result']
            row[arm] = {
                'hit_at_3': None if row['noise'] else matched(result['results'], q['expect'], 3),
                'primary_count': len(result['results']), 'related_count': len(result['related']),
                'nonempty': bool(result['results'] or result['related']),
            }
        row['lost_hit'] = not row['noise'] and row['main']['hit_at_3'] and not row['qa_full']['hit_at_3']
        row['gained_hit'] = not row['noise'] and not row['main']['hit_at_3'] and row['qa_full']['hit_at_3']
        row['added_noise'] = row['noise'] and not row['main']['nonempty'] and row['qa_full']['nonempty']
        # Literal expect strings can match several source rows. A length bin is
        # coverage, not a unique causal label; expose overlap instead of hiding it.
        labels = ['all', 'set:' + q['set']]
        labels += ['qa_length:' + label for label in bins] or ['no_QA_target']
        for label in labels:
            group = groups.setdefault(label, {'questions': 0, 'answerable': 0,
                'main_hit3': 0, 'qa_full_hit3': 0, 'main_noise_nonempty': 0,
                'qa_full_noise_nonempty': 0, 'lost_ids': [], 'gained_ids': [], 'added_noise_ids': []})
            group['questions'] += 1
            group['answerable'] += not row['noise']
            for arm, key in [('main', 'main_hit3'), ('qa_full', 'qa_full_hit3')]:
                group[key] += bool(row[arm]['hit_at_3'])
                if row['noise']:
                    group[arm + '_noise_nonempty'] += row[arm]['nonempty']
            for flag, key in [('lost_hit', 'lost_ids'), ('gained_hit', 'gained_ids'), ('added_noise', 'added_noise_ids')]:
                if row[flag]:
                    group[key].append(q['id'])
        details.append(row)
    inventory = Counter(length_bin('x' * r['answer_chars']) for r in data['qa_inventory'])
    covered = Counter(length_bin('x' * r['answer_chars']) for r in data['qa_inventory']
                      if r['chunk_id'] in covered_qa)
    return {'question_count': len(questions), 'groups': groups, 'details': details,
        'qa_inventory_count': len(data['qa_inventory']), 'total_rows': data['row_count'],
        'qa_inventory_length_bins': dict(inventory), 'covered_qa_rows_length_bins': dict(covered),
        'timings': timings, 'no_lost_hit_or_added_noise': not any(r['lost_hit'] or r['added_noise'] for r in details),
        'limitation': 'Source expect alternatives are literal and may overlap QA/non-QA sources. Bins overlap across questions and are descriptive coverage, not an independent causal test. Retrieval hits are not answer correctness.'}
