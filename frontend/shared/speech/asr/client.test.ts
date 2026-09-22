import { describe, expect, it, vi } from 'vitest'

import type { HttpAdapter } from '../http'
import {
  fetchMyAsrProvider,
  MY_ASR_PROVIDER_PATH,
  setMyAsrProvider,
  TRANSCRIBE_PATH,
  transcribeOnServer,
} from './client'
import {
  ASR_ERROR_MESSAGES,
  type AsrErrorCode,
  getAsrErrorMessage,
  isTerminalSpeechError,
} from './errors'

describe('ASR Errors (shared core)', () => {
  it('涵蓋所有 AsrErrorCode 且皆有中文訊息', () => {
    const codes: AsrErrorCode[] = [
      'not-supported',
      'not-allowed',
      'audio-capture',
      'service-not-allowed',
      'no-speech',
      'start-failed',
      'transcribe-failed',
      'vad-unavailable',
    ]
    for (const code of codes) {
      expect(ASR_ERROR_MESSAGES[code]).toBeTruthy()
      expect(getAsrErrorMessage(code)).toBe(ASR_ERROR_MESSAGES[code])
    }
  })

  it('未知錯誤碼回傳預設 fallback', () => {
    expect(getAsrErrorMessage('unknown-error' as any)).toBe(
      ASR_ERROR_MESSAGES['transcribe-failed'],
    )
    expect(getAsrErrorMessage('unknown-error' as any, '自訂錯誤')).toBe('自訂錯誤')
  })

  it('正確識別 Web Speech 終止性錯誤', () => {
    expect(isTerminalSpeechError('audio-capture')).toBe(true)
    expect(isTerminalSpeechError('not-allowed')).toBe(true)
    expect(isTerminalSpeechError('service-not-allowed')).toBe(true)
    expect(isTerminalSpeechError('no-speech')).toBe(false)
    expect(isTerminalSpeechError('aborted')).toBe(false)
    expect(isTerminalSpeechError(undefined)).toBe(false)
  })
})

describe('ASR API Client (shared core)', () => {
  it('fetchMyAsrProvider 送出正確路徑並解析回應', async () => {
    const mockRequest = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ value: 'sensevoice', effective: 'sensevoice', allowed: ['sensevoice'] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const http: HttpAdapter = { request: mockRequest }

    const profile = await fetchMyAsrProvider(http)
    expect(mockRequest).toHaveBeenCalledWith(MY_ASR_PROVIDER_PATH)
    expect(profile.value).toBe('sensevoice')
    expect(profile.effective).toBe('sensevoice')
    expect(profile.allowed).toEqual(['sensevoice'])
  })

  it('setMyAsrProvider 送出 PUT 請求與 JSON body', async () => {
    const mockRequest = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ value: 'breeze', effective: 'breeze', allowed: ['breeze'] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const http: HttpAdapter = { request: mockRequest }

    const profile = await setMyAsrProvider(http, 'breeze')
    expect(mockRequest).toHaveBeenCalledWith(MY_ASR_PROVIDER_PATH, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: 'breeze' }),
    })
    expect(profile.value).toBe('breeze')
  })

  it('transcribeOnServer 送出 FormData 包含 clip 與 filename', async () => {
    const mockRequest = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ text: '測試文字', provider: 'sensevoice', elapsed_seconds: 0.12 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const http: HttpAdapter = { request: mockRequest }

    const clip = new Blob(['sample-pcm'], { type: 'audio/wav' })
    const result = await transcribeOnServer(http, clip, 'speech.wav')

    expect(mockRequest).toHaveBeenCalledWith(
      TRANSCRIBE_PATH,
      expect.objectContaining({ method: 'POST' }),
    )
    expect(result.text).toBe('測試文字')
    expect(result.provider).toBe('sensevoice')
  })

  it('當 API 失敗時呼叫 http.parseError 或拋出自訂錯誤', async () => {
    const mockRequest = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: '權限不足' }), {
        status: 403,
      }),
    )
    const http: HttpAdapter = {
      request: mockRequest,
      parseError: vi.fn().mockResolvedValue('自訂解析：權限不足'),
    }

    await expect(fetchMyAsrProvider(http)).rejects.toThrow('自訂解析：權限不足')
    expect(http.parseError).toHaveBeenCalled()
  })
})
