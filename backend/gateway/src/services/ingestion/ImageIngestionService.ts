import OpenAI from 'openai';
import * as fs from 'fs';
import { config } from '../../config';
import { logger } from '../../utils/logger';

export interface ImageIngestionResult {
  type: 'image_description';
  content: string;
  model: string;
}

export class ImageIngestionService {
  private openai: OpenAI;

  constructor() {
    this.openai = new OpenAI({
      apiKey: config.VISION_LLM_API_KEY || undefined,
      baseURL: config.VISION_LLM_BASE_URL || undefined,
    });
  }

  async describe(filePath: string, traceId: string): Promise<ImageIngestionResult> {
    try {
      return await this.describeWithVision(filePath, traceId);
    } catch (err) {
      logger.warn({ event: 'media_ingestion_fallback', type: 'image', traceId, err });
      return this.describeWithOCR(filePath);
    }
  }

  private async describeWithVision(filePath: string, traceId: string): Promise<ImageIngestionResult> {
    const imageBuffer = await fs.promises.readFile(filePath);
    const base64 = imageBuffer.toString('base64');
    const ext = filePath.split('.').pop() || 'jpeg';
    const mimeType = ext === 'png' ? 'image/png' : ext === 'webp' ? 'image/webp' : 'image/jpeg';

    const response = await this.openai.chat.completions.create({
      model: config.VISION_LLM_MODEL,
      messages: [
        {
          role: 'user',
          content: [
            {
              type: 'image_url',
              image_url: { url: `data:${mimeType};base64,${base64}` },
            },
            {
              type: 'text',
              text: '請用繁體中文詳細描述這張圖片的內容，包含物件、場景、文字等重要細節。',
            },
          ],
        },
      ],
      max_tokens: 500,
    });

    const content = response.choices[0]?.message?.content ?? '（無法取得描述）';
    logger.info({ event: 'image_described', traceId, model: config.VISION_LLM_MODEL });
    return { type: 'image_description', content, model: config.VISION_LLM_MODEL };
  }

  private async describeWithOCR(filePath: string): Promise<ImageIngestionResult> {
    // Graceful fallback — tesseract.js requires dynamic import in Node CJS context
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const Tesseract = require('tesseract.js') as typeof import('tesseract.js');
      const { data } = await Tesseract.recognize(filePath, 'chi_tra+eng');
      const text = data.text.trim() || '（OCR 未識別出文字）';
      return { type: 'image_description', content: `[OCR 文字識別] ${text}`, model: 'tesseract' };
    } catch {
      return {
        type: 'image_description',
        content: '（圖片描述服務暫時無法使用）',
        model: 'none',
      };
    }
  }
}
