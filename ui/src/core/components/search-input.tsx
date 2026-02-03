import type { TextInputProps } from "@mantine/core";
import { TextInput } from "@mantine/core";
import { IconSearch, IconX } from "@tabler/icons-react";
import { useMemo } from "react";

import { useQueryParam } from "@/core/hooks/use-query-param";

interface SearchInputProps
  extends Omit<TextInputProps, "value" | "onChange" | "leftSection" | "rightSection"> {
  /** Query parameter key to sync with URL (e.g., "search", "q", "store_q") */
  queryKey: string;
}

/**
 * Reusable search input component that syncs with URL query parameters.
 * Includes a clear button (X icon) when there's text.
 * Accepts all TextInput props for full customization.
 *
 * @example
 * <SearchInput queryKey="search" placeholder="Search agents..." w={250} />
 */
export function SearchInput({
  queryKey,
  placeholder = "Search...",
  w = 250,
  ...rest
}: SearchInputProps) {
  const [searchQuery, setSearchQuery] = useQueryParam(queryKey);

  const showClearButton = useMemo(() => {
    return searchQuery.length > 0;
  }, [searchQuery]);

  const handleClear = () => {
    setSearchQuery("");
  };

  return (
    <TextInput
      placeholder={placeholder}
      leftSection={<IconSearch size={16} />}
      rightSection={
        showClearButton ? (
          <IconX
            size={16}
            style={{ cursor: "pointer" }}
            onClick={handleClear}
            data-testid={`search-clear-${queryKey}`}
          />
        ) : null
      }
      value={searchQuery}
      onChange={(e) => setSearchQuery(e.currentTarget.value)}
      w={w}
      {...rest}
    />
  );
}
