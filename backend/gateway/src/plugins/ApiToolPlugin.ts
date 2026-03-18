import * as fs from 'fs';
import axios, { AxiosRequestConfig } from 'axios';
import * as YAML from 'yaml';
import { IPlugin, PluginParams, PluginResult } from './IPlugin';
import { config } from '../config';
import { logger } from '../utils/logger';

interface ApiEntry {
  url: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  auth_type: 'bearer' | 'api_key' | 'basic' | 'none';
  auth_value?: string;
  auth_header?: string;
  rate_limit?: number; // req/min
  description?: string;
}

interface ApiRegistry {
  apis: Record<string, ApiEntry>;
}

interface SlidingWindowCounter {
  timestamps: number[];
  queue: Array<() => void>;
}

interface ApiToolParams extends PluginParams {
  api_id: string;
  params?: Record<string, unknown>;
  body?: Record<string, unknown>;
}

export class ApiToolPlugin implements IPlugin {
  id = 'api-tool';
  private registry: ApiRegistry = { apis: {} };
  private counters: Map<string, SlidingWindowCounter> = new Map();

  constructor() {
    this.loadRegistry();
  }

  private loadRegistry(): void {
    try {
      const raw = fs.readFileSync(config.API_REGISTRY_PATH, 'utf-8');
      // Task 6.1 – resolve env var placeholders in auth_value
      const resolved = raw.replace(/\$\{(\w+)\}/g, (_, key) => process.env[key] ?? '');
      this.registry = YAML.parse(resolved) as ApiRegistry;
      logger.info({ event: 'api_registry_loaded', count: Object.keys(this.registry.apis).length });
    } catch (err) {
      logger.warn({ event: 'api_registry_load_failed', err });
    }
  }

  async execute(params: PluginParams): Promise<PluginResult> {
    const { api_id, params: qp, body } = params as ApiToolParams;

    // Task 6.6 – unregistered api_id
    const entry = this.registry.apis[api_id];
    if (!entry) {
      return { type: 'tool_result', plugin: this.id, error: 'api_not_registered' };
    }

    // Task 6.5 – rate limiting
    const allowed = await this.checkRateLimit(api_id, entry.rate_limit);
    if (!allowed) {
      return { type: 'tool_result', plugin: this.id, error: 'local_queue_full' };
    }

    const headers: Record<string, string> = {};
    if (entry.auth_type === 'bearer') {
      headers['Authorization'] = `Bearer ${entry.auth_value}`;
    } else if (entry.auth_type === 'api_key' && entry.auth_header) {
      headers[entry.auth_header] = entry.auth_value ?? '';
    } else if (entry.auth_type === 'basic') {
      headers['Authorization'] = `Basic ${Buffer.from(entry.auth_value ?? '').toString('base64')}`;
    }

    const axiosConfig: AxiosRequestConfig = {
      method: entry.method,
      url: entry.url,
      headers,
      params: qp,
      data: body,
      timeout: config.API_TOOL_TIMEOUT_MS,
    };

    return this.callWithRetry(api_id, axiosConfig);
  }

  private async callWithRetry(apiId: string, axiosConfig: AxiosRequestConfig): Promise<PluginResult> {
    try {
      const response = await axios(axiosConfig);
      logger.info({ event: 'api_tool_success', api_id: apiId, status: response.status });
      return {
        type: 'tool_result',
        plugin: this.id,
        content: JSON.stringify(response.data),
        metadata: { status_code: response.status },
      };
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 429) {
          // Task 6.4 – 429 retry with Retry-After
          const retryAfter = Number(err.response.headers['retry-after'] ?? 2);
          await new Promise((r) => setTimeout(r, retryAfter * 1000));
          try {
            const retryResponse = await axios(axiosConfig);
            return {
              type: 'tool_result',
              plugin: this.id,
              content: JSON.stringify(retryResponse.data),
              metadata: { status_code: retryResponse.status },
            };
          } catch {
            return { type: 'tool_result', plugin: this.id, error: 'rate_limited' };
          }
        }
        if (err.code === 'ECONNABORTED') {
          return { type: 'tool_result', plugin: this.id, error: 'timeout' };
        }
      }
      return { type: 'tool_result', plugin: this.id, error: String(err) };
    }
  }

  /** Task 6.5 – Sliding window rate limiter */
  private async checkRateLimit(apiId: string, rateLimit?: number): Promise<boolean> {
    if (!rateLimit) return true;
    if (!this.counters.has(apiId)) {
      this.counters.set(apiId, { timestamps: [], queue: [] });
    }
    const counter = this.counters.get(apiId)!;
    const now = Date.now();
    const windowMs = 60 * 1000;
    counter.timestamps = counter.timestamps.filter((t) => now - t < windowMs);

    if (counter.timestamps.length < rateLimit) {
      counter.timestamps.push(now);
      return true;
    }

    // Queue the request to wait
    if (counter.queue.length >= config.API_TOOL_MAX_QUEUE) {
      return false; // queue full → reject
    }

    return new Promise<boolean>((resolve) => {
      counter.queue.push(() => {
        counter.timestamps.push(Date.now());
        resolve(true);
      });
      // Drain queue every second
      setTimeout(() => {
        const fn = counter.queue.shift();
        fn?.();
      }, windowMs / rateLimit);
    });
  }

  async healthCheck(): Promise<boolean> {
    return Object.keys(this.registry.apis).length > 0;
  }
}
