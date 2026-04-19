'use client';

import { useQuery } from '@tanstack/react-query';
import { getHealthSummary } from '@/lib/api/metrics';

export function useHealthSummary() {
  return useQuery({
    queryKey: ['metrics', 'health-summary'],
    queryFn: getHealthSummary,
    staleTime: 5 * 60 * 1000,
  });
}
