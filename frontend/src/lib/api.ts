const TOKEN_KEY = "pharmareg_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export interface ApiError {
  code: number;
  message: string;
  request_id?: string;
  extra?: Record<string, unknown>;
}

interface Envelope<T = unknown> {
  code: number;
  message: string;
  data: T;
}

export class ApiClientError extends Error {
  code: number;
  extra?: Record<string, unknown>;
  status: number;
  constructor(status: number, code: number, message: string, extra?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

async function request<T = unknown>(
  path: string,
  options: RequestInit & { idempotencyKey?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  if (options.body && typeof options.body === "string" && options.idempotencyKey === undefined) {
    // keep raw body
  }

  const resp = await fetch(`/api/v1${path}`, { ...options, headers });
  const payload = (await resp.json().catch(() => null)) as Envelope<T> | null;

  if (!resp.ok || !payload || payload.code !== 0) {
    const code = payload?.code ?? 5000;
    const message = payload?.message ?? "请求失败";
    if (resp.status === 401) {
      clearToken();
      window.location.href = "/login";
    }
    throw new ApiClientError(resp.status, code, message, (payload as ApiError)?.extra);
  }
  return payload.data as T;
}

export const api = {
  get: <T = unknown>(path: string) => request<T>(path, { method: "GET" }),
  post: <T = unknown>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
      idempotencyKey,
    }),
  put: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  delete: <T = unknown>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
