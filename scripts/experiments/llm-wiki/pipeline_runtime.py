"""Prepared corpora, one retrieval algorithm, and optional online query work.

Build document vectors before requests. Raw, extractive grouped MD and model
compiled MD use identical cosine, top-five and 8000-character selection. No
formal search, graph expansion, exact-document shortcut or source-unit rescue
is silently added to an MD-only arm. A caller supplies the immutable snapshot
validator and the process-local project model/credential scope.
"""

import copy


class Runtime:
    def __init__(self, payload, validator, helper):
        from memory.embedder import get_embedder

        self.validator = validator
        self.helper = helper
        self.trace = []
        grouped = helper.build_corpora(payload["sources"], payload["sections"])
        compiled = helper.build_corpora(payload["sources"], payload["compiled_sections"])
        self.records = {"raw":grouped["raw"], "grouped":grouped["md"],
                        "compiled":compiled["md"]}
        for bank, records in self.records.items():
            for record in records:
                record["src"] = bank
        self.vectors = {}
        self.indexes = {}
        embedder = get_embedder()
        for name, records in self.records.items():
            vectors = []
            for start in range(0, len(records), 64):
                batch = records[start:start + 64]
                result, spec, _ = embedder.encode_with_metadata(
                    [r["text"] for r in batch], input_type="document",
                    forced_identity=validator.identity,
                    titles=[r.get("title", r.get("topic", "")) for r in batch],
                )
                if spec.get("identity") != validator.identity:
                    raise ValueError("Corpus embedding identity differs")
                vectors.extend([list(map(float, v)) for v in result])
            self.vectors[name] = vectors
            self.indexes[name] = helper.PreparedIndex(records, vectors)
        # Citation membership and file hashes establish provenance, not fidelity.
        self.compiled = payload["compiled_sections"]

    def search(self, supplied_queries, controls):
        from tools.search_helpers import normalize_query_list

        if (not isinstance(controls, dict)
                or controls.keys() - {"banks", "multi", "rewrite"}
                or not isinstance(controls.get("banks"), list)
                or not controls["banks"]
                or any(bank not in self.records for bank in controls["banks"])
                or len(controls["banks"]) != len(set(controls["banks"]))
                or any(type(controls.get(key, False)) is not bool for key in ("multi", "rewrite"))):
            raise ValueError("Invalid pipeline controls")
        queries = normalize_query_list({"queries":supplied_queries})
        if not queries:
            raise ValueError("Pipeline needs an actual runtime query")
        if not controls.get("multi", False):
            queries = queries[:1]
        original_queries = list(queries)
        if controls.get("rewrite", False):
            rewrite = self.validator._rewrite(queries)
            queries = list(dict.fromkeys(queries + rewrite["queries"]))
        else:
            rewrite = None
        with self.validator.lock:
            valid, rejected = self.validator._valid()
            valid_refs = {ref for section in valid for ref in section["source_refs"]}
            valid_compiled, rejected_compiled = [], []
            if "compiled" in controls["banks"]:
                valid_compiled, rejected_compiled = self.validator.gate.validate_sections(
                    self.compiled, self.validator.payload["source_manifest"],
                    project_id=self.validator.pid, persona_id=self.validator.persona,
                    workspace_root=self.validator.root,
                    disabled_paths=self.validator.disabled,
                    current_source_personas=self.validator.personas_by_path,
                )
            compiled_refs = {r["id"] for r in valid_compiled}
            ranked, diagnostics = [], []
            for query in queries:
                vector = list(map(float, self.validator._vector(query)))
                for bank in controls["banks"]:
                    records, vectors = self.records[bank], self.vectors[bank]
                    if bank == "compiled" and not hasattr(self, "indexes"):
                        pairs = [(r,v) for r,v in zip(records,vectors) if r["id"] in compiled_refs]
                        records = [r for r,_ in pairs]
                        vectors = [v for _,v in pairs]
                    diagnostic = {}
                    if hasattr(self, "indexes"):
                        hits = self.indexes[bank].rank(
                            vector, valid_refs, top_k=5, threshold=.68,
                            char_budget=8000, diagnostics=diagnostic,
                            allowed_ids=compiled_refs if bank == "compiled" else None,
                        )
                    else:
                        hits = self.helper.rank_hits(records, vectors, vector,
                            valid_refs, top_k=5, threshold=.68, char_budget=8000,
                            diagnostics=diagnostic)
                    ranked.append(hits)
                    diagnostics.append({"bank":bank, "query_index":queries.index(query), **diagnostic})
            results = self.helper.merge_ranks(ranked, top_k=5, char_budget=8000)
            results = [{**r, "chunk_id":r["id"], "path":"prepared/" + r["id"],
                        "refs":r["source_refs"], "project_id":self.validator.pid,
                        "persona_id":self.validator.persona,
                        "trust_boundary":"untrusted_reference_data"} for r in results]
            self.trace.append({"controls":copy.deepcopy(controls),
                "input_queries":original_queries, "queries":queries,
                "rewrite":rewrite, "selected_ids":[r["id"] for r in results],
                "selected_refs":[r["source_refs"] for r in results],
                "selected_chars":sum(len(r["text"]) for r in results),
                "rejected_sections":rejected, "rejected_compiled":rejected_compiled,
                "diagnostics":diagnostics})
            return {"table":"knowledge", "queries":queries,
                    "embedding_versions":[], "results":results, "related":[],
                    "citations":[], "source_access_gate":True}
