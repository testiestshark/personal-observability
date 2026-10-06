// Pure helpers behind `bun run local` (scripts/local.ts). They live under src/ so
// they are typechecked and tested with everything else; the scripts themselves
// only run commands and are not worth unit testing.

type NetworkAddress = { address: string; family: string | number; internal: boolean };

// Hyper-V, WSL and Docker create adapters with private addresses of their own.
// They are reachable from this machine only, so a phone given one gets nowhere.
const VIRTUAL_ADAPTER = /vethernet|wsl|docker|virtualbox|vmware|hyper-v|loopback/i;

/** The address a phone on the same Wi-Fi should use, or null when there is none. */
export function pickLanAddress(
  interfaces: Record<string, NetworkAddress[] | undefined>,
): string | null {
  const candidates: { address: string; virtual: boolean }[] = [];

  for (const [name, addresses] of Object.entries(interfaces)) {
    for (const entry of addresses ?? []) {
      const isIPv4 = entry.family === "IPv4" || entry.family === 4;
      if (!isIPv4 || entry.internal || entry.address.startsWith("169.254.")) continue;
      candidates.push({ address: entry.address, virtual: VIRTUAL_ADAPTER.test(name) });
    }
  }

  return (candidates.find((c) => !c.virtual) ?? candidates[0])?.address ?? null;
}

// Container names are `supabase_<service>_<project_id>`, and both halves may contain
// underscores, so the service has to be matched against the known list.
const SUPABASE_SERVICES = [
  "edge_runtime",
  "pg_meta",
  "analytics",
  "imgproxy",
  "inbucket",
  "realtime",
  "storage",
  "studio",
  "pooler",
  "vector",
  "auth",
  "kong",
  "rest",
  "db",
];

/** Project ids of other local Supabase stacks among the running containers. */
export function otherSupabaseProjects(containerNames: string[], ownProjectId: string): string[] {
  const projects = new Set<string>();

  for (const name of containerNames) {
    const service = SUPABASE_SERVICES.find((s) => name.startsWith(`supabase_${s}_`));
    if (!service) continue;
    const project = name.slice(`supabase_${service}_`.length);
    if (project && project !== ownProjectId) projects.add(project);
  }

  return [...projects];
}

export function parseEnvFile(text: string): Record<string, string> {
  const values: Record<string, string> = {};

  for (const line of text.split(/\r?\n/)) {
    const match = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
    if (!match) continue;
    const [, key, raw] = match as unknown as [string, string, string];
    values[key] = raw.replace(/^(["'])(.*)\1$/, "$2");
  }

  return values;
}

/** True only for a Supabase API on this machine — never for the hosted project. */
export function isLocalSupabaseUrl(url: string | undefined): boolean {
  if (!url) return false;
  try {
    const { hostname } = new URL(url);
    return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
  } catch {
    return false;
  }
}

/** PID listening on a TCP port, read from Windows `netstat -ano -p TCP` output. */
export function listeningPid(netstatOutput: string, port: number): number | null {
  for (const line of netstatOutput.split(/\r?\n/)) {
    const [proto, local, , state, pid] = line.trim().split(/\s+/);
    if (proto !== "TCP" || state !== "LISTENING" || !local?.endsWith(`:${port}`)) continue;
    const parsed = Number(pid);
    if (Number.isInteger(parsed) && parsed > 0) return parsed;
  }
  return null;
}

/** Whether a process name is a runtime a dev server runs under, and so safe to replace. */
export function isDevProcess(processName: string): boolean {
  const base = processName.trim().split(/[\\/]/).pop() ?? "";
  return /^(node|bun)(\.exe)?$/i.test(base);
}

export function renderBanner(input: {
  port: number;
  lanAddress: string | null;
  branch: string;
  qr: string | null;
}): string {
  const rule = "=".repeat(60);
  const lines = ["", rule, "", `  Serving ${input.branch}`, ""];

  lines.push(`  This computer   http://localhost:${input.port}`);
  if (input.lanAddress) {
    lines.push(`  PHONE           http://${input.lanAddress}:${input.port}`);
    lines.push("", '  Same Wi-Fi only. Tap "Sign in as dev" on the login page.');
    if (input.qr) lines.push("", input.qr);
    lines.push("  Phone can't connect? See docs/LOCAL_DEV.md (one-time firewall step).");
  } else {
    lines.push("", "  No Wi-Fi address found, so there is nothing to open on a phone.");
  }

  lines.push("", rule, "");
  return lines.join("\n");
}
