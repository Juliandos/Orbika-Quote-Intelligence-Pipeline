"""Mirror supplier catalogs into PostgreSQL.

Revision ID: 20260713_0003
Revises: 20260621_0002
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op

revision = "20260713_0003"
down_revision = "20260621_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE provider_catalog_snapshots (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          provider_id text NOT NULL,
          provider_name text,
          provider_type text,
          snapshot_date date,
          source_path text NOT NULL UNIQUE,
          source_hash text,
          product_count integer NOT NULL DEFAULT 0,
          provider_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          snapshot_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          notes jsonb NOT NULL DEFAULT '[]'::jsonb,
          status text NOT NULL DEFAULT 'loaded',
          created_at timestamptz NOT NULL DEFAULT now(),
          loaded_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE provider_products (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          snapshot_id uuid NOT NULL REFERENCES provider_catalog_snapshots(id) ON DELETE CASCADE,
          provider_id text NOT NULL,
          provider_name text,
          provider_type text,
          title text NOT NULL,
          normalized_title text,
          category_name text,
          subcategory_name text,
          brand text,
          reference text,
          sku text,
          supplier_item_code text,
          detail_url text,
          detail_url_hash text,
          raw_match_type text,
          requires_manual_confirmation boolean NOT NULL DEFAULT false,
          searchable_text text,
          searchable_tokens jsonb NOT NULL DEFAULT '[]'::jsonb,
          taxonomy_labels jsonb NOT NULL DEFAULT '[]'::jsonb,
          notes jsonb NOT NULL DEFAULT '[]'::jsonb,
          raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_provider_catalog_snapshots_provider_id_snapshot_date_desc
          ON provider_catalog_snapshots (provider_id, snapshot_date DESC);
        CREATE INDEX ix_provider_catalog_snapshots_source_hash
          ON provider_catalog_snapshots (source_hash);
        CREATE INDEX ix_provider_products_snapshot_id
          ON provider_products (snapshot_id);
        CREATE INDEX ix_provider_products_provider_id
          ON provider_products (provider_id);
        CREATE INDEX ix_provider_products_reference
          ON provider_products (reference);
        CREATE INDEX ix_provider_products_detail_url_hash
          ON provider_products (detail_url_hash);
        CREATE INDEX ix_provider_products_normalized_title
          ON provider_products (normalized_title);
        CREATE INDEX ix_provider_products_provider_id_snapshot_id
          ON provider_products (provider_id, snapshot_id);

        CREATE TRIGGER set_updated_at_provider_products
          BEFORE UPDATE ON provider_products
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS provider_products;
        DROP TABLE IF EXISTS provider_catalog_snapshots;
        """
    )
