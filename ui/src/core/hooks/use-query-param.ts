import { useRouter } from "next/router";
import { useCallback, useEffect, useState } from "react";

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

  const [value, setValueState] = useState(defaultValue);

  const readValueFromLocation = useCallback(() => {
    if (typeof window === "undefined") return defaultValue;
    const searchParams = new URLSearchParams(window.location.search);
    return searchParams.get(key) ?? defaultValue;
  }, [key, defaultValue]);

  const updateUrl = useCallback(
    (newValue: string) => {
      if (typeof window === "undefined") return;

      const url = new URL(window.location.href);
      if (newValue) {
        url.searchParams.set(key, newValue);
      } else {
        url.searchParams.delete(key);
      }

      const nextPath = `${url.pathname}${url.search}${url.hash}`;
      window.history.replaceState(window.history.state, "", nextPath);

      if (router.isReady) {
        void router.replace(nextPath, undefined, { shallow });
      }
    },
    [router, key, shallow]
  );

  // Update URL when value changes
  const setValue = useCallback(
    (newValue: string) => {
      setValueState(newValue);
      updateUrl(newValue);
    },
    [updateUrl]
  );

  useEffect(() => {
    const nextValue = readValueFromLocation();
    if (nextValue !== value) {
      setValueState(nextValue);
    }
  }, [readValueFromLocation, router.asPath, value]);

  return [value, setValue];
}
