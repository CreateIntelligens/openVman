"""Compare production main/full-QA with LLM directory-to-full-page tools."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

from hybrid_benchmark import hybrid_script, insert
import main_wiki_benchmark as benchmark


ARMS = {
    'main': {},
    'main_noise': {'formal': True, 'products': True},
    'qa_full': {'formal': True, 'products': True, 'qa_full': True},
    'wiki_tool': {'products': True, 'wiki_tool': True},
}


def assemble(base, hybrid_source, page_source, runtime_source, payload, selector_model):
    script = hybrid_script(base, hybrid_source)
    script = insert(script, 'pipeline_arms = p.get("pipeline_arms", pipeline_matrix.ARMS)',
        'page_module = module("wiki_page_store", ' + repr(page_source) + ')\n'
        'wiki_tools = module("wiki_tool_runtime", ' + repr(runtime_source) + ')\n'
        'wiki_page_payload = p["dynamic"]["wiki_page_payload"]\n'
        'selector_model = ' + repr(selector_model) + '\n'
        'pipeline_arms = p.get("pipeline_arms", pipeline_matrix.ARMS)')
    script = insert(script, '    registry = ToolRegistry()', '''    import base64
    from tempfile import TemporaryDirectory
    page_temp = TemporaryDirectory(prefix="llm-wiki-pages-", dir="/tmp")
    stack.callback(page_temp.cleanup)
    page_root = Path(page_temp.name)
    (page_root / "wiki").mkdir()
    for relative, encoded in wiki_page_payload.items():
        (page_root / relative).write_bytes(base64.b64decode(encoded))
    def validate_wiki_sections(sections):
        from infra.db import get_knowledge_table, parse_record_metadata
        from personas.personas import normalize_persona_id
        table = get_knowledge_table(pid)
        metadata = table.search().select(["path", "metadata"]).limit(table.count_rows()).to_list()
        personas = {}
        for item in metadata:
            parsed = parse_record_metadata(item)
            path = str(parsed.get("path", "")).strip() or str(item.get("path", "")).strip()
            value = str(parsed.get("persona_id", "")).strip()
            if value not in ("", "global"):
                value = normalize_persona_id(value)
            personas.setdefault(path, []).append(value)
        return gate.validate_sections(sections, p["dynamic"]["source_manifest"],
            project_id=pid, persona_id=persona, workspace_root=wiki.root,
            disabled_paths=list_disabled_document_paths(pid), current_source_personas=personas)
    page_store = page_module.WikiPageStore(page_root, project_id=pid,
        persona_id=persona, validator=validate_wiki_sections)
    phase = "answer"
    def wiki_active():
        return bool(pipeline_arms.get(current_arm, {}).get("wiki_tool"))
    registry = ToolRegistry()''')
    script = insert(script, '    product = filter_products_tool()',
        '    wiki_answer_registry = ToolRegistry()\n    product = filter_products_tool()')
    script = insert(script, '    def products_enabled():',
        '    wiki_answer_registry.register(replace(product, handler=lambda args:timed_tool("products", product.handler, args)))\n'
        '    def products_enabled():')
    script = insert(script, '        return registry if products_enabled() else corpus_registry',
        '        return wiki_answer_registry if wiki_active() else registry if products_enabled() else corpus_registry')
    script = insert(script, 'def knowledge(arguments):',
        'def knowledge(arguments):\n    if wiki_active():\n        raise RuntimeError("wiki_tool attempted production knowledge search")')
    script = insert(script, '        calls.append(event)',
        '        event["phase"] = phase\n        calls.append(event)')
    script = insert(script, '            event["model"] = reply.model',
        '            event["model"] = reply.model\n'
        '            event["usage"] = reply.usage.as_dict() if reply.usage else None')
    script = insert(script, '    usage.append({k:kwargs.get(k) for k in ("provider", "model", "latency_ms", "raw")})',
        '    usage.append({**{k:kwargs.get(k) for k in ("provider", "model", "latency_ms", "raw")},\n'
        '        "phase":phase, "usage":kwargs["usage"].as_dict() if kwargs.get("usage") else None})')
    anchor = '    stack.enter_context(patch.object(embedder, "encode_query_with_fallback", measured("embedding_query", production_encode)))'
    script = insert(script, anchor, '''    def checked_encode(*args, **kwargs):
        row["embedding_calls_during_request"] = row.get("embedding_calls_during_request", 0) + 1
        if wiki_active():
            raise RuntimeError("wiki_tool attempted query embedding")
        return measured("embedding_query", production_encode)(*args, **kwargs)
    stack.enter_context(patch.object(embedder, "encode_query_with_fallback", checked_encode))
    from memory import retrieval as checked_retrieval
    original_fts = checked_retrieval._try_fts_search
    def checked_fts(*args, **kwargs):
        if wiki_active():
            raise RuntimeError("wiki_tool attempted FTS")
        return original_fts(*args, **kwargs)
    stack.enter_context(patch.object(checked_retrieval, "_try_fts_search", checked_fts))''')
    start = script.index('                    result = agent_loop.run_agent_loop(')
    end = script.index('                    if route and route["required"]', start)
    original = script[start:end].replace(
        '                    row.update(answer=result.reply, tool_steps=result.tool_steps)\n', '')
    replacement = '''                    if wiki_active():
                        phase = "selection"
                        selection_started = time.perf_counter()
                        selected = wiki_tools.select_pages(case["q"], case.get("history", []),
                            page_store, generate=llm_client.generate_chat_turn,
                            model=selector_model,
                            serialize_turn=agent_loop._assistant_tool_message)
                        row["wiki_selection_ms"] = (time.perf_counter()-selection_started)*1000
                        row["wiki_selection"] = selected
                        row["tool_steps"] = copy.deepcopy(selected["steps"])
                        phase = "answer"
                        messages = wiki_tools.answer_messages(messages, selected, page_store.catalog())
                        row["prompt_messages"] = copy.deepcopy(messages)
                        original_capture = capture
                        def capture(steps):
                            original_capture(selected["steps"] + steps)
                        answered = agent_loop.run_agent_loop(messages,
                            persona_id=persona, project_id=pid,
                            allow_forced_knowledge_search=False, force_knowledge_search=False,
                            force_web_search=False, force_memory_search=False,
                            reply_mode=p["mode"], on_tool_round=capture, text_listener=timer)
                        result = types.SimpleNamespace(reply=answered.reply,
                            tool_steps=selected["steps"] + answered.tool_steps)
                    else:
''' + ''.join('    '+line+'\n' for line in original.rstrip().splitlines())
    replacement += '                    row.update(answer=result.reply, tool_steps=result.tool_steps)\n'
    script = script[:start] + replacement + script[end:]
    script = insert(script, '                request_started = time.perf_counter()',
        '                phase = "answer"\n                request_started = time.perf_counter()')
    script = insert(script,
        '                    row["tool_steps"] = getattr(exc, "partial_steps", row["tool_steps"])',
        '                    partial = getattr(exc, "partial_steps", None)\n'
        '                    if wiki_active() and phase == "answer" and row.get("wiki_selection") and partial is not None:\n'
        '                        row["tool_steps"] = row["wiki_selection"]["steps"] + partial\n'
        '                    else:\n'
        '                        row["tool_steps"] = partial if partial is not None else row["tool_steps"]\n'
        '                    if getattr(exc, "partial_wiki_selection", None):\n'
        '                        row["wiki_selection"] = exc.partial_wiki_selection')
    script = insert(script, '    "hybrid_shadow":shadow.audit,',
        '    "wiki_page_inputs_sha256":p["dynamic"]["wiki_inputs_sha256"],\n'
        '    "wiki_selector_model":selector_model,\n'
        '    "wiki_page_directory":page_store.catalog(),\n'
        '    "hybrid_shadow":shadow.audit,')
    return script


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--wiki-directory', type=Path, required=True)
    parser.add_argument('--selector-model', default='gemini-3.5-flash-lite')
    known, rest = parser.parse_known_args()
    root = known.wiki_directory.resolve()
    metadata = (root/'compiled_sections.json').read_bytes()
    sections = json.loads(metadata)
    files = {'compiled_sections.json': metadata}
    for section in sections:
        name = section['compile_page']
        if not isinstance(name, str) or not __import__('re').fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Invalid page ID')
        files['wiki/'+name+'.md'] = (root/'wiki'/f'{name}.md').read_bytes()
    payload = {name: base64.b64encode(raw).decode() for name,raw in files.items()}
    here = Path(__file__).parent
    original_dynamic_payload = benchmark.dynamic_payload
    def payload_with_pages(*args, **kwargs):
        value = original_dynamic_payload(*args, **kwargs)
        value['wiki_page_payload'] = payload
        value['wiki_inputs_sha256'] = {name: hashlib.sha256(raw).hexdigest()
                                      for name, raw in files.items()}
        return value
    benchmark.dynamic_payload = payload_with_pages
    benchmark.CLEAN_INDEX_ARMS = ARMS
    benchmark.SCRIPT = assemble(benchmark.SCRIPT,
        (here/'hybrid_controls.py').read_text(), (here/'wiki_page_store.py').read_text(),
        (here/'wiki_tool_runtime.py').read_text(), payload, known.selector_model)
    sys.argv = [sys.argv[0], *rest]
    benchmark.main()
    for name, raw in files.items():
        if (root/name).read_bytes() != raw:
            raise ValueError('Wiki files changed during benchmark; results invalid')


if __name__ == '__main__':
    main()
