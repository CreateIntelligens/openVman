import { MotionSegmentPlayer, waitForDecodedFrame } from '../../../shared/avatar/motion/motion-controller.js'
import { MotionVideoCache } from '../../../shared/avatar/motion/video-cache.js'
import {
  HCIOT_MOTION_SEGMENTS,
  validateAvatarMotionManifest,
  type AvatarMotionState,
} from './avatarMotionProfile'

const cancelled = () => new DOMException('取消', 'AbortError')

interface SessionOptions {
  baseUrl: string
  signal: AbortSignal
  applyData: (payload: Uint8Array, url: string) => void
  onChange: (state: AvatarMotionState) => void
  onUpdate: () => void
}

/** Owns decoders and canvas observation, while the existing WASM instance owns all mouth rendering. */
export class AvatarMotionSession {
  private readonly abort = new AbortController()
  private readonly initialVideo: HTMLVideoElement
  private player: MotionSegmentPlayer | null = null
  private cache: MotionVideoCache | null = null
  private blobUrl: string | null = null
  private disposed = false
  private desired: AvatarMotionState = 'idle'
  private pending: Promise<boolean> | null = null
  private restoreDraw: (() => void) | null = null
  private frames = 0
  private renderedVideo: CanvasImageSource | null = null
  private frozen = false
  private held: HTMLCanvasElement | null = null
  private canvas: HTMLCanvasElement | null = null
  private readonly errors: string[] = []
  private readonly externalAbort = () => this.dispose()

  constructor(private readonly options: SessionOptions) {
    const video = window.characterVideo
    if (!video) throw new Error('角色播放器尚未初始化')
    this.initialVideo = video
    options.signal.addEventListener('abort', this.externalAbort, { once: true })
  }

  private assertActive(): void {
    if (this.disposed || this.options.signal.aborted) throw cancelled()
  }

