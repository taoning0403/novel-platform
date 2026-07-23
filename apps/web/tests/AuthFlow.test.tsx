/* eslint-disable @typescript-eslint/no-base-to-string, @typescript-eslint/require-await */
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { App, RouteFallback } from "../src/App";
import { resetApiClientForTests } from "../src/api/client";
import { AuthProvider, resetClientInstanceForTests } from "../src/auth/AuthProvider";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const publicSite = {
  site_name: "林间阅读室",
  purpose_statement: "供站点所有者与少量受邀阅读者非经营性使用。",
  privacy_statement: "仅处理登录、设备授权和阅读同步所需的最少信息。",
  icp_registration_number: null,
  icp_registration_url: null,
};

const admin = {
  id: "00000000-0000-0000-0000-000000000001",
  display_name: "管理员",
  role: "admin",
  capabilities: [
    "library.read",
    "library.upload",
    "translation.use",
  ],
  status: "active",
  last_login_at: "2026-07-15T00:00:00Z",
  created_at: "2026-07-15T00:00:00Z",
  updated_at: "2026-07-15T00:00:00Z",
};

const reader = {
  ...admin,
  id: "00000000-0000-0000-0000-000000000002",
  display_name: "受邀读者",
  role: "reader",
  capabilities: ["library.read"],
};

function tokenResponse(user = admin, recoveryMode = false) {
  return {
    access_token: "memory-token",
    token_type: "bearer",
    expires_in: 900,
    user,
    device: {
      id: "11111111-1111-1111-1111-111111111111",
      name: "Test browser",
      platform: "web",
    },
    session: {
      id: "22222222-2222-2222-2222-222222222222",
      created_at: "2026-07-15T00:00:00Z",
      expires_at: "2026-08-15T00:00:00Z",
      recovery_mode: recoveryMode,
    },
  };
}

function refreshDenied() {
  return jsonResponse(
    { error: { code: "invalid_refresh_token", message: "invalid", details: {} } },
    401,
  );
}

function renderApp(path = "/") {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AuthProvider><App /></AuthProvider>
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  const state: unknown = location.state;
  return (
    <output data-testid="location-probe">
      {JSON.stringify({ pathname: location.pathname, state })}
    </output>
  );
}

afterEach(() => {
  resetApiClientForTests();
  resetClientInstanceForTests();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

it("renders an accessible lazy-route fallback", () => {
  render(<RouteFallback />);
  expect(screen.getByRole("status")).toHaveTextContent("正在加载页面…");
  expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
});

it("renders the public non-commercial site statement without setup or fake filing data", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return refreshDenied();
    throw new Error(`unexpected request ${url}`);
  }));

  renderApp("/login");
  expect(await screen.findByRole("heading", { name: "林间阅读室" })).toBeInTheDocument();
  expect(screen.getByText(publicSite.purpose_statement)).toBeInTheDocument();
  expect(screen.getByLabelText("访问凭证")).toHaveAttribute("type", "password");
  expect(screen.queryByText(/Setup Token|创建第一个管理员|ICP备案/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
});

it("restores an authenticated admin from the HttpOnly refresh cookie", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return jsonResponse(tokenResponse());
    if (url.includes("/books?")) return jsonResponse([]);
    if (url.includes("/reader/recent?")) return jsonResponse([]);
    throw new Error(`unexpected request ${url}`);
  }));

  renderApp("/");
  expect(await screen.findByRole("heading", { name: "书库" })).toBeInTheDocument();
  const mainNavigation = screen.getByRole("navigation", { name: "主导航" });
  expect(within(mainNavigation).getByRole("link", { name: "管理" })).toBeInTheDocument();
  expect(within(mainNavigation).getByRole("link", { name: "上传" })).toBeInTheDocument();
  expect(window.localStorage.getItem("access_token")).toBeNull();
});

