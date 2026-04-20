'use client';

import { useQuery } from '@tanstack/react-query';
import { getCapitalHistory } from '@/lib/api/financial-health';
import { useAuth } from '@/hooks/use-auth';

export function useCapitalHistory(months = 6) {
  const auth = useAuth();

  const query = useQuery({
    queryKey: ['capital-history', auth.user?.id, months],
    queryFn: () => getCapitalHistory(months),
    enabled: Boolean(auth.user?.id),
    staleTime: 1000 * 60 * 5,
    retry: false,
  });

  return {
    data: query.data ?? null,
    isLoading: auth.isLoading || query.isLoading,
    error: auth.error ?? query.error,
    refetch: query.refetch,
  };
}
