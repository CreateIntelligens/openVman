import * as fs from 'fs';
import * as path from 'path';
import { v4 as uuidv4 } from 'uuid';
import * as mime from 'mime-types';
import cron from 'node-cron';
import { config } from '../config';
import { logger } from '../utils/logger';

export class TempStorageService {
  private readonly baseDir: string;
  private cronJob: ReturnType<typeof cron.schedule> | null = null;

  constructor() {
    this.baseDir = config.GATEWAY_TEMP_DIR;
    this.ensureBaseDir();
    this.startCronCleanup();
  }

  private ensureBaseDir(): void {
    fs.mkdirSync(this.baseDir, { recursive: true });
  }

  /** Task 2.2 – Check disk quota before accepting uploads */
  async checkQuota(): Promise<{ ok: boolean; usageMB: number; limitMB: number }> {
    const usageBytes = await this.getDirSizeBytes(this.baseDir);
    const usageMB = usageBytes / (1024 * 1024);
    const limitMB = config.GATEWAY_TEMP_DIR_MAX_MB;
    return { ok: usageMB < limitMB, usageMB, limitMB };
  }

  /** Task 2.1 – Write a media buffer to session-scoped temp file */
  async writeFile(
    sessionId: string,
    buffer: Buffer,
    mimeType: string
  ): Promise<string> {
    // Task 2.4 – Path traversal protection
    if (sessionId.includes('..') || sessionId.includes('%2F') || sessionId.includes('/')) {
      throw new Error('INVALID_SESSION_ID: path traversal detected');
    }

    const ext = mime.extension(mimeType) || 'bin';
    const sessionDir = path.join(this.baseDir, sessionId);
    fs.mkdirSync(sessionDir, { recursive: true });

    const filename = `${uuidv4()}.${ext}`;
    const filePath = path.join(sessionDir, filename);
    await fs.promises.writeFile(filePath, buffer);

    logger.info({ event: 'temp_file_written', path: filePath, sessionId });
    return filePath;
  }

  /** Task 2.3 – Validate single file size */
  validateFileSize(sizeBytes: number): boolean {
    const limitBytes = config.GATEWAY_MAX_FILE_SIZE_MB * 1024 * 1024;
    return sizeBytes <= limitBytes;
  }

  /** Task 2.6 – Active cleanup when session ends */
  async cleanupSession(sessionId: string): Promise<void> {
    if (sessionId.includes('..') || sessionId.includes('/')) return;
    const sessionDir = path.join(this.baseDir, sessionId);
    try {
      await fs.promises.rm(sessionDir, { recursive: true, force: true });
      logger.info({ event: 'session_cleanup', sessionId });
    } catch {
      // ignore if already gone
    }
  }

  /** Task 2.5 – Cron: every 5 minutes, delete files older than TTL */
  private startCronCleanup(): void {
    this.cronJob = cron.schedule('*/5 * * * *', async () => {
      await this.runTtlCleanup();
    });
    logger.info({ event: 'cron_cleanup_started', intervalMin: 5 });
  }

  async runTtlCleanup(): Promise<void> {
    const ttlMs = config.GATEWAY_TEMP_TTL_MIN * 60 * 1000;
    const now = Date.now();
    try {
      const sessDirs = await fs.promises.readdir(this.baseDir, { withFileTypes: true });
      for (const dirent of sessDirs) {
        if (!dirent.isDirectory()) continue;
        const sessPath = path.join(this.baseDir, dirent.name);
        const files = await fs.promises.readdir(sessPath);
        for (const file of files) {
          const filePath = path.join(sessPath, file);
          const stat = await fs.promises.stat(filePath);
          const ageMsVal = now - stat.mtimeMs;
          if (ageMsVal > ttlMs) {
            await fs.promises.unlink(filePath);
            logger.info({
              event: 'temp_file_cleanup',
              path: filePath,
              age_min: Math.round(ageMsVal / 60000),
            });
          }
        }
      }
    } catch (err) {
      logger.warn({ event: 'cron_cleanup_error', err });
    }
  }

  async getTempDirBytes(): Promise<number> {
    return this.getDirSizeBytes(this.baseDir);
  }

  private async getDirSizeBytes(dir: string): Promise<number> {
    let total = 0;
    try {
      const entries = await fs.promises.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          total += await this.getDirSizeBytes(full);
        } else {
          const stat = await fs.promises.stat(full);
          total += stat.size;
        }
      }
    } catch {
      // directory may not exist yet
    }
    return total;
  }

  destroy(): void {
    this.cronJob?.stop();
  }
}

export const tempStorage = new TempStorageService();
