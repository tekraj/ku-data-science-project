export const API_BASE = "/api";

export async function apiRequest(path: string, options: RequestInit = {}) {
  const { headers, body } = options;
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(headers || {}),
    },
  });

  if (!response.ok) {
    const error = new Error(`Request failed: ${response.status}`) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json();
}
