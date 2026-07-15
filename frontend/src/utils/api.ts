/** Shared fetch helpers — eliminates "Content-Type": "application/json" repetition. */

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T = unknown>(
  method: string,
  url: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  const data = await res.json();
  if (!res.ok || data.error) {
    throw new ApiError(data.error || `HTTP ${res.status}`, res.status, data);
  }
  return data as T;
}

export function apiGet<T = unknown>(url: string): Promise<T> {
  return request<T>('GET', url);
}

export function apiPost<T = unknown>(url: string, body?: unknown): Promise<T> {
  return request<T>('POST', url, body);
}

export function apiPut<T = unknown>(url: string, body?: unknown): Promise<T> {
  return request<T>('PUT', url, body);
}

export function apiDelete<T = unknown>(url: string): Promise<T> {
  return request<T>('DELETE', url);
}

/** Standardize error message for display to user. */
export function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return '网络错误：' + (e as Error).message;
}
