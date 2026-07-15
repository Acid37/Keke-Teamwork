import { useState, useCallback } from 'react';

/** Wraps an async action with busy flag and optional error side-effect. */
export function useAsyncAction(onError?: (msg: string) => void) {
  const [busy, setBusy] = useState(false);

  const run = useCallback(async <T>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    try {
      return await fn();
    } catch (e) {
      if (onError) {
        onError(e instanceof Error ? e.message : String(e));
        return undefined;
      }
      throw e;
    } finally {
      setBusy(false);
    }
  }, [onError]);

  return { busy, run } as const;
}
