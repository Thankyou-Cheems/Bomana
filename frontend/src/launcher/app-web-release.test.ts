import { describe, expect, it, vi } from "vitest";
import { fetchAppWebRelease } from "./app-web-release";

describe("App Web release", () => {
  it("reads an independently versioned same-origin release document", async () => {
    const fetcher = vi.fn(async () => Response.json({
      schema_version: 1,
      app_web_version: "1.3.5",
      source_commit: "a".repeat(40),
    }));
    await expect(fetchAppWebRelease(
      new URL("https://bomana.example/app/app-release.json"),
      fetcher as typeof fetch,
    )).resolves.toEqual({
      schemaVersion: 1,
      appWebVersion: "1.3.5",
      sourceCommit: "a".repeat(40),
    });
    expect(fetcher).toHaveBeenCalledWith(
      new URL("https://bomana.example/app/app-release.json"),
      expect.objectContaining({ method: "GET", mode: "same-origin", redirect: "error" }),
    );
  });

  it("rejects malformed release documents", async () => {
    const malformed = (async () => Response.json({ schema_version: 1, app_web_version: "1.3" })) as typeof fetch;
    await expect(fetchAppWebRelease(new URL("https://bomana.example/app/app-release.json"), malformed)).rejects.toThrow("invalid");
  });
});
