"""鶴記型號題 20 句：正式 .35 Chinese+詞表 vs .37 zhen+詞表，並行。"""
import asyncio, json, sys
from pathlib import Path
SRC = Path("/home/human/openVman/scripts/experiments/r2t2/multilang/heji_terms.py")
code = SRC.read_text().rsplit("asyncio.run(main())", 1)[0]
ns = {"__file__": str(SRC), "__name__": "heji"}
exec(compile(code, str(SRC), "exec"), ns)
env, r2t2, clips, to_pcm, cer, terms_heard, prompt = (ns[k] for k in ("env", "r2t2", "clips", "to_pcm", "cer", "terms_heard", "terms_prompt"))
assert "10.9.0.35" in env["ASR_R2T2_STREAM_URL"] and "10.9.0.37" in env["ASR_R2T2_DEV_STREAM_URL"]
ENGINES = {
    ".35 Chinese+詞表（正式）": (env["ASR_R2T2_STREAM_URL"], env["ASR_R2T2_SECRET_KEY"], "Chinese", asyncio.Semaphore(2)),
    ".37 zhen+詞表（dev，自動判斷）": (env["ASR_R2T2_DEV_STREAM_URL"], env["ASR_R2T2_DEV_SECRET_KEY"], "zhen", asyncio.Semaphore(6)),
}
async def main():
    items = [c for c in clips() if c["set"] == "heji" and c["voice"].startswith("edge")]
    rows = []
    async def one(item, name):
        url, key, lang, gate = ENGINES[name]
        pcm = to_pcm(item["audio"].read_bytes(), 0.0)
        async with gate:
            out = await r2t2(pcm, url, key, lang, prompt)
        got = terms_heard(item["terms"], out)
        rows.append({"id": item["id"], "voice": item["voice"], "engine": name, "ref": item["ref"], "out": out,
                     "cer": round(cer(item["ref"], out), 3), "hit": len(got), "total": len(item["terms"])})
    await asyncio.gather(*(one(i, n) for i in items for n in ENGINES))
    for name in ENGINES:
        r = [x for x in rows if x["engine"] == name]
        print("SUMMARY", name, "sentences", len(r), "CER", round(sum(x["cer"] for x in r) / len(r), 3),
              "terms", f'{sum(x["hit"] for x in r)}/{sum(x["total"] for x in r)}', flush=True)
    for x in sorted(rows, key=lambda x: (x["engine"], x["id"], x["voice"])):
        if x["hit"] < x["total"] or x["cer"] > 0.15:
            print(x["engine"][:4], x["id"], x["voice"][-12:], f'{x["hit"]}/{x["total"]}', x["cer"], "|", x["ref"][:30], "=>", x["out"][:40])
    Path(__file__).with_name("heji_35_chinese_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
asyncio.run(main())
