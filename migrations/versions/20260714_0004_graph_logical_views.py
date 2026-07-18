"""Add logical graph views over PostgreSQL quote and provider data.

Revision ID: 20260714_0004
Revises: 20260713_0003
Create Date: 2026-07-14
"""

from __future__ import annotations

from alembic import op

revision = "20260714_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS graph_edges;
        DROP VIEW IF EXISTS graph_nodes;

        CREATE VIEW graph_nodes AS
        WITH latest_provider_snapshot AS (
          SELECT DISTINCT ON (pcs.provider_id)
            pcs.provider_id,
            pcs.provider_name,
            pcs.provider_type,
            pcs.snapshot_date,
            pcs.source_path,
            pcs.product_count,
            pcs.provider_metadata,
            pcs.snapshot_metadata,
            pcs.notes,
            pcs.loaded_at
          FROM provider_catalog_snapshots pcs
          ORDER BY pcs.provider_id, pcs.snapshot_date DESC NULLS LAST, pcs.loaded_at DESC, pcs.id DESC
        )
        SELECT
          'email:' || e.id::text AS node_key,
          'email' AS node_type,
          e.id::text AS entity_id,
          q.quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          COALESCE(e.subject, e.sender, e.gmail_id) AS label,
          COALESCE(e.extraction_status, 'unknown') AS summary,
          jsonb_build_object(
            'gmail_id', e.gmail_id,
            'message_id', e.message_id,
            'thread_id', e.thread_id,
            'sender', e.sender,
            'subject', e.subject,
            'received_at', e.received_at,
            'extraction_status', e.extraction_status,
            'quote_url_count', e.quote_url_count,
            'raw_excerpt', e.raw_excerpt
          ) AS payload,
          e.created_at AS created_at
        FROM emails e
        LEFT JOIN quotes q ON q.email_id = e.id

        UNION ALL

        SELECT
          'quote:' || q.id::text AS node_key,
          'quote' AS node_type,
          q.id::text AS entity_id,
          q.quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          COALESCE(q.source_subject, q.quote_key) AS label,
          COALESCE(q.status, 'unknown') AS summary,
          jsonb_build_object(
            'aviso_id', q.aviso_id,
            'insurer', q.insurer,
            'status', q.status,
            'load_status', q.load_status,
            'priority', q.priority,
            'received_at', q.received_at,
            'processed_at', q.processed_at,
            'ready_for_review_at', q.ready_for_review_at,
            'sent_at', q.sent_at,
            'source_file_path', q.source_file_path,
            'warnings', q.warnings
          ) AS payload,
          q.created_at AS created_at
        FROM quotes q

        UNION ALL

        SELECT
          'vehicle:' || v.id::text AS node_key,
          'vehicle' AS node_type,
          v.id::text AS entity_id,
          q.quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          COALESCE(v.brand || ' ' || v.line, v.plate, v.vin, 'vehicle') AS label,
          COALESCE(v.model_year::text, 'vehicle') AS summary,
          jsonb_build_object(
            'plate', v.plate,
            'brand', v.brand,
            'line', v.line,
            'version', v.version,
            'model_year', v.model_year,
            'vin', v.vin,
            'color', v.color
          ) AS payload,
          v.created_at AS created_at
        FROM vehicles v
        JOIN quotes q ON q.id = v.quote_id

        UNION ALL

        SELECT
          'workshop:' || w.id::text AS node_key,
          'workshop' AS node_type,
          w.id::text AS entity_id,
          q.quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          COALESCE(w.commercial_name, w.delivery_workshop, w.city, 'workshop') AS label,
          COALESCE(w.city, 'workshop') AS summary,
          jsonb_build_object(
            'commercial_name', w.commercial_name,
            'delivery_workshop', w.delivery_workshop,
            'city', w.city,
            'address', w.address,
            'phone', w.phone
          ) AS payload,
          w.created_at AS created_at
        FROM workshops w
        JOIN quotes q ON q.id = w.quote_id

        UNION ALL

        SELECT
          'part:' || p.id::text AS node_key,
          'part' AS node_type,
          p.id::text AS entity_id,
          q.quote_key,
          p.id AS part_id,
          NULL::text AS provider_id,
          p.name AS label,
          COALESCE(p.status, 'requested') AS summary,
          jsonb_build_object(
            'position', p.position,
            'name', p.name,
            'normalized_name', p.normalized_name,
            'requested_reference', p.requested_reference,
            'quantity', p.quantity,
            'raw_status', p.raw_status,
            'observations', p.observations
          ) AS payload,
          p.created_at AS created_at
        FROM parts p
        JOIN quotes q ON q.id = p.quote_id

        UNION ALL

        SELECT
          'supplier_match:' || sm.id::text AS node_key,
          'supplier_match' AS node_type,
          sm.id::text AS entity_id,
          q.quote_key,
          sm.part_id,
          sm.provider_id,
          sm.product_name AS label,
          COALESCE(sm.match_type, 'unknown') || ' / ' || COALESCE(sm.score_percent::text, '0') || '%' AS summary,
          jsonb_build_object(
            'provider_id', sm.provider_id,
            'provider_name', sm.provider_name,
            'product_name', sm.product_name,
            'reference', sm.reference,
            'sku', sm.sku,
            'brand', sm.brand,
            'category_name', sm.category_name,
            'subcategory_name', sm.subcategory_name,
            'detail_url', sm.detail_url,
            'detail_url_hash', sm.detail_url_hash,
            'price', sm.price,
            'currency', sm.currency,
            'availability', sm.availability,
            'match_type', sm.match_type,
            'score_percent', sm.score_percent,
            'rank', sm.rank,
            'reasons', sm.reasons,
            'risk_flags', sm.risk_flags,
            'snapshot_ref', sm.snapshot_ref
          ) AS payload,
          sm.created_at AS created_at
        FROM supplier_matches sm
        JOIN parts p ON p.id = sm.part_id
        JOIN quotes q ON q.id = p.quote_id

        UNION ALL

        SELECT
          'agentic_review:' || ar.id::text AS node_key,
          'agentic_review' AS node_type,
          ar.id::text AS entity_id,
          q.quote_key,
          ar.part_id,
          NULL::text AS provider_id,
          COALESCE(ar.reviewer_mode, 'agentic review') AS label,
          COALESCE(ar.status, 'unknown') AS summary,
          jsonb_build_object(
            'reviewer_mode', ar.reviewer_mode,
            'model', ar.model,
            'status', ar.status,
            'top_match_id', ar.top_match_id,
            'confidence_percent', ar.confidence_percent,
            'summary_comment', ar.summary_comment,
            'selected_options', ar.selected_options,
            'risk_notes', ar.risk_notes,
            'preference_notes', ar.preference_notes,
            'trace_file_path', ar.trace_file_path
          ) AS payload,
          ar.created_at AS created_at
        FROM agentic_reviews ar
        JOIN parts p ON p.id = ar.part_id
        JOIN quotes q ON q.id = p.quote_id

        UNION ALL

        SELECT
          'provider:' || lps.provider_id AS node_key,
          'provider' AS node_type,
          lps.provider_id AS entity_id,
          NULL::text AS quote_key,
          NULL::uuid AS part_id,
          lps.provider_id,
          COALESCE(lps.provider_name, lps.provider_id) AS label,
          COALESCE(lps.provider_type, 'catalog') AS summary,
          jsonb_build_object(
            'provider_name', lps.provider_name,
            'provider_type', lps.provider_type,
            'snapshot_date', lps.snapshot_date,
            'source_path', lps.source_path,
            'product_count', lps.product_count,
            'provider_metadata', lps.provider_metadata,
            'snapshot_metadata', lps.snapshot_metadata,
            'notes', lps.notes
          ) AS payload,
          lps.loaded_at AS created_at
        FROM latest_provider_snapshot lps

        UNION ALL

        SELECT
          'provider_snapshot:' || pcs.id::text AS node_key,
          'provider_snapshot' AS node_type,
          pcs.id::text AS entity_id,
          NULL::text AS quote_key,
          NULL::uuid AS part_id,
          pcs.provider_id,
          COALESCE(pcs.provider_name, pcs.provider_id) AS label,
          COALESCE(pcs.provider_type, 'catalog') AS summary,
          jsonb_build_object(
            'provider_id', pcs.provider_id,
            'provider_name', pcs.provider_name,
            'provider_type', pcs.provider_type,
            'snapshot_date', pcs.snapshot_date,
            'source_path', pcs.source_path,
            'source_hash', pcs.source_hash,
            'product_count', pcs.product_count,
            'provider_metadata', pcs.provider_metadata,
            'snapshot_metadata', pcs.snapshot_metadata,
            'notes', pcs.notes,
            'status', pcs.status
          ) AS payload,
          pcs.loaded_at AS created_at
        FROM provider_catalog_snapshots pcs

        UNION ALL

        SELECT
          'provider_product:' || pp.id::text AS node_key,
          'provider_product' AS node_type,
          pp.id::text AS entity_id,
          NULL::text AS quote_key,
          NULL::uuid AS part_id,
          pp.provider_id,
          pp.title AS label,
          COALESCE(pp.category_name, pp.provider_name, pp.provider_id) AS summary,
          jsonb_build_object(
            'snapshot_id', pp.snapshot_id,
            'provider_id', pp.provider_id,
            'provider_name', pp.provider_name,
            'provider_type', pp.provider_type,
            'title', pp.title,
            'normalized_title', pp.normalized_title,
            'category_name', pp.category_name,
            'subcategory_name', pp.subcategory_name,
            'brand', pp.brand,
            'reference', pp.reference,
            'sku', pp.sku,
            'supplier_item_code', pp.supplier_item_code,
            'detail_url', pp.detail_url,
            'detail_url_hash', pp.detail_url_hash,
            'raw_match_type', pp.raw_match_type,
            'requires_manual_confirmation', pp.requires_manual_confirmation,
            'searchable_text', pp.searchable_text,
            'searchable_tokens', pp.searchable_tokens,
            'taxonomy_labels', pp.taxonomy_labels,
            'notes', pp.notes
          ) AS payload,
          pp.created_at AS created_at
        FROM provider_products pp

        UNION ALL

        SELECT
          'customer_preference:' || cp.id::text AS node_key,
          'customer_preference' AS node_type,
          cp.id::text AS entity_id,
          NULL::text AS quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          COALESCE(cp.preference_type, cp.scope) AS label,
          CASE WHEN cp.active THEN 'active' ELSE 'inactive' END AS summary,
          jsonb_build_object(
            'scope', cp.scope,
            'scope_key', cp.scope_key,
            'preference_type', cp.preference_type,
            'value', cp.value,
            'notes', cp.notes,
            'active', cp.active,
            'created_by', cp.created_by
          ) AS payload,
          cp.created_at AS created_at
        FROM customer_preferences cp;

        CREATE VIEW graph_edges AS
        SELECT
          'email_to_quote:' || q.id::text AS edge_key,
          'email_to_quote' AS edge_type,
          'email:' || e.id::text AS source_node_key,
          'email' AS source_node_type,
          e.id::text AS source_entity_id,
          'quote:' || q.id::text AS target_node_key,
          'quote' AS target_node_type,
          q.id::text AS target_entity_id,
          q.quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          'email produced quote' AS label,
          jsonb_build_object(
            'gmail_id', e.gmail_id,
            'sender', e.sender,
            'subject', e.subject
          ) AS evidence,
          q.created_at AS created_at
        FROM quotes q
        JOIN emails e ON e.id = q.email_id

        UNION ALL

        SELECT
          'quote_to_vehicle:' || v.id::text AS edge_key,
          'quote_to_vehicle' AS edge_type,
          'quote:' || q.id::text AS source_node_key,
          'quote' AS source_node_type,
          q.id::text AS source_entity_id,
          'vehicle:' || v.id::text AS target_node_key,
          'vehicle' AS target_node_type,
          v.id::text AS target_entity_id,
          q.quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          'quote vehicle context' AS label,
          jsonb_build_object(
            'plate', v.plate,
            'brand', v.brand,
            'line', v.line,
            'version', v.version,
            'model_year', v.model_year,
            'vin', v.vin
          ) AS evidence,
          v.created_at AS created_at
        FROM vehicles v
        JOIN quotes q ON q.id = v.quote_id

        UNION ALL

        SELECT
          'quote_to_workshop:' || w.id::text AS edge_key,
          'quote_to_workshop' AS edge_type,
          'quote:' || q.id::text AS source_node_key,
          'quote' AS source_node_type,
          q.id::text AS source_entity_id,
          'workshop:' || w.id::text AS target_node_key,
          'workshop' AS target_node_type,
          w.id::text AS target_entity_id,
          q.quote_key,
          NULL::uuid AS part_id,
          NULL::text AS provider_id,
          'quote workshop context' AS label,
          jsonb_build_object(
            'commercial_name', w.commercial_name,
            'delivery_workshop', w.delivery_workshop,
            'city', w.city
          ) AS evidence,
          w.created_at AS created_at
        FROM workshops w
        JOIN quotes q ON q.id = w.quote_id

        UNION ALL

        SELECT
          'quote_to_part:' || p.id::text AS edge_key,
          'quote_to_part' AS edge_type,
          'quote:' || q.id::text AS source_node_key,
          'quote' AS source_node_type,
          q.id::text AS source_entity_id,
          'part:' || p.id::text AS target_node_key,
          'part' AS target_node_type,
          p.id::text AS target_entity_id,
          q.quote_key,
          p.id AS part_id,
          NULL::text AS provider_id,
          'requested part' AS label,
          jsonb_build_object(
            'position', p.position,
            'name', p.name,
            'requested_reference', p.requested_reference,
            'quantity', p.quantity,
            'status', p.status
          ) AS evidence,
          p.created_at AS created_at
        FROM parts p
        JOIN quotes q ON q.id = p.quote_id

        UNION ALL

        SELECT
          'part_to_supplier_match:' || sm.id::text AS edge_key,
          'part_to_supplier_match' AS edge_type,
          'part:' || p.id::text AS source_node_key,
          'part' AS source_node_type,
          p.id::text AS source_entity_id,
          'supplier_match:' || sm.id::text AS target_node_key,
          'supplier_match' AS target_node_type,
          sm.id::text AS target_entity_id,
          q.quote_key,
          p.id AS part_id,
          sm.provider_id,
          'supplier candidate' AS label,
          jsonb_build_object(
            'provider_id', sm.provider_id,
            'provider_name', sm.provider_name,
            'product_name', sm.product_name,
            'reference', sm.reference,
            'sku', sm.sku,
            'detail_url', sm.detail_url,
            'detail_url_hash', sm.detail_url_hash,
            'match_type', sm.match_type,
            'score_percent', sm.score_percent,
            'rank', sm.rank,
            'risk_flags', sm.risk_flags,
            'reasons', sm.reasons
          ) AS evidence,
          sm.created_at AS created_at
        FROM supplier_matches sm
        JOIN parts p ON p.id = sm.part_id
        JOIN quotes q ON q.id = p.quote_id

        UNION ALL

        SELECT
          'part_to_agentic_review:' || ar.id::text AS edge_key,
          'part_to_agentic_review' AS edge_type,
          'part:' || p.id::text AS source_node_key,
          'part' AS source_node_type,
          p.id::text AS source_entity_id,
          'agentic_review:' || ar.id::text AS target_node_key,
          'agentic_review' AS target_node_type,
          ar.id::text AS target_entity_id,
          q.quote_key,
          p.id AS part_id,
          NULL::text AS provider_id,
          'agentic review' AS label,
          jsonb_build_object(
            'reviewer_mode', ar.reviewer_mode,
            'model', ar.model,
            'status', ar.status,
            'confidence_percent', ar.confidence_percent,
            'top_match_id', ar.top_match_id
          ) AS evidence,
          ar.created_at AS created_at
        FROM agentic_reviews ar
        JOIN parts p ON p.id = ar.part_id
        JOIN quotes q ON q.id = p.quote_id

        UNION ALL

        SELECT
          'agentic_review_to_supplier_match:' || ar.id::text AS edge_key,
          'agentic_review_to_supplier_match' AS edge_type,
          'agentic_review:' || ar.id::text AS source_node_key,
          'agentic_review' AS source_node_type,
          ar.id::text AS source_entity_id,
          'supplier_match:' || sm.id::text AS target_node_key,
          'supplier_match' AS target_node_type,
          sm.id::text AS target_entity_id,
          q.quote_key,
          p.id AS part_id,
          sm.provider_id,
          'top match selected by review' AS label,
          jsonb_build_object(
            'top_match_id', ar.top_match_id,
            'confidence_percent', ar.confidence_percent,
            'summary_comment', ar.summary_comment
          ) AS evidence,
          ar.created_at AS created_at
        FROM agentic_reviews ar
        JOIN parts p ON p.id = ar.part_id
        JOIN quotes q ON q.id = p.quote_id
        JOIN supplier_matches sm ON sm.id = ar.top_match_id

        UNION ALL

        SELECT
          'provider_to_snapshot:' || pcs.id::text AS edge_key,
          'provider_to_snapshot' AS edge_type,
          'provider:' || pcs.provider_id AS source_node_key,
          'provider' AS source_node_type,
          pcs.provider_id AS source_entity_id,
          'provider_snapshot:' || pcs.id::text AS target_node_key,
          'provider_snapshot' AS target_node_type,
          pcs.id::text AS target_entity_id,
          NULL::text AS quote_key,
          NULL::uuid AS part_id,
          pcs.provider_id,
          'provider snapshot' AS label,
          jsonb_build_object(
            'snapshot_date', pcs.snapshot_date,
            'source_path', pcs.source_path,
            'product_count', pcs.product_count
          ) AS evidence,
          pcs.loaded_at AS created_at
        FROM provider_catalog_snapshots pcs

        UNION ALL

        SELECT
          'snapshot_to_product:' || pp.id::text AS edge_key,
          'snapshot_to_product' AS edge_type,
          'provider_snapshot:' || pp.snapshot_id::text AS source_node_key,
          'provider_snapshot' AS source_node_type,
          pp.snapshot_id::text AS source_entity_id,
          'provider_product:' || pp.id::text AS target_node_key,
          'provider_product' AS target_node_type,
          pp.id::text AS target_entity_id,
          NULL::text AS quote_key,
          NULL::uuid AS part_id,
          pp.provider_id,
          'catalog product' AS label,
          jsonb_build_object(
            'title', pp.title,
            'reference', pp.reference,
            'sku', pp.sku,
            'detail_url_hash', pp.detail_url_hash
          ) AS evidence,
          pp.created_at AS created_at
        FROM provider_products pp

        UNION ALL

        SELECT
          'supplier_match_to_product:' || sm.id::text AS edge_key,
          'supplier_match_to_product' AS edge_type,
          'supplier_match:' || sm.id::text AS source_node_key,
          'supplier_match' AS source_node_type,
          sm.id::text AS source_entity_id,
          'provider_product:' || pp.id::text AS target_node_key,
          'provider_product' AS target_node_type,
          pp.id::text AS target_entity_id,
          q.quote_key,
          sm.part_id,
          sm.provider_id,
          'resolved product' AS label,
          jsonb_build_object(
            'provider_id', sm.provider_id,
            'detail_url_hash', sm.detail_url_hash,
            'provider_product_id', pp.id,
            'product_title', pp.title
          ) AS evidence,
          sm.created_at AS created_at
        FROM supplier_matches sm
        JOIN parts p ON p.id = sm.part_id
        JOIN quotes q ON q.id = p.quote_id
        JOIN provider_products pp
          ON pp.provider_id = sm.provider_id
         AND pp.detail_url_hash = sm.detail_url_hash
        WHERE sm.detail_url_hash IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS graph_edges;
        DROP VIEW IF EXISTS graph_nodes;
        """
    )



