-- Migration 0016: Stripe hosted Checkout (provider=stripe) + webhook event idempotency
-- pay_orders keeps the shared state machine; this side table marks provider=stripe orders
CREATE TABLE stripe_orders (
  order_id       TEXT PRIMARY KEY,
  provider       TEXT NOT NULL DEFAULT 'stripe' CHECK (provider = 'stripe'),
  session_id     TEXT,
  session_url    TEXT,
  payment_intent TEXT,
  state          TEXT NOT NULL CHECK (state IN ('pending','paid','failed','cancelled',
                   'review','refunded')),
  note           TEXT,
  refund_id      TEXT,
  created_at     REAL NOT NULL,
  updated_at     REAL NOT NULL
);
CREATE INDEX idx_stripe_orders_session ON stripe_orders(session_id);

-- every processed webhook event id (unique) -> replay / duplicate = no-op
CREATE TABLE stripe_events (
  event_id    TEXT PRIMARY KEY,
  type        TEXT NOT NULL,
  order_id    TEXT,
  result      TEXT NOT NULL,
  received_at REAL NOT NULL
);
