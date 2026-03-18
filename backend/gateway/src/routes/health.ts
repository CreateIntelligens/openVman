import { FastifyInstance } from 'fastify';
import { tempStorage } from '../services/TempStorageService';
import { queueAvailable, redisClient, getDlqJobs, QUEUE_NAMES } from '../queue/QueueManager';
import { config } from '../config';

export async function healthRoutes(fastify: FastifyInstance) {
  /** Task 9.1 – GET /health */
  fastify.get('/health', async () => {
    const quota = await tempStorage.checkQuota();
    
    return {
      status: queueAvailable ? 'ok' : 'degraded',
      uptime_seconds: process.uptime(),
      version: '0.1.0',
      dependencies: {
        redis: queueAvailable ? 'connected' : 'disconnected',
        temp_storage: quota.ok ? 'ok' : 'quota_full',
      },
      stats: {
        temp_usage_mb: Math.round(quota.usageMB),
        temp_limit_mb: quota.limitMB,
      }
    };
  });

  /** Task 3.6 – GET /admin/queue/dlq */
  fastify.get('/admin/queue/dlq', async (request: any) => {
    const limit = parseInt(request.query.limit) || 20;
    const jobs = await getDlqJobs(limit);
    return { count: jobs.length, jobs };
  });
}
