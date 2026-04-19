import { apiClient } from '@/lib/api/client';
import type { Metrics } from '@/types/metrics';

export function getMetrics(month: string) {
  return apiClient<Metrics>(`/metrics?month=${month}`);
}

// Phase 5 (2026-04-19): three-layer Flow model.
// Ref: financeapp-vault/01-Metrics/Поток.md
export interface FlowMetric {
  basic_flow: number;
  free_capital: number;          // Basic - credit_body_payments
  full_flow: number;
  cc_debt_compensator: number;   // Δ долга по КК за период
  credit_body_payments: number;  // тело обязательных платежей
  lifestyle_indicator: number | null;
  zone: 'healthy' | 'tight' | 'deficit';
  trend: number | null;
}

export interface CapitalMetric {
  capital: number;
  trend: number | null;
  trend_3m?: number | null;
  trend_6m?: number | null;
  trend_12m?: number | null;
  snapshots_count?: number;
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

export interface BufferStabilityMetric {
  months: number | null;
  zone: 'critical' | 'minimum' | 'normal' | 'excellent' | null;
  deposit_balance: number;
  avg_monthly_expense: number;
}

export interface MetricsSummary {
  flow: FlowMetric;
  capital: CapitalMetric;
  dti: DTIMetric;
  buffer_stability: BufferStabilityMetric;
  reserve: ReserveMetric;  // legacy compat
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
