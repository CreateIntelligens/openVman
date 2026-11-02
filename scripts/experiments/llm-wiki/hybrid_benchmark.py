"""Run three independent factors on production hybrid retrieval, without MD.

CLI: same required arguments as main_wiki_benchmark.py, plus --clean-index.
The baseline runner owns input validation, isolated Docker execution, timing,
read-only checks and checkpoint handling. This adapter requires every insertion
anchor exactly once so a runner refactor fails before making an API call.
"""

import hashlib
from pathlib import Path

from hybrid_controls import ARMS
import main_wiki_benchmark as benchmark


def insert(script, anchor, replacement):
    if script.count(anchor) != 1:
        raise ValueError("Hybrid runner insertion anchor changed")
    return script.replace(anchor, replacement)


def hybrid_script(base, source):
    script = insert(base, 'pipeline_arms = p.get("pipeline_arms", pipeline_matrix.ARMS)',
                    'hybrid = module("hybrid_controls", ' + repr(source) + ')\n'
                    'pipeline_arms = p.get("pipeline_arms", pipeline_matrix.ARMS)')
    anchor = '    registry = ToolRegistry()'
    prepare = '''    from infra import db as hybrid_db
    from memory.embedder import get_embedder
    original_table = hybrid_db.get_table
    shadow_started = time.perf_counter()
    source_table = original_table("knowledge", pid)
    shadow = hybrid.ShadowIndex(source_table,
        identity=get_settings().resolved_embedding_write_identity,
        encode=get_embedder().encode_with_metadata)
    shadow_prepare_ms = (time.perf_counter() - shadow_started) * 1000
    stack.callback(shadow.close)
    def selected_table(table_name, project_id="default", embedding_version=None):
        if table_name == "knowledge" and pipeline_arms.get(current_arm, {}).get("qa_full"):
            if project_id != pid:
                raise ValueError("Shadow lookup crossed project scope")
            cfg = get_settings()
            version = embedding_version or cfg.resolved_embedding_active_version
            if cfg.resolve_embedding_identity(version) != cfg.resolved_embedding_write_identity:
                raise ValueError("Shadow lookup requested another embedding identity")
            return shadow.table
        return original_table(table_name, project_id, embedding_version)
    stack.enter_context(patch.object(hybrid_db, "get_table", selected_table))
    registry = ToolRegistry()'''
    script = insert(script, anchor, prepare)
    script = insert(script, '        queries = original_queries(current, previous)',
                    '        if pipeline_arms.get(current_arm, {}).get("no_context"):\n'
                    '            return [current] if current else []\n'
                    '        queries = original_queries(current, previous)')
    script = insert(script, '    if p["pipelines"]:\n        started = time.perf_counter()',
                    '    if p["pipelines"] and any("banks" in a for a in pipeline_arms.values()):\n        started = time.perf_counter()')
    script = insert(script, '    "pipeline_prepare_ms":pipeline_prepare_ms,',
                    '    "hybrid_shadow":shadow.audit, "shadow_prepare_ms":shadow_prepare_ms,\n'
                    '    "hybrid_controls_sha256":' + repr(hashlib.sha256(source.encode()).hexdigest()) + ',\n'
                    '    "pipeline_prepare_ms":pipeline_prepare_ms,')
    return script


def main():
    source = (Path(__file__).parent / 'hybrid_controls.py').read_text()
    benchmark.CLEAN_INDEX_ARMS = ARMS
    benchmark.SCRIPT = hybrid_script(benchmark.SCRIPT, source)
    benchmark.main()


if __name__ == '__main__':
    main()
