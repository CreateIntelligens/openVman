"""Frozen QA-only evaluation gates; original machine labels remain unchanged."""

import math
import statistics

from clean_index_analysis import analyze


ARMS = {
    "main": {},
    "qa_full": {"formal": True, "products": True, "qa_full": True},
}
LENGTH_BINS = ((100, "0-100"), (300, "101-300"),
               (800, "301-800"), (math.inf, "801+"))


def length_bin(answer):
    return next(label for limit, label in LENGTH_BINS if len(answer) <= limit)


def percentile(values, fraction=.9):
    values = sorted(values)
    return values[math.ceil(fraction * len(values)) - 1] if values else None


def noise_reference(live):
    records = {(r['id'], r['rep'], r['variant']): r for r in live['records']}
    first, retrieval = [], []
    for (cid, rep, arm), a in records.items():
        if arm != 'main':
            continue
        b = records[cid, rep, 'main_noise']
        if a.get('error') or b.get('error'):
            continue
        times = [r['latency'].get('first_text_ms') for r in (a, b)]
        if all(type(t) in (int, float) and math.isfinite(t) for t in times):
            first.append(times[1] - times[0])
            retrieval.append(b['read_timing']['knowledge_ms']
                             - a['read_timing']['knowledge_ms'])
    if not first or not retrieval:
        raise ValueError('Missing identical-main noise reference')
    return {
        'pairs': len(first), 'first_text_p90_added_ms': max(0, percentile(first)),
        'retrieval_p90_added_ms': max(0, percentile(retrieval)),
        'first_text_median_added_ms': statistics.median(first),
        'retrieval_median_added_ms': statistics.median(retrieval),
    }


def evaluate(live, judged, reference, groups):
    """Only stable regressions and candidate-only critical questions block quality.

    A critical question is new if any candidate repeat is critical and all three
    same-question main repeats are not. Shared flags and increased counts remain
    visible; they are not silently relabeled or removed from the denominator.
    """
    if set(live['arms']) != set(ARMS) or live['arms'] != ARMS:
        raise ValueError('QA-only evaluation requires the exact frozen arms')
    result = analyze(live, judged)
    grades = {(r['id'], r['rep'], r['variant']): r for r in judged}
    added, existing, per_question = [], [], []
    strata = {}
    for cid in result['case_ids']:
        main = [grades[cid, rep, 'main'] for rep in range(3)]
        candidate = [grades[cid, rep, 'qa_full'] for rep in range(3)]
        a, b = sum(r['critical'] for r in main), sum(r['critical'] for r in candidate)
        entry = {
            'id': cid, 'main_pass': sum(r['pass'] for r in main),
            'candidate_pass': sum(r['pass'] for r in candidate),
            'main_critical': a, 'candidate_critical': b,
            'main_pass_reps': [r['pass'] for r in main],
            'candidate_pass_reps': [r['pass'] for r in candidate],
            'group': groups[cid],
            'critical_details': [{k: r.get(k) for k in
                ('rep', 'variant', 'reason', 'unsupported_claims')}
                for r in main + candidate if r['critical']],
        }
        entry['delta_pass'] = entry['candidate_pass'] - entry['main_pass']
        entry['stable_regression'] = entry['main_pass'] == 3 and entry['candidate_pass'] <= 1
        entry['new_critical'] = a == 0 and b > 0
        if entry['new_critical']:
            added.append(entry)
        if a:
            existing.append(entry)
        per_question.append(entry)
        group = strata.setdefault(groups[cid], {'questions': 0, 'main_pass': 0,
            'candidate_pass': 0, 'stable_regressions': [], 'new_critical': []})
        group['questions'] += 1
        for name in ('main_pass', 'candidate_pass'):
            group[name] += entry[name]
        for flag, key in (('stable_regression', 'stable_regressions'), ('new_critical', 'new_critical')):
            if entry[flag]:
                group[key].append(cid)
    retrieval = {}
    for arm in ARMS:
        rows = [r for r in live['records'] if r['variant'] == arm and not r.get('error')]
        values = [r['read_timing']['knowledge_ms'] for r in rows]
        retrieval[arm] = {'n': len(values), 'median_ms': statistics.median(values) if values else None,
                          'p90_ms': percentile(values)}
    paired = result['arms']['qa_full']['paired_first_text_latency']
    retrieval_delta = (retrieval['qa_full']['median_ms'] - retrieval['main']['median_ms'])
    latency = {
        'reference': reference, 'retrieval': retrieval,
        'retrieval_median_added_ms': retrieval_delta,
        'first_text_pairs': paired['measured_pairs'],
        'first_text_paired_median_added_ms': paired['median_added_ms'],
        'first_text_paired_p90_added_ms': paired['p90_added_ms'],
        'first_text_missing': paired['missing_pairs'],
        'retrieval_gate': retrieval_delta <= reference['retrieval_p90_added_ms'],
        'first_text_gate': paired['complete'] and paired['p90_added_ms'] <= reference['first_text_p90_added_ms'],
    }
    stable = [r for r in per_question if r['stable_regression']]
    gates = {'no_stable_regression': not stable, 'no_new_critical': not added,
             'retrieval': latency['retrieval_gate'], 'first_text': latency['first_text_gate'],
             'no_execution_or_judge_failures': all(r['errors'] == 0 for r in result['arms'].values())}
    return {
        'machine_grading_only': True, 'raw_comparison': result,
        'per_question': per_question, 'length_groups': strata,
        'new_critical': added, 'main_existing_critical': existing,
        'stable_regressions': stable, 'latency': latency,
        'gates': gates, 'eligible_for_dev': all(gates.values()),
        'old_200ms_gate_superseded': True,
    }
