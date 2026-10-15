import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { decisionDebugModuleUrl } from './decisionDebugModule.mjs'

// useAvatarChat is split across sibling modules; tests read and load them as
// one unit. Listed leaves first so each module's imports are already built.
const MODULES = [
  'avatarChatTypes',
  'chatSseStream',
  'useAvatarTransport',
  'useAvatarVisualInput',
  'useAvatarTextTurn',
  'useAvatarChat',
]

const read = (name) => readFileSync(new URL(`../../${name}.ts`, import.meta.url), 'utf8')

/** Source text of useAvatarChat.ts first, then the modules it delegates to. */
export const avatarChatSource = ['useAvatarChat', ...MODULES.filter((name) => name !== 'useAvatarChat')]
  .map(read)
  .join('\n')

const VUE_STUB = [
  'const ref = (value) => ({ value });',
  'const readonly = (value) => value;',
  'const onUnmounted = () => undefined;',
].join('\n')

const toDataUrl = (code) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`

/** Load useAvatarChat with Vue stubbed and `apiFetchStub` defining apiFetch. */
export async function loadAvatarChat(apiFetchStub = 'const apiFetch = (...args) => fetch(...args);') {
  const urls = {}
  for (const name of MODULES) {
    const compiled = ts.transpileModule(read(name), {
      compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
    }).outputText
      .replace(/from ['"]\.\.\/components\/debug\/decisionDebug['"]/, `from "${decisionDebugModuleUrl}"`)
      .replace(/import\s*\{[^}]*\}\s*from\s*['"]vue['"];?/, VUE_STUB)
      .replace(/import\s*\{\s*apiFetch\s*\}\s*from\s*['"][^'"]+['"];?/, apiFetchStub)
      .replace(/from ['"]\.\/(\w+)['"]/g, (_match, dep) => {
        if (!urls[dep]) throw new Error(`${name} imports ${dep} before it is built`)
        return `from "${urls[dep]}"`
      })
    urls[name] = toDataUrl(compiled)
  }
  return import(urls.useAvatarChat)
}
