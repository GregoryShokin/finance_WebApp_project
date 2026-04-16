import { apiClient } from '@/lib/api/client';
import type { Metrics } from '@/types/metrics';

export function getMetrics(month: string) {
  return apiClient<Metrics>(`/metrics?month=${month}`);
}

export interface FlowMetric {
  basic_flow: number;
  full_flow: number;
  lifestyle_indicator: number | null;
  zone: 'healthy' | 'tight' | 'deficit';
  trend: number | null;
}

export interface CapitalMetric {
  capital: number;
  trend: number | null;
}

export interface DTIMetric {
  dti_percent: number | null;
  zone: 'normal' | 'acceptable' | 'danger' | 'critical' | null;
  monthly_payments: number;
  regular_income: number;
}

export interface ReserveMetric {
  months: number | null;
  zone: 'critical' | 'minimum' | 'normal' | 'excellent' | null;
  available_cash: number;
  monthly_outflow: number;
}

export interface MetricsSummary {
  flow: FlowMetric;
  capital: CapitalMetric;
  dti: DTIMetric;
  reserve: ReserveMetric;
  fi_score: number;
}

export function getMetricsSummary() {
  return apiClient<MetricsSummary>('/metrics/summary');
}

export interface HealthRecommendation {
  metric: string;
  zone: string;
  priority: number;
  message_key: string;
  title: string;
  message: string;
}

export interface HealthSummary {
  metrics: MetricsSummary;
  fi_score: number;
  fi_zone: 'risk' | 'growth' | 'path' | 'freedom';
  weakest_metric: string;
  recommendations: HealthRecommendation[];
}

export function getHealthSummary() {
  return apiClient<HealthSummary>('/metrics/health');
}
