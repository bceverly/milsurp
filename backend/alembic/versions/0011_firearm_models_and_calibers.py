"""A canonical list of models, their makers and what they chamber.

Three facts the application kept guessing from the words in a title, and which
somebody who knows the trade could simply state:

*What a model is called.* Dealers name the model far more often than the maker,
and they name it several ways. "M1 Carbine" is also "US M1 Carbine", ".30 M1
Carbine" and "Carbine, Cal .30, M1".

*Who made it.* ``manufacturer_models`` could give a model exactly one maker,
which is wrong for most of the interesting ones -- the M1 Carbine was built by
Inland, Winchester, Rock-Ola, IBM, Underwood, Quality Hardware, National Postal
Meter, Standard Products and Saginaw. Worse, it forced a rule on top: a model
two makers claimed identified neither and was dropped from matching, because
picking whichever row came first would have been an accident of ordering. With
a join table both makers are simply on the model, and the model still says
which gun it is. That rule can go.

*What it chambers.* Also a list, and for a reason of its own: a model built
across decades is often chambered in more than one round. The Steyr M95 was
made in 8x50mmR and rebarreled wholesale to 8x56mmR between the wars, and both
are correct for a rifle sold today as "an M95". This needs the calibers table
underneath it, because the trade writes the same cartridge several ways and
they have to be one row before any of it is any use: ".32 ACP" and "7.65mm
Browning" are the same round, so are ".30-06" and "7.62x63mm", and until they
are one row a filter on either shows half the listings.

Every one of these tables can also hold a *pending* row -- a name a scan met
that nothing explains, written down once so an admin can rule on it, rather
than asked again on every scan and answered by nobody. Pending rows take no
part in matching.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = sa.String(16)
#: SQLAlchemy's Enum stores the member *name*, and every other status column
#: in this schema is uppercase for that reason -- scan_runs.status holds
#: 'SUCCESS', users.role holds 'ADMIN'. A default of 'approved' here reads
#: back as a value the enum does not recognize and every query raises.
_APPROVED = sa.text("'APPROVED'")


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("calibers"):
        op.create_table(
            "calibers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False, unique=True, index=True),
            sa.Column("aliases", sa.Text(), nullable=True),
            sa.Column("status", _STATUS, nullable=False, server_default=_APPROVED, index=True),
            sa.Column(
                "merged_into_id",
                sa.Integer(),
                sa.ForeignKey("calibers.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("first_seen_in", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("firearm_models"):
        op.create_table(
            "firearm_models",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False, unique=True, index=True),
            sa.Column("aliases", sa.Text(), nullable=True),
            sa.Column("kind", sa.String(32), nullable=True, index=True),
            sa.Column("status", _STATUS, nullable=False, server_default=_APPROVED, index=True),
            sa.Column(
                "merged_into_id",
                sa.Integer(),
                sa.ForeignKey("firearm_models.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "position", sa.Integer(), nullable=False, server_default=sa.text("1000"), index=True
            ),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.text("1"), index=True
            ),
            sa.Column("wikipedia_url", sa.String(500), nullable=True),
            sa.Column("first_seen_in", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("firearm_model_calibers"):
        op.create_table(
            "firearm_model_calibers",
            sa.Column(
                "firearm_model_id",
                sa.Integer(),
                sa.ForeignKey("firearm_models.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "caliber_id",
                sa.Integer(),
                sa.ForeignKey("calibers.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    if not inspector.has_table("firearm_model_manufacturers"):
        op.create_table(
            "firearm_model_manufacturers",
            sa.Column(
                "firearm_model_id",
                sa.Integer(),
                sa.ForeignKey("firearm_models.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "manufacturer_id",
                sa.Integer(),
                sa.ForeignKey("manufacturers.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    existing = _columns(bind, "manufacturers")
    if existing and "status" not in existing:
        op.add_column(
            "manufacturers",
            sa.Column("status", _STATUS, nullable=False, server_default=_APPROVED),
        )
        op.create_index("ix_manufacturers_status", "manufacturers", ["status"])
    if existing and "merged_into_id" not in existing:
        # No ForeignKey here. SQLite cannot add one to an existing table
        # without rebuilding it, and rebuilding a table an admin has been
        # editing is a much worse trade than a column the application
        # constrains itself. The ORM still declares the relationship, which is
        # what every reader goes through.
        op.add_column("manufacturers", sa.Column("merged_into_id", sa.Integer(), nullable=True))
        op.create_index("ix_manufacturers_merged_into_id", "manufacturers", ["merged_into_id"])
    if existing and "first_seen_in" not in existing:
        op.add_column("manufacturers", sa.Column("first_seen_in", sa.Text(), nullable=True))

    _carry_over_the_old_models(bind)


def _carry_over_the_old_models(bind) -> None:
    """Fold ``manufacturer_models`` into the new pair of tables.

    Every row becomes a model, and a name two makers claimed becomes *one*
    model with two makers -- which is the shape those rows were always
    describing and the reason for the change.

    The old table is left in place and unread. Dropping it is a one-way door
    on the only copy of a list an admin has been curating, and it costs
    nothing to keep; a later migration can remove it once this one has been
    running for a while.
    """
    inspector = sa.inspect(bind)
    if not inspector.has_table("manufacturer_models"):
        return
    if bind.execute(sa.text("SELECT COUNT(*) FROM firearm_models")).scalar_one():
        return  # Already carried over, or the admin has started their own list.

    rows = bind.execute(
        sa.text("SELECT manufacturer_id, name FROM manufacturer_models ORDER BY name")
    ).all()
    by_name: dict[str, list[int]] = {}
    for manufacturer_id, name in rows:
        cleaned = (name or "").strip()
        if cleaned:
            by_name.setdefault(cleaned, []).append(manufacturer_id)

    for name, manufacturer_ids in by_name.items():
        model_id = bind.execute(
            sa.text(
                "INSERT INTO firearm_models (name, status, position, enabled) "
                "VALUES (:name, 'APPROVED', 1000, 1) RETURNING id"
            ),
            {"name": name},
        ).scalar_one()
        for manufacturer_id in dict.fromkeys(manufacturer_ids):
            bind.execute(
                sa.text(
                    "INSERT INTO firearm_model_manufacturers "
                    "(firearm_model_id, manufacturer_id) VALUES (:model, :maker)"
                ),
                {"model": model_id, "maker": manufacturer_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in (
        "firearm_model_manufacturers",
        "firearm_model_calibers",
        "firearm_models",
        "calibers",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
    existing = _columns(bind, "manufacturers")
    for column in ("status", "merged_into_id", "first_seen_in"):
        if column in existing:
            op.drop_column("manufacturers", column)
