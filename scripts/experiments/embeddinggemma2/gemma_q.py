import json, torch
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("google/embeddinggemma-2", device="cuda", model_kwargs={"torch_dtype": torch.bfloat16})
qs = json.load(open("/work/extra_queries.json"))
v = m.encode([f"task: search result | query: {x['q']}" for x in qs], normalize_embeddings=True)
json.dump(v.tolist(), open("/work/extra_gemma.json", "w"))
print("ok", v.shape)
