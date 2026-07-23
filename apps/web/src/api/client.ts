import type {
  ApiErrorBody,
  CredentialLoginPayload,
  CredentialReissuePayload,
  Book,
  BookDetail,
  BookListItem,
  BookPreference,
  BookPatchPayload,
  Device,
  Edition,
  FileFormat,
  ImportCommitPayload,
  ImportCommitResult,
  ImportOperation,
  ImportRecord,
  IssuedReaderCredential,
  Me,
  PatchEditionPayload,
  PatchPreferencePayload,
  Passkey,
  PasskeyRegistrationResult,
  ProfilePayload,
  PublicSiteSettings,
  ReaderCreatePayload,
  ReaderIdentity,
  ReaderPatchPayload,
  ReaderOpen,
  ReaderSection,
  ReaderSettings,
  ReaderSettingsPayload,
  ReadingProgress,
  ReadingProgressPayload,
  RecentReading,
  Session,
  SecurityAuditEvent,
  SiteSettings,
  SiteSettingsPatch,
  Series,
  SeriesCreatePayload,
  SeriesDetail,
  SeriesPatchPayload,
  TokenResponse,
  User,
  WebAuthnOptions,
} from "./types";

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

let accessToken: string | null = null;
let refreshFlight: Promise<TokenResponse> | null = null;
let authFailureHandler: (() => void) | null = null;

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    code: string,
    status: number,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function configureAuthFailure(handler: (() => void) | null): void {
  authFailureHandler = handler;
}

function apiError(body: ApiErrorBody | null, status: number): ApiError {
  return new ApiError(
    body?.error.message ?? "请求失败，请稍后重试。",
    body?.error.code ?? "request_failed",
    status,
    body?.error.details ?? {},
  );
}

async function responseBody<T>(response: Response): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json().catch(() => null)) as T;
}

async function refreshAccessToken(): Promise<TokenResponse> {
  if (refreshFlight !== null) {
    return refreshFlight;
  }
  refreshFlight = (async () => {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
      setAccessToken(null);
      authFailureHandler?.();
      throw apiError(body, response.status);
    }
    const body = await responseBody<TokenResponse>(response);
    setAccessToken(body.access_token);
    return body;
  })().finally(() => {
    refreshFlight = null;
  });
  return refreshFlight;
}

