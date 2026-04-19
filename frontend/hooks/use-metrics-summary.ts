'use client';

import { useQuery } from '@tanstack/react-query';
import { getMetricsSummary } from '@/lib/api/metrics';

export function useMetricsSummary() {
  return useQuery({
    queryKey: ['metrics', 'summary'],
    queryFn: getMetricsSummary,
    staleTime: 5 * 60 * 1000,
  });
}
