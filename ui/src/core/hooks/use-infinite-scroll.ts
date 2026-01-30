import { useEffect, useRef } from "react";

interface UseInfiniteScrollOptions {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
}

/**
 * Custom hook for infinite scroll with IntersectionObserver.
 * Works inside ScrollArea components by using a ref for the scroll container.
 *
 * @returns sentinelRef - attach to a div at the bottom of scrollable content
 * @returns scrollContainerRef - attach to ScrollArea's viewportRef
 *
 * @example
 * const { sentinelRef, scrollContainerRef } = useInfiniteScroll({
 *   hasNextPage,
 *   isFetchingNextPage,
 *   fetchNextPage,
 * });
 *
 * <ScrollArea viewportRef={scrollContainerRef}>
 *   <Table ... />
 *   <div ref={sentinelRef} style={{ height: 1 }} />
 * </ScrollArea>
 */
export function useInfiniteScroll({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: UseInfiniteScrollOptions) {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!sentinelRef.current || !hasNextPage || isFetchingNextPage) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          fetchNextPage();
        }
      },
      {
        root: scrollContainerRef.current,
        threshold: 0.1,
      }
    );

    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return { sentinelRef, scrollContainerRef };
}