  async start(): Promise<void> {
    try {
      this.assertActive()
      const signal = this.abort.signal
      const [manifest, data, video] = await Promise.all([
        this.fetch('manifest.json').then((response) => response.json()),
        this.fetch('combined_data.json.gz').then((response) => response.arrayBuffer()),
        this.fetch('01.webm').then((response) => response.blob()),
      ])
      this.assertActive()
      validateAvatarMotionManifest(manifest)
      this.installObserver()
      this.freezeFrame()
      this.initialVideo.pause()
      this.blobUrl = URL.createObjectURL(video)
      await this.loadVideo(this.initialVideo, this.blobUrl)
      this.assertActive()
      if (this.initialVideo.videoWidth !== 1080 || this.initialVideo.videoHeight !== 1920
        || this.initialVideo.duration < 31.99 || this.initialVideo.duration > 32.2) {
        throw new Error('HCIOT 動作影片尺寸或長度不符')
      }
      this.options.applyData(new Uint8Array(data), `${this.options.baseUrl}/combined_data.json.gz`)
      this.assertActive()
      // Speaking uses the same idle entry decoder, keeping the pool bounded and useful.
      const cacheSegments = { ...HCIOT_MOTION_SEGMENTS }
      delete (cacheSegments as Partial<typeof cacheSegments>).speaking
      const deviceMemory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory
      const cache = new MotionVideoCache(this.initialVideo, cacheSegments, {
        maxEntries: deviceMemory !== undefined && deviceMemory <= 4 ? 2 : 3,
        createVideo: async (source) => {
          this.assertActive()
          const standby = document.createElement('video')
          standby.hidden = true
          document.body.appendChild(standby)
          try {
            await this.loadVideo(standby, source)
            this.assertActive()
            return standby
          } catch (error) {
            standby.pause()
            standby.removeAttribute('src')
            standby.load()
            standby.remove()
            throw error
          }
        },
      })
      this.cache = cache
      try { await cache.warm() }
      catch (error) {
        cache.dispose({ keepActive: true })
        this.cache = null
        this.assertActive()
        this.recordError(error)
      }
      this.assertActive()
      const cacheState = (state: string) => state === 'speaking' ? 'idle' : state
      this.player = new MotionSegmentPlayer(this.initialVideo, HCIOT_MOTION_SEGMENTS, {
        reuseContinuousSegment: true,
        beforeSeek: () => {
          // Keep the outgoing animation moving during a cache miss. Only the
          // single-decoder fallback must hide its own seek immediately.
          if (!this.cache) this.freezeFrame()
          this.options.onUpdate()
        },
        ...(this.cache ? {
          acquireVideo: (state: string, requestSignal: AbortSignal) => this.cache!.acquire(cacheState(state), requestSignal),
          activateVideo: (selected: HTMLVideoElement, state: string) => {
            this.assertActive()
            this.freezeFrame()
            this.cache!.activate(selected, cacheState(state), { deferRefill: true })
            window.characterVideo = selected
          },
        } : {}),
        afterSeek: async (state, requestSignal, selected) => {
          // play()/seeked and a draw of the right element do not prove that
          // its decoded surface has advanced to the requested segment yet.
          await waitForDecodedFrame(selected, requestSignal, HCIOT_MOTION_SEGMENTS[state as AvatarMotionState])
          await this.waitForRenderedFrame(selected, requestSignal)
          await this.revealFrame(requestSignal)
          void this.cache?.refill()?.then(
            () => { if (!this.disposed) this.options.onUpdate() },
            (error) => { if (!this.disposed) this.recordError(error) },
          )
        },
        onChange: (state) => {
          this.desired = state as AvatarMotionState
          this.options.onChange(this.desired)
          this.options.onUpdate()
        },
        onError: (error) => this.recordError(error),
      })
      // The controller also requests loops and one-shot completion itself. Track those
      // promises too, so a speech gate cannot bypass an in-flight automatic transition.
      const transition = this.player.setState.bind(this.player)
      this.player.setState = (state, reason) => {
        this.desired = state as AvatarMotionState
        const pending = transition(state, reason).catch((error) => {
          if (!this.disposed) this.recordError(error)
          return false
        }).finally(() => { if (this.pending === pending) this.pending = null })
        this.pending = pending
        return pending
      }
      if (!await this.player.setState('idle') || signal.aborted) throw cancelled()
    } catch (error) {
      this.dispose()
      throw error
    }
  }

  private async fetch(name: string): Promise<Response> {
    const response = await fetch(`${this.options.baseUrl}/${name}`, { signal: this.abort.signal })
    if (!response.ok) throw new Error(`HCIOT 素材 ${name} HTTP ${response.status}`)
    return response
  }

  private loadVideo(video: HTMLVideoElement, source: string): Promise<void> {
    const signal = this.abort.signal
    this.assertActive()
    video.muted = true
    video.playsInline = true
    video.loop = false
    video.preload = 'auto'
    return new Promise((resolve, reject) => {
      const finish = (error?: unknown) => {
        clearTimeout(timer)
        video.removeEventListener('loadeddata', loaded)
        video.removeEventListener('error', failed)
        signal.removeEventListener('abort', aborted)
        error ? reject(error) : resolve()
      }
      const loaded = () => finish()
      const failed = () => finish(new Error('HCIOT 動作影片無法解碼'))
      const aborted = () => finish(cancelled())
      const timer = setTimeout(() => finish(new Error('HCIOT 動作影片載入逾時')), 15000)
      video.addEventListener('loadeddata', loaded)
      video.addEventListener('error', failed)
      signal.addEventListener('abort', aborted, { once: true })
      video.src = source
      video.load()
    })
  }

  private installObserver(): void {
    this.canvas = document.getElementById('canvas_video') as HTMLCanvasElement | null
    this.held = document.getElementById('avatar-motion-held') as HTMLCanvasElement | null
    const context = this.canvas?.getContext('2d')
    if (!context || !this.held) throw new Error('HCIOT 動作舞台尚未準備')
    Object.assign(this.held.style, {
      objectFit: 'contain', width: '100%', height: '100%', pointerEvents: 'none',
    })
    const original = context.drawImage
    const session = this
    const observed = function (source: CanvasImageSource, ...args: number[]) {
      Reflect.apply(original, context, [source, ...args])
      if (source === window.characterVideo) {
        session.frames += 1
        session.renderedVideo = source
      }
    } as typeof context.drawImage
    context.drawImage = observed
    this.restoreDraw = () => {
      if (context.drawImage === observed) context.drawImage = original
    }
  }

