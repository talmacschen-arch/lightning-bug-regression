"""normalize case_categories.id_prefix

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-02

Shorten the id_prefix of the three case categories to a concise form:

    bug_regression   -> bug-
    extension        -> ext-
    external_systems -> xs-

Accompanying (same PR, not this migration): case filenames + YAML ``id``
fields + intra-notes cross references + the add-test-case skill rules +
test fixtures are all updated to the new prefixes.

``case_results.case_id`` / ``case_skip_list.case_id`` are FK-less Text
columns, so existing run history keeps the old strings (no error; only the
"view case" link in the run detail page no longer resolves to the renamed
file). That is expected local-data drift and out of scope here.

Up:
  * UPDATE case_categories SET id_prefix (concise form) WHERE name IN (...)
Down:
  * reverse UPDATE back to the previous prefixes
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_FORWARD = {
    "bug_regression": "bug-",
    "extension": "ext-",
    "external_systems": "xs-",
}

_REVERSE = {
    "bug_regression": "lg-bug-",
    "extension": "lg-ext-",
    "external_systems": "lg-xs-",
}


def _apply(mapping: dict[str, str]) -> None:
    for name, prefix in mapping.items():
        op.execute(
            f"UPDATE case_categories SET id_prefix = '{prefix}' WHERE name = '{name}'"
        )


def upgrade() -> None:
    _apply(_FORWARD)


def downgrade() -> None:
    _apply(_REVERSE)
