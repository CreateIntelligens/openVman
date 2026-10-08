import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source = readFileSync(new URL('../../../components/debug/decisionDebug.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText
export const decisionDebugModuleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
