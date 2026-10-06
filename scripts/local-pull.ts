// `bun run local:pull` — replace all local data with a copy of the hosted data.
// See docs/LOCAL_DEV.md.
import {
  LocalError,
  devEmail,
  ensureEnvFile,
  mainCheckout,
  pullHostedData,
  startSupabase,
} from "./local/steps";

async function main() {
  const checkout = mainCheckout();
  ensureEnvFile(checkout);
  startSupabase();
  await pullHostedData(checkout, devEmail());
}

main().catch((error: unknown) => {
  if (!(error instanceof LocalError)) throw error;
  console.error(`\x1b[31m[local] ${error.message}\x1b[0m`);
  process.exit(1);
});
