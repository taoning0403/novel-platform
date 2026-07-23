/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api, configureAuthFailure, setAccessToken } from "../api/client";
import type {
  LoginDevice,
  LoginSession,
  Passkey,
  PublicSiteSettings,
  TokenResponse,
  User,
} from "../api/types";
import { randomUuid } from "../shared/uuid";
import { createPasskey, getPasskeyAssertion } from "./webauthn";

type AuthPhase = "loading" | "anonymous" | "authenticated";

interface AuthContextValue {
  phase: AuthPhase;
  user: User | null;
  device: LoginDevice | null;
  session: LoginSession | null;
  site: PublicSiteSettings | null;
  siteError: boolean;
  login: (credential: string, deviceName: string) => Promise<User>;
  loginWithPasskey: (deviceName: string) => Promise<User>;
  registerPasskey: (name: string) => Promise<Passkey>;
  logout: () => Promise<void>;
  updateDisplayName: (displayName: string) => Promise<void>;
  refreshSite: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const CLIENT_INSTANCE_KEY = "novel_client_instance_id";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let inMemoryClientInstanceId: string | null = null;

function randomClientInstanceId(): string {
  return randomUuid();
}

function clientInstanceId(): string {
  if (inMemoryClientInstanceId !== null) return inMemoryClientInstanceId;
  try {
    const existing = window.localStorage.getItem(CLIENT_INSTANCE_KEY);
    if (existing !== null && UUID_PATTERN.test(existing)) {
      inMemoryClientInstanceId = existing;
      return existing;
    }
    if (existing !== null) window.localStorage.removeItem(CLIENT_INSTANCE_KEY);
  } catch {
    // Hardened/private browser modes can disable local storage.
  }
  inMemoryClientInstanceId = randomClientInstanceId();
  try {
    window.localStorage.setItem(CLIENT_INSTANCE_KEY, inMemoryClientInstanceId);
  } catch {
    // The in-memory identifier remains a non-security device hint for this tab.
  }
  return inMemoryClientInstanceId;
}

function loginDevice(name: string) {
  return {
    client_instance_id: clientInstanceId(),
    name,
    platform: "web" as const,
    app_version: "0.9.0",
  };
}

export function defaultDeviceName(): string {
  const platform = navigator.platform || "Web 浏览器";
  return `${platform} 上的浏览器`;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<AuthPhase>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [device, setDevice] = useState<LoginDevice | null>(null);
  const [session, setSession] = useState<LoginSession | null>(null);
  const [site, setSite] = useState<PublicSiteSettings | null>(null);
  const [siteError, setSiteError] = useState(false);

  const clearAuth = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setDevice(null);
    setSession(null);
    setPhase("anonymous");
  }, []);

  const applyTokenResponse = useCallback((result: TokenResponse) => {
    setUser(result.user);
    setDevice(result.device);
    setSession(result.session);
    setPhase("authenticated");
  }, []);

  const refreshSite = useCallback(async () => {
    try {
      setSite(await api.publicSite());
      setSiteError(false);
    } catch {
      setSiteError(true);
    }
  }, []);

  useEffect(() => {
    configureAuthFailure(clearAuth);
    let active = true;
    void (async () => {
      try {
        const publicSite = await api.publicSite();
        if (active) {
          setSite(publicSite);
          setSiteError(false);
        }
      } catch {
        if (active) setSiteError(true);
      }
      try {
        const result = await api.refresh();
        if (active) applyTokenResponse(result);
      } catch {
        if (active) clearAuth();
      }
    })();
    return () => {
      active = false;
      configureAuthFailure(null);
    };
  }, [applyTokenResponse, clearAuth]);

  const login = useCallback(
    async (credential: string, deviceName: string) => {
      const result = await api.login({
        credential,
        refresh_token_delivery: "cookie",
        device: loginDevice(deviceName),
      });
      applyTokenResponse(result);
      return result.user;
    },
    [applyTokenResponse],
  );

  const loginWithPasskey = useCallback(
    async (deviceName: string) => {
      const challenge = await api.passkeyAuthenticationOptions();
      const assertion = await getPasskeyAssertion(challenge.options);
      const result = await api.verifyPasskeyAuthentication(
        challenge.challenge_id,
        assertion,
        loginDevice(deviceName),
      );
      applyTokenResponse(result);
      return result.user;
    },
    [applyTokenResponse],
  );

  const registerPasskey = useCallback(
    async (name: string) => {
      const challenge = await api.passkeyRegistrationOptions();
      const credential = await createPasskey(challenge.options);
      const result = await api.verifyPasskeyRegistration(
        challenge.challenge_id,
        name,
        credential,
      );
      if (result.authentication) applyTokenResponse(result.authentication);
      return result.passkey;
    },
    [applyTokenResponse],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      clearAuth();
    }
  }, [clearAuth]);

  const updateDisplayName = useCallback(async (displayName: string) => {
    setUser(await api.updateProfile({ display_name: displayName }));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      phase,
      user,
      device,
      session,
      site,
      siteError,
      login,
      loginWithPasskey,
      registerPasskey,
      logout,
      updateDisplayName,
      refreshSite,
    }),
    [
      phase,
      user,
      device,
      session,
      site,
      siteError,
      login,
      loginWithPasskey,
      registerPasskey,
      logout,
      updateDisplayName,
      refreshSite,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

export function resetClientInstanceForTests(): void {
  inMemoryClientInstanceId = null;
}
