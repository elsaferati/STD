-- Migration 010: Add mail_to column to orders table
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS mail_to TEXT NOT NULL DEFAULT '';
