import { describe, expect, it, vi } from "vitest";
import { bindPageSession } from "./page-session";

describe("page session recovery", () => {
  it("keeps PiP acquisition alive when hidden, cancels at freeze, and reconnects on return", () => {
    const document = Object.assign(new EventTarget(), { visibilityState: "hidden" });
    const window = new EventTarget();
    const save = vi.fn(), suspend = vi.fn(), reconnect = vi.fn();
    const close = bindPageSession({ document, window, save, suspend, reconnect });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(save).toHaveBeenCalledOnce();
    expect(suspend).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("freeze"));
    expect(suspend).toHaveBeenCalledOnce();
    document.dispatchEvent(new Event("resume"));
    expect(reconnect).toHaveBeenCalledOnce();
    document.visibilityState = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    expect(reconnect).toHaveBeenCalledTimes(2);
    window.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: true }));
    expect(reconnect).toHaveBeenCalledTimes(3);
    close();
    document.dispatchEvent(new Event("resume"));
    expect(reconnect).toHaveBeenCalledTimes(3);
  });
});
