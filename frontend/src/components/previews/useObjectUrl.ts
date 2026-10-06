import { useEffect, useRef, useState } from "react";

/**
 * Fetch binary content into an object URL, revoking it on unmount or when
 * the fetcher identity changes (new file/page/revision). Bearer auth means
 * <img src>/<video src> can't hit the API directly — blobs + object URLs
 * are the desktop-safe path.
 */
export function useObjectUrl(
  fetcher: (() => Promise<string>) | null,
  deps: unknown[],
): { url: string | null; loading: boolean; error: string | null } {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!fetcher) {
      setUrl(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetcher()
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = u;
        setUrl(u);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Final revoke on unmount.
  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  return { url, loading, error };
}
