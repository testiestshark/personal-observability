// The steps behind `bun run local` and `bun run local:pull`. Everything here runs
// a command or touches the local stack; the decisions worth testing are the pure
// helpers in src/lib/local-dev/local-dev.ts.
//
// This is a script, not application code, which is why it may use the local
// service-role key to create the dev account. Nothing under src/ imports it.
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  isDevProcess,
  isLocalSupabaseUrl,
  isPlainEmail,
  listeningPid,
  parseEnvFile,
} from "../../src/lib/local-dev/local-dev";

// Must match project_id in supabase/config.toml: it is the Docker container suffix.
const PROJECT_ID = "personal_observability";
const DB_CONTAINER = `supabase_db_${PROJECT_ID}`;

// Committed on purpose. It only ever opens the database on this machine; the email
// it pairs with stays in the gitignored .env.local because this repo is public.
export const DEV_PASSWORD = "12345678";
export const PORT = 8080;

export class LocalError extends Error {}

export function say(message: string) {
  console.log(`\x1b[36m[local]\x1b[0m ${message}`);
}

export function warn(message: string) {
  console.warn(`\x1b[33m[local] ${message}\x1b[0m`);
}

type RunResult = { ok: boolean; stdout: string; stderr: string };

function run(
  command: string,
  args: string[],
  options: { cwd?: string; input?: string; show?: boolean } = {},
): RunResult {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    input: options.input,
    encoding: "utf8",
    maxBuffer: 256 * 1024 * 1024,
    stdio: options.show ? ["ignore", "inherit", "inherit"] : ["pipe", "pipe", "pipe"],
  });
  return {
    ok: result.status === 0,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? (result.error ? String(result.error) : ""),
  };
}

const lastLines = (text: string) => text.trim().split(/\r?\n/).slice(-3).join("\n");

const supabase = (args: string[], options: Parameters<typeof run>[2] = {}) =>
  run("bun", ["x", "supabase", ...args], options);

