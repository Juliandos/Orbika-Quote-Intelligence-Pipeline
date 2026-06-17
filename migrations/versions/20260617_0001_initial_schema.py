"""Initial Orbika local PostgreSQL schema.

Revision ID: 20260617_0001
Revises:
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op

revision = "20260617_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS trigger AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TABLE emails (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          gmail_id text UNIQUE NOT NULL,
          message_id text,
          thread_id text,
          sender text NOT NULL,
          subject text,
          received_at timestamptz,
          internal_date_ms bigint,
          extraction_status text NOT NULL,
          quote_url_count integer NOT NULL DEFAULT 0,
          warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
          raw_excerpt text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE quotes (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          quote_key text UNIQUE NOT NULL,
          email_id uuid REFERENCES emails(id),
          aviso_id text,
          insurer text,
          source_subject text,
          quote_url_masked text,
          quote_url_hash text,
          load_status text,
          status text NOT NULL,
          priority text DEFAULT 'normal',
          received_at timestamptz,
          processed_at timestamptz,
          ready_for_review_at timestamptz,
          sent_at timestamptz,
          last_error text,
          warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
          source_file_path text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT quotes_status_check CHECK (
            status IN (
              'new',
              'pending_extraction',
              'extracting',
              'extracted',
              'pending_matching',
              'matching',
              'pending_agentic_review',
              'agentic_reviewing',
              'ready_for_review',
              'needs_manual_review',
              'quoted',
              'sent',
              'failed',
              'needs_retry',
              'archived'
            )
          )
        );

        CREATE TABLE vehicles (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          quote_id uuid UNIQUE REFERENCES quotes(id) ON DELETE CASCADE,
          plate text,
          brand text,
          line text,
          version text,
          model_year integer,
          vin text,
          color text,
          raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE workshops (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          quote_id uuid UNIQUE REFERENCES quotes(id) ON DELETE CASCADE,
          commercial_name text,
          delivery_workshop text,
          city text,
          address text,
          phone text,
          raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE parts (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          quote_id uuid REFERENCES quotes(id) ON DELETE CASCADE,
          position integer NOT NULL,
          name text NOT NULL,
          normalized_name text,
          requested_reference text,
          quantity numeric,
          raw_status text,
          status text NOT NULL DEFAULT 'requested',
          observations text,
          raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT parts_status_check CHECK (
            status IN (
              'requested',
              'matched',
              'no_match',
              'needs_review',
              'accepted',
              'discarded'
            )
          )
        );

        CREATE TABLE supplier_matches (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          part_id uuid REFERENCES parts(id) ON DELETE CASCADE,
          provider_id text NOT NULL,
          provider_name text,
          product_name text NOT NULL,
          reference text,
          sku text,
          brand text,
          category_name text,
          subcategory_name text,
          detail_url text,
          detail_url_hash text,
          price numeric,
          currency text DEFAULT 'COP',
          availability text,
          match_type text,
          score_percent integer NOT NULL,
          rank integer,
          reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
          risk_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
          snapshot_ref text,
          raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT supplier_matches_score_percent_check CHECK (
            score_percent >= 0 AND score_percent <= 100
          )
        );

        CREATE TABLE agentic_reviews (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          part_id uuid REFERENCES parts(id) ON DELETE CASCADE,
          top_match_id uuid REFERENCES supplier_matches(id),
          reviewer_mode text NOT NULL,
          model text,
          status text NOT NULL,
          confidence_percent integer,
          summary_comment text,
          selected_options jsonb NOT NULL DEFAULT '[]'::jsonb,
          risk_notes jsonb NOT NULL DEFAULT '[]'::jsonb,
          preference_notes jsonb NOT NULL DEFAULT '[]'::jsonb,
          trace_file_path text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT agentic_reviews_confidence_percent_check CHECK (
            confidence_percent IS NULL
            OR (confidence_percent >= 0 AND confidence_percent <= 100)
          )
        );

        CREATE TABLE customer_preferences (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          scope text NOT NULL,
          scope_key text,
          preference_type text NOT NULL,
          value jsonb NOT NULL,
          notes text,
          active boolean NOT NULL DEFAULT true,
          created_by text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE tasks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          task_key text UNIQUE,
          kind text NOT NULL,
          status text NOT NULL,
          triggered_by text,
          started_at timestamptz,
          finished_at timestamptz,
          exit_code integer,
          input_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          result_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          counters jsonb NOT NULL DEFAULT '{}'::jsonb,
          log_file_path text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT tasks_status_check CHECK (
            status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'blocked')
          )
        );

        CREATE TABLE events (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          event_type text NOT NULL,
          quote_id uuid REFERENCES quotes(id),
          task_id uuid REFERENCES tasks(id),
          severity text NOT NULL DEFAULT 'info',
          message text,
          payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE daily_summaries (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          summary_date date UNIQUE NOT NULL,
          quotes_total integer NOT NULL DEFAULT 0,
          quotes_ready integer NOT NULL DEFAULT 0,
          quotes_failed integer NOT NULL DEFAULT 0,
          parts_total integer NOT NULL DEFAULT 0,
          parts_with_matches integer NOT NULL DEFAULT 0,
          provider_hits jsonb NOT NULL DEFAULT '{}'::jsonb,
          payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_emails_received_at_desc ON emails (received_at DESC);
        CREATE INDEX ix_emails_extraction_status ON emails (extraction_status);
        CREATE INDEX ix_quotes_status ON quotes (status);
        CREATE INDEX ix_quotes_received_at_desc ON quotes (received_at DESC);
        CREATE INDEX ix_quotes_aviso_id ON quotes (aviso_id);
        CREATE INDEX ix_quotes_source_subject ON quotes (source_subject);
        CREATE INDEX ix_quotes_status_received_at_desc ON quotes (status, received_at DESC);
        CREATE INDEX ix_vehicles_plate ON vehicles (plate);
        CREATE INDEX ix_vehicles_brand_line_model_year ON vehicles (brand, line, model_year);
        CREATE INDEX ix_vehicles_vin ON vehicles (vin);
        CREATE INDEX ix_workshops_commercial_name ON workshops (commercial_name);
        CREATE INDEX ix_workshops_city ON workshops (city);
        CREATE UNIQUE INDEX ux_parts_quote_id_position ON parts (quote_id, position);
        CREATE INDEX ix_parts_status ON parts (status);
        CREATE INDEX ix_parts_normalized_name ON parts (normalized_name);
        CREATE INDEX ix_supplier_matches_part_id ON supplier_matches (part_id);
        CREATE INDEX ix_supplier_matches_provider_id ON supplier_matches (provider_id);
        CREATE INDEX ix_supplier_matches_part_id_rank ON supplier_matches (part_id, rank);
        CREATE INDEX ix_supplier_matches_part_id_score_percent_desc
          ON supplier_matches (part_id, score_percent DESC);
        CREATE INDEX ix_supplier_matches_match_type ON supplier_matches (match_type);
        CREATE INDEX ix_agentic_reviews_part_id ON agentic_reviews (part_id);
        CREATE INDEX ix_agentic_reviews_status ON agentic_reviews (status);
        CREATE INDEX ix_agentic_reviews_created_at_desc ON agentic_reviews (created_at DESC);
        CREATE INDEX ix_customer_preferences_scope_scope_key
          ON customer_preferences (scope, scope_key);
        CREATE INDEX ix_customer_preferences_preference_type
          ON customer_preferences (preference_type);
        CREATE INDEX ix_customer_preferences_active_true
          ON customer_preferences (active)
          WHERE active = true;
        CREATE INDEX ix_tasks_kind ON tasks (kind);
        CREATE INDEX ix_tasks_status ON tasks (status);
        CREATE INDEX ix_tasks_started_at_desc ON tasks (started_at DESC);
        CREATE INDEX ix_events_created_at_desc ON events (created_at DESC);
        CREATE INDEX ix_events_event_type ON events (event_type);
        CREATE INDEX ix_events_quote_id ON events (quote_id);
        CREATE INDEX ix_events_task_id ON events (task_id);
        CREATE INDEX ix_daily_summaries_summary_date_desc
          ON daily_summaries (summary_date DESC);

        CREATE TRIGGER set_updated_at_emails
          BEFORE UPDATE ON emails
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_quotes
          BEFORE UPDATE ON quotes
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_vehicles
          BEFORE UPDATE ON vehicles
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_workshops
          BEFORE UPDATE ON workshops
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_parts
          BEFORE UPDATE ON parts
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_supplier_matches
          BEFORE UPDATE ON supplier_matches
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_agentic_reviews
          BEFORE UPDATE ON agentic_reviews
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_customer_preferences
          BEFORE UPDATE ON customer_preferences
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_tasks
          BEFORE UPDATE ON tasks
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER set_updated_at_daily_summaries
          BEFORE UPDATE ON daily_summaries
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS daily_summaries;
        DROP TABLE IF EXISTS events;
        DROP TABLE IF EXISTS tasks;
        DROP TABLE IF EXISTS customer_preferences;
        DROP TABLE IF EXISTS agentic_reviews;
        DROP TABLE IF EXISTS supplier_matches;
        DROP TABLE IF EXISTS parts;
        DROP TABLE IF EXISTS workshops;
        DROP TABLE IF EXISTS vehicles;
        DROP TABLE IF EXISTS quotes;
        DROP TABLE IF EXISTS emails;
        DROP FUNCTION IF EXISTS set_updated_at();
        """
    )
