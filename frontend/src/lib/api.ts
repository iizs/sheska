const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("sheska_token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("sheska_token");
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    return res.json();
  }
  // application/zip, octet-stream, text/* 등 binary/non-json은 Blob으로 반환
  return res.blob() as unknown as T;
}

export function setToken(token: string) {
  localStorage.setItem("sheska_token", token);
}

export function clearToken() {
  localStorage.removeItem("sheska_token");
}

export async function login(email: string, password: string) {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  const data = await request<{ access_token: string }>("/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  setToken(data.access_token);
  return data;
}

export async function getMe() {
  return request<{ id: number; email: string; role: string }>("/users/me");
}

export async function listPages(): Promise<{ pages: string[] }> {
  return request("/wiki/pages");
}

export async function getPage(pagePath: string): Promise<{ page_path: string; content: string }> {
  return request(`/wiki/pages/${pagePath}`);
}

export async function requestEdit(pagePath: string, editText: string) {
  return request(`/wiki/pages/${pagePath}/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edit_text: editText }),
  });
}

export async function getIndex(): Promise<{ content: string }> {
  return request("/wiki/index");
}

export async function downloadZip(): Promise<Blob> {
  return request<Blob>("/wiki/zip");
}

export async function listSources(): Promise<{ filename: string; size: number }[]> {
  return request("/sources/");
}

export async function uploadSource(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request("/sources/", { method: "POST", body: form });
}

export async function listJobs(page = 1, size = 20) {
  return request<{ items: any[]; total: number; page: number; size: number }>(
    `/jobs/?page=${page}&size=${size}`
  );
}

export async function getJob(jobId: string) {
  return request<any>(`/jobs/${jobId}`);
}

export async function getAuthConfig() {
  return request<{ signup_enabled: boolean }>("/auth/config");
}

export async function signup(email: string, password: string) {
  const data = await request<{ access_token: string }>("/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
  return data;
}

export async function listUsers() {
  return request<any[]>("/users/");
}

export async function updateUserRole(userId: number, role: "admin" | "member") {
  return request(`/users/${userId}/role`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
}

export async function updateUserActive(userId: number, isActive: boolean) {
  return request(`/users/${userId}/active`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: isActive }),
  });
}

export async function downloadSource(filename: string): Promise<Blob> {
  return request<Blob>(`/sources/${encodeURIComponent(filename)}`);
}

export async function submitWikiCommand(commandText: string) {
  return request<{ job_id: string; status: string }>("/wiki/commands", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command_text: commandText }),
  });
}

export async function cancelJob(jobId: string) {
  return request<any>(`/jobs/${jobId}/cancel`, { method: "POST" });
}

export const LINT_CATEGORIES = [
  "user_reported",
  "dangling_link",
  "orphan_page",
  "frontmatter_missing",
  "stale",
  "duplicate",
  "quality_low",
  "split_candidate",
  "merge_candidate",
  "tag_inconsistency",
  "other",
] as const;

export type LintCategory = (typeof LINT_CATEGORIES)[number];
export type LintStatus = "open" | "acknowledged" | "wont_fix";
export type LintSource = "lint:tier1" | "lint:tier2" | "user:web" | "agent:explorer";

export interface LintFinding {
  finding_id: string;
  category: LintCategory;
  source: LintSource;
  status: LintStatus;
  page_path: string | null;
  description: string;
  details: Record<string, any> | null;
  created_at: string;
  reported_by: string;
  decided_by: string | null;
  decided_at: string | null;
  resolution_reason: string | null;
}

export async function listLintFindings(params: {
  status?: LintStatus;
  category?: LintCategory;
  source?: LintSource;
  page?: number;
  size?: number;
} = {}) {
  const q = new URLSearchParams();
  if (params.status) q.set("status", params.status);
  if (params.category) q.set("category", params.category);
  if (params.source) q.set("source", params.source);
  q.set("page", String(params.page ?? 1));
  q.set("size", String(params.size ?? 20));
  return request<{
    items: LintFinding[];
    total: number;
    page: number;
    size: number;
  }>(`/lint/findings?${q.toString()}`);
}

export async function createLintFinding(body: {
  page_path?: string | null;
  description: string;
  category?: LintCategory;
}) {
  return request<LintFinding>("/lint/findings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function decideLintFinding(
  findingId: string,
  status: "acknowledged" | "wont_fix",
  resolutionReason: string,
) {
  return request<LintFinding>(`/lint/findings/${findingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, resolution_reason: resolutionReason }),
  });
}
