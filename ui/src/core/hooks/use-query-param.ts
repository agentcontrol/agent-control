import { useRouter } from "next/router";
import { useCallback, useMemo, useRef } from "react";

interface UseQueryParamOptions {
  /** Default value when param is not in URL */
  defaultValue?: string;
  /** Whether to use shallow routing (no data fetching, default: true) */
  shallow?: boolean;
}

/**
 * Sync a state value with a URL query parameter.
 * Enables shareable URLs and preserves state on refresh/back navigation.
 *
 * @param key - The query parameter key (e.g., "search" for ?search=value)
 * @param options - Configuration options
 * @returns [value, setValue] - Similar to useState, but synced with URL
 *
 * @example
 * const [search, setSearch] = useQueryParam("search");
 * // URL: /agents?search=hello
 * // search = "hello"
 */
export function useQueryParam(
  key: string,
  options: UseQueryParamOptions = {}
): [string, (value: string) => void] {
  const { defaultValue = "", shallow = true } = options;
  const router = useRouter();

  // Derive value directly from router.query (no local state needed)
  const value = useMemo(() => {
    if (!router.isReady) return defaultValue;
    const urlValue = router.query[key];
    return typeof urlValue === "string" ? urlValue : defaultValue;
  }, [router.isReady, router.query, key, defaultValue]);

  // Track if we're currently updating to prevent loops
  const isUpdatingRef = useRef(false);

  // Update URL when value changes
  const setValue = useCallback(
    (newValue: string) => {
      if (!router.isReady || isUpdatingRef.current) return;

      isUpdatingRef.current = true;

      const query = { ...router.query };
      if (newValue) {
        query[key] = newValue;
      } else {
        delete query[key];
      }

      router.replace({ pathname: router.pathname, query }, undefined, { shallow }).finally(() => {
        isUpdatingRef.current = false;
      });
    },
    [router, key, shallow]
  );

  return [value, setValue];
}
