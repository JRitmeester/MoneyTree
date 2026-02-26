"""Resolve line item category strings to Category IDs and root ancestors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, CategoryMapping


@dataclass
class Resolver:
    cat_name_to_id: dict[str, int] = field(default_factory=dict)
    cat_id_to_cat: dict[int, Category] = field(default_factory=dict)
    mapping_dict: dict[str, int] = field(default_factory=dict)  # bank_category -> category_id
    children_by_parent: dict[Optional[int], list[int]] = field(default_factory=dict)


def build_resolver(db: Session) -> Resolver:
    """Build lookup structures from the database."""
    all_cats = db.execute(select(Category)).scalars().all()
    mappings = db.execute(select(CategoryMapping)).scalars().all()

    r = Resolver()
    for c in all_cats:
        r.cat_name_to_id[c.name] = c.id
        r.cat_id_to_cat[c.id] = c
        r.children_by_parent.setdefault(c.parent_id, []).append(c.id)

    for m in mappings:
        r.mapping_dict[m.bank_category] = m.category_id

    return r


def find_root(cat_id: int, resolver: Resolver) -> int:
    """Walk parent_id up to find the root ancestor."""
    seen = set()
    current = cat_id
    while current in resolver.cat_id_to_cat:
        cat = resolver.cat_id_to_cat[current]
        if cat.parent_id is None or cat.parent_id in seen:
            return current
        seen.add(current)
        current = cat.parent_id
    return current


def resolve_category(cat_string: str, resolver: Resolver) -> tuple[Optional[int], Optional[int]]:
    """Resolve a line item category string to (category_id, root_category_id).

    Returns (None, None) if unresolvable.
    """
    if not cat_string:
        return None, None

    cat_id: Optional[int] = None

    # 1. If contains ">", try path resolution
    if ">" in cat_string:
        parts = [p.strip() for p in cat_string.split(">") if p.strip()]
        parent_id: Optional[int] = None
        resolved = True
        for part in parts:
            # Find category with this name under parent_id
            found = False
            for cid, cat in resolver.cat_id_to_cat.items():
                if cat.name == part and cat.parent_id == parent_id:
                    parent_id = cid
                    found = True
                    break
            if not found:
                # Try without parent constraint (looser match)
                if part in resolver.cat_name_to_id:
                    parent_id = resolver.cat_name_to_id[part]
                    found = True
                else:
                    resolved = False
                    break
        if resolved and parent_id is not None:
            cat_id = parent_id

    # 2. Direct name lookup
    if cat_id is None:
        cat_id = resolver.cat_name_to_id.get(cat_string)

    if cat_id is None:
        return None, None

    # 3. If it's a bank category with a mapping, use the mapping target's root
    cat = resolver.cat_id_to_cat.get(cat_id)
    if cat and cat.is_bank_category and cat_string in resolver.mapping_dict:
        mapped_id = resolver.mapping_dict[cat_string]
        root_id = find_root(mapped_id, resolver)
        return cat_id, root_id

    # 4. Walk up to find root
    root_id = find_root(cat_id, resolver)
    return cat_id, root_id


def has_children(cat_id: int, resolver: Resolver) -> bool:
    """Check if a category has any children."""
    return len(resolver.children_by_parent.get(cat_id, [])) > 0


def get_direct_children(cat_id: int, resolver: Resolver) -> list[int]:
    """Get direct child category IDs."""
    return resolver.children_by_parent.get(cat_id, [])


def is_descendant_of(cat_id: int, ancestor_id: int, resolver: Resolver) -> bool:
    """Check if cat_id is a descendant of ancestor_id (or equal)."""
    if cat_id == ancestor_id:
        return True
    seen = set()
    current = cat_id
    while current in resolver.cat_id_to_cat:
        if current == ancestor_id:
            return True
        cat = resolver.cat_id_to_cat[current]
        if cat.parent_id is None or cat.parent_id in seen:
            return False
        seen.add(current)
        current = cat.parent_id
    return False


def find_direct_child_ancestor(cat_id: int, parent_id: int, resolver: Resolver) -> Optional[int]:
    """For a category that's a descendant of parent_id, find which direct child of parent_id
    is on the path. Returns None if cat_id == parent_id (directly at this level)."""
    if cat_id == parent_id:
        return None

    direct_children = set(get_direct_children(parent_id, resolver))

    # Walk up from cat_id until we find a direct child of parent_id
    seen = set()
    current = cat_id
    while current in resolver.cat_id_to_cat:
        if current in direct_children:
            return current
        cat = resolver.cat_id_to_cat[current]
        if cat.parent_id is None or cat.parent_id in seen:
            return None
        seen.add(current)
        current = cat.parent_id
    return None
