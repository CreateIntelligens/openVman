import * as path from 'path';
import * as fs from 'fs';
import * as childProcess from 'child_process';
import { promisify } from 'util';
import OpenAI from 'openai';
import { config } from '../../config';
import { logger } from '../../utils/logger';

const execFile = promisify(childProcess.execFile);

export interface AudioIngestionResult {
  type: 'audio_transcript';
  content: string;
  model: string;
}

export class AudioIngestionService {
  private openai: OpenAI;

  constructor() {
    this.openai = new OpenAI({ apiKey: config.WHISPER_API_KEY || undefined });
  }

  async transcribe(filePath: string, traceId: string): Promise<AudioIngestionResult> {
    if (config.WHISPER_PROVIDER === 'openai') {
      return this.transcribeWithApi(filePath, traceId);
    }
    return this.transcribeWithLocal(filePath, traceId);
  }

  private async transcribeWithApi(filePath: string, traceId: string): Promise<AudioIngestionResult> {
    const fileStream = fs.createReadStream(filePath) as unknown as File;
    const response = await this.openai.audio.transcriptions.create({
      model: 'whisper-1',
      file: fileStream,
      language: 'zh',
    });
    logger.info({ event: 'audio_transcribed', traceId, model: 'whisper-1' });
    return { type: 'audio_transcript', content: response.text, model: 'whisper-1' };
  }

  private async transcribeWithLocal(filePath: string, traceId: string): Promise<AudioIngestionResult> {
    try {
      const outDir = path.dirname(filePath);
      await execFile(config.WHISPER_LOCAL_BIN, [filePath, '--language', 'zh', '--output_dir', outDir]);
      const txtPath = filePath.replace(/\.[^.]+$/, '.txt');
      const content = await fs.promises.readFile(txtPath, 'utf-8');
      logger.info({ event: 'audio_transcribed_local', traceId });
      return { type: 'audio_transcript', content: content.trim(), model: 'whisper-local' };
    } catch (err) {
      logger.warn({ event: 'audio_transcription_failed', traceId, err });
      return { type: 'audio_transcript', content: '（音訊轉錄失敗）', model: 'none' };
    }
  }
}
