import type {
  ConditionNode,
  ConditionNodeInput,
  ValidationErrorItem,
} from '@/core/api/types';
import { getEvaluator } from '@/core/evaluators';

const VALID_SELECTOR_ROOTS = ['input', 'output', 'name', 'type', 'context', '*'];

export type ConditionBuilderLeaf = {
  id: string;
  kind: 'leaf';
  selectorPath: string;
  evaluatorName: string;
  config: Record<string, unknown>;
};

export type ConditionBuilderGroup = {
  id: string;
  kind: 'and' | 'or';
  children: ConditionBuilderNode[];
};

export type ConditionBuilderNot = {
  id: string;
  kind: 'not';
  child: ConditionBuilderNode;
};

export type ConditionBuilderNode =
  | ConditionBuilderLeaf
  | ConditionBuilderGroup
  | ConditionBuilderNot;

export type ConditionBuilderError = {
  field: string | null;
  message: string;
};

export function createNodeId(): string {
  return `condition-${Math.random().toString(36).slice(2, 10)}`;
}

export function createLeafNode(
  evaluatorName = 'regex',
  selectorPath = '*',
  config?: Record<string, unknown>
): ConditionBuilderLeaf {
  const evaluator = getEvaluator(evaluatorName);
  return {
    id: createNodeId(),
    kind: 'leaf',
    selectorPath,
    evaluatorName,
    config: config ?? evaluator?.toConfig(evaluator.initialValues) ?? {},
  };
}

export function createGroupNode(
  kind: 'and' | 'or' = 'and',
  children: ConditionBuilderNode[] = [createLeafNode()]
): ConditionBuilderGroup {
  return {
    id: createNodeId(),
    kind,
    children,
  };
}

export function createNotNode(
  child: ConditionBuilderNode = createLeafNode()
): ConditionBuilderNot {
  return {
    id: createNodeId(),
    kind: 'not',
    child,
  };
}

export function deserializeConditionNode(node: ConditionNode): ConditionBuilderNode {
  if (node.selector && node.evaluator) {
    return createLeafNode(
      node.evaluator.name,
      node.selector.path ?? '*',
      (node.evaluator.config as Record<string, unknown>) ?? {}
    );
  }

  if (node.and?.length) {
    return createGroupNode(
      'and',
      node.and.map((child) => deserializeConditionNode(child))
    );
  }

  if (node.or?.length) {
    return createGroupNode(
      'or',
      node.or.map((child) => deserializeConditionNode(child))
    );
  }

  if (node.not) {
    return createNotNode(deserializeConditionNode(node.not));
  }

  return createLeafNode();
}

export function serializeConditionNode(
  node: ConditionBuilderNode
): ConditionNodeInput {
  if (node.kind === 'leaf') {
    return {
      selector: { path: node.selectorPath },
      evaluator: {
        name: node.evaluatorName,
        config: node.config,
      },
    };
  }

  if (node.kind === 'not') {
    return {
      not: serializeConditionNode(node.child),
    };
  }

  return {
    [node.kind]: node.children.map((child) => serializeConditionNode(child)),
  };
}

export function updateConditionNode(
  root: ConditionBuilderNode,
  targetId: string,
  updater: (node: ConditionBuilderNode) => ConditionBuilderNode
): ConditionBuilderNode {
  if (root.id === targetId) {
    return updater(root);
  }

  if (root.kind === 'not') {
    return {
      ...root,
      child: updateConditionNode(root.child, targetId, updater),
    };
  }

  if (root.kind === 'and' || root.kind === 'or') {
    return {
      ...root,
      children: root.children.map((child) =>
        updateConditionNode(child, targetId, updater)
      ),
    };
  }

  return root;
}

export function insertChildNode(
  root: ConditionBuilderNode,
  parentId: string,
  child: ConditionBuilderNode
): ConditionBuilderNode {
  return updateConditionNode(root, parentId, (node) => {
    if (node.kind !== 'and' && node.kind !== 'or') {
      return node;
    }
    return {
      ...node,
      children: [...node.children, child],
    };
  });
}

export function replaceConditionNode(
  root: ConditionBuilderNode,
  targetId: string,
  replacement: ConditionBuilderNode
): ConditionBuilderNode {
  if (root.id === targetId) {
    return replacement;
  }

  if (root.kind === 'not') {
    return {
      ...root,
      child: replaceConditionNode(root.child, targetId, replacement),
    };
  }

  if (root.kind === 'and' || root.kind === 'or') {
    return {
      ...root,
      children: root.children.map((child) =>
        child.id === targetId
          ? replacement
          : replaceConditionNode(child, targetId, replacement)
      ),
    };
  }

  return root;
}

