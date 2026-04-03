'use client';

import { useQuery } from '@tanstack/react-query';
import { getFinancialHealth } from '@/lib/api/financial-health';
import { useAuth } from '@/hooks/use-auth';

export function useFinancialHealth() {
  const auth = useAuth();

  const query = useQuery({
    queryKey: ['financial-health', auth.user?.id],
    queryFn: () => getFinancialHealth(auth.user!.id),
    enabled: Boolean(auth.user?.id),
    staleTime: 1000 * 60 * 5,
    retry: false,
  });

  return {
    data: query.data ?? null,
    isLoading: auth.isLoading || query.isLoading,
    error: auth.error ?? query.error,
    refetch: query.refetch,
    user: auth.user,
  };
}