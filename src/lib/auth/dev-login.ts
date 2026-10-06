// The one-tap "Sign in as dev" used by `bun run local`. See docs/LOCAL_DEV.md.
//
// Two conditions, both checked on the server: the app must be talking to a Supabase
// on this machine, and scripts/local.ts must have passed credentials in the
// environment. `import.meta.env.DEV` alone is not enough, because the Lovable
// preview also runs `vite dev` — against hosted Supabase.
import { isLocalSupabaseUrl } from "@/lib/local-dev/local-dev";

export type DevLogin = { email: string; password: string };

export const DEV_LOGIN_UNAVAILABLE_MESSAGE =
  "Dev sign-in is only available from `bun run local` against local Supabase.";

export function resolveDevLogin(input: {
  supabaseUrl: string | undefined;
  email: string | undefined;
  password: string | undefined;
}): DevLogin | null {
  if (!isLocalSupabaseUrl(input.supabaseUrl)) return null;
  if (!input.email || !input.password) return null;
  return { email: input.email, password: input.password };
}
