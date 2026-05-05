'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
import { getMe, logout as logoutRequest } from '@/lib/api/auth';
import { clearTokens, getAccessToken, getRefreshToken } from '@/lib/auth/token';

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
      clearTokens();
      setToken(null);
    }
  }, [query.error]);

  // Server-side logout — revoke the refresh token, then clear local cookies.
  // Network failure shouldn't block local clearing: the user clicked Выйти,
  // they expect to be signed out regardless of whether revocation reached the
  // server (next prune job will collect orphaned rows by expiry).
  const logout = useCallback(async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        await logoutRequest(refreshToken);
      } catch {
        // ignore — local clear still proceeds
      }
    }
    clearTokens();
    setToken(null);
  }, []);

  return {
    mounted,
    token,
    user: query.data ?? null,
    isLoading: mounted && Boolean(token) && query.isLoading,
    isAuthenticated: Boolean(token && query.data),
    error: query.error,
    refetch: query.refetch,
    logout,
  };
}
