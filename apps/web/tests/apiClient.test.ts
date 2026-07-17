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
