import { Queue, Worker, QueueEvents, Job } from 'bullmq';
import { Redis } from 'ioredis';
import { config } from '../config';
import { logger } from '../utils/logger';

// ─── Redis Connection ─────────────────────────────────────────────
export let redisClient: Redis | null = null;
export let queueAvailable = false;

export function createRedisConnection(): Redis {
  const client = new Redis(config.REDIS_URL, {
    maxRetriesPerRequest: null,
    enableReadyCheck: false,
  });

  client.on('ready', () => {
    queueAvailable = true;
    logger.info({ event: 'redis_connected', url: config.REDIS_URL });
  });

  client.on('error', (err) => {
    queueAvailable = false;
    logger.warn({ event: 'redis_error', err: err.message });
  });

  return client;
}

// ─── Queue Names ─────────────────────────────────────────────────
export const QUEUE_NAMES = {
  MEDIA_INGESTION: 'media-ingestion',
  CAMERA_LIVE: 'plugin-camera-live',
  API_TOOL: 'plugin-api-tool',
  WEB_CRAWLER: 'plugin-web-crawler',
  DLQ: 'dlq',
} as const;

// ─── Queue Factory ────────────────────────────────────────────────
const queues: Map<string, Queue> = new Map();

export function getQueue(name: string): Queue | null {
  if (!redisClient || !queueAvailable) return null;
  if (!queues.has(name)) {
    queues.set(
      name,
      new Queue(name, {
        connection: redisClient,
        defaultJobOptions: {
          attempts: 3,
          backoff: { type: 'exponential', delay: 1000 },
          removeOnComplete: 100,
          removeOnFail: false, // keep for DLQ inspection
        },
      })
    );
  }
  return queues.get(name)!;
}

// ─── Priority Constants ───────────────────────────────────────────
export const PRIORITY = { HIGH: 1, NORMAL: 5, LOW: 10 } as const;

// ─── DLQ Handler ─────────────────────────────────────────────────
export function setupDLQHandler(worker: Worker): void {
  worker.on('failed', async (job: Job | undefined, err: Error) => {
    if (!job) return;
    if (job.attemptsMade >= (job.opts.attempts ?? 3)) {
      const dlqQueue = getQueue(QUEUE_NAMES.DLQ);
      if (!dlqQueue) return;
      await dlqQueue.add(
        'failed-job',
        {
          original_queue: job.queueName,
          job_id: job.id,
          name: job.name,
          data: job.data,
          reason: err.message,
          failed_at: new Date().toISOString(),
        },
        { priority: PRIORITY.LOW }
      );
      logger.warn({
        event: 'job_moved_to_dlq',
        job_id: job.id,
        queue: job.queueName,
        reason: err.message,
      });
    }
  });
}

// ─── Job Submission (with sync fallback) ─────────────────────────
export async function enqueueJob(
  queueName: string,
  jobName: string,
  data: unknown,
  priority: number = PRIORITY.NORMAL
): Promise<{ jobId: string; mode: 'queued' | 'sync' }> {
  const queue = getQueue(queueName);
  if (queue) {
    const job = await queue.add(jobName, data, {
      priority,
      timeout: config.QUEUE_JOB_TIMEOUT_MS,
    });
    return { jobId: job.id!, mode: 'queued' };
  }

  // Task 3.5 – sync fallback when Redis unavailable
  logger.warn({ event: 'queue_sync_fallback', queueName });
  const syncId = `sync-${Date.now()}`;
  return { jobId: syncId, mode: 'sync' };
}

// ─── DLQ Query ───────────────────────────────────────────────────
export async function getDlqJobs(limit = 20): Promise<unknown[]> {
  const dlqQueue = getQueue(QUEUE_NAMES.DLQ);
  if (!dlqQueue) return [];
  const jobs = await dlqQueue.getJobs(['waiting', 'delayed', 'failed'], 0, limit - 1);
  return jobs.map((j) => ({
    job_id: j.id,
    reason: j.data?.reason ?? 'unknown',
    failed_at: j.data?.failed_at,
    original_queue: j.data?.original_queue,
  }));
}

// ─── Init ─────────────────────────────────────────────────────────
export function initQueues(): Redis {
  redisClient = createRedisConnection();
  return redisClient;
}
