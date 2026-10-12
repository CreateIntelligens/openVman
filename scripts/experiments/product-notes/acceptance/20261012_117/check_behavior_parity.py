"""Read actual metadata in the container and compare resolved language caches."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
CODE = r'''
import copy,hashlib,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,'/app')
from memory.language_detect import detect_document_language
projects=['proj-0cc5c610b4','dev-c0c8fdff34']
roots=[Path('/data/projects')/p/'workspace' for p in projects]
raw=[(p/'.doc_meta.json').read_bytes() for p in roots]
metadata=[json.loads(value) for value in raw]
paths=set(metadata[0])|set(metadata[1])
differences=[p for p in paths if metadata[0].get(p)!=metadata[1].get(p)]
assert len(differences)==99
normalized=copy.deepcopy(metadata)
for path in differences:
    a,b=[values.get(path,{}) for values in metadata]
    keys=(set(a)|set(b))
    assert all(a.get(k)==b.get(k) for k in keys-{'language','language_source'})
    for index in range(2):
        entry=normalized[index].get(path,{})
        if not entry.get('language'):
            sample=(roots[index]/path).read_text(encoding='utf-8-sig')[:20000]
            normalized[index][path]={**entry,'language':detect_document_language(sample),
                                    'language_source':'auto'}
assert normalized[0]==normalized[1]
assert len(normalized[0])==129
assert all((roots[0]/path).read_bytes()==(roots[1]/path).read_bytes()
           for path in paths if path.startswith('knowledge/')
           and (roots[0]/path).is_file())
assert [(p/'.doc_meta.json').read_bytes() for p in roots]==raw
canonical=json.dumps(normalized[0],sort_keys=True,separators=(',',':')).encode()
print(json.dumps({'status':'verified','raw_metadata_equal':False,
  'resolved_metadata_equal':True,'different_language_cache_entries':len(differences),
  'document_entries':len(normalized[0]),'raw_metadata_sha256':[
      hashlib.sha256(v).hexdigest() for v in raw],
  'resolved_metadata_sha256':hashlib.sha256(canonical).hexdigest(),
  'knowledge_contents_equal':True,
  'method':'Infer missing language/source only; preserve every other key; no writes',
  'production_project':projects[0],'test_project':projects[1]}))
'''


def main():
    result = subprocess.run(
        ["docker", "exec", "-i", "-w", "/app", "openvman-api-1",
         "python3", "-B", "-"],
        input=CODE, capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    frozen = json.loads((ROOT / "behavior_parity.json").read_text())
    assert data["raw_metadata_sha256"] == frozen["raw_metadata_sha256"]
    path = ROOT / "parity_verification.json"
    if path.exists():
        assert json.loads(path.read_text()) == data
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
