import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import multipart from '@fastify/multipart';
import { tempStorage } from '../services/TempStorageService';
import { enqueueJob, QUEUE_NAMES, PRIORITY } from '../queue/QueueManager';
import { logger } from '../utils/logger';
import { supportedMimeTypes } from '../config';

export async function uploadRoutes(fastify: FastifyInstance) {
  fastify.register(multipart, {
    limits: {
      fileSize: 100 * 1024 * 1024, // 100MB fallback
    },
  });

  /** Task 4.6 – POST /upload */
  fastify.post('/upload', async (request: FastifyRequest, reply: FastifyReply) => {
    // 1. Check disk quota
    const quota = await tempStorage.checkQuota();
    if (!quota.ok) {
      return reply.code(413).send({ error: 'storage_quota_exceeded', usageMB: quota.usageMB, limitMB: quota.limitMB });
    }

    const data = await request.file();
    if (!data) {
      return reply.code(400).send({ error: 'no_file_uploaded' });
    }

    // 2. Validate MIME type
    if (!supportedMimeTypes.has(data.mimetype)) {
      return reply.code(400).send({ error: 'unsupported_mime_type', mime_type: data.mimetype });
    }

    const sessionId = (request.query as any).session_id || 'default';
    const traceId = (request.query as any).trace_id || `tr-${Date.now()}`;

    try {
      // 3. Read buffer and validate file size
      const buffer = await data.toBuffer();
      if (!tempStorage.validateFileSize(buffer.length)) {
        return reply.code(413).send({ error: 'file_too_large' });
      }

      // 4. Save to temp storage
      const filePath = await tempStorage.writeFile(sessionId, buffer, data.mimetype);

      // 5. Enqueue ingestion job
      const { jobId, mode } = await enqueueJob(
        QUEUE_NAMES.MEDIA_INGESTION,
        'process-media',
        {
          filePath,
          mimeType: data.mimetype,
          sessionId,
          traceId,
        },
        PRIORITY.NORMAL
      );

      logger.info({ event: 'upload_success', jobId, mode, sessionId, traceId });

      return reply.code(202).send({
        status: 'accepted',
        job_id: jobId,
        mode,
        session_id: sessionId,
        trace_id: traceId,
      });
    } catch (err: any) {
      logger.error({ event: 'upload_error', err: err.message, sessionId, traceId });
      return reply.code(500).send({ error: 'internal_server_error' });
    }
  });
}
