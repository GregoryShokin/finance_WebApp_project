'use client';

import Cookies from 'js-cookie';
import { ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY } from './constants';

const isProd = process.env.NODE_ENV === 'production';

const accessCookieOptions = {
  expires: 7,
  sameSite: 'lax' as const,
  secure: isProd,
};

// Refresh-cookie is sent ONLY in the body of /auth/refresh and /auth/logout —
// SameSite=Strict prevents it leaking on cross-site navigations even though
// it's not the transport for normal requests.
const refreshCookieOptions = {
  expires: 30,
  sameSite: 'strict' as const,
  secure: isProd,
};

export function getAccessToken() {
  const value = Cookies.get(ACCESS_TOKEN_KEY);
  return value ? value : null;
}

export function setAccessToken(token: string) {
  Cookies.set(ACCESS_TOKEN_KEY, token, accessCookieOptions);
}

export function removeAccessToken() {
  Cookies.remove(ACCESS_TOKEN_KEY);
}

export function getRefreshToken() {
  const value = Cookies.get(REFRESH_TOKEN_KEY);
  return value ? value : null;
}

export function setRefreshToken(token: string) {
  Cookies.set(REFRESH_TOKEN_KEY, token, refreshCookieOptions);
}

export function removeRefreshToken() {
  Cookies.remove(REFRESH_TOKEN_KEY);
}

export function setTokenPair(tokens: { access_token: string; refresh_token: string }) {
  setAccessToken(tokens.access_token);
  setRefreshToken(tokens.refresh_token);
}

export function clearTokens() {
  removeAccessToken();
  removeRefreshToken();
}
