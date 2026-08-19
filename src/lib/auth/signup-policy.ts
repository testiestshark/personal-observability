/**
 * Whether this app offers account creation.
 *
 * Public signup is closed: this is a single-user product and the owner account
 * already exists. It is *disabled, not deleted* — `signUp` in `auth.functions.ts`
 * and the create-account UI in `routes/login.tsx` are all still here, and setting
 * `VITE_ALLOW_SIGNUP=true` brings them back. Don't remove them as dead code.
 *
 * This governs only what this app offers. The authoritative block is Supabase's own
 * "Allow new users to sign up" setting on the hosted project — without that, someone
 * can still register by calling the Supabase auth API directly, never touching this
 * code. Both levers are meant to be on together.
 */

/**
 * Fail closed: only the exact string `true` enables signup. Anything else — unset,
 * empty, `1`, `yes`, a typo — means off.
 *
 * `VITE_*` variables are inlined at build time, so a build that never saw the flag
 * (a CI build, a fresh clone, a host with no env configured) must land on closed
 * rather than open registration.
 */
export function parseSignupFlag(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === "true";
}

export const SIGNUP_ENABLED = parseSignupFlag(import.meta.env["VITE_ALLOW_SIGNUP"]);

/** Shown when someone reaches signup anyway — a stale tab, or a direct POST. */
export const SIGNUP_CLOSED_MESSAGE = "Account creation is closed for this workspace.";
