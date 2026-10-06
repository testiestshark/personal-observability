/**
 * Names the branch `bun run local` is serving. Port 8080 always shows the most
 * recently started worktree, so without this a phone gives no clue which one.
 */
export function DevBadge({ branch }: { branch: string }) {
  return (
    <p
      aria-label={`Local build of ${branch}`}
      className="pointer-events-none fixed top-2 right-2 z-50 max-w-[70vw] truncate rounded-full border border-border bg-card/90 px-2.5 py-1 text-[11px] text-muted-foreground backdrop-blur"
    >
      local · {branch}
    </p>
  );
}
