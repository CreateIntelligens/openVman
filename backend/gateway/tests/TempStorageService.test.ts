import * as fs from 'fs';
import * as path from 'path';
import { TempStorageService } from '../src/services/TempStorageService';

describe('TempStorageService', () => {
  let service: TempStorageService;
  const testDir = path.join(__dirname, 'tmp-test');

  beforeAll(() => {
    // Override config for test if needed, but here we just use the service
    service = new TempStorageService();
    // Manually set baseDir for test isolation if possible, 
    // but our service reads from config. 
    // For this mock, we'll just assume config is okay or mock it.
  });

  afterAll(async () => {
    service.destroy();
    if (fs.existsSync(testDir)) {
      await fs.promises.rm(testDir, { recursive: true, force: true });
    }
  });

  it('should prevent path traversal', async () => {
    const buffer = Buffer.from('hello');
    await expect(service.writeFile('../etc', buffer, 'text/plain'))
      .rejects.toThrow('INVALID_SESSION_ID');
  });

  it('should validate file size', () => {
    const small = 1024;
    const large = 1024 * 1024 * 1024; // 1GB
    expect(service.validateFileSize(small)).toBe(true);
    // Assuming config.GATEWAY_MAX_FILE_SIZE_MB is 100
    expect(service.validateFileSize(large)).toBe(false);
  });

  it('should check quota', async () => {
    const quota = await service.checkQuota();
    expect(quota).toHaveProperty('ok');
    expect(quota).toHaveProperty('usageMB');
  });
});
