import { z } from 'zod';

const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on']);
const FALSE_VALUES = new Set(['0', 'false', 'no', 'off']);

function booleanFromEnv(fallback: boolean) {
  return z
    .union([z.boolean(), z.string(), z.undefined()])
    .transform((value, ctx) => {
      if (value === undefined) return fallback;
      if (typeof value === 'boolean') return value;

      const normalized = value.trim().toLowerCase();
      if (!normalized) return fallback;
      if (TRUE_VALUES.has(normalized)) return true;
      if (FALSE_VALUES.has(normalized)) return false;

      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `expected one of ${[...TRUE_VALUES, ...FALSE_VALUES].join(', ')}`,
      });
      return z.NEVER;
    });
}

export const backendServerEnvSchema = z.object({
  BACKEND_SERVER_PORT: z.coerce.number().int().min(1).max(65535).default(8080),
  BACKEND_SERVER_HOST: z.string().trim().min(1).default('0.0.0.0'),
  LOG_LEVEL: z.enum(['trace', 'debug', 'info', 'warn', 'error']).default('info'),
  LOG_PRETTY: booleanFromEnv(true),
});

export type BackendServerConfig = z.infer<typeof backendServerEnvSchema>;

export function parseBackendServerConfig(
  rawEnv: Record<string, string | undefined> | NodeJS.ProcessEnv
): BackendServerConfig {
  const parsed = backendServerEnvSchema.safeParse(rawEnv);
  if (parsed.success) {
    return parsed.data;
  }

  const detail = parsed.error.issues
    .map((issue) => `${issue.path.join('.') || 'env'}: ${issue.message}`)
    .join('; ');
  throw new Error(`Invalid backend server environment: ${detail}`);
}

export const config: BackendServerConfig = Object.freeze(
  parseBackendServerConfig(process.env)
);
