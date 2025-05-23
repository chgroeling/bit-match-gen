from decoder_forge.bit_pattern import BitPattern
from functools import reduce
from dataclasses import dataclass
from typing import cast
from typing import Optional


@dataclass(eq=True, frozen=True)
class DecodeNode:
    """Base class for nodes in a decode tree.

    This class acts as an abstract base class for different node types used in
    representing a hierarchical decode tree built from BitPattern objects.
    """

    pass


@dataclass(eq=True, frozen=True)
class DecodeLeaf(DecodeNode):
    """Leaf node in a decode tree holding a BitPattern and its original form.

    Attributes:
        pat (BitPattern): The pattern after processing (e.g. after applying a mask).
        origin (BitPattern): The original BitPattern from which this leaf was derived.
    """

    pat: BitPattern
    origin: BitPattern


@dataclass(eq=True, frozen=True)
class DecodeTree(DecodeNode):
    """Internal tree node representing a group of BitPatterns sharing fixed bits.

    Attributes:
        pat (BitPattern): A BitPattern representing the common fixed bits for this
            group.  Can be None for the root node.
        children (list[DecodeNode]): A list of child nodes (either DecodeLeaf or
            DecodeTree) representing further subdivisions of patterns.
    """

    pat: Optional[BitPattern]
    children: list[DecodeNode]


def compute_common_fixedmask(pats: list[BitPattern]) -> int:
    """Compute the common fixed mask for a list of BitPattern objects.

    This function calculates the bitwise AND (intersection) of the fixedmask attributes
    from all BitPattern objects in the provided list. The result is an integer that
    represents the bits that are fixed (common) across every pattern.

    Args:
        pats (list[BitPattern]): A list of BitPattern objects whose fixedmask values
            will be combined.

    Returns:
        int: The bitwise AND of all fixedmask attributes of the BitPattern objects.

    Examples:
        >>> p1 = BitPattern(0b111, 0b101, 3)
        >>> p2 = BitPattern(0b101, 0b001, 3)
        >>> compute_common_fixedmask([p1, p2])
        5

    """

    def logic_and(fma: int, fmb: int) -> int:
        return fma & fmb

    out = reduce(logic_and, (i.fixedmask for i in pats))
    return out


def build_groups_by_fixed_bits(
    pats: list[BitPattern],
) -> dict[BitPattern, list[tuple[BitPattern, BitPattern]]]:
    """
    Group BitPatterns based on their fixed bits after splitting by a common mask.

    This function computes a common fixed mask for the provided BitPattern objects and
    then splits each pattern using the 'split_by_mask' method. The patterns are grouped
    by the part of the pattern that corresponds to the fixed bits of the computed mask.

    Args:
        pats (list[BitPattern]): A list of BitPattern objects to be grouped.

    Returns:
        dict: A dictionary where each key is the fixed portion (result of splitting by
        the mask) and each value is a list of tuples. Each tuple contains:

        - The remainder of the pattern after splitting
        - The original BitPattern object before the split

    Raises:
        ValueError: If 'split_by_mask' is invoked with a mask not contained within the
            pattern's fixedmask.
    """

    # find fixed parts
    mask = compute_common_fixedmask(pats)

    groups: dict[BitPattern, list[tuple[BitPattern, BitPattern]]] = {}
    for pn in pats:
        pa, pb = pn.split_by_mask(mask)
        group = groups.get(pa, list())
        group.append((pb, pn))
        groups[pa] = group

    return groups


