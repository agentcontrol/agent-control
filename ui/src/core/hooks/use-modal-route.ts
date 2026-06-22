import { useRouter } from 'next/router';
import { useCallback, useMemo } from 'react';

import { SUBMODAL_NAMES } from '@/core/constants/modal-routes';

/**
 * Hook to manage modal state via URL query parameters
 *
 * URL structure:
 * - ?modal=control-store - Opens Control Store modal
 * - ?modal=control-store&submodal=add-new - Opens Control Store with Add New Control modal
 * - ?modal=control-store&submodal=create&rule=regex - Opens Control Store with Create Control modal
 * - ?modal=control-store&submodal=edit&controlId=123 - Opens Control Store with Edit Control modal
 * - ?modal=edit&controlId=123 - Opens Edit Control modal directly (from agent detail page)
 */
export function useModalRoute() {
  const router = useRouter();
  const { modal, submodal, rule, controlId } = router.query;

  const modalState = useMemo(() => {
    return {
      modal: typeof modal === 'string' ? modal : null,
      submodal: typeof submodal === 'string' ? submodal : null,
      rule: typeof rule === 'string' ? rule : null,
      controlId: typeof controlId === 'string' ? controlId : null,
    };
  }, [modal, submodal, rule, controlId]);

  const openModal = useCallback(
    (
      modalName: string,
      params?: { submodal?: string; rule?: string; controlId?: string }
    ) => {
      const query: Record<string, string> = { modal: modalName };
      if (params?.submodal) query.submodal = params.submodal;
      if (params?.rule) query.rule = params.rule;
      if (params?.controlId) query.controlId = params.controlId;

      router.push(
        {
          pathname: router.pathname,
          query: { ...router.query, ...query },
        },
        undefined,
        { shallow: true }
      );
    },
    [router]
  );

  const closeModal = useCallback(() => {
    // Remove all modal-related query parameters
    const query = { ...router.query };
    delete query.modal;
    delete query.submodal;
    delete query.rule;
    delete query.controlId;

    router.push(
      {
        pathname: router.pathname,
        query,
      },
      undefined,
      { shallow: true }
    );
  }, [router]);

  const closeSubmodal = useCallback(() => {
    // Extract and discard submodal-related params, keep the rest
    const {
      submodal: currentSubmodal,
      rule,
      controlId,
      ...rest
    } = router.query;
    // Silence unused vars - we're destructuring to remove them
    void rule;
    void controlId;

    // If closing from "create", go back to "add-new" instead of closing everything
    // This allows the user to select a different rule
    if (currentSubmodal === SUBMODAL_NAMES.CREATE) {
      router.push(
        {
          pathname: router.pathname,
          query: {
            ...rest,
            modal: router.query.modal,
            submodal: SUBMODAL_NAMES.ADD_NEW,
          },
        },
        undefined,
        { shallow: true }
      );
    } else {
      // Otherwise, remove all submodal params (closes back to parent modal)
      router.push(
        {
          pathname: router.pathname,
          query: rest,
        },
        undefined,
        { shallow: true }
      );
    }
  }, [router]);

  return {
    ...modalState,
    openModal,
    closeModal,
    closeSubmodal,
  };
}
