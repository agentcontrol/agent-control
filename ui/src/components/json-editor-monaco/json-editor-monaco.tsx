import { JsonEditorView } from '@/core/page-components/agent-detail/modals/edit-control/json-editor-view';
import type { JsonEditorViewProps } from '@/core/page-components/agent-detail/modals/edit-control/types';

export function JsonEditorMonaco(props: JsonEditorViewProps) {
  return <JsonEditorView {...props} />;
}
