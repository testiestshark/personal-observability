import { resolveDevLogin } from "./dev-login";

const local = {
  supabaseUrl: "http://127.0.0.1:54321",
  email: "me@example.com",
  password: "12345678",
};

describe("resolveDevLogin", () => {
  it("offers the dev sign-in when `bun run local` supplied credentials for local Supabase", () => {
    expect(resolveDevLogin(local)).toEqual({ email: "me@example.com", password: "12345678" });
  });

  it("refuses against hosted Supabase even with credentials present, so the Lovable preview never shows it", () => {
    expect(
      resolveDevLogin({ ...local, supabaseUrl: "https://ivdhucdiycnbgvdetagw.supabase.co" }),
    ).toBeNull();
  });

  it("refuses when either credential is missing, which is every run not started by `bun run local`", () => {
    expect(resolveDevLogin({ ...local, email: undefined })).toBeNull();
    expect(resolveDevLogin({ ...local, password: "" })).toBeNull();
    expect(resolveDevLogin({ ...local, supabaseUrl: undefined })).toBeNull();
  });
});
