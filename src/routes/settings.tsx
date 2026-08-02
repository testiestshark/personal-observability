import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useState } from "react";

import { PageHeader, Placeholder, PlaceholderRow } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { signOut } from "@/lib/auth/auth.functions";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Personal Observability" },
      {
        name: "description",
        content: "Preferences, privacy choices and data handling for your personal workspace.",
      },
      { property: "og:title", content: "Settings — Personal Observability" },
      {
        property: "og:description",
        content: "Preferences, privacy choices and data handling for your workspace.",
      },
    ],
  }),
  component: Settings,
});

function Settings() {
  const router = useRouter();
  const { user } = Route.useRouteContext();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      await router.invalidate();
      await router.navigate({ to: "/login" });
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Settings"
        title="How this behaves"
        subtitle="Nothing is configurable yet — placeholders only."
      />

      <div className="grid gap-4">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Account</h2>
          <div className="mt-2">
            <PlaceholderRow label="Signed in as" value={user?.email ?? "—"} />
          </div>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={handleSignOut}
            disabled={signingOut}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </Button>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Preferences</h2>
          <div className="mt-2">
            <PlaceholderRow label="Display name" value="—" />
            <PlaceholderRow label="Time zone" value="—" />
            <PlaceholderRow label="Week starts on" value="—" />
            <PlaceholderRow label="Units" value="—" />
          </div>
        </section>

        <Placeholder label="Privacy" note="This workspace is private by design." height="h-20" />
        <Placeholder label="Data export" note="Download or delete everything." height="h-20" />
      </div>
    </>
  );
}
