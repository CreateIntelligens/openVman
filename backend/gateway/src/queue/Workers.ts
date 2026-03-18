import { Worker, Job } from 'bullmq';
import { redisClient, QUEUE_NAMES, setupDLQHandler } from './QueueManager';
import { MediaDispatcher } from '../services/MediaDispatcher';
import { CameraLivePlugin } from '../plugins/CameraLivePlugin';
import { ApiToolPlugin } from '../plugins/ApiToolPlugin';
import { WebCrawlerPlugin } from '../plugins/WebCrawlerPlugin';
import { logger } from '../utils/logger';
import { config } from '../config';
import axios from 'axios';

const mediaDispatcher = new MediaDispatcher();
const cameraPlugin = new CameraLivePlugin();
const apiPlugin = new ApiToolPlugin();
const crawlerPlugin = new WebCrawlerPlugin();

/** Task 3.3 – Worker implementation */
export function startWorkers() {
  if (!redisClient) return;

  // 1. Media Ingestion Worker
  const mediaWorker = new Worker(
    QUEUE_NAMES.MEDIA_INGESTION,
    async (job: Job) => {
      const { filePath, mimeType, sessionId, traceId } = job.data;
      logger.info({ event: 'worker_start', queue: QUEUE_NAMES.MEDIA_INGESTION, jobId: job.id });
      
      const result = await mediaDispatcher.dispatch(filePath, mimeType, traceId);
      
      // Task 8.2 – Forward to Backend
      await forwardToBackend({
        trace_id: traceId,
        session_id: sessionId,
        client_id: 'unknown', // should be passed in data
        original_text: '', // from context
        enriched_context: [result],
        media_refs: [filePath],
        locale: config.MESSAGE_LOCALE_DEFAULT || 'zh-TW',
      });
      
      return result;
    },
    { connection: redisClient }
  );

  // 2. Camera Live Worker (for snapshot tasks)
  const cameraWorker = new Worker(
    QUEUE_NAMES.CAMERA_LIVE,
    async (job: Job) => {
      return await cameraPlugin.execute(job.data);
    },
    { connection: redisClient }
  );

  // 3. API Tool Worker
  const apiWorker = new Worker(
    QUEUE_NAMES.API_TOOL,
    async (job: Job) => {
      return await apiPlugin.execute(job.data);
    },
    { connection: redisClient }
  );

  // 4. Web Crawler Worker
  const crawlerWorker = new Worker(
    QUEUE_NAMES.WEB_CRAWLER,
    async (job: Job) => {
      const result = await crawlerPlugin.execute(job.data);
      
      // Task 7.6 – Trigger Brain ingestion if success
      if (result.type === 'crawl_result' && result.content) {
          try {
              await axios.post(`${config.BACKEND_INTERNAL_URL}/api/knowledge/ingest`, {
                  content: result.content,
                  metadata: { source_url: result.metadata?.url }
              });
          } catch (err) {
              logger.warn({ event: 'brain_ingestion_failed', url: result.metadata?.url });
          }
      }
      return result;
    },
    { connection: redisClient }
  );

  setupDLQHandler(mediaWorker);
  setupDLQHandler(cameraWorker);
  setupDLQHandler(apiWorker);
  setupDLQHandler(crawlerWorker);

  logger.info({ event: 'workers_started' });
}

interface UserInputEnriched {
    trace_id: string;
    session_id: string;
    client_id: string;
    original_text: string;
    enriched_context: any[];
    media_refs: string[];
    locale: string;
}

/** Task 8.2 – Forward enriched message to Backend */
async function forwardToBackend(payload: UserInputEnriched) {
    try {
        await axios.post(`${config.BACKEND_INTERNAL_URL}/internal/enrich`, payload);
        logger.info({ event: 'enriched_message_forwarded', traceId: payload.trace_id });
    } catch (err: any) {
        logger.error({ event: 'forward_to_backend_failed', traceId: payload.trace_id, err: err.message });
    }
}
