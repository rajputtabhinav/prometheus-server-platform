type TokenBundle = {
  access_token: string;
  refresh_token: string;
  expires_in_seconds: number;
};

export class NonRetryableRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NonRetryableRequestError";
  }
}

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const ACCESS_KEY = "prometheus.access_token";
const REFRESH_KEY = "prometheus.refresh_token";
const EXPIRY_KEY = "prometheus.access_token_expiry";
const AUTH_FAILURE_UNTIL_KEY = "prometheus.auth_failure_until";
const AUTH_FAILURE_MESSAGE_KEY = "prometheus.auth_failure_message";
const AUTH_FAILURE_COOLDOWN_MS = 60_000;

let loginPromise: Promise<TokenBundle> | null = null;
let refreshPromise: Promise<TokenBundle> | null = null;
let authFailureUntil = 0;
let lastAuthError: Error | null = null;

function tokenStillValid() {
  const expiry = Number(window.localStorage.getItem(EXPIRY_KEY) ?? "0");
  return expiry > Date.now() + 10_000;
}

function storeTokens(bundle: TokenBundle) {
  window.localStorage.setItem(ACCESS_KEY, bundle.access_token);
  window.localStorage.setItem(REFRESH_KEY, bundle.refresh_token);
  window.localStorage.setItem(EXPIRY_KEY, String(Date.now() + bundle.expires_in_seconds * 1000));
  authFailureUntil = 0;
  lastAuthError = null;
  window.localStorage.removeItem(AUTH_FAILURE_UNTIL_KEY);
  window.localStorage.removeItem(AUTH_FAILURE_MESSAGE_KEY);
}

function markAuthFailure(error: Error) {
  authFailureUntil = Date.now() + AUTH_FAILURE_COOLDOWN_MS;
  lastAuthError = error;
  window.localStorage.setItem(AUTH_FAILURE_UNTIL_KEY, String(authFailureUntil));
  window.localStorage.setItem(AUTH_FAILURE_MESSAGE_KEY, error.message);
}

function getAuthFailure() {
  if (!lastAuthError) {
    const persistedUntil = Number(window.localStorage.getItem(AUTH_FAILURE_UNTIL_KEY) ?? "0");
    const persistedMessage = window.localStorage.getItem(AUTH_FAILURE_MESSAGE_KEY);
    if (persistedUntil > Date.now() && persistedMessage) {
      authFailureUntil = persistedUntil;
      lastAuthError = new NonRetryableRequestError(persistedMessage);
    }
  }
  if (Date.now() < authFailureUntil && lastAuthError) {
    throw lastAuthError;
  }
}

export function isAuthUnavailable() {
  try {
    getAuthFailure();
    return false;
  } catch (error) {
    return error instanceof NonRetryableRequestError;
  }
}

async function performLogin(): Promise<TokenBundle> {
  getAuthFailure();
  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: "operator", password: "prometheus-operator" })
  });

  if (!response.ok) {
    const error =
      response.status === 404
        ? new NonRetryableRequestError(
            "Prometheus backend is running without /api/v1/auth/login. Restart the backend so the running server matches the current codebase."
          )
        : new Error("Unable to authenticate web operator session.");
    markAuthFailure(error);
    throw error;
  }

  const bundle = (await response.json()) as TokenBundle;
  storeTokens(bundle);
  return bundle;
}

async function login(): Promise<TokenBundle> {
  if (!loginPromise) {
    loginPromise = performLogin().finally(() => {
      loginPromise = null;
    });
  }
  return loginPromise;
}

async function performRefresh(): Promise<TokenBundle> {
  getAuthFailure();
  const refreshToken = window.localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) {
    return login();
  }

  const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken })
  });

  if (!response.ok) {
    if (response.status === 404) {
      const error = new NonRetryableRequestError(
        "Prometheus backend is running without /api/v1/auth/refresh. Restart the backend so the running server matches the current codebase."
      );
      markAuthFailure(error);
      throw error;
    }
    return login();
  }

  const bundle = (await response.json()) as TokenBundle;
  storeTokens(bundle);
  return bundle;
}

async function refresh(): Promise<TokenBundle> {
  if (!refreshPromise) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export async function getAccessToken(): Promise<string> {
  const current = window.localStorage.getItem(ACCESS_KEY);
  if (current && tokenStillValid()) {
    return current;
  }

  const bundle = current ? await refresh() : await login();
  return bundle.access_token;
}

export async function jsonFetcher<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  let response = await fetch(url, {
    ...init,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
      ...(init?.headers ?? {})
    }
  });

  if (response.status === 401) {
    const refreshed = await refresh();
    response = await fetch(url, {
      ...init,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${refreshed.access_token}`,
        ...(init?.headers ?? {})
      }
    });
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
      }
    } catch {
      // Keep the generic error when the response body is not JSON.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

/** GET binary (e.g. artifact download) with Bearer auth and refresh-on-401. */
export async function authenticatedBlob(url: string): Promise<Blob> {
  const token = await getAccessToken();
  const fetchAuthorized = (accessToken: string) =>
    fetch(url, {
      method: "GET",
      headers: {
        authorization: `Bearer ${accessToken}`
      }
    });

  let response = await fetchAuthorized(token);
  if (response.status === 401) {
    const refreshed = await refresh();
    response = await fetchAuthorized(refreshed.access_token);
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
      }
    } catch {
      // Non-JSON error body.
    }
    throw new Error(message);
  }

  return response.blob();
}
