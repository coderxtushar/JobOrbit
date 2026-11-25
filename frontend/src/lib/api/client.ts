/**
 * Fetch wrapper for the JobOrbit API, reached through the same-origin proxy at
 * /api/backend (see src/app/api/backend/[...path]/route.ts).
 *
 * Every failure becomes an {@link ApiError} carrying the backend's own error code and
 * message, so pages can show the real reason ("The emergency stop is on...") instead of a
 * generic "something went wrong".
 */
import type { components } from "@/types/api";

export type Schemas = components["schemas"];

const BASE = "/api/backend";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: Record<string, string>;

  constructor(message: string, status: number, code = "http_error", fieldErrors = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
  }

  get isUnreachable(): boolean {
    return this.code === "backend_unreachable" || this.status === 0;
  }
}

type Query = Record<string, string | number | boolean | null | undefined | string[]>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Query;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** Return the raw Response (for text reports and images). */
  raw?: boolean;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item));
    else params.set(key, String(value));
  }
  const search = params.toString();
  return `${BASE}${path}${search ? `?${search}` : ""}`;
}

async function toError(response: Response): Promise<ApiError> {
  let message = `HTTP ${response.status}`;
  let code = "http_error";
  let fieldErrors: Record<string, string> = {};
  try {
    const body = await response.json();
    const error = body?.error ?? {};
    if (error.message) message = error.message;
    if (error.code) code = error.code;
    if (error.field_errors) fieldErrors = error.field_errors;
    if (!error.message && Array.isArray(body?.detail)) {
      message = body.detail.map((item: { msg?: string }) => item.msg).join("; ");
    }
  } catch {
    /* not JSON */
  }
  return new ApiError(message, response.status, code, fieldErrors);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, form, signal, raw } = options;
  const headers: HeadersInit = { accept: "application/json" };
  let payload: BodyInit | undefined;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["content-type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: payload,
      signal,
      cache: "no-store",
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError("The JobOrbit dashboard server is not reachable.", 0, "backend_unreachable");
  }
  if (!response.ok) throw await toError(response);
  if (raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** URL for a resource the browser loads directly (an evidence image, a report download). */
export function backendUrl(path: string, query?: Query): string {
  return buildUrl(path, query);
}
