import { describe, expect, it, vi } from "vitest";
import { LatestSampleProcessor } from "./latest-sample-processor";

describe("LatestSampleProcessor", () => {
  it("keeps at most one active and one latest sample", async () => {
    const processed: number[] = [];
    let releaseFirst!: () => void;
    const process = vi.fn(async (sample: number) => {
      processed.push(sample);
      if (sample === 1) await new Promise<void>((resolve) => { releaseFirst = resolve; });
    });
    const processor = new LatestSampleProcessor(process);

    processor.push(1);
    processor.push(2);
    processor.push(3);
    await vi.waitFor(() => expect(process).toHaveBeenCalledTimes(1));
    releaseFirst();
    await vi.waitFor(() => expect(process).toHaveBeenCalledTimes(2));
    expect(processed).toEqual([1, 3]);
  });
});
