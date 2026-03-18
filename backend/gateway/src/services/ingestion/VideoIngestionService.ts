import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import ffmpeg from 'fluent-ffmpeg';
import ffprobe from '@ffprobe-installer/ffprobe';
import { ImageIngestionService } from './ImageIngestionService';
import { logger } from '../../utils/logger';

ffmpeg.setFfprobePath(ffprobe.path);

export interface VideoIngestionResult {
  type: 'video_description';
  content: string;
  frames_analyzed: number;
}

export class VideoIngestionService {
  private imageService: ImageIngestionService;

  constructor() {
    this.imageService = new ImageIngestionService();
  }

  async describe(filePath: string, traceId: string): Promise<VideoIngestionResult> {
    const frameDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'vman-frames-'));
    try {
      const framePaths = await this.extractFrames(filePath, frameDir);
      const descriptions: string[] = [];

      for (let i = 0; i < framePaths.length; i++) {
        const result = await this.imageService.describe(framePaths[i], traceId);
        descriptions.push(`[影格 ${i + 1}/${framePaths.length}] ${result.content}`);
      }

      logger.info({ event: 'video_described', traceId, frames: framePaths.length });
      return {
        type: 'video_description',
        content: descriptions.join('\n'),
        frames_analyzed: framePaths.length,
      };
    } finally {
      await fs.promises.rm(frameDir, { recursive: true, force: true });
    }
  }

  private extractFrames(videoPath: string, outDir: string): Promise<string[]> {
    return new Promise((resolve, reject) => {
      ffmpeg(videoPath)
        .output(path.join(outDir, 'frame-%d.jpg'))
        .outputOptions(['-vf', 'fps=1', '-q:v', '2'])
        .on('end', async () => {
          const files = (await fs.promises.readdir(outDir))
            .filter((f) => f.endsWith('.jpg'))
            .sort()
            .map((f) => path.join(outDir, f));
          resolve(files);
        })
        .on('error', reject)
        .run();
    });
  }
}
