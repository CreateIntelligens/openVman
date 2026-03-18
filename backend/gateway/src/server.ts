import Fastify from 'fastify';
import cors from '@fastify/cors';
import { config } from './config';
import { logger } from './utils/logger';
import { initQueues } from './queue/QueueManager';
import { startWorkers as runWorkers } from './queue/Workers';
import { uploadRoutes } from './routes/upload';
import { healthRoutes } from './routes/health';
import { registerMetrics } from './utils/metrics';

const fastify = Fastify({
  logger: false, // Use our custom pino logger
});

async function bootstrap() {
  try {
    // 1. Plugins
    await fastify.register(cors);
    
    // 2. Init Queues & Workers
    initQueues();
    runWorkers();

    // 3. Register Routes
    await fastify.register(uploadRoutes);
    await fastify.register(healthRoutes);

    // 4. Metrics
    if (config.METRICS_ENABLED) {
      registerMetrics(fastify);
    }

    // 5. Start Server
    await fastify.listen({ port: config.GATEWAY_PORT, host: '0.0.0.0' });
    logger.info({ event: 'server_started', port: config.GATEWAY_PORT });

    // 6. Graceful Shutdown
    const signals: NodeJS.Signals[] = ['SIGTERM', 'SIGINT'];
    signals.forEach((sig) => {
      process.on(sig, async () => {
        logger.info({ event: 'shutdown_init', signal: sig });
        await fastify.close();
        process.exit(0);
      });
    });

  } catch (err) {
    logger.error({ event: 'bootstrap_failed', err });
    process.exit(1);
  }
}

bootstrap();
