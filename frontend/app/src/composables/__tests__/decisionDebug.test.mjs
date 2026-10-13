import assert from 'node:assert/strict'
import { test } from 'node:test'
import { decisionDebugModuleUrl } from './helpers/decisionDebugModule.mjs'
const { parseDecisionDebug, labelValue } = await import(decisionDebugModuleUrl)
const valid = {turn_id:'turn',status:'available',provider:'clef',hop_id:'clef-primary',model:'clef-flash',elapsed_ms:45,signals:[{id:'tone',type:'choice',value:'frustrated',confidence:.92,accepted:true}],policy:{tone:'frustrated'}}
test('parser rejects malformed diagnostics before rendering',()=>{
 for(const elapsed_ms of [undefined,'45',NaN,Infinity,-1]) assert.equal(parseDecisionDebug({...valid,elapsed_ms}),null)
 assert.equal(parseDecisionDebug({...valid,signals:[{...valid.signals[0],accepted:'true'}]}),null)
 assert.equal(parseDecisionDebug({...valid,signals:[{...valid.signals[0],confidence:1.5}]}),null)
 assert.equal(parseDecisionDebug({...valid,signals:[{...valid.signals[0],value:'arbitrary interpretation'}]}),null)
 assert.equal(parseDecisionDebug({...valid,signals:[{...valid.signals[0],id:'constructor'}]}),null)
 assert.equal(parseDecisionDebug({...valid,signals:[{...valid.signals[0],id:'unknown'}]}),null)
 assert.equal(parseDecisionDebug(valid).signals[0].value,'frustrated')
 assert.equal(labelValue('frustrated'),'挫折／不耐煩')
})
test('every question Brain sends has a label, so the panel never rejects a whole report',async()=>{
 // Brain 每多一題，前台不認得的 id 會讓整份報告被丟掉、面板不顯示；兩邊各改各的就會發生。
 const { readFile } = await import('node:fs/promises')
 const source = await readFile(new URL('../../../../../brain/api/core/turn_decisions.py', import.meta.url), 'utf8')
 const ids = new Set([
  ...[...source.matchAll(/^\s+"(\w+)": \{\n\s+"type": "(?:noul|choice)"/gm)].map(m => m[1]),
  ...[...source.matchAll(/questions\["(\w+)"\] = \{/g)].map(m => m[1]),
 ])
 assert.ok(ids.has('wants_previous_picture') && ids.has('tone') && ids.has('needs_knowledge'))
 for (const id of ids) {
  const report = {...valid, signals:[{id, type:'noul', probability_true:.9, resolved:true, accepted:true}], policy:{}}
  assert.notEqual(parseDecisionDebug(report), null, `Brain question ${id} has no label in decisionDebug.ts`)
 }
})
