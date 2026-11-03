"""Measure LLM directory input load; no answers, embeddings, FTS or page bodies."""

import argparse
import json
from pathlib import Path
import subprocess

from experiment_io import validate_output


SCRIPT = r'''
import json,logging,sys,time,types
from unittest.mock import patch
logging.disable(logging.CRITICAL)
p=json.load(sys.stdin)
runtime=types.ModuleType('readonly_runtime');exec(p['runtime'],runtime.__dict__)
from core import llm_client,provider_router
from core.gemini_credentials import project_model_scope
records=[]
with runtime.readonly_search(p['project_id']),project_model_scope(p['project_id']),patch.object(llm_client,'record_usage_event',lambda **kw:None),patch.object(provider_router,'record_error_event',lambda **kw:None):
 for repetition in range(2):
  for multiplier in [1,4,16]:
   directory=[{'page_id':f'copy{copy}-'+r['page_id'],'title':r['title']} for copy in range(multiplier) for r in p['catalog']]
   text=json.dumps(directory,ensure_ascii=False,separators=(',',':'))
   for model in [p['selector_model']]:
    started=time.perf_counter();row={'rep':repetition,'multiplier':multiplier,'directory_entries':len(directory),'directory_chars':len(text),'requested_model':model or 'production'}
    try:
     reply=llm_client.generate_chat_turn([{'role':'system','content':p['selector_rules']+'\nWiki目錄：\n'+text},{'role':'user','content':p['question']}],tools=[p['schema']],model_override=model,max_tokens=600)
     row.update(model=reply.model,usage=reply.usage.as_dict() if reply.usage else None,tool_calls=[{'name':t.name,'arguments':t.arguments} for t in reply.tool_calls])
    except Exception as exc:row['error_type']=type(exc).__name__
    row['ms']=(time.perf_counter()-started)*1000;records.append(row)
print(json.dumps({'records':records,'readonly':True,'scope':'Synthetic duplicate-directory load, no new facts or answers; not real heterogeneous-KB selection accuracy'},ensure_ascii=False))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--cases',type=Path,required=True)
    parser.add_argument('--selector-model',default='gemini-3.5-flash-lite')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from wiki_page_store import TOOL_SCHEMA
    from wiki_tool_runtime import SELECTOR_RULES
    target=validate_output(args.output)
    if target.exists():raise ValueError('Output exists')
    p={'project_id':args.project,'catalog':json.loads(args.catalog.read_text()),
       'question':json.loads(args.cases.read_text())[0]['q'],'schema':TOOL_SCHEMA,
       'selector_model':args.selector_model,'selector_rules':SELECTOR_RULES,
       'runtime':(Path(__file__).parent/'readonly_runtime.py').read_text()}
    result=subprocess.run(['docker','exec','-i','-w','/app','openvman-api-1','python','-c',SCRIPT],input=json.dumps(p,ensure_ascii=False),capture_output=True,text=True)
    if result.returncode:
        with target.with_suffix('.failure.json').open('x') as f:json.dump({'returncode':result.returncode,'stderr':result.stderr},f)
        raise SystemExit('Directory scaling probe failed')
    with target.open('x') as f:f.write(result.stdout)


if __name__=='__main__':main()
