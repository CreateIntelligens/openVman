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
