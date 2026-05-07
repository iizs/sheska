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
  if (res.headers.get("content-type")?.includes("application/zip")) {
    return res.blob() as unknown as T;
  }
  return res.json();
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

export async function listJobs() {
  return request<any[]>("/jobs/");
}

export async function getJob(jobId: string) {
  return request<any>(`/jobs/${jobId}`);
}
