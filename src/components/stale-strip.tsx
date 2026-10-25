import { Link } from "@tanstack/react-router";
import { TriangleAlert } from "lucide-react";

/** Names the sources whose Worker has stopped. Renders nothing when all are healthy. */
export function StaleStrip({ sources }: { sources: string[] }) {
  if (sources.length === 0) return null;
  return (
    <Link
      to="/integrations"
      className="mb-5 flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
    >
      <TriangleAlert className="size-4 shrink-0" aria-hidden />
      <span>{sources.map((name) => `${name} sync stopped`).join(" · ")}</span>
    </Link>
  );
}
