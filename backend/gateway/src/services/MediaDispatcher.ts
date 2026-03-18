import { ImageIngestionService } from './ingestion/ImageIngestionService';
import { VideoIngestionService } from './ingestion/VideoIngestionService';
import { AudioIngestionService } from './ingestion/AudioIngestionService';
import { DocumentIngestionService } from './ingestion/DocumentIngestionService';
import { config, supportedMimeTypes } from '../config';
import { logger } from '../utils/logger';

export type EnrichedContextItem =
  | { type: 'image_description'; content: string; model?: string }
  | { type: 'video_description'; content: string; frames_analyzed?: number }
  | { type: 'audio_transcript'; content: string; model?: string }
  | { type: 'document_content'; content: string; page_count?: number }
  | { type: 'processing_error'; reason: string; mime_type?: string };

export class MediaDispatcher {
  private imageService = new ImageIngestionService();
  private videoService = new VideoIngestionService();
  private audioService = new AudioIngestionService();
  private documentService = new DocumentIngestionService();

  async dispatch(
    filePath: string,
    mimeType: string,
    traceId: string
  ): Promise<EnrichedContextItem> {
    if (!supportedMimeTypes.has(mimeType)) {
      return { type: 'processing_error', reason: 'unsupported_type', mime_type: mimeType };
    }

    const timeoutMs = config.MEDIA_PROCESSING_TIMEOUT_MS;

    try {
      const result = await this.withTimeout(
        this.process(filePath, mimeType, traceId),
        timeoutMs
      );
      return result;
    } catch (err: unknown) {
      const reason = err instanceof Error && err.message === 'TIMEOUT' ? 'timeout' : String(err);
      logger.warn({ event: 'media_dispatch_error', traceId, mimeType, reason });
      return { type: 'processing_error', reason, mime_type: mimeType };
    }
  }

  private async process(
    filePath: string,
    mimeType: string,
    traceId: string
  ): Promise<EnrichedContextItem> {
    if (mimeType.startsWith('image/')) {
      return this.imageService.describe(filePath, traceId);
    }
    if (mimeType.startsWith('video/')) {
      return this.videoService.describe(filePath, traceId);
    }
    if (mimeType.startsWith('audio/')) {
      return this.audioService.transcribe(filePath, traceId);
    }
    if (
      mimeType === 'application/pdf' ||
      mimeType.includes('wordprocessingml') ||
      mimeType.includes('spreadsheetml')
    ) {
      return this.documentService.parse(filePath, traceId);
    }
    return { type: 'processing_error', reason: 'unsupported_type', mime_type: mimeType };
  }

  private withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('TIMEOUT')), ms);
      promise.then(
        (val) => { clearTimeout(timer); resolve(val); },
        (err) => { clearTimeout(timer); reject(err); }
      );
    });
  }
}
