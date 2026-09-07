// Bound the caller's wait even when an adapter or response body never settles.
export function abortableTask<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = (): void => { signal.removeEventListener("abort", abort); reject(signal.reason ?? new DOMException("Aborted", "AbortError")); };
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
    operation.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}
