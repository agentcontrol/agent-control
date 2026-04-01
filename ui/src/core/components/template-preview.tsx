import {
  Alert,
  Box,
  Collapse,
  Group,
  Loader,
  Text,
  Textarea,
  UnstyledButton,
} from '@mantine/core';
import { useDebouncedCallback } from '@mantine/hooks';
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import { useCallback, useEffect, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import type {
  ProblemDetail,
  TemplateDefinition,
  TemplateValue,
} from '@/core/api/types';
import { useRenderTemplate } from '@/core/hooks/query-hooks/use-render-template';

type TemplatePreviewProps = {
  template: TemplateDefinition;
  values: Record<string, TemplateValue>;
  /** Called when the render endpoint returns parameter-level errors. */
  onErrors?: (errors: Record<string, string>) => void;
  debounceMs?: number;
  defaultOpen?: boolean;
};

/**
 * Calls the render preview endpoint and displays the rendered control JSON.
 */
export function TemplatePreview({
  template,
  values,
  onErrors,
  debounceMs = 600,
  defaultOpen = false,
}: TemplatePreviewProps) {
  const [opened, setOpened] = useState(defaultOpen);
  const [renderedJson, setRenderedJson] = useState('');
  const [renderError, setRenderError] = useState<ProblemDetail | null>(null);
  const renderTemplate = useRenderTemplate();

  const doRender = useCallback(async () => {
    setRenderError(null);
    try {
      const result = await renderTemplate.mutateAsync({
        template,
        template_values: values,
      });
      if (result?.control) {
        // Strip template authoring metadata — show only what the engine sees.
        const {
          template: _t,
          template_values: _tv,
          ...rendered
        } = result.control as Record<string, unknown>;
        setRenderedJson(JSON.stringify(rendered, null, 2));
        onErrors?.({});
      }
    } catch (error) {
      if (isApiError(error)) {
        setRenderError(error.problemDetail);
        const paramErrors: Record<string, string> = {};
        for (const item of error.problemDetail.errors ?? []) {
          if (item.field?.startsWith('template_values.')) {
            const paramName = item.field.replace('template_values.', '');
            paramErrors[paramName] = item.message;
          }
        }
        if (Object.keys(paramErrors).length > 0) {
          onErrors?.(paramErrors);
        }
      }
      setRenderedJson('');
    }
  }, [template, values, renderTemplate, onErrors]);

  const debouncedRender = useDebouncedCallback(doRender, debounceMs);

  useEffect(() => {
    debouncedRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template, values]);

  return (
    <Box>
      <UnstyledButton onClick={() => setOpened((o) => !o)} w="100%">
        <Group gap="xs" mb={opened ? 'xs' : 0}>
          {opened ? (
            <IconChevronDown size={14} />
          ) : (
            <IconChevronRight size={14} />
          )}
          <Text size="sm" fw={500}>
            Preview rendered control
          </Text>
          {renderTemplate.isPending ? <Loader size={14} /> : null}
        </Group>
      </UnstyledButton>

      <Collapse in={opened}>
        {renderError ? (
          <Alert color="red" variant="light" title="Render error" mb="xs">
            <Text size="xs">{renderError.detail}</Text>
            {renderError.errors?.map((err, i) => (
              <Text key={i} size="xs" c="dimmed" mt={2}>
                {err.field}: {err.message}
              </Text>
            ))}
          </Alert>
        ) : null}

        <Textarea
          value={renderedJson}
          readOnly
          autosize
          minRows={6}
          maxRows={16}
          styles={{
            input: {
              fontFamily: 'monospace',
              fontSize: 12,
              backgroundColor: 'var(--mantine-color-dark-7)',
              color: 'var(--mantine-color-gray-3)',
            },
          }}
          placeholder={
            renderTemplate.isPending
              ? 'Rendering...'
              : 'Fill in parameters to see a preview'
          }
        />
      </Collapse>
    </Box>
  );
}
