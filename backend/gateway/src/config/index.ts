import { z } from 'zod';

const envSchema = z.object({
  // Server
  GATEWAY_PORT: z.coerce.number().default(8050),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),

  // Redis
  REDIS_URL: z.string().default('redis://localhost:6379'),

  // Temp Storage
  GATEWAY_TEMP_DIR: z.string().default('/tmp/vman-gateway'),
  GATEWAY_TEMP_TTL_MIN: z.coerce.number().default(30),
  GATEWAY_TEMP_DIR_MAX_MB: z.coerce.number().default(2048),
  GATEWAY_MAX_FILE_SIZE_MB: z.coerce.number().default(100),

  // Media Processing
  MEDIA_PROCESSING_TIMEOUT_MS: z.coerce.number().default(5000),
  MEDIA_SUPPORTED_TYPES: z.string().default(
    'image/jpeg,image/png,image/webp,video/mp4,video/quicktime,audio/mpeg,audio/wav,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ),

  // Vision LLM
  VISION_LLM_PROVIDER: z.enum(['openai', 'local-llava']).default('openai'),
  VISION_LLM_API_KEY: z.string().default(''),
  VISION_LLM_MODEL: z.string().default('gpt-4o'),
  VISION_LLM_BASE_URL: z.string().default(''),

  // Whisper
  WHISPER_PROVIDER: z.enum(['openai', 'local']).default('openai'),
  WHISPER_API_KEY: z.string().default(''),
  WHISPER_LOCAL_BIN: z.string().default('/usr/local/bin/whisper'),

  // MarkItDown
  MARKITDOWN_URL: z.string().default('http://localhost:8200'),

  // Camera Live
  CAMERA_SNAPSHOT_INTERVAL_SEC: z.coerce.number().default(5),

  // API Tool
  API_TOOL_TIMEOUT_MS: z.coerce.number().default(10000),
  API_TOOL_MAX_QUEUE: z.coerce.number().default(10),
  API_REGISTRY_PATH: z.string().default('./config/api-registry.yaml'),

  // Web Crawler
  CRAWLER_TIMEOUT_MS: z.coerce.number().default(15000),
  CRAWLER_CACHE_TTL_MIN: z.coerce.number().default(60),
  CRAWLER_IGNORE_ROBOTS: z.coerce.boolean().default(false),
  CRAWLER_BLOCKED_DOMAINS: z.string().default(''),

  // Backend internal
  BACKEND_INTERNAL_URL: z.string().default('http://localhost:8080'),

  // Queue
  QUEUE_JOB_TIMEOUT_MS: z.coerce.number().default(30000),

  // Metrics
  METRICS_ENABLED: z.coerce.boolean().default(true),
  METRICS_PORT: z.coerce.number().default(9090),

  // Logging
  LOG_LEVEL: z.enum(['trace', 'debug', 'info', 'warn', 'error']).default('info'),
});

export type Config = z.infer<typeof envSchema>;

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  console.error('❌ Invalid environment variables:', parsed.error.format());
  process.exit(1);
}

export const config: Config = parsed.data;

// Derived helper values
export const supportedMimeTypes = new Set(
  config.MEDIA_SUPPORTED_TYPES.split(',').map((t) => t.trim())
);

export const blockedDomains = new Set(
  config.CRAWLER_BLOCKED_DOMAINS.split(',').map((d) => d.trim()).filter(Boolean)
);

// Clamp camera interval to valid range
export function getValidCameraInterval(): number {
  const interval = config.CAMERA_SNAPSHOT_INTERVAL_SEC;
  if (interval < 2 || interval > 60) {
    console.warn(
      `WARN: CAMERA_SNAPSHOT_INTERVAL_SEC=${interval} out of range [2, 60], using default 5s`
    );
    return 5;
  }
  return interval;
}
