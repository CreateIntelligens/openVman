"""Summarize clean-index paired trials and the identical-main noise control."""

import math
import re
import statistics

from compare_followup import compare_records


def timing_summary(rows):
    values = sorted(r['latency']['first_text_ms'] for r in rows
                    if not r.get('error') and r.get('answer', '').strip()
                    and type(r.get('latency', {}).get('first_text_ms')) in (int, float)
                    and math.isfinite(r['latency']['first_text_ms'])
                    and r['latency']['first_text_ms'] >= 0)
    return {'n': len(values), 'missing': len(rows) - len(values),
            'median_ms': statistics.median(values) if values else None,
            'p90_ms': values[math.ceil(.9 * len(values)) - 1] if values else None}


def prompt_signature(messages):
    # Production adds the request clock. Keep the date/timezone and all facts;
    # allow only its HH:MM:SS value to differ between separate main requests.
    return [{**m, 'content': re.sub(
        r'(current_time: \d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}',
        r'\1 <request_clock>', m['content'])} for m in messages]


def analyze(live, judged):
    result = compare_records(live, judged)
    result['absolute_first_text'] = {
        arm: timing_summary([r for r in live['records'] if r['variant'] == arm])
        for arm in result['arms']
    }
    if 'main_noise' not in result['arms']:
        return result
    records = {(r['id'], r['rep'], r['variant']): r for r in live['records']}
    grades = {(r['id'], r['rep'], r['variant']): r for r in judged}
    pairs = []
    for cid in result['case_ids']:
        for rep in range(3):
            base, noise = records[cid, rep, 'main'], records[cid, rep, 'main_noise']
            if prompt_signature(base['prompt_messages']) != prompt_signature(noise['prompt_messages']):
                raise ValueError('Identical-main control had different input prompts')
            a, b = grades[cid, rep, 'main'], grades[cid, rep, 'main_noise']
            pairs.append({'id': cid, 'rep': rep,
                          'answer_equal': base['answer'] == noise['answer'],
                          'pass_disagrees': a['pass'] != b['pass'],
                          'critical_disagrees': a['critical'] != b['critical']})
    secondary_regressions = {}
    for variant in result['arms'].keys() - {'main', 'main_noise'}:
        secondary_regressions[variant] = []
        for cid in result['case_ids']:
            failing = [rep for rep in range(3) if not grades[cid, rep, variant]['pass']]
            if len(failing) >= 2 and all(grades[cid, rep, 'main_noise']['pass'] for rep in range(3)):
                secondary_regressions[variant].append({'id': cid, 'failing_reps': failing})
    result['main_noise'] = {
        'input_prompts_equal_except_production_request_clock': True,
        'secondary_baseline_regressions': secondary_regressions,
        'pass_disagreement_pairs': sum(x['pass_disagrees'] for x in pairs),
        'critical_disagreement_pairs': sum(x['critical_disagrees'] for x in pairs),
        'same_answer_grade_disagreements': [x for x in pairs if x['answer_equal']
                                           and (x['pass_disagrees'] or x['critical_disagrees'])],
        'pairs': pairs,
        'warning': 'Operational difference threshold and latency gate are unchanged; main-vs-main noise is diagnostic, not permission to ignore a regression.',
    }
    return result
