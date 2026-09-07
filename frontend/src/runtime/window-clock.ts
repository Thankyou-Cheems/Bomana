/** Keep active sampling on the visible PiP window and release waits when it closes. */
export class WindowClock {
  readonly #current: () => Window;
  readonly #pending = new Set<() => void>();
  constructor(current: () => Window) { this.#current = current; }
  wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
    const clock = this.#current();
    return new Promise((resolve) => {
      let settled = false, timer = 0;
      const finish = (): void => {
        if (settled) return;
        settled = true;
        clock.clearTimeout(timer);
        signal?.removeEventListener("abort", finish);
        this.#pending.delete(finish);
        resolve();
      };
      this.#pending.add(finish);
      if (signal?.aborted) { finish(); return; }
      signal?.addEventListener("abort", finish, { once: true });
      timer = clock.setTimeout(finish, milliseconds);
    });
  }
  wake(): void { for (const finish of [...this.#pending]) finish(); }
}
