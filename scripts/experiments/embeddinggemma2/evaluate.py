import json, sys
import numpy as np
E = json.load(open(sys.argv[1])); G = json.load(open(sys.argv[2]))
docs, qs = E["docs"], E["queries"]
def norm(m):
    m = np.asarray(m, dtype=np.float32); return m / np.linalg.norm(m, axis=1, keepdims=True)
models = {"bge-m3": (norm([d["bge"] for d in docs]), norm([q["bge"] for q in qs]))}
gd, gq = np.asarray(G["docs"], np.float32), np.asarray(G["queries"], np.float32)
for dim in (768, 512, 256):
    models[f"gemma2-{dim}"] = (norm(gd[:, :dim]), norm(gq[:, :dim]))
texts = [d["text"] for d in docs]
for name, (D, Q) in models.items():
    S = Q @ D.T
    kb_hit = {k: 0 for k in (1, 3, 5)}; kb_n = 0; by_lang = {}; rel_top = []; noise_top = []; ranks = []
    r3_cov = []
    for i, q in enumerate(qs):
        order = np.argsort(-S[i])
        if q["set"] == "kb":
            if q["expect"] is None:
                noise_top.append(float(S[i, order[0]])); continue
            keys = q["expect"].split("|")
            hits = [r for r, j in enumerate(order[:20]) if any(k in texts[j] for k in keys)]
            first = hits[0] + 1 if hits else 99
            ranks.append(first); kb_n += 1
            for k in kb_hit: kb_hit[k] += first <= k
            by_lang.setdefault(q["lang"], [0, 0]); by_lang[q["lang"]][0] += first <= 3; by_lang[q["lang"]][1] += 1
            rel_top.append(float(S[i, order[0]]))
        else:
            top = " ".join(texts[j] for j in order[:10])
            models_ = q["models"]
            if not models_: continue
            r3_cov.append(sum(m.split("/")[0] in top for m in models_) / len(models_))
    mrr = np.mean([1 / r if r < 99 else 0 for r in ranks])
    # 相關題 top1 相似度 vs 閒聊 top1：可分性
    auc = np.mean([[a > b for b in noise_top] for a in rel_top])
    print(f"{name:12s} kb hit@1/3/5 {kb_hit[1]}/{kb_hit[3]}/{kb_hit[5]} of {kb_n}  MRR {mrr:.3f}  "
          f"by-lang@3 " + " ".join(f"{l}:{a}/{b}" for l, (a, b) in sorted(by_lang.items())) +
          f"  r3 model-coverage@10 {np.mean(r3_cov):.2f}  sep AUC {auc:.2f} (rel top1 med {np.median(rel_top):.2f}, noise max {max(noise_top):.2f})")
