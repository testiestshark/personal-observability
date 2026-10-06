// `bun run local` — one command to see this worktree on this computer and a phone.
// What it does and why is in docs/LOCAL_DEV.md.
import { networkInterfaces } from "node:os";

import { pickLanAddress, renderBanner } from "../src/lib/local-dev/local-dev";
import {
  DEV_PASSWORD,
  LocalError,
  PORT,
  applyMigrations,
  currentBranch,
  devEmail,
  ensureDependencies,
  ensureDevAccount,
  ensureEnvFile,
  freePort,
  localDatabaseIsEmpty,
  mainCheckout,
  pullHostedData,
  say,
  serve,
  startSupabase,
  warn,
} from "./local/steps";

async function main() {
  const checkout = mainCheckout();
  ensureEnvFile(checkout);
  ensureDependencies();
  const email = devEmail();

  startSupabase();
  applyMigrations();

  if (localDatabaseIsEmpty()) {
    say("The local database is empty, so pulling a copy from hosted.");
    try {
      await pullHostedData(checkout, email);
    } catch (error) {
      if (!(error instanceof LocalError)) throw error;
      warn(
        `${error.message}\nStarting anyway with an empty database. Retry with: bun run local:pull`,
      );
    }
  }
  await ensureDevAccount(email);

  freePort();
  const branch = currentBranch();
  const lanAddress = pickLanAddress(networkInterfaces());

  // Imported here, not at the top: on a fresh worktree the package only exists once
  // ensureDependencies has run.
  const { default: qrcode } = await import("qrcode-terminal");

  const code = await serve(
    { DEV_LOGIN_EMAIL: email, DEV_LOGIN_PASSWORD: DEV_PASSWORD, LOCAL_DEV_BRANCH: branch },
    () => {
      const print = (qr: string | null) =>
        console.log(renderBanner({ port: PORT, lanAddress, branch, qr }));
      if (lanAddress) qrcode.generate(`http://${lanAddress}:${PORT}`, { small: true }, print);
      else print(null);
    },
  );
  process.exit(code);
}

main().catch((error: unknown) => {
  if (!(error instanceof LocalError)) throw error;
  console.error(`\x1b[31m[local] ${error.message}\x1b[0m`);
  process.exit(1);
});
