'use client';

import Cookies from 'js-cookie';
import { ACCESS_TOKEN_KEY } from './constants';

const cookieOptions = {
  expires: 7,
  sameSite: 'lax' as const,
};

export function getAccessToken() {
  return Cookies.get(ACCESS_TOKEN_KEY) ?? null;
}

export function setAccessToken(token: string) {
  Cookies.set(ACCESS_TOKEN_KEY, token, cookieOptions);
}

export function removeAccessToken() {
  Cookies.remove(ACCESS_TOKEN_KEY);
}
