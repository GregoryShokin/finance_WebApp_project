'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { getMe } from '@/lib/api/auth';
import { getAccessToken, removeAccessToken } from '@/lib/auth/token';

export function useAuth() {
  const [mounted, setMounted] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
    setToken(getAccessToken());
  }, []);

  const query = useQuery({
    queryKey: ['auth', 'me', token],
    queryFn: getMe,
    enabled: mounted && Boolean(token),
    staleTime: 1000 * 60 * 5,
    retry: false,
  });

  useEffect(() => {
    if (query.error) {
      removeAccessToken();
      setToken(null);
    }
  }, [query.error]);

  return {
    mounted,
    token,
    user: query.data ?? null,
    isLoading: mounted && Boolean(token) && query.isLoading,
    isAuthenticated: Boolean(token && query.data),
    error: query.error,
    refetch: query.refetch,
  };
}
