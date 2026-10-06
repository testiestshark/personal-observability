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

export type LocalDevInfo = {
  /** Whether the one-tap dev sign-in will work. */
  devLogin: boolean;
  /** The branch `bun run local` is serving, for the on-screen badge. */
  branch: string | null;
};

async function readDevLogin() {
  // Statically false in a production build, so the bundler drops everything below
  // and no hosted deployment can perform a dev sign-in whatever its environment.
  if (!import.meta.env.DEV) return null;

  const { resolveDevLogin } = await import("./dev-login");
  return resolveDevLogin({
    supabaseUrl: process.env["SUPABASE_URL"] || import.meta.env["VITE_SUPABASE_URL"],
    email: process.env["DEV_LOGIN_EMAIL"],
    password: process.env["DEV_LOGIN_PASSWORD"],
  });
}

/** What `bun run local` set up for this server. All-off everywhere else. */
export const getLocalDevInfo = createServerFn({ method: "GET" }).handler(
  async (): Promise<LocalDevInfo> => {
    const devLogin = await readDevLogin();
    return {
      devLogin: devLogin !== null,
      branch: devLogin ? (process.env["LOCAL_DEV_BRANCH"] ?? null) : null,
    };
  },
);

/** Sign in as the local dev account, through the same call as the real form. */
export const signInAsDev = createServerFn({ method: "POST" }).handler(
  async (): Promise<{ error: string | null }> => {
    const devLogin = await readDevLogin();
    if (!devLogin) {
      const { DEV_LOGIN_UNAVAILABLE_MESSAGE } = await import("./dev-login");
      return { error: DEV_LOGIN_UNAVAILABLE_MESSAGE };
    }

    const { createSupabaseRequestClient } = await import("./supabase-request.server");
    const supabase = createSupabaseRequestClient();
    const { error } = await supabase.auth.signInWithPassword(devLogin);

    return { error: error ? error.message : null };
  },
);

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
