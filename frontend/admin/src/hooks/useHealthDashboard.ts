import { useCallback, useEffect, useState } from "react";
import { fetchHealthDetailed, fetchMetrics, type MetricsSnapshot } from "../api/metrics";

export interface HealthData {
  status: string;
  tables: string[];
  workspace_documents: number;
  chat_enabled: boolean;
  embedding_model: string;
  llm_provider: string;
  llm_model: string;
}

const REFRESH_INTERVAL = 30;

export function useHealthDashboard() {
  const [data, setData] = useState<HealthData | null>(null);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [healthError, setHealthError] = useState("");
  const [metricsError, setMetricsError] = useState("");
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL);

  const load = useCallback(async () => {
    setLoading(true);

    const [healthResult, metricsResult] = await Promise.allSettled([
      fetchHealthDetailed<HealthData>(),
      fetchMetrics(),
    ]);

    if (healthResult.status === "fulfilled") {
      setData(healthResult.value);
      setHealthError("");
    } else {
      setHealthError(String(healthResult.reason));
    }

    if (metricsResult.status === "fulfilled") {
      setMetrics(metricsResult.value);
      setMetricsError("");
    } else {
      setMetricsError(String(metricsResult.reason));
    }

    setLastChecked(new Date());
    setLoading(false);
    setCountdown(REFRESH_INTERVAL);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setCountdown((current) => {
        if (current <= 1) {
          void load();
          return REFRESH_INTERVAL;
        }

        return current - 1;
      });
    }, 1000);

    return () => window.clearInterval(interval);
  }, [load]);

  return {
    countdown,
    data,
    healthError,
    isOk: data?.status === "ok",
    lastChecked,
    load,
    loading,
    metrics,
    metricsError,
  };
}
