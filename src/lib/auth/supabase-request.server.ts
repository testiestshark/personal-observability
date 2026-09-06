// Server-only. Request-scoped Supabase client whose auth session lives in cookies
// rather than localStorage, so SSR loaders and top-level browser navigations
// (e.g. an OAuth/App-installation callback) can both see who the user is.
//
// The generated client in @/integrations/supabase/client.ts stores its session in
// localStorage, which is invisible to the server. That client is unused by app
// code; this module is the one auth actually runs on.
import { createServerClient } from "@supabase/ssr";
import { getCookies, setCookie, setResponseHeader } from "@tanstack/react-start/server";

import type { Database } from "@/integrations/supabase/types";

// Duplicated from the generated client.ts, which exports no reusable helper and
// must not be edited by hand. New-style Supabase API keys (sb_publishable_ /
// sb_secret_) are opaque strings rather than JWTs, so supabase-js sending them as
// `Authorization: Bearer <key>` is rejected — the key belongs in `apikey` instead.
// A real user JWT never equals the API key, so this only strips the default.
function isNewSupabaseApiKey(value: string): boolean {
  return value.startsWith("sb_publishable_") || value.startsWith("sb_secret_");
}

function createSupabaseFetch(supabaseKey: string): typeof fetch {
  return (input, init) => {
    const headers = new Headers(
      typeof Request !== "undefined" && input instanceof Request ? input.headers : undefined,
    );

    if (init?.headers) {
      new Headers(init.headers).forEach((value, key) => headers.set(key, value));
    }

    if (
      isNewSupabaseApiKey(supabaseKey) &&
      headers.get("Authorization") === `Bearer ${supabaseKey}`
    ) {
      headers.delete("Authorization");
    }

    headers.set("apikey", supabaseKey);
    return fetch(input, { ...init, headers });
  };
}

/**
 * Build a Supabase client bound to the current request's cookies.
 *
 * Must be called once per request — never cached in a module-level variable, or
 * one visitor's session would leak into another's render.
 */
export function createSupabaseRequestClient() {
  // Lovable's published runtime exposes the unprefixed names, while editor
  // previews may only have the committed VITE_* public values available at
  // build time. These values are intentionally public; secrets must never use
  // this fallback.
  const SUPABASE_URL = process.env["SUPABASE_URL"] || import.meta.env["VITE_SUPABASE_URL"];
  const SUPABASE_PUBLISHABLE_KEY =
    process.env["SUPABASE_PUBLISHABLE_KEY"] || import.meta.env["VITE_SUPABASE_PUBLISHABLE_KEY"];

  if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) {
    const missing = [
      ...(!SUPABASE_URL ? ["SUPABASE_URL/VITE_SUPABASE_URL"] : []),
      ...(!SUPABASE_PUBLISHABLE_KEY
        ? ["SUPABASE_PUBLISHABLE_KEY/VITE_SUPABASE_PUBLISHABLE_KEY"]
        : []),
    ];
    throw new Error(`Missing Supabase environment variable(s): ${missing.join(", ")}.`);
  }

  return createServerClient<Database>(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
    global: { fetch: createSupabaseFetch(SUPABASE_PUBLISHABLE_KEY) },
    cookies: {
      getAll() {
        return Object.entries(getCookies()).map(([name, value]) => ({ name, value }));
      },
      setAll(cookiesToSet, headers) {
        for (const { name, value, options } of cookiesToSet) {
          setCookie(name, value, options);
        }
        // Supabase asks us to mark responses that set auth cookies as uncacheable,
        // so a CDN can never serve one user's session token to somebody else.
        for (const [name, value] of Object.entries(headers)) {
          setResponseHeader(name as Parameters<typeof setResponseHeader>[0], value);
        }
      },
    },
  });
}
