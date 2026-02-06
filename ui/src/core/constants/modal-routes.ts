/**
 * Constants for modal route names used in URL query parameters
 * These are used with useModalRoute hook for consistent modal navigation
 */

export const MODAL_NAMES = {
  CONTROL_STORE: 'control-store',
  EDIT: 'edit',
} as const;

export const SUBMODAL_NAMES = {
  ADD_NEW: 'add-new',
  CREATE: 'create',
  EDIT: 'edit',
} as const;

export type ModalName = (typeof MODAL_NAMES)[keyof typeof MODAL_NAMES];
export type SubmodalName = (typeof SUBMODAL_NAMES)[keyof typeof SUBMODAL_NAMES];
