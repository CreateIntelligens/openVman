/**
 * IPlugin — uniform interface for all Gateway plugins.
 */
export interface PluginParams {
  session_id: string;
  client_id: string;
  trace_id: string;
  [key: string]: unknown;
}

export interface PluginResult {
  type: string;
  plugin: string;
  content?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface IPlugin {
  id: string;
  execute(params: PluginParams): Promise<PluginResult>;
  healthCheck(): Promise<boolean>;
  cleanup?(sessionId: string): Promise<void>;
}
