"""Re-run the existing 150 retrieval questions with only full-QA vectors changed."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from experiment_io import validate_output
from main_wiki_benchmark import main_sources


HERE = Path(__file__).resolve().parent
SCRIPT = r'''
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import time
import types
from unittest.mock import patch

p = json.load(sys.stdin)
for name, digest in p['main_hashes'].items():
    assert hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest() == digest

def module(name, source):
    value = types.ModuleType(name)
    sys.modules[name] = value
    exec(source, value.__dict__)
    return value

runtime = module('readonly_runtime', p['runtime'])
hybrid = module('hybrid_controls', p['hybrid'])
from config import get_settings
from core.gemini_credentials import project_model_scope
from infra import db, project_context
from memory import embedder
pid = p['project_id']
root = project_context.resolve_project_context(pid).project_root
before = runtime._manifest(root)
production_encode = embedder.encode_query_with_fallback
settings = get_settings()
settings_before = settings.model_dump(mode='json')
current_arm = 'main'
records = []
with runtime.readonly_search(pid) as search, project_model_scope(pid), ExitStack() as stack:
    stack.enter_context(patch.object(embedder, 'encode_query_with_fallback', production_encode))
    source_table = db.get_knowledge_table(pid)
    rows = source_table.to_arrow().to_pylist()
    shadow = hybrid.ShadowIndex(source_table,
        identity=get_settings().resolved_embedding_write_identity,
        encode=embedder.get_embedder().encode_with_metadata)
    stack.callback(shadow.close)
    original_table = db.get_table
    def selected(table_name, project_id='default', embedding_version=None):
        if current_arm == 'qa_full' and table_name == 'knowledge':
            assert project_id == pid
            cfg = get_settings()
            version = embedding_version or cfg.resolved_embedding_active_version
            assert cfg.resolve_embedding_identity(version) == cfg.resolved_embedding_write_identity
            return shadow.table
        return original_table(table_name, project_id, embedding_version)
    stack.enter_context(patch.object(db, 'get_table', selected))
    qa_inventory = []
    for row in rows:
        meta = db.parse_record_metadata(row)
        if meta.get('question') and '回答：' in row['text']:
            qa_inventory.append({'chunk_id': row['chunk_id'], 'path': row['path'],
                'answer_chars': len(row['text'].split('回答：', 1)[1]), 'text': row['text']})
    for index, question in enumerate(p['questions']):
        order = ['main', 'qa_full'] if index % 2 == 0 else ['qa_full', 'main']
        for current_arm in order:
            started = time.perf_counter()
            # Keep the production k3 and threshold; no new k/threshold sweep.
            result = search(question['q'], top_k=3, threshold=.68)
            records.append({'id': question['id'], 'variant': current_arm,
                            'retrieval_ms': (time.perf_counter()-started)*1000,
                            'result': result})
        print(json.dumps({'completed': index+1}), file=sys.stderr, flush=True)
    audit = shadow.audit
assert runtime._manifest(root) == before
assert get_settings() is settings and get_settings().model_dump(mode='json') == settings_before
print(json.dumps({'records': records, 'questions': p['questions'],
    'qa_inventory': qa_inventory, 'row_count': len(rows), 'shadow_audit': audit,
    'readonly_check': {'changed_paths': []}, 'config_unchanged': True}, ensure_ascii=False))
'''


def questions():
    result = []
    for name in ('queries.json', 'extra_queries.json'):
        path = HERE.parent / 'embeddinggemma2' / name
        for index, original in enumerate(json.loads(path.read_text())):
            if original['set'] not in ('kb', 'xl', 'asr', 'noise') or 'expect' not in original:
                continue
            row = dict(original)
            row.setdefault('id', f'{path.stem}_{index:03d}')
            row.update(source_file=name, source_index=index)
            result.append(row)
    if len(result) != 150 or len({r['id'] for r in result}) != 150:
        raise ValueError('Existing 150-question set changed')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--main-ref', required=True)
    parser.add_argument('--container', default='openvman-api-1')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = validate_output(args.output)
    if target.exists():
        parser.error('Output exists; do not overwrite frozen results')
    commit, hashes = main_sources(args.main_ref)
    payload = {'project_id': args.project, 'questions': questions(),
               'main_commit': commit, 'main_hashes': hashes,
               'runtime': (HERE/'readonly_runtime.py').read_text(),
               'hybrid': (HERE/'hybrid_controls.py').read_text()}
    process = subprocess.run(
        ['docker', 'exec', '-i', '-w', '/app', args.container, 'python', '-c', SCRIPT],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
    )
    with target.with_suffix('.process.json').open('x') as stream:
        json.dump({'returncode': process.returncode, 'stderr': process.stderr}, stream)
    if process.returncode:
        raise SystemExit('Regression process failed; private diagnostics retained')
    data = json.loads(process.stdout)
    if len(data['records']) != 300 or data['readonly_check']['changed_paths']:
        raise ValueError('Incomplete or mutable regression run')
    data['main_commit'] = commit
    data['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with target.open('x') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=1)
    print(json.dumps({'questions': 150, 'arms': ['main', 'qa_full'],
                      'qa_rows': len(data['qa_inventory']), 'readonly': True}))


if __name__ == '__main__':
    main()
