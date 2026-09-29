// PROTOTYPE — throwaway. Not production code. Lives on branch prototype/hevy-api only.
//
// Question it answers (issue #21): how does the real Hevy public API behave?
//   1. Does a new workout show up as an `updated` event?
//   2. Which timestamp does `since` compare against, and is it > or >=?
//   3. Does `set.index` count within an exercise or across the whole workout?
//   4. Rate limits (any 429s / rate-limit headers under a modest burst?)
//   5. Is there a public webhook-subscription route (read-only check)?
//
// Run from this worktree, loading the key from the main checkout's .env.local:
//   bun --env-file=../personal-observability/.env.local scripts/hevy/PROTOTYPE_probe.ts <command>
//
// Commands:
//   info                   who the key belongs to, workout count
//   snapshot               record every event since 1970 into .hevy-probe/ (the baseline)
//   diff                   events now vs the last snapshot: what appeared / changed / vanished
//   sets [workoutId]       exercise.index and set.index for one workout (default: newest)
//   since                  probe the `since` boundary around the newest event's timestamps
//   burst [n]              n sequential GETs (default 30), report statuses + rate headers
//   webhook                GET /v1/webhook-subscription (read only)
//
// GET only. The key is never printed. Data files go to .hevy-probe/ (gitignored, wipe me).

import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";

const BASE = "https://api.hevyapp.com";
const KEY = process.env.HEVY_API_KEY;
const OUT = ".hevy-probe";

if (!KEY) {
  console.error("HEVY_API_KEY is not set. Add it to .env.local and pass --env-file.");
  process.exit(1);
}

type Json = any; // prototype

async function get(path: string, params: Record<string, string | number> = {}) {
  const url = new URL(path, BASE);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  const res = await fetch(url, { method: "GET", headers: { "api-key": KEY! } });
  const text = await res.text();
  let body: Json = text;
  try {
    body = JSON.parse(text);
  } catch {}
  return { status: res.status, headers: res.headers, body, url: url.pathname + url.search };
}

async function ok(path: string, params: Record<string, string | number> = {}) {
  const r = await get(path, params);
  if (r.status !== 200) {
    console.error(`${r.status} ${r.url}`, typeof r.body === "string" ? r.body : JSON.stringify(r.body));
    process.exit(1);
  }
  return r.body;
}

async function allEvents(since = "1970-01-01T00:00:00Z") {
  const events: Json[] = [];
  let page = 1;
  let pageCount = 1;
  do {
    const b = await ok("/v1/workouts/events", { since, page, pageSize: 10 });
    pageCount = b.page_count ?? 1;
    events.push(...(b.events ?? []));
    page++;
  } while (page <= pageCount);
  return events;
}

function summarise(e: Json) {
  if (e.type === "deleted") return { type: e.type, id: e.id, deleted_at: e.deleted_at ?? "(none)" };
  const w = e.workout ?? {};
  return {
    type: e.type,
    id: w.id,
    title: w.title,
    created_at: w.created_at,
    updated_at: w.updated_at,
    start_time: w.start_time,
  };
}

const eventId = (e: Json) => (e.type === "deleted" ? e.id : e.workout?.id);

function latestSnapshot(): Json | null {
  if (!existsSync(OUT)) return null;
  const files = readdirSync(OUT).filter((f) => f.startsWith("PROTOTYPE-snapshot-")).sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  return { file: f, ...JSON.parse(readFileSync(`${OUT}/${f}`, "utf8")) };
}