function canRefresh(path: string): boolean {
  return ![
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/passkeys/authentication/options",
    "/api/v1/auth/passkeys/authentication/verify",
  ].includes(path);
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  allowRetry = true,
): Promise<T> {
  const tokenUsed = accessToken;
  const headers = new Headers(options.headers);
  if (
    options.body !== undefined
    && !(options.body instanceof FormData)
    && !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  if (tokenUsed !== null) {
    headers.set("Authorization", `Bearer ${tokenUsed}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });
  if (response.status === 401 && allowRetry && tokenUsed !== null && canRefresh(path)) {
    if (accessToken === tokenUsed) {
      await refreshAccessToken();
    }
    return request<T>(path, options, false);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
    if (response.status === 401 && tokenUsed !== null && canRefresh(path)) {
      setAccessToken(null);
      authFailureHandler?.();
    }
    throw apiError(body, response.status);
  }
  return responseBody<T>(response);
}

async function requestBlob(path: string, allowRetry = true): Promise<Blob> {
  const tokenUsed = accessToken;
  const headers = new Headers();
  if (tokenUsed !== null) headers.set("Authorization", `Bearer ${tokenUsed}`);
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    credentials: "include",
  });
  if (response.status === 401 && allowRetry && tokenUsed !== null && canRefresh(path)) {
    if (accessToken === tokenUsed) await refreshAccessToken();
    return requestBlob(path, false);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
    if (response.status === 401 && tokenUsed !== null) {
      setAccessToken(null);
      authFailureHandler?.();
    }
    throw apiError(body, response.status);
  }
  return response.blob();
}

export interface InspectImportOptions {
  file: File;
  operation: ImportOperation;
  textEncoding?: string;
  targetBookId?: string;
  targetEditionId?: string;
  onProgress?: (percentage: number) => void;
}

function uploadImport(
  options: InspectImportOptions,
  allowRetry = true,
): Promise<ImportRecord> {
  const tokenUsed = accessToken;
  const form = new FormData();
  form.set("file", options.file);
  form.set("operation", options.operation);
  form.set("text_encoding", options.textEncoding ?? "auto");
  if (options.targetBookId) form.set("target_book_id", options.targetBookId);
  if (options.targetEditionId) form.set("target_edition_id", options.targetEditionId);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/v1/imports/inspect`);
    xhr.withCredentials = true;
    if (tokenUsed !== null) xhr.setRequestHeader("Authorization", `Bearer ${tokenUsed}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        options.onProgress?.(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onerror = () => reject(new ApiError("上传网络连接失败。", "network_error", 0));
    xhr.onload = () => {
      const body = (() => {
        try {
          return JSON.parse(xhr.responseText) as ImportRecord | ApiErrorBody;
        } catch {
          return null;
        }
      })();
      if (xhr.status === 401 && allowRetry && tokenUsed !== null) {
        void (async () => {
          try {
            if (accessToken === tokenUsed) await refreshAccessToken();
            resolve(await uploadImport(options, false));
          } catch (error) {
            reject(error instanceof Error ? error : new Error("上传认证刷新失败。"));
          }
        })();
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        if (xhr.status === 401 && tokenUsed !== null) {
          setAccessToken(null);
          authFailureHandler?.();
        }
        reject(apiError(body as ApiErrorBody | null, xhr.status));
        return;
      }
      options.onProgress?.(100);
      resolve(body as ImportRecord);
    };
    xhr.send(form);
  });
}

export interface BookFilters {
  query?: string;
  format?: FileFormat | "";
  language?: string;
  editionType?: "source" | "translation" | "";
  sort?: "updated_desc" | "created_desc" | "title_asc";
}

export const api = {
  live: () => request<{ status: string }>("/api/v1/health/live"),
  ready: () => request<{ status: string }>("/api/v1/health/ready"),
  publicSite: () => request<PublicSiteSettings>("/api/v1/site"),
  login: async (payload: CredentialLoginPayload) => {
    const result = await request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setAccessToken(result.access_token);
    return result;
  },
  passkeyAuthenticationOptions: () =>
    request<WebAuthnOptions>("/api/v1/auth/passkeys/authentication/options", {
      method: "POST",
    }),
  verifyPasskeyAuthentication: async (
    challengeId: string,
    credential: Record<string, unknown>,
    device: CredentialLoginPayload["device"],
  ) => {
    const result = await request<TokenResponse>(
      "/api/v1/auth/passkeys/authentication/verify",
      {
        method: "POST",
        body: JSON.stringify({
          challenge_id: challengeId,
          credential,
          refresh_token_delivery: "cookie",
          device,
        }),
      },
    );
    setAccessToken(result.access_token);
    return result;
  },
  passkeyRegistrationOptions: () =>
    request<WebAuthnOptions>("/api/v1/auth/passkeys/registration/options", {
      method: "POST",
    }),
  verifyPasskeyRegistration: async (
    challengeId: string,
    name: string,
    credential: Record<string, unknown>,
  ) => {
    const result = await request<PasskeyRegistrationResult>(
      "/api/v1/auth/passkeys/registration/verify",
      {
        method: "POST",
        body: JSON.stringify({ challenge_id: challengeId, name, credential }),
      },
    );
    if (result.authentication) setAccessToken(result.authentication.access_token);
    return result;
  },
  listPasskeys: () => request<Passkey[]>("/api/v1/auth/passkeys"),
  renamePasskey: (passkeyId: string, name: string) =>
    request<Passkey>(`/api/v1/auth/passkeys/${passkeyId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  revokePasskey: (passkeyId: string) =>
    request<void>(`/api/v1/auth/passkeys/${passkeyId}`, { method: "DELETE" }),
  refresh: () => refreshAccessToken(),
  me: () => request<Me>("/api/v1/auth/me"),
  logout: async () => {
    try {
      await request<void>("/api/v1/auth/logout", { method: "POST" });
    } finally {
      setAccessToken(null);
    }
  },
  listSessions: () => request<Session[]>("/api/v1/auth/sessions"),
  revokeSession: (sessionId: string) =>
    request<void>(`/api/v1/auth/sessions/${sessionId}`, { method: "DELETE" }),
  revokeOtherSessions: () =>
    request<{ revoked_count: number }>("/api/v1/auth/sessions/revoke-others", {
      method: "POST",
    }),
  listDevices: () => request<Device[]>("/api/v1/devices"),
  renameDevice: (deviceId: string, name: string) =>
    request<Device>(`/api/v1/devices/${deviceId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  revokeDevice: (deviceId: string) =>
    request<void>(`/api/v1/devices/${deviceId}/revoke`, { method: "POST" }),
  updateProfile: (payload: ProfilePayload) =>
    request<User>("/api/v1/users/me", { method: "PATCH", body: JSON.stringify(payload) }),
  listBooks: (filters: BookFilters = {}, limit = 100, offset = 0) => {
    const search = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (filters.query) search.set("query", filters.query);
    if (filters.format) search.set("format", filters.format);
    if (filters.language) search.set("language", filters.language);
    if (filters.editionType) search.set("edition_type", filters.editionType);
    if (filters.sort) search.set("sort", filters.sort);
    return request<BookListItem[]>(`/api/v1/books?${search}`);
  },
  getBook: (bookId: string) => request<BookDetail>(`/api/v1/books/${bookId}`),
  patchBook: (bookId: string, payload: BookPatchPayload) =>
    request<Book>(`/api/v1/books/${bookId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteBook: (bookId: string) =>
    request<void>(`/api/v1/books/${bookId}`, { method: "DELETE" }),
  patchEdition: (bookId: string, editionId: string, payload: PatchEditionPayload) =>
    request<Edition>(`/api/v1/books/${bookId}/editions/${editionId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteEdition: (bookId: string, editionId: string) =>
    request<void>(`/api/v1/books/${bookId}/editions/${editionId}`, {
      method: "DELETE",
    }),
  getPreferences: (bookId: string) =>
    request<BookPreference>(`/api/v1/books/${bookId}/preferences`),
  patchPreferences: (bookId: string, payload: PatchPreferencePayload) =>
    request<BookPreference>(`/api/v1/books/${bookId}/preferences`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  inspectImport: (options: InspectImportOptions) => uploadImport(options),
  getImport: (importId: string) => request<ImportRecord>(`/api/v1/imports/${importId}`),
  commitImport: (importId: string, payload: ImportCommitPayload) =>
    request<ImportCommitResult>(`/api/v1/imports/${importId}/commit`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteImport: (importId: string) =>
    request<void>(`/api/v1/imports/${importId}`, { method: "DELETE" }),
  listSeries: () => request<Series[]>("/api/v1/series"),
  createSeries: (payload: SeriesCreatePayload) =>
    request<Series>("/api/v1/series", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSeries: (seriesId: string) => request<SeriesDetail>(`/api/v1/series/${seriesId}`),
  patchSeries: (seriesId: string, payload: SeriesPatchPayload) =>
    request<Series>(`/api/v1/series/${seriesId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteSeries: (seriesId: string) =>
    request<void>(`/api/v1/series/${seriesId}`, { method: "DELETE" }),
  addBookToSeries: (seriesId: string, bookId: string) =>
    request<SeriesDetail>(`/api/v1/series/${seriesId}/books/${bookId}`, {
      method: "POST",
    }),
  removeBookFromSeries: (seriesId: string, bookId: string) =>
    request<void>(`/api/v1/series/${seriesId}/books/${bookId}`, { method: "DELETE" }),
  openReader: (editionId: string) =>
    request<ReaderOpen>(`/api/v1/editions/${editionId}/reader/open`, { method: "POST" }),
  getReaderSection: (editionId: string, sectionId: string) =>
    request<ReaderSection>(
      `/api/v1/editions/${editionId}/reader/sections/${encodeURIComponent(sectionId)}`,
    ),
  getReaderResource: (editionId: string, resourceId: string) =>
    requestBlob(
      `/api/v1/editions/${editionId}/reader/resources/${encodeURIComponent(resourceId)}`,
    ),
  saveReadingProgress: (
    editionId: string,
    payload: ReadingProgressPayload,
    keepalive = false,
  ) => request<ReadingProgress>(`/api/v1/editions/${editionId}/reader/progress`, {
    method: "PATCH",
    body: JSON.stringify(payload),
    keepalive,
  }),
  getReaderSettings: () => request<ReaderSettings>("/api/v1/reader/settings"),
  patchReaderSettings: (payload: ReaderSettingsPayload) =>
    request<ReaderSettings>("/api/v1/reader/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  recentReading: (limit = 12) =>
    request<RecentReading[]>(`/api/v1/reader/recent?limit=${limit}`),
  getAdminSite: () => request<SiteSettings>("/api/v1/admin/site"),
  patchAdminSite: (payload: SiteSettingsPatch) =>
    request<SiteSettings>("/api/v1/admin/site", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  listReaders: () => request<ReaderIdentity[]>("/api/v1/admin/readers"),
  createReader: (payload: ReaderCreatePayload) =>
    request<IssuedReaderCredential>("/api/v1/admin/readers", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getReader: (readerId: string) =>
    request<ReaderIdentity>(`/api/v1/admin/readers/${readerId}`),
  patchReader: (readerId: string, payload: ReaderPatchPayload) =>
    request<ReaderIdentity>(`/api/v1/admin/readers/${readerId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  suspendReaderCredential: (readerId: string) =>
    request<void>(`/api/v1/admin/readers/${readerId}/credential/suspend`, {
      method: "POST",
    }),
  resumeReaderCredential: (readerId: string) =>
    request<void>(`/api/v1/admin/readers/${readerId}/credential/resume`, {
      method: "POST",
    }),
  revokeReaderCredential: (readerId: string) =>
    request<void>(`/api/v1/admin/readers/${readerId}/credential/revoke`, {
      method: "POST",
    }),
  reissueReaderCredential: (readerId: string, payload: CredentialReissuePayload) =>
    request<IssuedReaderCredential>(
      `/api/v1/admin/readers/${readerId}/credential/reissue`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  revokeReaderSessions: (readerId: string) =>
    request<{ revoked_count: number }>(
      `/api/v1/admin/readers/${readerId}/sessions/revoke-all`,
      { method: "POST" },
    ),
  listReaderDevices: (readerId: string) =>
    request<Device[]>(`/api/v1/admin/readers/${readerId}/devices`),
  revokeReaderDevice: (readerId: string, deviceId: string) =>
    request<void>(`/api/v1/admin/readers/${readerId}/devices/${deviceId}/revoke`, {
      method: "POST",
    }),
  readerAudit: (readerId: string) =>
    request<SecurityAuditEvent[]>(`/api/v1/admin/readers/${readerId}/audit`),
  listAudit: (filters: {
    eventType?: string;
    subjectUserId?: string;
    outcome?: string;
    createdFrom?: string;
    createdTo?: string;
  } = {}) => {
    const search = new URLSearchParams({ limit: "200", offset: "0" });
    if (filters.eventType) search.set("event_type", filters.eventType);
    if (filters.subjectUserId) search.set("subject_user_id", filters.subjectUserId);
    if (filters.outcome) search.set("outcome", filters.outcome);
    if (filters.createdFrom) search.set("created_from", filters.createdFrom);
    if (filters.createdTo) search.set("created_to", filters.createdTo);
    return request<SecurityAuditEvent[]>(`/api/v1/admin/audit?${search}`);
  },
  fetchProtectedFile: (path: string) => requestBlob(path),
};

export function userFacingError(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message}（${error.code}）`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "发生未知错误，请稍后重试。";
}

export function resetApiClientForTests(): void {
  accessToken = null;
  refreshFlight = null;
  authFailureHandler = null;
}
