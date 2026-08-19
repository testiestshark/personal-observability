import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { signIn, signUp } from "@/lib/auth/auth.functions";
import { SIGNUP_ENABLED } from "@/lib/auth/signup-policy";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Sign in — Personal Observability" },
      { name: "description", content: "Sign in to your private observability workspace." },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: LoginPage,
});

type Mode = "signin" | "signup";

function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setNotice(null);

    try {
      if (mode === "signin") {
        const result = await signIn({ data: { email, password } });
        if (result.error) {
          setError(result.error);
          return;
        }
      } else {
        const result = await signUp({ data: { email, password } });
        if (result.error) {
          setError(result.error);
          return;
        }
        if (result.needsEmailConfirmation) {
          setNotice("Check your email to confirm the account, then sign in.");
          setMode("signin");
          return;
        }
      }

      // Re-run loaders so the root context picks up the new session cookie.
      await router.invalidate();
      await router.navigate({ to: "/" });
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-background px-5 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <p className="font-display text-lg leading-tight text-foreground">
            Personal
            <br />
            Observability
          </p>
          <p className="mt-2 text-xs text-muted-foreground">Private workspace</p>
        </div>

        <h1 className="font-display text-2xl leading-tight text-foreground">
          {mode === "signin" ? "Sign in" : "Create your account"}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {mode === "signin"
            ? "This workspace is private to you."
            : "Set up the single account for this workspace."}
        </p>

        <form onSubmit={handleSubmit} className="mt-7 grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={pending}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={pending}
            />
            {mode === "signup" ? (
              <p className="text-xs text-muted-foreground">At least 8 characters.</p>
            ) : null}
          </div>

          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          {notice ? (
            <p role="status" className="text-sm text-muted-foreground">
              {notice}
            </p>
          ) : null}

          <Button type="submit" disabled={pending} className="mt-1 w-full">
            {pending ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
          </Button>
        </form>

        {/*
          Signup is closed, not removed — see lib/auth/signup-policy.ts. With the flag
          off there is no way to reach "signup" mode, so the branches above render only
          their sign-in side; they stay because VITE_ALLOW_SIGNUP=true restores the
          whole flow. Don't simplify them away as unreachable.
        */}
        {SIGNUP_ENABLED ? (
          <p className="mt-6 text-sm text-muted-foreground">
            {mode === "signin" ? "No account yet?" : "Already have an account?"}{" "}
            <button
              type="button"
              className="text-foreground underline underline-offset-4 hover:no-underline"
              onClick={() => {
                setMode(mode === "signin" ? "signup" : "signin");
                setError(null);
                setNotice(null);
              }}
            >
              {mode === "signin" ? "Create one" : "Sign in"}
            </button>
          </p>
        ) : null}
      </div>
    </div>
  );
}
