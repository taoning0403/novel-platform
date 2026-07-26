/* eslint-disable @typescript-eslint/no-base-to-string, @typescript-eslint/require-await */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  api,
  getAccessToken,
  resetApiClientForTests,
  setAccessToken,
} from "../src/api/client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const unauthorized = {
  error: { code: "access_token_expired", message: "expired", details: {} },
};

afterEach(() => {
  resetApiClientForTests();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("authenticated API client", () => {
  it("uses one single-flight refresh for concurrent 401 responses", async () => {
    setAccessToken("old-access-token");
    let refreshCount = 0;
    let bookCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/auth/refresh")) {
          refreshCount += 1;
          return jsonResponse({ access_token: "new-access-token" });
        }
        if (url.includes("/api/v1/books")) {
          bookCount += 1;
          const authorization = new Headers(init?.headers).get("Authorization");
          if (authorization === "Bearer old-access-token") return jsonResponse(unauthorized, 401);
          expect(authorization).toBe("Bearer new-access-token");
          return jsonResponse([]);
        }
        throw new Error(`unexpected request ${url}`);
      }),
    );

    const [first, second] = await Promise.all([api.listBooks(), api.listBooks()]);
    expect(first).toEqual([]);
    expect(second).toEqual([]);
    expect(refreshCount).toBe(1);
    expect(bookCount).toBe(4);
    expect(getAccessToken()).toBe("new-access-token");
  });

  it("does not retry forever when refresh fails", async () => {
    setAccessToken("expired-access-token");
    let refreshCount = 0;
    let bookCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/v1/auth/refresh")) {
          refreshCount += 1;
          return jsonResponse(unauthorized, 401);
        }
        bookCount += 1;
        return jsonResponse(unauthorized, 401);
      }),
    );

    await expect(api.listBooks()).rejects.toMatchObject({ status: 401 });
    expect(refreshCount).toBe(1);
    expect(bookCount).toBe(1);
    expect(getAccessToken()).toBeNull();
    await expect(api.listBooks()).rejects.toMatchObject({ status: 401 });
    expect(refreshCount).toBe(1);
    expect(bookCount).toBe(2);
  });

  it("keeps access tokens in memory instead of localStorage", () => {
    setAccessToken("memory-only-secret");
    expect(getAccessToken()).toBe("memory-only-secret");
    expect(Object.values(window.localStorage)).not.toContain("memory-only-secret");
    expect(window.localStorage.getItem("access_token")).toBeNull();
    expect(window.localStorage.getItem("refresh_token")).toBeNull();
  });

  it("uses the self credential endpoint without persisting or placing the API key in a URL", async () => {
    setAccessToken("current-access-token");
    const providerKey = "unit-test-api-client-credential";
    const fetchMock = vi.fn(async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      const url = String(input);
      expect(url).toMatch(/\/api\/v1\/me\/provider-credential$/);
      expect(url).not.toContain(providerKey);
      expect(new Headers(init?.headers).get("Authorization")).toBe(
        "Bearer current-access-token",
      );
      if (init?.method === "PUT") {
        expect(JSON.parse(String(init.body))).toEqual({
          api_key: providerKey,
          provider: "deepseek",
          model: "deepseek-reasoner",
          thinking_enabled: true,
        });
        return jsonResponse({
          configured: true,
          provider: "deepseek",
          provider_name: "DeepSeek",
          base_url: "https://api.deepseek.com/v1",
          model: "deepseek-reasoner",
          thinking_enabled: true,
          version: 1,
          updated_at: "2026-07-25T09:30:00Z",
          usage: {
            all_time: {
              request_count: 0,
              prompt_tokens: 0,
              completion_tokens: 0,
              total_tokens: 0,
            },
            current_month: {
              request_count: 0,
              prompt_tokens: 0,
              completion_tokens: 0,
              total_tokens: 0,
            },
          },
        });
      }
      if (init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      return jsonResponse({
        configured: false,
        provider: "openai_compatible",
        provider_name: "OpenAI",
        base_url: "https://api.openai.com/v1",
        model: "gpt-4.1-mini",
        thinking_enabled: false,
        version: null,
        updated_at: null,
        usage: {
          all_time: {
            request_count: 0,
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
          },
          current_month: {
            request_count: 0,
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
          },
        },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    expect(await api.getProviderCredential()).toMatchObject({ configured: false });
    expect(
      await api.updateProviderCredential({
        api_key: providerKey,
        provider: "deepseek",
        model: "deepseek-reasoner",
        thinking_enabled: true,
      }),
    ).toMatchObject({ configured: true, version: 1 });
    await api.deleteProviderCredential();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(Object.values(window.localStorage)).not.toContain(providerKey);
  });

  it("refreshes an expired access token before logging out", async () => {
    setAccessToken("expired-access-token");
    let logoutCount = 0;
    let refreshCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/auth/refresh")) {
          refreshCount += 1;
          return jsonResponse({ access_token: "fresh-access-token" });
        }
        if (url.endsWith("/api/v1/auth/logout")) {
          logoutCount += 1;
          const authorization = new Headers(init?.headers).get("Authorization");
          if (authorization === "Bearer expired-access-token") {
            return jsonResponse(unauthorized, 401);
          }
          expect(authorization).toBe("Bearer fresh-access-token");
          return new Response(null, { status: 204 });
        }
        throw new Error(`unexpected request ${url}`);
      }),
    );

    await api.logout();
    expect(refreshCount).toBe(1);
    expect(logoutCount).toBe(2);
    expect(getAccessToken()).toBeNull();
  });
});
