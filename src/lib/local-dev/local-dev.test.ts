import {
  isDevProcess,
  isLocalSupabaseUrl,
  listeningPid,
  otherSupabaseProjects,
  parseEnvFile,
  pickLanAddress,
  renderBanner,
} from "./local-dev";

describe("pickLanAddress", () => {
  const address = (value: string, internal = false) => ({
    address: value,
    family: "IPv4" as const,
    internal,
  });

  it("picks the home Wi-Fi address over loopback", () => {
    expect(
      pickLanAddress({
        "Loopback Pseudo-Interface 1": [address("127.0.0.1", true)],
        WiFi: [address("192.168.55.137")],
      }),
    ).toBe("192.168.55.137");
  });

  it("prefers a real adapter over Docker and WSL virtual switches, which a phone cannot reach", () => {
    expect(
      pickLanAddress({
        "vEthernet (WSL (Hyper-V firewall))": [address("172.28.160.1")],
        "vEthernet (Default Switch)": [address("192.168.96.1")],
        WiFi: [address("10.0.0.12")],
      }),
    ).toBe("10.0.0.12");
  });

  it("ignores IPv6 and link-local addresses", () => {
    expect(
      pickLanAddress({
        WiFi: [
          { address: "fe80::1", family: "IPv6", internal: false },
          address("169.254.10.4"),
          address("192.168.1.20"),
        ],
      }),
    ).toBe("192.168.1.20");
  });

  it("returns null when the machine is offline", () => {
    expect(pickLanAddress({ lo: [address("127.0.0.1", true)] })).toBeNull();
  });
});

describe("otherSupabaseProjects", () => {
  it("names each other project once, however many of its containers are up", () => {
    expect(
      otherSupabaseProjects(
        [
          "supabase_db_cmg_data_platform",
          "supabase_kong_cmg_data_platform",
          "supabase_pg_meta_cmg_data_platform",
          "supabase_db_personal_observability",
          "supabase_edge_runtime_personal_observability",
        ],
        "personal_observability",
      ),
    ).toEqual(["cmg_data_platform"]);
  });

  it("leaves containers that are not Supabase stacks alone", () => {
    expect(
      otherSupabaseProjects(
        ["garmin-sync", "postgres", "supabase_unknown"],
        "personal_observability",
      ),
    ).toEqual([]);
  });
});

describe("parseEnvFile", () => {
  it("reads quoted and bare values and skips comments", () => {
    expect(
      parseEnvFile(
        [
          "# local only",
          'SUPABASE_URL="http://127.0.0.1:54321"',
          "DEV_LOGIN_EMAIL=me@example.com",
          "",
        ].join("\r\n"),
      ),
    ).toEqual({ SUPABASE_URL: "http://127.0.0.1:54321", DEV_LOGIN_EMAIL: "me@example.com" });
  });
});

describe("isLocalSupabaseUrl", () => {
  it("accepts the local stack", () => {
    expect(isLocalSupabaseUrl("http://127.0.0.1:54321")).toBe(true);
    expect(isLocalSupabaseUrl("http://localhost:54321")).toBe(true);
  });

  it("rejects hosted Supabase, a missing value and a lookalike hostname", () => {
    expect(isLocalSupabaseUrl("https://ivdhucdiycnbgvdetagw.supabase.co")).toBe(false);
    expect(isLocalSupabaseUrl(undefined)).toBe(false);
    expect(isLocalSupabaseUrl("not a url")).toBe(false);
    expect(isLocalSupabaseUrl("https://localhost.example.com")).toBe(false);
  });
});

describe("listeningPid", () => {
  const netstat = [
    "",
    "Active Connections",
    "",
    "  Proto  Local Address          Foreign Address        State           PID",
    "  TCP    0.0.0.0:54321          0.0.0.0:0              LISTENING       6120",
    "  TCP    192.168.55.137:50800   20.90.1.1:8080         ESTABLISHED     900",
    "  TCP    [::]:8080              [::]:0                 LISTENING       24680",
  ].join("\r\n");

  it("finds the process listening on the port", () => {
    expect(listeningPid(netstat, 8080)).toBe(24680);
  });

  it("does not mistake an outbound connection to the same port number for a listener", () => {
    expect(listeningPid(netstat, 50800)).toBeNull();
  });

  it("does not match a longer port that merely starts with the same digits", () => {
    expect(listeningPid(netstat, 5432)).toBeNull();
  });
});

describe("isDevProcess", () => {
  it("recognises the runtimes a dev server runs under", () => {
    expect(isDevProcess("node.exe")).toBe(true);
    expect(isDevProcess("bun.exe")).toBe(true);
    expect(isDevProcess("/usr/local/bin/node")).toBe(true);
  });

  it("refuses anything else, so an unrelated program on the port is never killed", () => {
    expect(isDevProcess("com.docker.backend.exe")).toBe(false);
    expect(isDevProcess("")).toBe(false);
  });
});

describe("renderBanner", () => {
  it("shows the phone address, the branch and the QR code", () => {
    const banner = renderBanner({
      port: 8080,
      lanAddress: "192.168.55.137",
      branch: "feature/local-command",
      qr: "<QR>",
    });

    expect(banner).toContain("http://192.168.55.137:8080");
    expect(banner).toContain("http://localhost:8080");
    expect(banner).toContain("feature/local-command");
    expect(banner).toContain("<QR>");
  });

  it("says so plainly when there is no network to reach the phone on", () => {
    const banner = renderBanner({ port: 8080, lanAddress: null, branch: "main", qr: null });

    expect(banner).toContain("http://localhost:8080");
    expect(banner).toContain("No Wi-Fi address found");
  });
});
