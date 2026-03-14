import { modals } from '@mantine/modals';
import type { ReactNode } from 'react';

const CONFIRM_BTN_CLASS = 'confirm-modal-confirm-btn';
const CONFIRM_MODAL_DEFAULTS = {
  size: 'sm',
  centered: true,
  cancelProps: { variant: 'default', size: 'sm' },
};

export type ConfirmModalOptions = {
  title: string;
  children: ReactNode;
  onConfirm: () => void;
  onCancel?: () => void;
  confirmLabel?: string;
  cancelLabel?: string;
};

/**
 * Open a standard (non-destructive) confirmation modal.
 *
 * Returns the modal id, which can be used to close it programmatically if needed.
 */
export function openActionConfirmModal({
  title,
  children,
  onConfirm,
  onCancel,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
}: ConfirmModalOptions): string {
  return modals.openConfirmModal({
    ...CONFIRM_MODAL_DEFAULTS,
    title,
    children,
    labels: { confirm: confirmLabel, cancel: cancelLabel },
    confirmProps: {
      variant: 'filled',
      color: 'violet',
      size: CONFIRM_MODAL_DEFAULTS.size,
      className: CONFIRM_BTN_CLASS,
    },
    onConfirm,
    onCancel,
  });
}

/**
 * Open a destructive confirmation modal (e.g. remove/delete).
 *
 * Returns the modal id, which can be used to close it programmatically if needed.
 */
export function openDestructiveConfirmModal({
  title,
  children,
  onConfirm,
  onCancel,
  confirmLabel = 'Remove',
  cancelLabel = 'Cancel',
}: ConfirmModalOptions): string {
  return modals.openConfirmModal({
    ...CONFIRM_MODAL_DEFAULTS,
    title,
    children,
    labels: { confirm: confirmLabel, cancel: cancelLabel },
    confirmProps: {
      variant: 'filled',
      color: 'red.7',
      size: CONFIRM_MODAL_DEFAULTS.size,
      c: 'white',
    },
    onConfirm,
    onCancel,
  });
}
