import axios from 'axios';
import OpenAI from 'openai';
import { IPlugin, PluginParams, PluginResult } from './IPlugin';
import { config, getValidCameraInterval } from '../config';
import { logger } from '../utils/logger';

interface CameraParams extends PluginParams {
  camera_url: string;
}

export class CameraLivePlugin implements IPlugin {
  id = 'camera-live';

  private timers: Map<string, ReturnType<typeof setInterval>> = new Map();
  private openai: OpenAI;

  constructor() {
    this.openai = new OpenAI({
      apiKey: config.VISION_LLM_API_KEY || undefined,
      baseURL: config.VISION_LLM_BASE_URL || undefined,
    });
  }

  /** Task 5.1–5.3 – Start snapshot loop */
  async execute(params: PluginParams): Promise<PluginResult> {
    const { session_id, camera_url } = params as CameraParams;
    if (!camera_url) {
      return { type: 'camera_scene', plugin: this.id, error: 'missing_camera_url' };
    }

    // Task 5.3 – interval validation happens via getValidCameraInterval()
    const intervalSec = getValidCameraInterval();

    // Take first snapshot immediately
    const firstResult = await this.snapshot(session_id, camera_url);

    // Task 5.2 – set up repeating timer
    const timer = setInterval(async () => {
      await this.snapshot(session_id, camera_url);
    }, intervalSec * 1000);

    this.timers.set(session_id, timer);

    return firstResult;
  }

  private async snapshot(sessionId: string, cameraUrl: string): Promise<PluginResult> {
    try {
      const response = await axios.get<ArrayBuffer>(cameraUrl, {
        responseType: 'arraybuffer',
        timeout: 5000,
      });
      const base64 = Buffer.from(response.data).toString('base64');

      // Describe via Vision LLM
      const chat = await this.openai.chat.completions.create({
        model: config.VISION_LLM_MODEL,
        messages: [
          {
            role: 'user',
            content: [
              {
                type: 'image_url',
                image_url: { url: `data:image/jpeg;base64,${base64}` },
              },
              { type: 'text', text: '請用繁體中文簡短描述當前攝影機畫面。' },
            ],
          },
        ],
        max_tokens: 200,
      });
      const content = chat.choices[0]?.message?.content ?? '（無法描述）';
      logger.info({ event: 'camera_snapshot', sessionId, status: 'ok' });
      return { type: 'camera_scene', plugin: this.id, content };
    } catch (err) {
      // Task 5.4 – connection failure: stop timer and report
      logger.warn({ event: 'camera_snapshot_failed', sessionId, err });
      this.stopTimer(sessionId);
      return {
        type: 'camera_scene',
        plugin: this.id,
        error: 'unavailable',
        metadata: { status: 'unavailable' },
      };
    }
  }

  async healthCheck(): Promise<boolean> {
    return true;
  }

  /** Task 5.5 – Cleanup timer on session end */
  async cleanup(sessionId: string): Promise<void> {
    this.stopTimer(sessionId);
  }

  private stopTimer(sessionId: string): void {
    const timer = this.timers.get(sessionId);
    if (timer) {
      clearInterval(timer);
      this.timers.delete(sessionId);
      logger.info({ event: 'camera_timer_stopped', sessionId });
    }
  }
}
