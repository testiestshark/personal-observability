// Server functions for authentication. This module ships RPC stubs to the client
// bundle, so the server-only Supabase client is imported dynamically inside each
// handler rather than at the top level.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

import { SIGNUP_CLOSED_MESSAGE, SIGNUP_ENABLED } from "./signup-policy";

export type AuthUser = {
  id: string;
  email: string | null;
};

const credentialsSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(8, "Password must be at least 8 characters."),
});

export type Credentials = z.infer<typeof credentialsSchema>;

/** Resolve the signed-in user, or null. Safe to call on every render. */
export const getCurrentUser = createServerFn({ method: "GET" }).handler(
  async (): Promise<AuthUser | null> => {
    const { createSupabaseRequestClient } = await import("./supabase-request.server");
    const supabase = createSupabaseRequestClient();

    // getUser() revalidates the token with the auth server, unlike getSession()
    // which trusts whatever the cookie says.
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user) return null;

    return { id: data.user.id, email: data.user.email ?? null };
  },
);

export const signIn = createServerFn({ method: "POST" })
  .validator((data: Credentials) => credentialsSchema.parse(data))
  .handler(async ({ data }): Promise<{ error: string | null }> => {
    const { createSupabaseRequestClient } = await import("./supabase-request.server");
    const supabase = createSupabaseRequestClient();

    const { error } = await supabase.auth.signInWithPassword({
      email: data.email,
      password: data.password,
    });

    return { error: error ? error.message : null };
  });

export const signUp = createServerFn({ method: "POST" })
  .validator((data: Credentials) => credentialsSchema.parse(data))
  .handler(async ({ data }): Promise<{ error: string | null; needsEmailConfirmation: boolean }> => {
    // Refuse before touching Supabase. Hiding the UI alone would not close signup:
    // this handler is a POST endpoint that anyone can call directly.
    if (!SIGNUP_ENABLED) {
      return { error: SIGNUP_CLOSED_MESSAGE, needsEmailConfirmation: false };
    }

    const { createSupabaseRequestClient } = await import("./supabase-request.server");
    const supabase = createSupabaseRequestClient();

    const { data: result, error } = await supabase.auth.signUp({
      email: data.email,
      password: data.password,
    });

    if (error) return { error: error.message, needsEmailConfirmation: false };

    // With email confirmations on, signUp succeeds but returns no session —
    // the account is not usable until the emailed link is followed.
    return { error: null, needsEmailConfirmation: result.session === null };
  });

export const signOut = createServerFn({ method: "POST" }).handler(async (): Promise<void> => {
  const { createSupabaseRequestClient } = await import("./supabase-request.server");
  const supabase = createSupabaseRequestClient();
  await supabase.auth.signOut();
});
