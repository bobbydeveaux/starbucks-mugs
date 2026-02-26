/**
 * OIDC Authentication Helpers
 *
 * Implements the Authorization Code Flow with PKCE for the TripWire dashboard.
 * The identity provider details are configured via environment variables.
 */

import { setToken, clearToken } from '@/api/client';

// ---------------------------------------------------------------------------
// Configuration (from Vite environment variables)
// ---------------------------------------------------------------------------

export interface OidcConfig {
  /** OIDC provider authorization endpoint, e.g. https://auth.example.com/authorize */
  authorizationEndpoint: string;
  /** Token endpoint, e.g. https://auth.example.com/token */
  tokenEndpoint: string;
  /** Client ID registered with the OIDC provider */
  clientId: string;
  /** Redirect URI registered with the OIDC provider (must match exactly) */
  redirectUri: string;
  /** Space-separated OAuth scopes, e.g. "openid profile email" */
  scope: string;
}

function getOidcConfig(): OidcConfig {
  return {
    authorizationEndpoint:
      import.meta.env.VITE_OIDC_AUTHORIZATION_ENDPOINT ?? '',
    tokenEndpoint: import.meta.env.VITE_OIDC_TOKEN_ENDPOINT ?? '',
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID ?? '',
    redirectUri:
      import.meta.env.VITE_OIDC_REDIRECT_URI ??
      `${window.location.origin}/auth/callback`,
    scope: import.meta.env.VITE_OIDC_SCOPE ?? 'openid profile email',
  };
}

// ---------------------------------------------------------------------------
// PKCE helpers
// ---------------------------------------------------------------------------

async function generateCodeVerifier(): Promise<string> {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return base64urlEncode(array);
}

async function generateCodeChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return base64urlEncode(new Uint8Array(digest));
}

function base64urlEncode(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

// ---------------------------------------------------------------------------
// State storage (sessionStorage to survive page reload but not new tab)
// ---------------------------------------------------------------------------

const STATE_KEY = 'tripwire_oidc_state';
const VERIFIER_KEY = 'tripwire_oidc_verifier';

function generateState(): string {
  const array = new Uint8Array(16);
  crypto.getRandomValues(array);
  return base64urlEncode(array);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Redirects the browser to the OIDC provider's authorization endpoint.
 * Stores PKCE code verifier and state in sessionStorage for callback validation.
 */
export async function initiateLogin(): Promise<void> {
  const config = getOidcConfig();
  const state = generateState();
  const verifier = await generateCodeVerifier();
  const challenge = await generateCodeChallenge(verifier);

  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(VERIFIER_KEY, verifier);

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: config.scope,
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  });

  window.location.href = `${config.authorizationEndpoint}?${params}`;
}

/**
 * Handles the OIDC callback after the provider redirects back.
 * Validates state, exchanges the authorization code for tokens,
 * and stores the access token via setToken().
 *
 * @returns true on success, false if state mismatch or exchange fails.
 */
export async function handleCallback(
  searchParams: URLSearchParams,
): Promise<boolean> {
  const config = getOidcConfig();

  const code = searchParams.get('code');
  const returnedState = searchParams.get('state');
  const storedState = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(VERIFIER_KEY);

  // Clean up session storage regardless of outcome
  sessionStorage.removeItem(STATE_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);

  if (!code || !returnedState || returnedState !== storedState || !verifier) {
    return false;
  }

  try {
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: config.redirectUri,
      client_id: config.clientId,
      code_verifier: verifier,
    });

    const response = await fetch(config.tokenEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });

    if (!response.ok) return false;

    const tokens = (await response.json()) as {
      access_token?: string;
      token_type?: string;
    };

    if (!tokens.access_token) return false;

    setToken(tokens.access_token);
    return true;
  } catch {
    return false;
  }
}

/**
 * Clears the stored access token (logout).
 * Callers should redirect to the login page after calling this.
 */
export function logout(): void {
  clearToken();
}
