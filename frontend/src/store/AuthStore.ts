import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  role: "admin" | "company" | "user" | null;
  name: string | null;
  email: string | null;
  login: (
    token: string,
    role: "admin" | "company" | "user",
    name: string,
    email: string
  ) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      role: null,
      name: null,
      email: null,
      login: (token, role, name, email) =>
        set({
          token,
          role,
          name,
          email,
        }),
      logout: () =>
        set({
          token: null,
          role: null,
          name: null,
          email: null,
        }),
    }),
    {
      name: "recruito-auth",
    }
  )
);
