"""Shared helpers for building and resolving category paths.

Since categories.name is now unique per-parent rather than globally (see
migration l2m3n4o5p6q7), a bare name is no longer a reliable identifier
across the whole tree (two categories can both be named "Overig" under
different parents). Anywhere a category needs a stable string identifier
(sync export/import format v3, the dashboard/budget "hierarchical name"
display), we use a path built from the " > " separator, e.g.
"Vervoer > Auto > Onderhoud". This module is the single place that builds
or resolves such paths, so export and import never duplicate the logic.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category

PATH_SEPARATOR = " > "

# Sensible defaults applied to ancestor categories implicitly created while
# resolving a path that doesn't fully exist yet on the destination.
DEFAULT_ANCESTOR_CATEGORY_TYPE = "expense"
DEFAULT_ANCESTOR_IS_FIXED = False


def full_category_path(cat_id: int | None, cat_by_id: dict) -> str:
    """Build a hierarchical path like 'Vervoer > Auto > Onderhoud' for a
    category id, given a dict of {id: Category-like object with .name/.parent_id}.
    """
    parts = []
    seen = set()
    current = cat_id
    while current in cat_by_id:
        if current in seen:
            break
        seen.add(current)
        cat = cat_by_id[current]
        parts.append(cat.name)
        current = cat.parent_id
    parts.reverse()
    return PATH_SEPARATOR.join(parts)


def split_category_path(path: str) -> list[str]:
    """Split a 'Parent > Child > Leaf' path into its segments, trimming
    incidental whitespace around each segment."""
    return [p.strip() for p in path.split(PATH_SEPARATOR) if p.strip()]


def resolve_or_create_category_path(
    db: Session,
    path: str,
    path_index: dict[str, Category],
) -> Category | None:
    """Resolve a 'Parent > Child' path to its leaf Category, creating any
    missing segments (ancestors, or the leaf itself) with sensible defaults
    (category_type='expense', is_fixed=False).

    `path_index` caches already-resolved paths -> Category across a whole
    import call, so repeated lookups avoid re-hitting the DB and newly
    created categories are immediately visible to later resolutions.
    """
    segments = split_category_path(path)
    if not segments:
        return None

    parent: Category | None = None
    node: Category | None = None
    built: list[str] = []
    for segment in segments:
        built.append(segment)
        current_path = PATH_SEPARATOR.join(built)
        node = path_index.get(current_path)
        if node is None:
            parent_id = parent.id if parent else None
            node = db.execute(
                select(Category).where(Category.name == segment, Category.parent_id == parent_id)
            ).scalar_one_or_none()
        if node is None:
            node = Category(
                name=segment,
                parent_id=parent.id if parent else None,
                category_type=DEFAULT_ANCESTOR_CATEGORY_TYPE,
                is_fixed=DEFAULT_ANCESTOR_IS_FIXED,
            )
            db.add(node)
            db.flush()
        path_index[current_path] = node
        parent = node
    return node