it("logs a reader in with one credential and stores only a non-security device hint", async () => {
  const randomBytes = Array.from({ length: 16 }, (_, index) => index);
  const getRandomValues = vi.fn((bytes: Uint8Array) => {
    bytes.set(randomBytes);
    return bytes;
  });
  vi.stubGlobal("crypto", { getRandomValues, randomUUID: undefined });
  window.localStorage.setItem("novel_client_instance_id", "tampered-value");
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return refreshDenied();
    if (url.endsWith("/auth/login")) {
      const payload = JSON.parse(String(init?.body)) as {
        credential: string;
        refresh_token_delivery: string;
        device: { client_instance_id: string; name: string };
      };
      expect(payload).not.toHaveProperty("username");
      expect(payload).not.toHaveProperty("password");
      expect(payload.credential).toBe("npa_reader_once");
      expect(payload.refresh_token_delivery).toBe("cookie");
      expect(payload.device.client_instance_id).toBe(
        "00010203-0405-4607-8809-0a0b0c0d0e0f",
      );
      return jsonResponse(tokenResponse(reader));
    }
    if (url.includes("/books?")) return jsonResponse([]);
    if (url.includes("/reader/recent?")) return jsonResponse([]);
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/login");
  await screen.findByRole("heading", { name: "登录" });
  fireEvent.change(screen.getByLabelText("访问凭证"), {
    target: { value: "npa_reader_once" },
  });
  fireEvent.change(screen.getByLabelText("设备名称"), {
    target: { value: "阅读器" },
  });
  fireEvent.click(screen.getByRole("button", { name: "进入书库" }));

  expect(await screen.findByRole("heading", { name: "书库" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "上传" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "管理" })).not.toBeInTheDocument();
  await waitFor(() => expect(window.localStorage.getItem("novel_client_instance_id")).toBeTruthy());
  expect(window.localStorage.getItem("access_token")).toBeNull();
  expect(window.localStorage.getItem("refresh_token")).toBeNull();
});

it("confines an administrator recovery login to Passkey enrollment", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return jsonResponse(tokenResponse(admin, true));
    throw new Error(`unexpected request ${url}`);
  }));

  renderApp("/");
  expect(await screen.findByRole("heading", { name: "Passkey 与管理员会话" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "登记新的 Passkey" })).toBeInTheDocument();
  const mainNavigation = screen.getByRole("navigation", { name: "主导航" });
  expect(
    within(mainNavigation).getByRole("link", { name: "登记 Passkey" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "共享书库" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "管理" })).not.toBeInTheDocument();
});

it("keeps the administrator Passkey action distinct from reader credential login", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return refreshDenied();
    throw new Error(`unexpected request ${url}`);
  }));

  renderApp("/login");
  expect(await screen.findByRole("button", { name: "使用安全设备登录" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "进入书库" })).toBeInTheDocument();
  expect(screen.getByText("管理员")).toBeInTheDocument();
});

it("opens mobile navigation and closes it after a route change", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return jsonResponse(tokenResponse());
    if (url.includes("/books?")) return jsonResponse([]);
    if (url.includes("/reader/recent?")) return jsonResponse([]);
    throw new Error(`unexpected request ${url}`);
  }));

  renderApp("/");
  await screen.findByRole("heading", { name: "书库" });
  fireEvent.click(screen.getByRole("button", { name: "打开主导航" }));
  const drawer = await screen.findByRole("dialog");
  fireEvent.click(within(drawer).getByRole("link", { name: "身份" }));

  expect(
    await screen.findByRole("heading", { name: "我的身份" }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
});

it("clears a private return path on explicit logout", async () => {
  vi.stubGlobal("fetch", vi.fn(async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return jsonResponse(tokenResponse());
    if (url.includes("/books?")) return jsonResponse([]);
    if (url.includes("/reader/recent?")) return jsonResponse([]);
    if (url.endsWith("/auth/logout") && init?.method === "POST") {
      return new Response(null, { status: 204 });
    }
    throw new Error(`unexpected request ${url}`);
  }));

  render(
    <MemoryRouter
      initialEntries={[{
        pathname: "/",
        state: { from: "/books/private-book" },
      }]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AuthProvider>
        <App />
        <LocationProbe />
      </AuthProvider>
    </MemoryRouter>,
  );

  await screen.findByRole("heading", { name: "书库" });
  fireEvent.click(screen.getByRole("button", { name: "退出" }));
  expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  expect(screen.getByTestId("location-probe")).toHaveTextContent(
    JSON.stringify({ pathname: "/login", state: null }),
  );
});

it("keeps the credential and device name after a failed login", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/site")) return jsonResponse(publicSite);
    if (url.endsWith("/auth/refresh")) return refreshDenied();
    if (url.endsWith("/auth/login")) {
      return jsonResponse(
        {
          error: {
            code: "invalid_access_credential",
            message: "访问凭证无效或已失效。",
            details: {},
          },
        },
        401,
      );
    }
    throw new Error(`unexpected request ${url}`);
  }));

  renderApp("/login");
  const credential = await screen.findByLabelText("访问凭证");
  const deviceName = screen.getByLabelText("设备名称");
  fireEvent.change(credential, { target: { value: "retry-safe-value" } });
  fireEvent.change(deviceName, { target: { value: "卧室阅读器" } });
  fireEvent.click(screen.getByRole("button", { name: "进入书库" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "访问凭证无效或已失效",
  );
  expect(credential).toHaveValue("retry-safe-value");
  expect(deviceName).toHaveValue("卧室阅读器");
});
