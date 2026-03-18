import { FastifyInstance } from 'fastify';
import client from 'prom-client';
import { config } from '../config';

/** Task 9.2 – Prometheus metrics */

// 1. Define Metrics
export const mediaProcessingMs = new client.Histogram({
  name: 'gateway_media_processing_ms',
  help: 'Duration of media processing in ms',
  labelNames: ['mime_type', 'status'],
});

export const pluginExecutionsTotal = new client.Counter({
  name: 'gateway_plugin_executions_total',
  help: 'Total number of plugin executions',
  labelNames: ['plugin', 'status'],
});

export const tempDirBytes = new client.Gauge({
  name: 'gateway_temp_dir_bytes',
  help: 'Current size of temp storage in bytes',
});

// 2. Register Collection
export function registerMetrics(fastify: FastifyInstance) {
  client.collectDefaultMetrics();

  fastify.get('/metrics', async (request, reply) => {
    reply.header('Content-Type', client.register.contentType);
    return await client.register.metrics();
  });
}