const commands: Record<string, (args: string[]) => Promise<void>> = {
  async info() {
    const user = await ok("/v1/user/info");
    const count = await ok("/v1/workouts/count");
    console.table({ hevy_user_id: user.data?.id, name: user.data?.name, workout_count: count.workout_count });
  },

  async snapshot() {
    const takenAt = new Date().toISOString();
    const events = await allEvents();
    mkdirSync(OUT, { recursive: true });
    const file = `${OUT}/PROTOTYPE-snapshot-${takenAt.replace(/[:.]/g, "-")}.json`;
    writeFileSync(file, JSON.stringify({ takenAt, events }, null, 2));
    const types = events.reduce((a: Record<string, number>, e) => ((a[e.type] = (a[e.type] ?? 0) + 1), a), {});
    console.log(`Saved ${events.length} events to ${file}`);
    console.table(types);
    const ids = events.map(eventId);
    console.log(`Distinct workout ids: ${new Set(ids).size} (events: ${ids.length}) — equal means one event per workout`);
    console.log("Newest 5:");
    console.table(events.slice(0, 5).map(summarise));
  },

  async diff() {
    const prev = latestSnapshot();
    if (!prev) return console.log("No snapshot yet. Run `snapshot` first.");
    const now = await allEvents();
    const key = (e: Json) => `${e.type}:${eventId(e)}:${e.workout?.updated_at ?? e.deleted_at ?? ""}`;
    const before = new Set(prev.events.map(key));
    const after = new Set(now.map(key));
    console.log(`Comparing against ${prev.file} (taken ${prev.takenAt})`);
    console.log("\nNEW or CHANGED events since snapshot:");
    console.table(now.filter((e) => !before.has(key(e))).map(summarise));
    console.log("\nEvents in snapshot that are GONE now (replaced or expired):");
    console.table(prev.events.filter((e: Json) => !after.has(key(e))).map(summarise));
    console.log("\nIncremental check — events?since=<snapshot takenAt>:");
    console.table((await allEvents(prev.takenAt)).map(summarise));
  },

  async sets([id]) {
    let w: Json;
    if (id) w = await ok(`/v1/workouts/${id}`);
    else w = (await ok("/v1/workouts", { page: 1, pageSize: 1 })).workouts?.[0];
    if (!w) return console.log("No workouts found.");
    console.log(`${w.title} (${w.id}) ${w.start_time}`);
    const rows = (w.exercises ?? []).flatMap((ex: Json) =>
      (ex.sets ?? []).map((s: Json) => ({
        "exercise.index": ex.index,
        exercise: ex.title,
        superset_id: ex.superset_id,
        "set.index": s.index,
        type: s.type,
        weight_kg: s.weight_kg,
        reps: s.reps,
        rpe: s.rpe,
      })),
    );
    console.table(rows);
    const restarts = (w.exercises ?? []).every((ex: Json) => ex.sets?.[0]?.index === 0 || ex.sets?.[0]?.index === 1);
    console.log(
      (w.exercises?.length ?? 0) < 2
        ? "Need a workout with 2+ exercises to tell."
        : restarts
          ? "VERDICT: set.index restarts per exercise."
          : "VERDICT: set.index runs across the whole workout.",
    );
  },

  async since() {
    const events = await allEvents();
    const newest = events.find((e) => e.type === "updated");
    if (!newest) return console.log("No updated events to probe.");
    const w = newest.workout;
    console.log(`Probing with workout ${w.id} "${w.title}"`);
    console.table({ created_at: w.created_at, updated_at: w.updated_at, start_time: w.start_time });
    const shift = (iso: string, ms: number) => new Date(new Date(iso).getTime() + ms).toISOString();
    const probes: Record<string, string> = {
      "updated_at - 1s": shift(w.updated_at, -1000),
      "updated_at exact": w.updated_at,
      "updated_at + 1s": shift(w.updated_at, 1000),
    };
    if (w.created_at !== w.updated_at) {
      probes["created_at exact"] = w.created_at;
      probes["between created and updated"] = shift(w.created_at, 1000);
    }
    const rows = [];
    for (const [label, since] of Object.entries(probes)) {
      const found = (await allEvents(since)).some((e) => eventId(e) === w.id);
      rows.push({ label, since, workout_returned: found });
    }
    console.table(rows);
    console.log(
      "Read: returned at 'exact' ⇒ >=; not at exact but at -1s ⇒ >. If it still appears 'between created and updated' ⇒ compared to updated_at.",
    );
    if (w.created_at === w.updated_at)
      console.log("Tip: edit this workout in the app (e.g. its note), then rerun to separate created_at from updated_at.");
  },

  async burst([n = "30"]) {
    const rows = [];
    for (let i = 0; i < Number(n); i++) {
      const t = performance.now();
      const r = await get("/v1/workouts/count");
      const rate = [...r.headers.entries()].filter(([h]) => /rate|limit|retry/i.test(h));
      rows.push({ i, status: r.status, ms: Math.round(performance.now() - t), headers: JSON.stringify(Object.fromEntries(rate)) });
      if (r.status === 429) break;
    }
    console.table(rows);
  },

  async webhook() {
    const r = await get("/v1/webhook-subscription");
    const redact = (k: string, v: unknown) => (/token|auth|secret/i.test(k) && v ? "<redacted>" : v);
    console.log(r.status, typeof r.body === "string" ? r.body : JSON.stringify(r.body, redact, 2));
  },
};

const [cmd = "", ...args] = process.argv.slice(2);
if (!commands[cmd]) {
  console.log(`Commands: ${Object.keys(commands).join(", ")}`);
  process.exit(cmd ? 1 : 0);
}
await commands[cmd](args);