  private freezeFrame(): void {
    if (!this.held || !this.canvas) return
    const context = this.held.getContext('2d')
    if (this.frozen && context) {
      // An interrupted fade must hold the composite the user actually saw,
      // rather than flashing back to the fully opaque earlier pose.
      context.globalCompositeOperation = 'destination-in'
      context.globalAlpha = Number(this.held.style.opacity)
      context.fillRect(0, 0, this.held.width, this.held.height)
      context.globalAlpha = 1
      context.globalCompositeOperation = 'destination-over'
      context.drawImage(this.canvas, 0, 0)
      context.globalCompositeOperation = 'source-over'
    } else {
      this.held.width = this.canvas.width
      this.held.height = this.canvas.height
      context?.drawImage(this.canvas, 0, 0)
    }
    this.frozen = true
    this.held.style.opacity = '1'
  }

  private waitForRenderedFrame(video: HTMLVideoElement, signal: AbortSignal): Promise<void> {
    const first = this.frames, started = performance.now()
    return this.animate(signal, () => {
      if (performance.now() - started > 4000) throw new Error('HCIOT 對嘴引擎沒有呈現新畫面')
      return this.frames > first && this.renderedVideo === video
    })
  }

  private async revealFrame(signal: AbortSignal): Promise<void> {
    const started = performance.now()
    await this.animate(signal, () => {
      const progress = Math.min(1, (performance.now() - started) / 180)
      const fade = progress * progress * (3 - 2 * progress)
      if (this.held) this.held.style.opacity = String(1 - fade)
      return progress === 1
    })
    this.frozen = false
  }

  private animate(signal: AbortSignal, tick: () => boolean): Promise<void> {
    return new Promise((resolve, reject) => {
      let frame = 0
      const finish = (error?: unknown) => {
        cancelAnimationFrame(frame)
        signal.removeEventListener('abort', aborted)
        error ? reject(error) : resolve()
      }
      const aborted = () => finish(cancelled())
      const next = () => {
        try {
          this.assertActive()
          if (signal.aborted) return aborted()
          if (tick()) return finish()
          frame = requestAnimationFrame(next)
        } catch (error) { finish(error) }
      }
      signal.addEventListener('abort', aborted, { once: true })
      next()
    })
  }

  setState(state: AvatarMotionState, force = false): Promise<boolean> {
    if (this.disposed || !this.player) return Promise.resolve(false)
    if (!force && this.desired === state) {
      if (this.pending) return this.pending
      if (!this.player.transitioning && this.player.state === state) return Promise.resolve(true)
    }
    return this.player.setState(state)
  }

  private recordError(error: unknown): void {
    this.errors.push(error instanceof Error ? error.message : String(error))
    if (this.errors.length > 30) this.errors.shift()
    this.options.onUpdate()
  }

  snapshot() {
    return {
      state: this.player?.state ?? null,
      transitioning: this.player?.transitioning ?? false,
      loops: this.player?.loops ?? 0,
      transitions: [...(this.player?.transitions ?? [])],
      cache: this.cache?.snapshot() ?? null,
      errors: [...this.errors, ...(this.player?.errors ?? [])],
    }
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    this.options.signal.removeEventListener('abort', this.externalAbort)
    this.abort.abort()
    this.player?.dispose()
    // The global decoder is reused by the next ordinary character load.
    this.cache?.dispose({ keepActive: true })
    this.cache = null
    this.restoreDraw?.()
    this.restoreDraw = null
    if (this.held) this.held.style.opacity = '0'
    const active = this.player?.video ?? this.initialVideo
    active.pause()
    active.loop = false
    if (this.blobUrl) URL.revokeObjectURL(this.blobUrl)
    this.blobUrl = null
  }
}
