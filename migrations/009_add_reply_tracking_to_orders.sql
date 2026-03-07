-- Migration 009: Add reply tracking columns to orders table
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS reply_email_sent_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS waiting_for_client_reply BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS client_replied_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS client_reply_message_id TEXT,
  ADD COLUMN IF NOT EXISTS missing_fields_snapshot TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS orders_waiting_reply_idx
  ON orders (waiting_for_client_reply) WHERE waiting_for_client_reply = TRUE;
