import type { Valued } from "./valued";

/**
 * Thin fetch wrappers for the M1 search slice (docs/api.md §5, §7 — the
 * thin M1 subset issue #43 implements, not the full multi-origin/budget/SSE
 * resource). `credentials: "include"` on every call so the httpOnly session
 * cookie (docs/api.md §2) rides along automatically.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public problem: unknown
  ) {
    super(`API error ${status}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let problem: unknown;
    try {
      problem = await response.json();
    } catch {
      problem = { title: response.statusText };
    }
    throw new ApiError(response.status, problem);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface UserResponse {
  id: string;
  username: string;
  email: string;
  role: string;
  created_at: string;
}

export function login(body: LoginRequest): Promise<UserResponse> {
  return request<UserResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface SearchIn {
  origin: string;
  destination: string;
  depart_month: string;
}

export interface SearchResponse {
  id: string;
  state: "pending" | "running" | "ready" | "failed";
  origin: string;
  destination: string;
  depart_month: string;
  failure_reason: string | null;
  created_at: string;
  completed_at: string | null;
}

export function createSearch(body: SearchIn): Promise<SearchResponse> {
  return request<SearchResponse>("/api/v1/searches", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getSearch(id: string): Promise<SearchResponse> {
  return request<SearchResponse>(`/api/v1/searches/${id}`);
}

export interface Segment {
  origin: string;
  destination: string;
  departure_utc: string;
  arrival_utc: string | null;
  marketing_carrier: string;
  flight_number: string;
}

export interface ObservationResponse {
  itinerary_id: string;
  source: string;
  price: Valued<{ amount_minor: number; currency: string }>;
  freshness: string;
  confidence: string;
  retrieved_at: string;
  slices: { segments: Segment[] }[];
  limitations: string[];
}

export function getSearchResults(id: string): Promise<ObservationResponse[]> {
  return request<ObservationResponse[]>(`/api/v1/searches/${id}/results`);
}
