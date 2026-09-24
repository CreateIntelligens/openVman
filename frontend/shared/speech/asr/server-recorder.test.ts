import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { HttpAdapter } from '../http'
import { ServerRecorder } from './server-recorder'

class FakeRecorder {
  static instances: FakeRecorder[] = []
  static isTypeSupported = (type: string) => type === 'audio/webm'
  state: 'inactive' | 'recording' = 'inactive'
  mimeType: string
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  payload = 'audio-bytes'

  constructor(_stream: MediaStream, options: { mimeType?: string }) {
    this.mimeType = options.mimeType ?? ''
    FakeRecorder.instances.push(this)
  }

  start() {
    this.state = 'recording'
  }

  stop() {
    this.state = 'inactive'
    if (this.payload) {
      this.ondataavailable?.({ data: new Blob([this.payload]) })
    }
    this.onstop?.()
  }
}

describe('ServerRecorder (shared core)', () => {
  let stopTrack: ReturnType<typeof vi.fn>
  let mockRequest: ReturnType<typeof vi.fn>
  let http: HttpAdapter

  beforeEach(() => {
    FakeRecorder.instances = []
    vi.clearAllMocks()
    stopTrack = vi.fn()
    mockRequest = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ text: ' 你好 ', provider: 'breeze' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    http = {
      request: mockRequest,
    }

    vi.stubGlobal('MediaRecorder', FakeRecorder)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: stopTrack }],
        }),
      },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('開始收音後 recording 為 true，停止才上傳並交出轉寫結果', async () => {
    const onResult = vi.fn()
    const onError = vi.fn()
    const recorder = new ServerRecorder({ http, onResult, onError })

    const startPromise = recorder.start()
    await startPromise

    expect(recorder.recording).toBe(true)
    expect(mockRequest).not.toHaveBeenCalled()

    recorder.stop()
    expect(recorder.recording).toBe(false)

    // 等待非同步上傳完畢
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledWith('你好', { language: null }))
    expect(stopTrack).toHaveBeenCalled()
    expect(mockRequest).toHaveBeenCalledTimes(1)

    // 驗證路徑與 FormData
    const [path, init] = mockRequest.mock.calls[0]
    expect(path).toBe('/api/v1/asr/transcribe')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    const file = (init.body as FormData).get('file') as File
    expect(file.name).toBe('speech.webm')
  })

  it('上傳期間 transcribing 為 true，完成後還原', async () => {
    let resolveResponse: (res: Response) => void = () => {}
    mockRequest.mockReturnValue(
      new Promise((resolve) => {
        resolveResponse = resolve
      }),
    )

    const recorder = new ServerRecorder({ http })
    await recorder.start()
    expect(recorder.recording).toBe(true)

    recorder.stop()
    expect(recorder.recording).toBe(false)
    expect(recorder.transcribing).toBe(true)

    resolveResponse(
      new Response(JSON.stringify({ text: '測試完成', provider: 'breeze' }), {
        status: 200,
      }),
    )

    await vi.waitFor(() => expect(recorder.transcribing).toBe(false))
  })

  it('麥克風權限被拒時回報 not-allowed 錯誤碼且 recording 為 false', async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(new Error('Permission denied'))
    const onError = vi.fn()
    const recorder = new ServerRecorder({ http, onError })

    const started = await recorder.start()

    expect(started).toBe(false)
    expect(recorder.recording).toBe(false)
    expect(onError).toHaveBeenCalledWith('not-allowed')
    expect(mockRequest).not.toHaveBeenCalled()
  })

  it('空片段（沒有錄到聲音）回報 no-speech 錯誤碼且不上傳', async () => {
    const onError = vi.fn()
    const recorder = new ServerRecorder({ http, onError })
    await recorder.start()

    // 模擬錄音為空
    FakeRecorder.instances[0].payload = ''
    recorder.stop()

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('no-speech'))
    expect(mockRequest).not.toHaveBeenCalled()
  })

  it('後端回應轉錄失敗佔位字時回報 transcribe-failed 且不觸發 onResult', async () => {
    mockRequest.mockResolvedValue(
      new Response(JSON.stringify({ text: '（音訊轉錄失敗）', provider: 'breeze' }), {
        status: 200,
      }),
    )
    const onResult = vi.fn()
    const onError = vi.fn()
    const recorder = new ServerRecorder({ http, onResult, onError })

    await recorder.start()
    recorder.stop()

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('transcribe-failed'))
    expect(onResult).not.toHaveBeenCalled()
  })

  it('後端 HTTP 錯誤時回報 transcribe-failed 且不觸發 onResult', async () => {
    mockRequest.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Server error' }), {
        status: 500,
      }),
    )
    const onResult = vi.fn()
    const onError = vi.fn()
    const recorder = new ServerRecorder({ http, onResult, onError })

    await recorder.start()
    recorder.stop()

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('transcribe-failed'))
    expect(onResult).not.toHaveBeenCalled()
  })

  it('不支援 MediaRecorder 時回報 not-supported', async () => {
    vi.stubGlobal('MediaRecorder', undefined)
    const onError = vi.fn()
    const recorder = new ServerRecorder({ http, onError })

    expect(recorder.supported).toBe(false)
    const started = await recorder.start()
    expect(started).toBe(false)
    expect(onError).toHaveBeenCalledWith('not-supported')
  })

  it('若在取得麥克風串流前取消，會釋放串流且不開啟錄音', async () => {
    let resolveStream: (s: any) => void = () => {}
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(
      new Promise((resolve) => {
        resolveStream = resolve
      }),
    )

    const recorder = new ServerRecorder({ http })
    const startPromise = recorder.start()
    recorder.stop()

    resolveStream({
      getTracks: () => [{ stop: stopTrack }],
    })

    const started = await startPromise
    expect(started).toBe(false)
    expect(recorder.recording).toBe(false)
    expect(stopTrack).toHaveBeenCalled()
  })

  it('dispose 後不處理任何後續轉寫與回呼', async () => {
    let resolveResponse: (res: Response) => void = () => {}
    mockRequest.mockReturnValue(
      new Promise((resolve) => {
        resolveResponse = resolve
      }),
    )
    const onResult = vi.fn()
    const onError = vi.fn()
    const recorder = new ServerRecorder({ http, onResult, onError })

    await recorder.start()
    recorder.stop()
    recorder.dispose()

    resolveResponse(
      new Response(JSON.stringify({ text: '太遲了', provider: 'breeze' }), {
        status: 200,
      }),
    )

    await new Promise((r) => setTimeout(r, 10))
    expect(onResult).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('上傳時附帶專案與語言分流，並把後端聽出的語言交給 onResult', async () => {
    mockRequest.mockResolvedValueOnce(
      new Response(JSON.stringify({ text: '我現在頭很痛', provider: 'breeze', language: 'nan' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const onResult = vi.fn()
    const recorder = new ServerRecorder({
      http,
      onResult,
      formFields: () => ({ project_id: 'proj-hospital', language_routes: 'zh,nan' }),
    })

    await recorder.start()
    recorder.stop()

    await vi.waitFor(() => expect(onResult).toHaveBeenCalledWith('我現在頭很痛', { language: 'nan' }))
    const form = mockRequest.mock.calls[0][1].body as FormData
    expect(form.get('project_id')).toBe('proj-hospital')
    expect(form.get('language_routes')).toBe('zh,nan')
  })
})
