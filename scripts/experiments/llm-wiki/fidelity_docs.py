"""Audit cited and uncited catalog Wiki claims against exact source blocks."""

import argparse
from collections import Counter
import concurrent.futures
import hashlib
import json
import os
import random
import re

from compile_docs import CITE, DEFAULT_OUTPUT, output_directory, write_json


JUDGE = """你是產品型錄忠實度裁判，判斷 wiki 句子的每項事實是否被它所引用的原文支持。
只能依引用區塊，不能用外部常識、相鄰未引用區塊、型號規則或計算補足缺失。
特別核對機型、相數、材質、數字、單位、額定/最大、選配/標配、適用限制。
supported：全部事實都有原文依據，允許不改變事實的簡潔轉述與標題。
partial：部分事實無依據、過度概括、遺失重要適用條件。
unsupported：內容矛盾或引用完全未提。
輸出 JSON：{{"label":"supported|partial|unsupported","reason":"60字內具體理由"}}
wiki句子：{claim}
引用原文：
{sources}
"""


def claims_from_wiki(wiki):
    claims = []
    for path in sorted(wiki.glob("*.md")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#") or re.fullmatch(r"[-| :]+", line):
                continue
            # Keep the sentence's trailing citation; never lend it to an earlier sentence.
            units = re.findall(
                r"[^。！？!?]+[。！？!?](?:\s*\[S\d+\])*|[^。！？!?]+$", line
            )
            for unit in units:
                unit = unit.strip()
                if not CITE.sub("", unit).strip(" -*>"):
                    continue
                refs = CITE.findall(unit)
                claims.append({
                    "claim_id": f"C{len(claims) + 1:04d}",
                    "page": path.name,
                    "line": number,
                    "text": unit,
                    "refs": list(dict.fromkeys(ref[1:-1] for ref in refs)),
                })
    return claims


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.sample_size <= 200:
        parser.error("--sample-size must be between 1 and 200")
    outdir = output_directory(args.output)
    blocks = {
        block["id"]: block
        for block in json.loads((outdir / "src_blocks.json").read_text())
    }
    population = claims_from_wiki(outdir / "wiki")
    if not population:
        raise ValueError("No Wiki claims found")
    # Persist the whole population so absence of citations remains measurable.
    write_json(outdir / "fidelity_docs_population.json", population)
    count = min(args.sample_size, len(population))
    sample = sorted(
        random.Random(args.seed).sample(population, count),
        key=lambda claim: claim["claim_id"],
    )
    os.environ.setdefault("LINT_MODEL", "gemini-3.8-flash")
    import llm

    def judge(claim):
        claim = dict(claim)
        claim["bad_refs"] = [r for r in claim["refs"] if r not in blocks]
        if not claim["refs"]:
            claim.update(label="no_citation", reason="沒有來源引用")
        elif claim["bad_refs"]:
            claim.update(label="bad_citation", reason="含不存在的來源區塊")
        else:
            result = llm.gen(JUDGE.format(
                claim=claim["text"],
                sources="\n\n".join(
                    f"[{ref}] {blocks[ref]['heading']}\n{blocks[ref]['text']}"
                    for ref in claim["refs"]
                ),
            ), model="gemini-3.8-flash")
            if result.get("label") not in {"supported", "partial", "unsupported"}:
                raise ValueError(f"Invalid judge label: {claim['claim_id']}")
            claim.update(label=result["label"], reason=result.get("reason", ""))
        return claim

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        judged = list(pool.map(judge, sample))
    write_json(outdir / "fidelity_docs_claims.json", judged)
    labels = Counter(claim["label"] for claim in judged)
    missing = sum(not c["refs"] for c in population)
    bad = sum(any(r not in blocks for r in c["refs"]) for c in population)
    summary = {
        "model": "gemini-3.8-flash",
        "population": len(population),
        "population_scope": "所有 wiki/*.md 含 index.md 的非標題內容句；表格列若有亦納入。",
        "population_sha256": hashlib.sha256(json.dumps(
            population, ensure_ascii=False, sort_keys=True
        ).encode()).hexdigest(),
        "sample_size": count,
        "sampling": "deterministic uniform random without replacement",
        "seed": args.seed,
        "coverage": count / len(population),
        "labels": dict(labels),
        "strict_supported_rate": labels["supported"] / count,
        "denominator_note": "樣本內缺引用、錯引用均列入分母；比率僅代表抽樣結果。",
        "population_citation_audit": {"no_citation": missing, "bad_citation": bad},
        "usage": llm.USAGE,
    }
    write_json(outdir / "fidelity_docs.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
