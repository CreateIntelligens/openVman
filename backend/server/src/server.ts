import Fastify from 'fastify';
import { WebSocketServer, WebSocket } from 'ws';
import { v4 as uuidv4 } from 'uuid';
import pino from 'pino';

const logger = pino({
  level: 'info',
  transport: { target: 'pino-pretty', options: { colorize: true } }
});

const fastify = Fastify({ logger: false });

// Session Map (as per 01_BACKEND_SPEC)
const activeSessions = new Map<string, any>();

/** Task 8.3 – POST /internal/enrich */
fastify.post('/internal/enrich', async (request, reply) => {
  const payload = request.body as any;
  const { trace_id, session_id, enriched_context } = payload;

  logger.info({
    event: 'internal_enrich_received',
    trace_id,
    session_id,
    context_types: enriched_context.map((c: any) => c.type),
  });

  // Here we would find the active WebSocket session and push the context
  // to the brain generation pipeline.
  // For now, we just acknowledge.
  
  return { status: 'acknowledged', trace_id };
});

// Simple WebSocket Server (as per 01_BACKEND_SPEC)
const wss = new WebSocketServer({ noServer: true });

wss.on('connection', (ws: WebSocket) => {
  const clientId = `client-${uuidv4().slice(0, 8)}`;
  logger.info({ event: 'ws_connected', clientId });

  ws.on('message', (message) => {
    try {
      const data = JSON.parse(message.toString());
      logger.info({ event: 'ws_message', clientId, data });
      
      // Handle events: client_init, user_speak, etc.
      if (data.event === 'client_init') {
        activeSessions.set(data.client_id || clientId, { socket: ws, status: 'idle' });
      }
    } catch (err) {
      logger.error({ event: 'ws_parse_error', clientId, err });
    }
  });

  ws.on('close', () => {
    logger.info({ event: 'ws_disconnected', clientId });
    // Cleanup activeSessions...
  });
});

async function start() {
  try {
    const port = 8080;
    await fastify.listen({ port, host: '0.0.0.0' });
    
    // Integrate WS with Fastify
    fastify.server.on('upgrade', (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    });

    logger.info({ event: 'backend_started', port });
  } catch (err) {
    logger.error(err);
    process.exit(1);
  }
}

start();
