import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'

const directory = dirname(fileURLToPath(import.meta.url))

export function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

export async function runtimeHarness(t, behavior = {}) {
  const previous = { document: globalThis.document, window: globalThis.window, harness: globalThis.__avatarRuntimeTest }
  const unmounts = [], engines = [], videos = [], creations = []
  let canvas = { dataset: {}, isConnected: true }
  const harness = {
    unmounts,
    async create(options) {
      creations.push(options)
      await behavior.create?.(options, creations.length)
      const listeners = new Set()
      const engine = {
        video: options.video, stops: 0, disposals: 0, loads: [], commits: [], pcm: [],
        async loadCharacter(base, { signal }) {
          this.loads.push({ base, signal })
          await behavior.load?.(base, signal)
          if (signal.aborted) throw new DOMException('取消', 'AbortError')
          this.commits.push(base)
        },
        async prepare() { await behavior.prepare?.() },
        async appendPcm(pcm) { this.pcm.push([...pcm]); await behavior.append?.(pcm) },
        async finishAudio() { await behavior.finish?.() },
        stop() { this.stops++ },
        dispose() { this.disposals++; this.stop() },
        subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
        emit(state) { for (const listener of listeners) listener(state) },
        fail(error) { options.onError?.(error) },
      }
      engines.push(engine)
      return engine
    },
  }
  globalThis.__avatarRuntimeTest = harness
  globalThis.window = {}
  globalThis.document = {
    getElementById: id => id === 'canvas_video' ? canvas : null,
    createElement(tag) {
      if (tag !== 'video') throw new Error(`Unexpected DOM element: ${tag}`)
      const video = { removed: false, remove() { this.removed = true } }
      videos.push(video)
      return video
    },
    body: { appendChild() {} },
  }
  t.after(() => {
    globalThis.document = previous.document
    globalThis.window = previous.window
    globalThis.__avatarRuntimeTest = previous.harness
  })
  const { outputFiles } = await build({
    entryPoints: [resolve(directory, '../useOpenVmanAvatarRuntime.ts')],
    bundle: true, write: false, platform: 'node', format: 'esm', logLevel: 'error',
    plugins: [{
      name: 'runtime-contract-boundaries',
      setup(builder) {
        builder.onResolve({ filter: /^vue$/ }, () => ({ path: 'vue', namespace: 'runtime-test' }))
        builder.onResolve({ filter: /shared\/avatar-engine\/index\.mjs$/ }, () => ({ path: 'engine', namespace: 'runtime-test' }))
        builder.onLoad({ filter: /.*/, namespace: 'runtime-test' }, ({ path }) => ({
          loader: 'js',
          contents: path === 'vue' ? `
            export const ref = value => ({ value });
            export const readonly = value => value;
            export const computed = getter => ({ get value() { return getter(); } });
            export const onUnmounted = callback => globalThis.__avatarRuntimeTest.unmounts.push(callback);
          ` : `
            const harness = globalThis.__avatarRuntimeTest;
            export const AvatarEngine = { create: options => harness.create(options) };
            export const decodeRenderPayload = () => { throw new Error('This fixture has no motion payload'); };
          `,
        }))
      },
    }],
  })
  const module = await import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}#${Math.random()}`)
  return {
    use: module.useOpenVmanAvatarRuntime, engines, videos, creations, unmounts,
    setCanvas(value) { canvas = value },
    get canvas() { return canvas },
    unmount(index = 0) { unmounts.splice(index, 1)[0]?.() },
  }
}
