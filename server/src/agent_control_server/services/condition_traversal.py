"""Shared condition-tree traversal helpers."""

from collections.abc import Iterator

from agent_control_models import ConditionNode


def iter_condition_leaves_with_paths(
    node: ConditionNode,
    *,
    path: str,
) -> Iterator[tuple[str, ConditionNode]]:
    """Yield each leaf condition with its dotted/bracketed field path."""
    if node.is_leaf():
        yield path, node
        return

    if node.and_ is not None:
        for index, child in enumerate(node.and_):
            yield from iter_condition_leaves_with_paths(
                child,
                path=f"{path}.and[{index}]",
            )
        return

    if node.or_ is not None:
        for index, child in enumerate(node.or_):
            yield from iter_condition_leaves_with_paths(
                child,
                path=f"{path}.or[{index}]",
            )
        return

    if node.not_ is not None:
        yield from iter_condition_leaves_with_paths(node.not_, path=f"{path}.not")