function psql(sql: string): RunResult {
  return run(
    "docker",
    ["exec", "-i", DB_CONTAINER, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-tA", "-1"],
    { input: sql },
  );
}

/** The primary checkout: the one worktree that holds .env.local and the hosted link. */
export function mainCheckout(): string {
  const result = run("git", ["worktree", "list", "--porcelain"]);
  const first = /^worktree (.+)$/m.exec(result.stdout)?.[1]?.trim();
  if (!result.ok || !first) throw new LocalError("Not inside a git checkout of this project.");
  return first;
}

export function currentBranch(): string {
  const branch = run("git", ["branch", "--show-current"]).stdout.trim();
  return branch || "detached HEAD";
}

export function ensureEnvFile(main: string) {
  if (existsSync(".env.local")) return;
  const source = join(main, ".env.local");
  if (!existsSync(source)) {
    throw new LocalError(
      `No .env.local here or in ${main}. Copy .env.example to .env.local there and fill it in.`,
    );
  }
  copyFileSync(source, ".env.local");
  say("Copied .env.local from the main checkout.");
}

export function ensureDependencies() {
  if (existsSync("node_modules")) return;
  say("Installing dependencies (first run in this worktree)...");
  if (!run("bun", ["install"], { show: true }).ok) throw new LocalError("bun install failed.");
}

export function devEmail(): string {
  const env = parseEnvFile(readFileSync(".env.local", "utf8"));
  const email = env["DEV_LOGIN_EMAIL"];
  // Interpolated into SQL below, so hold it to a plain address rather than escape it.
  if (!isPlainEmail(email)) {
    throw new LocalError(
      "Add DEV_LOGIN_EMAIL=<your email> to .env.local (in the main checkout too, so new worktrees inherit it).",
    );
  }
  return email;
}

function runningContainers(): string[] {
  const result = run("docker", ["ps", "--format", "{{.Names}}"]);
  if (!result.ok)
    throw new LocalError("Docker is not running. Start Docker Desktop and try again.");
  return result.stdout.split(/\r?\n/).filter(Boolean);
}

export function startSupabase() {
  if (runningContainers().includes(DB_CONTAINER)) return;
  say("Starting local Supabase...");
  if (!supabase(["start"], { show: true }).ok) throw new LocalError("supabase start failed.");
}

export function applyMigrations() {
  const result = supabase(["migration", "up", "--local"]);
  if (result.ok) return;
  // All worktrees share one database, so it often holds a migration from a branch
  // this worktree does not have. The CLI then refuses to apply anything. That must
  // not block looking at the app, but it does mean new migrations here were skipped.
  const detail = `${result.stdout}\n${result.stderr}`;
  if (/not found in local migrations directory/.test(detail)) {
    const versions = [...new Set(detail.match(/\b\d{14}\b/g) ?? [])].join(", ");
    warn(
      `The shared database has migrations from another branch (${versions}), so none of this worktree's own were applied. Fine unless this branch adds a migration.`,
    );
    return;
  }
  warn("Could not apply this worktree's migrations; continuing with the database as it is.");
  warn(lastLines(detail));
}

type LocalStack = { apiUrl: string; serviceRoleKey: string };

function localStack(): LocalStack {
  const result = supabase(["status", "-o", "env"]);
  const status = parseEnvFile(result.stdout);
  const apiUrl = status["API_URL"];
  const serviceRoleKey = status["SERVICE_ROLE_KEY"];
  if (!result.ok || !apiUrl || !serviceRoleKey) {
    throw new LocalError("Could not read the local Supabase status.");
  }
  // `supabase status` only ever describes the local stack; this guards against that
  // changing, because what follows creates and deletes accounts.
  if (!isLocalSupabaseUrl(apiUrl)) throw new LocalError(`Refusing: ${apiUrl} is not local.`);
  return { apiUrl, serviceRoleKey };
}

async function authAdmin(stack: LocalStack, method: string, path: string, body?: unknown) {
  const response = await fetch(`${stack.apiUrl}/auth/v1/admin/${path}`, {
    method,
    headers: {
      apikey: stack.serviceRoleKey,
      Authorization: `Bearer ${stack.serviceRoleKey}`,
      "Content-Type": "application/json",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    throw new LocalError(`Local auth ${method} ${path} failed: ${await response.text()}`);
  }
}

function localUserId(email: string): string | null {
  const result = psql(`select id from auth.users where email = '${email}';`);
  if (!result.ok) throw new LocalError(`Could not read local accounts: ${result.stderr.trim()}`);
  return result.stdout.trim() || null;
}

/**
 * Make sure the dev account exists with the known password. `id` pins the account
 * to the hosted user's id, so rows pulled from hosted already belong to it.
 */
export async function ensureDevAccount(email: string, id?: string) {
  const stack = localStack();
  const existing = localUserId(email);

  if (existing && (!id || existing === id)) {
    await authAdmin(stack, "PUT", `users/${existing}`, { password: DEV_PASSWORD });
    return;
  }
  if (existing) await authAdmin(stack, "DELETE", `users/${existing}`);

  await authAdmin(stack, "POST", "users", {
    ...(id ? { id } : {}),
    email,
    password: DEV_PASSWORD,
    email_confirm: true,
  });
  say(`Created the local dev account ${email}.`);
}

export function localDatabaseIsEmpty(): boolean {
  const result = psql(`
    select coalesce(sum((xpath('/row/n/text()',
      query_to_xml(format('select count(*) as n from %I.%I', schemaname, tablename), false, true, '')
    ))[1]::text::bigint), 0)
    from pg_tables where schemaname = 'public';`);
  if (!result.ok) throw new LocalError(`Could not count local rows: ${result.stderr.trim()}`);
  return result.stdout.trim() === "0";
}

function hostedFailure(action: string, result: RunResult): LocalError {
  const detail = `${result.stderr}\n${result.stdout}`;
  const hint = /403|401|unauthori[sz]ed|forbidden|access token|not logged in/i.test(detail)
    ? "The Supabase CLI is probably signed in to the wrong account. Run `bunx supabase projects list`: if this project is not listed, run `bunx supabase login` with the account that owns it, or set SUPABASE_ACCESS_TOKEN in .env.local."
    : /not linked|project ref/i.test(detail)
      ? "The main checkout is not linked to the hosted project. Run `bunx supabase link` there."
      : lastLines(detail);
  return new LocalError(`Could not ${action} from hosted Supabase.\n${hint}`);
}

/** Replace all local data with a copy of the hosted data. */
export async function pullHostedData(main: string, email: string) {
  // The hosted link (supabase/.temp) is gitignored and exists only in the main
  // checkout, so hosted commands run from there whichever worktree this is.
  const hosted = ["--workdir", main, "--linked"];

  say("Reading your account from hosted Supabase...");
  const lookup = supabase([
    "db",
    "query",
    ...hosted,
    "-o",
    "json",
    `select id from auth.users where email = '${email}'`,
  ]);
  if (!lookup.ok) throw hostedFailure("read your account", lookup);
  const hostedId = /"id":\s*"([0-9a-f-]{36})"/.exec(lookup.stdout)?.[1];
  if (!hostedId) throw new LocalError(`No hosted account found for ${email}.`);

  const folder = mkdtempSync(join(tmpdir(), "po-pull-"));
  try {
    const file = join(folder, "data.sql");
    say("Copying hosted data...");
    const dump = supabase([
      "db",
      "dump",
      ...hosted,
      "--data-only",
      "--schema",
      "public",
      "-f",
      file,
    ]);
    if (!dump.ok) throw hostedFailure("copy the data", dump);

    // One transaction (psql -1): if the copy does not fit the local schema, everything
    // rolls back and the existing local data survives. A local account under a
    // different id goes in the same transaction, because deleting it cascades to
    // every row it owns.
    const clear = `delete from auth.users where email = '${email}' and id <> '${hostedId}';
      do $$ declare t text; begin
      for t in select format('%I.%I', schemaname, tablename) from pg_tables where schemaname = 'public'
      loop execute 'truncate table ' || t || ' cascade'; end loop; end $$;`;
    const load = psql(`${clear}\n${readFileSync(file, "utf8")}`);
    if (!load.ok) {
      throw new LocalError(
        `The hosted data did not load, so local data is unchanged. Hosted may have a table this worktree's migrations lack.\n${lastLines(load.stderr)}`,
      );
    }

    // After the load, so the account is created under the hosted id the rows carry.
    await ensureDevAccount(email, hostedId);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
  say("Local data now matches hosted.");
}

const windows = process.platform === "win32";

function portOwner(): number | null {
  return windows
    ? listeningPid(run("netstat", ["-ano", "-p", "TCP"]).stdout, PORT)
    : Number(
        run("lsof", ["-ti", `tcp:${PORT}`, "-sTCP:LISTEN"])
          .stdout.trim()
          .split("\n")[0],
      ) || null;
}

/** Take port 8080 from an earlier dev server, so the phone address never changes. */
export function freePort() {
  const pid = portOwner();
  if (!pid) return;

  const name = windows
    ? (
        run("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"]).stdout.split(",")[0] ?? ""
      ).replace(/"/g, "")
    : run("ps", ["-p", String(pid), "-o", "comm="]).stdout;
  if (!isDevProcess(name)) {
    throw new LocalError(
      `Port ${PORT} is held by ${name.trim() || `process ${pid}`}, which is not a dev server. Close it and try again.`,
    );
  }

  say(`Taking over port ${PORT} from the dev server that was running (process ${pid}).`);
  if (windows) run("taskkill", ["/PID", String(pid), "/T", "/F"]);
  else run("kill", [String(pid)]);

  // Vite starts with --strictPort, so it must not race the old server's exit.
  for (let attempt = 0; attempt < 20 && portOwner(); attempt++) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
  }
}

/** Start Vite and call `onReady` once it is serving. Resolves when it exits. */
export function serve(env: Record<string, string>, onReady: () => void): Promise<number> {
  return new Promise((resolve) => {
    const child = spawn("bun", ["x", "vite", "dev", "--port", String(PORT), "--strictPort"], {
      env: { ...process.env, FORCE_COLOR: "1", ...env },
      stdio: ["inherit", "pipe", "inherit"],
    });

    let announced = false;
    child.stdout.on("data", (chunk: Buffer) => {
      process.stdout.write(chunk);
      if (announced || !/Local:|ready in/.test(chunk.toString())) return;
      announced = true;
      // Let Vite finish printing its own address list before the banner follows it.
      setTimeout(onReady, 400);
    });
    child.on("exit", (code) => resolve(code ?? 0));
  });
}
