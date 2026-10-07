import json, torch
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("google/embeddinggemma-2", device="cuda", model_kwargs={"torch_dtype": torch.bfloat16})
print({k: v for k, v in m.prompts.items() if k in ("query", "document", "Document", "QuestionAnswering", "SearchQuery", "Retrieval", "STS")})
E = json.load(open("/work/export.json")); X = json.load(open("/work/extra_queries.json"))
qs = [q["q"] for q in E["queries"]] + [x["q"] for x in X]
out = {}
for name in ("query", "QuestionAnswering"):
    if name in m.prompts:
        out[name] = m.encode(qs, prompt_name=name, normalize_embeddings=True).tolist()
docs = [x["text"] for x in E["docs"]]
out["docs_document_prompt"] = m.encode(docs, prompt_name="document" if "document" in m.prompts else "Document", normalize_embeddings=True, batch_size=16).tolist()
json.dump(out, open("/work/gemma_variants.json", "w")); print("ok", list(out))
