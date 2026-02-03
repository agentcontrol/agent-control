import { useRouter } from "next/router";
import { useCallback, useMemo } from "react";

/**
 * Hook to manage modal state via URL query parameters
 * 
 * URL structure:
 * - ?modal=control-store - Opens Control Store modal
 * - ?modal=control-store&submodal=add-new - Opens Control Store with Add New Control modal
 * - ?modal=control-store&submodal=create&evaluator=regex - Opens Control Store with Create Control modal
 * - ?modal=control-store&submodal=edit&controlId=123 - Opens Control Store with Edit Control modal
 * - ?modal=edit&controlId=123 - Opens Edit Control modal directly (from agent detail page)
 */
export function useModalRoute() {
  const router = useRouter();
  const { modal, submodal, evaluator, controlId } = router.query;

  const modalState = useMemo(() => {
    return {
      modal: typeof modal === "string" ? modal : null,
      submodal: typeof submodal === "string" ? submodal : null,
      evaluator: typeof evaluator === "string" ? evaluator : null,
      controlId: typeof controlId === "string" ? controlId : null,
    };
  }, [modal, submodal, evaluator, controlId]);

  const openModal = useCallback(
    (modalName: string, params?: { submodal?: string; evaluator?: string; controlId?: string }) => {
      const query: Record<string, string> = { modal: modalName };
      if (params?.submodal) query.submodal = params.submodal;
      if (params?.evaluator) query.evaluator = params.evaluator;
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
    delete query.evaluator;
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
    const { submodal: currentSubmodal, evaluator: _evaluator, controlId: _controlId, ...rest } = router.query;
    
    // If closing from "create", go back to "add-new" instead of closing everything
    if (currentSubmodal === "create") {
      router.push(
        {
          pathname: router.pathname,
          query: { ...rest, modal: router.query.modal, submodal: "add-new" },
        },
        undefined,
        { shallow: true }
      );
    } else {
      // Otherwise, remove all submodal params
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