export function deleteConditionNode(
  root: ConditionBuilderNode,
  targetId: string
): ConditionBuilderNode {
  if (root.id === targetId) {
    return createLeafNode();
  }

  if (root.kind === 'not') {
    if (root.child.id === targetId) {
      return createLeafNode();
    }
    return {
      ...root,
      child: deleteConditionNode(root.child, targetId),
    };
  }

  if (root.kind === 'and' || root.kind === 'or') {
    const nextChildren = root.children
      .filter((child) => child.id !== targetId)
      .map((child) => deleteConditionNode(child, targetId));

    return {
      ...root,
      children: nextChildren.length > 0 ? nextChildren : [createLeafNode()],
    };
  }

  return root;
}

export function moveConditionNode(
  root: ConditionBuilderNode,
  targetId: string,
  direction: 'up' | 'down'
): ConditionBuilderNode {
  if (root.kind === 'not') {
    return {
      ...root,
      child: moveConditionNode(root.child, targetId, direction),
    };
  }

  if (root.kind === 'and' || root.kind === 'or') {
    const index = root.children.findIndex((child) => child.id === targetId);
    if (index >= 0) {
      const swapIndex = direction === 'up' ? index - 1 : index + 1;
      if (swapIndex < 0 || swapIndex >= root.children.length) {
        return root;
      }

      const nextChildren = [...root.children];
      [nextChildren[index], nextChildren[swapIndex]] = [
        nextChildren[swapIndex]!,
        nextChildren[index]!,
      ];
      return {
        ...root,
        children: nextChildren,
      };
    }

    return {
      ...root,
      children: root.children.map((child) =>
        moveConditionNode(child, targetId, direction)
      ),
    };
  }

  return root;
}

export function wrapConditionNodeWithNot(
  root: ConditionBuilderNode,
  targetId: string
): ConditionBuilderNode {
  return replaceConditionNode(root, targetId, createNotNode(getNodeById(root, targetId)));
}

export function unwrapNotConditionNode(
  root: ConditionBuilderNode,
  targetId: string
): ConditionBuilderNode {
  return updateConditionNode(root, targetId, (node) => {
    if (node.kind !== 'not') {
      return node;
    }
    return node.child;
  });
}

export function getNodeById(
  root: ConditionBuilderNode,
  targetId: string
): ConditionBuilderNode {
  if (root.id === targetId) {
    return root;
  }

  if (root.kind === 'not') {
    return getNodeById(root.child, targetId);
  }

  if (root.kind === 'and' || root.kind === 'or') {
    for (const child of root.children) {
      try {
        return getNodeById(child, targetId);
      } catch {
        // Continue searching siblings.
      }
    }
  }

  throw new Error(`Condition node '${targetId}' not found`);
}

export function validateConditionTree(
  node: ConditionBuilderNode,
  path = 'data.condition',
  depth = 1,
  maxDepth = 6
): ConditionBuilderError[] {
  const errors: ConditionBuilderError[] = [];

  if (depth > maxDepth) {
    errors.push({
      field: path,
      message: `Condition nesting depth exceeds maximum of ${maxDepth}`,
    });
  }

  if (node.kind === 'leaf') {
    if (!node.selectorPath.trim()) {
      errors.push({
        field: `${path}.selector.path`,
        message: 'Selector path is required',
      });
    } else {
      const root = node.selectorPath.split('.')[0];
      if (!VALID_SELECTOR_ROOTS.includes(root)) {
        errors.push({
          field: `${path}.selector.path`,
          message: `Invalid path root '${root}'. Must be one of: ${VALID_SELECTOR_ROOTS.join(', ')}`,
        });
      }
    }

    if (!node.evaluatorName.trim()) {
      errors.push({
        field: `${path}.evaluator.name`,
        message: 'Evaluator is required',
      });
    }

    const evaluator = getEvaluator(node.evaluatorName);
    if (evaluator?.validate) {
      const formValues = evaluator.fromConfig(node.config);
      for (const [field, validate] of Object.entries(evaluator.validate)) {
        const message = validate(
          (formValues as Record<string, unknown>)[field],
          formValues
        );
        if (message) {
          errors.push({
            field: `${path}.evaluator.config.${field}`,
            message,
          });
        }
      }
    }

    return errors;
  }

  if (node.kind === 'not') {
    return [
      ...errors,
      ...validateConditionTree(node.child, `${path}.not`, depth + 1, maxDepth),
    ];
  }

  if (node.children.length === 0) {
    errors.push({
      field: `${path}.${node.kind}`,
      message: `'${node.kind}' must contain at least one child condition`,
    });
  }

  node.children.forEach((child, index) => {
    errors.push(
      ...validateConditionTree(
        child,
        `${path}.${node.kind}[${index}]`,
        depth + 1,
        maxDepth
      )
    );
  });

  return errors;
}

export function getConditionErrorsForPath(
  errors: ValidationErrorItem[] | ConditionBuilderError[],
  path: string
): string[] {
  return errors
    .filter((error) => error.field === path || error.field?.startsWith(`${path}.`))
    .map((error) => error.message);
}
