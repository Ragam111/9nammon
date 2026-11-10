/** ค่าคงที่ของแดชบอร์ดบนพอร์ต 8421 — ไม่มี client secret ในไฟล์นี้ */

export const GOOGLE_CLIENT_ID =
  "456424591178-g3ufhccbhmnvt74ne7hfq27432b3sm19.apps.googleusercontent.com";

export const ALLOWED_ORIGINS = Object.freeze([
  "http://localhost:8421",
  "http://127.0.0.1:8421",
]);

/** 8420 = worker nodes, 8421 = main dashboard UI. localhost เท่านั้น */
export const WORKER_PORT = 8420;
export const DASHBOARD_PORT = 8421;

export const AUTH_PATH = "/auth/google";
export const CLUSTER_PATH = "/api/cluster/status";
export const LOG_STREAM_PATH = "/api/logs/stream";

export const MIN_POLL_MS = 5000;
export const POLL_MS = 8000;
export const LOG_CAP = 500;
/** ไม่ประมวลผลก้อนสตรีมใหญ่กว่านี้ในรอบเดียว */
export const MAX_CHUNK_BYTES = 32 * 1024;