def build_decode_tree_by_fixed_bits(
    pats: list[BitPattern], decoder_width: int
) -> DecodeTree:
    """Construct a hierarchical decode tree by grouping BitPatterns with shared fixed
    bits.

    First, each BitPattern is extended to the specified decoder_width using the
    extend_and_shift_to_msb() method and wrapped into a DecodeLeaf node. These leaves
    are grouped into a DecodeTree hierarchy. The grouping is done by computing a common
    fixed mask for the current set of patterns and splitting them via split_by_mask.
    Subtrees are created for groups with more than one member and non-zero fixed
    portion, while single-member groups are combined using the combine() method.

    Note:
        At various points during tree construction, the children of a node are kept
        sorted in descending order based on the total count of fixed bits. This ensures
        the nodes with the longest fixed matches are processed first.

    Args:
        pats (list[BitPattern]): List of BitPattern objects to be organized.
        decoder_width (int): The target bit width for extending each BitPattern.

    Returns:
        DecodeTree: The root node of the constructed hierarchical decode tree.

    Raises:
        ValueError: If any BitPattern cannot be split using the computed common fixed mask.

    Example:
        >>> tree = build_decode_tree_by_fixed_bits([pattern1, pattern2, pattern3], 8)
        >>> print(tree)

    """

    pats_unfolded: list[DecodeNode] = [
        DecodeLeaf(pat=i.extend_and_shift_to_msb(decoder_width), origin=i) for i in pats
    ]
    root = DecodeTree(pat=None, children=pats_unfolded)

    stack: list[DecodeTree] = []
    stack.append(root)

    def longest_match(i):
        pat_str = str(i.pat)
        no_zeros = pat_str.count("0")
        no_ones = pat_str.count("1")
        return no_zeros + no_ones

    while len(stack) != 0:
        current_tree = stack.pop()
        leafs = cast(list[DecodeLeaf], [i for i in current_tree.children])

        if len(pats) == 0:
            continue

        current_tree.children.clear()

        # remember which patterns were orginated by which origin
        pats_to_origins = {i.pat: i.origin for i in leafs}

        # split pats into groups with fixed bits
        fgrps = build_groups_by_fixed_bits([i.pat for i in leafs])

        for outer_pat, inner_pats in fgrps.items():
            if len(inner_pats) == 1:
                combined_pat = outer_pat.combine(inner_pats[0][0])
                src_pat = inner_pats[0][1]
                dleaf = DecodeLeaf(pat=combined_pat, origin=pats_to_origins[src_pat])
                current_tree.children.append(dleaf)

                # keep children list sorted
                current_tree.children.sort(key=longest_match, reverse=True)
            else:
                if outer_pat.fixedmask != 0x0:  # catch all
                    children: list[DecodeNode] = [
                        DecodeLeaf(pat=i, origin=pats_to_origins[src_pat])
                        for (i, src_pat) in inner_pats
                    ]

                    dtree = DecodeTree(pat=outer_pat, children=children)
                    current_tree.children.append(dtree)

                    # keep children list sorted
                    current_tree.children.sort(key=longest_match, reverse=True)
                    stack.append(dtree)  # process during next cycles
                else:
                    children = [
                        DecodeLeaf(pat=i, origin=pats_to_origins[src_pat])
                        for (i, src_pat) in inner_pats
                    ]
                    current_tree.children.extend(children)

                    # keep children list sorted
                    current_tree.children.sort(key=longest_match, reverse=True)
    return root


def flatten_decode_tree(
    tree: DecodeTree,
) -> list[tuple[BitPattern, Optional[BitPattern], int, bool, bool]]:
    """
    Flatten a hierarchical DecodeTree into a list of tuples.

    This function converts a DecodeTree hierarchy into a flat list for easier
    traversal or debugging. Each element in the list is a tuple containing:

    - The BitPattern object at that node.
    - The original BitPattern object (None for internal tree nodes).
    - The depth level of the node within the tree.
    - A boolean indicating if the node is the first child
    - A boolean indicating if the node is the last child (used for backtracking
      information during visual representation).

    Args:
        tree (DecodeTree): The root node of the DecodeTree to be flattened.

    Returns:
        list: A list of tuples, each containing: (BitPattern, origin BitPattern or None,
            depth integer, last_child flag boolean).

    Example:
        >>> flat_list = build_flat_tree(tree)
        >>> for node in flat_list:
        ...     print(node)

    """

    stack: list[tuple[DecodeNode, int, bool, bool]] = []
    stack.extend(
        (
            (i, 0, idx == len(tree.children) - 1, idx == 0)
            for idx, i in enumerate(reversed(tree.children))
        )
    )

    flattend_tree: list[tuple[BitPattern, Optional[BitPattern], int, bool, bool]] = []
    while len(stack) != 0:
        item, depth, first_child, last_child = stack.pop()
        if isinstance(item, DecodeLeaf):
            flattend_tree.append(
                (item.pat, item.origin, depth, first_child, last_child)
            )
        elif isinstance(item, DecodeTree):
            dtree = cast(DecodeTree, item)
            assert dtree.pat is not None
            flattend_tree.append((dtree.pat, None, depth, first_child, last_child))

            stack.extend(
                (
                    (i, depth + 1, idx == len(item.children) - 1, idx == 0)
                    for idx, i in enumerate(reversed(item.children))
                )
            )
    return flattend_tree
