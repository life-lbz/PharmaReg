import { api, getToken, setToken, clearToken } from "./api";

export interface UserInfo {
  id: number;
  username: string;
  display_name: string;
  employee_no: string;
  department?: string | null;
  roles: string[];
  permissions: string[];
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export async function login(username: string, password: string): Promise<UserInfo> {
  const resp = await api.post<LoginResponse>("/sys/auth/login", { username, password });
  setToken(resp.access_token);
  return fetchMe();
}

export async function fetchMe(): Promise<UserInfo> {
  return api.get<UserInfo>("/sys/auth/me");
}

export async function logout(): Promise<void> {
  try {
    await api.post("/sys/auth/logout");
  } finally {
    clearToken();
  }
}

export function hasPermission(user: UserInfo | null, permission: string): boolean {
  if (!user) return false;
  return user.permissions.includes("*") || user.permissions.includes(permission);
}

export function isAuthenticated(): boolean {
  return Boolean(getToken());
}
