-- Migration 0013: plan orders (PromptPay, manual confirm), order audit log, per-user plan limits
CREATE TABLE pay_orders (
  order_id      TEXT PRIMARY KEY,
  username      TEXT    NOT NULL,
  plan          TEXT    NOT NULL,
  amount_satang INTEGER NOT NULL CHECK (amount_satang > 0),
  status        TEXT    NOT NULL CHECK (status IN ('pending','paid','active','cancelled',
                          'refund_requested','refunded','refund_rejected','expired')),
  payload       TEXT,
  ledger_id     INTEGER,
  refund_ledger_id INTEGER,
  refund_reason TEXT,
  created_at    REAL    NOT NULL,
  pay_deadline  REAL    NOT NULL,
  paid_at       REAL,
  active_until  REAL,
  updated_at    REAL    NOT NULL
);
CREATE INDEX idx_pay_orders_user   ON pay_orders(username, created_at);
CREATE INDEX idx_pay_orders_status ON pay_orders(status);

-- every state change: who / when / from -> to
CREATE TABLE pay_order_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id    TEXT NOT NULL,
  from_status TEXT,
  to_status   TEXT NOT NULL,
  actor       TEXT NOT NULL,
  actor_role  TEXT,
  note        TEXT,
  at          REAL NOT NULL
);
CREATE INDEX idx_pay_events_order ON pay_order_events(order_id, id);

-- active paid plan per user: overrides the free daily_limit of the user's free-tier keys
CREATE TABLE org_plan_limits (
  username    TEXT PRIMARY KEY,
  plan        TEXT    NOT NULL,
  daily_limit INTEGER NOT NULL CHECK (daily_limit >= 0),
  order_id    TEXT,
  expires_at  REAL    NOT NULL
);
CREATE INDEX idx_plan_limits_exp ON org_plan_limits(expires_at);
