import { create } from "zustand";
import { UserInfo } from "@/lib/auth";

interface AuthState {
  user: UserInfo | null;
  loading: boolean;
  setUser: (user: UserInfo | null) => void;
  setLoading: (loading: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: true,
  setUser: (user) => set({ user }),
  setLoading: (loading) => set({ loading }),
}));

export function can(user: UserInfo | null, permission: string): boolean {
  if (!user) return false;
  return user.permissions.includes("*") || user.permissions.includes(permission);
}
