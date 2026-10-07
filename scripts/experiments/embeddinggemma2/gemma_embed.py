import json, time, torch
from sentence_transformers import SentenceTransformer
d = json.load(open("/work/export.json"))
t0 = time.time()
model = SentenceTransformer("google/embeddinggemma-2", device="cuda", model_kwargs={"torch_dtype": torch.bfloat16})
print("load s", round(time.time() - t0, 1), "prompts", list(model.prompts)[:12])
docs = [f"title: {x['title'] or x['heading'] or 'none'} | text: {x['text']}" for x in d["docs"]]
torch.cuda.reset_peak_memory_stats()
t0 = time.time()
dv = model.encode(docs, batch_size=16, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
td = time.time() - t0
t0 = time.time()
qv = model.encode([f"task: search result | query: {x['q']}" for x in d["queries"]], batch_size=16, normalize_embeddings=True, convert_to_numpy=True)
tq = time.time() - t0
# single-query latency
lat = []
for x in d["queries"][:20]:
    s = time.time(); model.encode([f"task: search result | query: {x['q']}"], normalize_embeddings=True); lat.append(time.time() - s)
print(f"docs {len(docs)} in {td:.1f}s, queries {len(qv)} in {tq:.2f}s, single median {sorted(lat)[10]*1000:.0f}ms, peak VRAM {torch.cuda.max_memory_allocated()/2**30:.2f} GiB, dim {dv.shape[1]}")
json.dump({"docs": dv.tolist(), "queries": qv.tolist()}, open("/work/gemma.json", "w"))
