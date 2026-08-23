const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const TOKEN_STORAGE_KEY = "industrial_copilot_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface FastApiValidationError {
  loc?: unknown[];
  msg?: string;
}

/** FastAPI's `detail` is either a plain string (most of this app's own
 * HTTPException raises) or, for a 422 from Pydantic's own request
 * validation, an array of {loc, msg, ...} objects — dumping that array
 * through JSON.stringify is what produced raw, unreadable JSON in the UI
 * (e.g. registering with a username containing a space). Extracts a
 * human-readable message for either shape. */
function extractErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = (detail as FastApiValidationError[])
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : undefined;
        return field && e.msg ? `${field}: ${e.msg}` : e.msg;
      })
      .filter((m): m is string => Boolean(m));
    return messages.length ? messages.join("; ") : null;
  }
  return detail ? JSON.stringify(detail) : null;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  isFormData?: boolean;
  params?: Record<string, string | number | boolean | undefined>;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(API_BASE_URL + path);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, isFormData = false, params } = options;
  const headers: Record<string, string> = {};

  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let requestBody: BodyInit | undefined;
  if (body !== undefined) {
    if (isFormData) {
      requestBody = body as FormData;
    } else {
      headers["Content-Type"] = "application/json";
      requestBody = JSON.stringify(body);
    }
  }

  const response = await fetch(buildUrl(path, params), {
    method,
    headers,
    body: requestBody,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = extractErrorDetail(data.detail) ?? detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}
