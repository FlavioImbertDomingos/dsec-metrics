import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, type Me, type Meta, setCsrfToken } from "@/api/client";

export const meKey = ["me"] as const;

/** The signed-in user, or null when there is no session. */
export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: async (): Promise<Me | null> => {
      try {
        const me = await api<Me>("/api/me");
        setCsrfToken(me.csrf_token);
        return me;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setCsrfToken(null);
          return null;
        }
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}

export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/meta"),
    staleTime: Infinity,
  });
}

export function useSignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { username: string; password: string }) =>
      api<Me>("/api/auth/login", { method: "POST", body: credentials }),
    onSuccess: (me) => {
      setCsrfToken(me.csrf_token);
      queryClient.setQueryData(meKey, me);
    },
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api<undefined>("/api/auth/logout", { method: "POST" }),
    onSettled: () => {
      setCsrfToken(null);
      queryClient.setQueryData(meKey, null);
    },
  });
}
