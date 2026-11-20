window.REA_DATA = {
  "generated": "2026-11-19",
  "app": "Claude desktop 5.11492.5.0 (app.asar)",
  "rea": "rea-agents 6.9.0",
  "runs": [
    {
      "label": "รอบที่ 1: entry index.pre.js",
      "file": ".vite/build/index.pre.js",
      "log": "run.log",
      "evidence_id": "ev_299fe27a0644f9b3...",
      "sources_selected": [
        ".vite/build/index.pre.js"
      ],
      "unselected_files": 996,
      "parsed_js": 1,
      "skipped_js": 0,
      "parse_failures": 0,
      "ipc_main_handlers": 0,
      "ipc_renderer_listeners": 0,
      "sender_validation_observations": 0,
      "coverage": {
        "application": "partial",
        "semantic": "partial",
        "static_not_examined": 780
      },
      "unknowns": {
        "application": 992,
        "semantic": 29360
      },
      "limitations": [
        "6 integrity contradiction(s) were recorded; mismatched content is observed-untrusted.",
        "Artifact integrity metadata contradicts observed bytes at node_modules/@ant/claude-native/claude-native-binding.node; the observed bytes are untrusted.",
        "Artifact integrity metadata contradicts observed bytes at node_modules/node-pty/prebuilds/win32-x64/conpty.node; the observed bytes are untrusted.",
        "Artifact integrity metadata contradicts observed bytes at node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node; the observed bytes are untrusted."
      ]
    },
    {
      "label": "รอบที่ 2: index.pre.js + 2 chunk",
      "file": "index.pre.js, index.chunk-Bj6yHbbm.js, index.chunk-DL8fZzVo.js",
      "log": "run-ipc.log",
      "evidence_id": "ev_550ae6815815468f...",
      "sources_selected": [
        ".vite/build/index.pre.js",
        ".vite/build/index.chunk-Bj6yHbbm.js",
        ".vite/build/index.chunk-DL8fZzVo.js"
      ],
      "unselected_files": 994,
      "parsed_js": 2,
      "skipped_js": 1,
      "parse_failures": 0,
      "ipc_main_handlers": 0,
      "ipc_renderer_listeners": 0,
      "sender_validation_observations": 11,
      "coverage": {
        "application": "partial",
        "semantic": "partial",
        "static_not_examined": 779
      },
      "unknowns": {
        "application": 991,
        "semantic": 49348
      },
      "limitations": [
        ".vite/build/index.chunk-DL8fZzVo.js: Resource constraint during analyze_javascript_application: Owned JavaScript worker exhausted its 1024 MiB V8 old-space heap (max_heap_mb) while analyzing .vite/build/index.chunk-DL8fZzVo.js ...",
        "6 integrity contradiction(s) were recorded; mismatched content is observed-untrusted.",
        "Artifact integrity metadata contradicts observed bytes at node_modules/@ant/claude-native/claude-native-binding.node; the observed bytes are untrusted.",
        "Artifact integrity metadata contradicts observed bytes at node_modules/node-pty/prebuilds/win32-x64/conpty.node; the observed bytes are untrusted."
      ]
    },
    {
      "label": "รอบที่ 3: chunk 7.5 MB ตัวเดียว",
      "file": ".vite/build/index.chunk-DL8fZzVo.js",
      "log": "run-dl8f.log",
      "evidence_id": "ev_247565d4944c58d7...",
      "sources_selected": [
        ".vite/build/index.chunk-DL8fZzVo.js"
      ],
      "unselected_files": 996,
      "parsed_js": 0,
      "skipped_js": 1,
      "parse_failures": 0,
      "ipc_main_handlers": 0,
      "ipc_renderer_listeners": 0,
      "sender_validation_observations": 0,
      "coverage": {
        "application": "partial",
        "semantic": "partial",
        "static_not_examined": 781
      },
      "unknowns": {
        "application": 993,
        "semantic": 9372
      },
      "limitations": [
        ".vite/build/index.chunk-DL8fZzVo.js: Resource constraint during analyze_javascript_application: Owned JavaScript worker exhausted its 1536 MiB V8 old-space heap (max_heap_mb) while analyzing .vite/build/index.chunk-DL8fZzVo.js ...",
        "6 integrity contradiction(s) were recorded; mismatched content is observed-untrusted.",
        "Artifact integrity metadata contradicts observed bytes at node_modules/@ant/claude-native/claude-native-binding.node; the observed bytes are untrusted.",
        "Artifact integrity metadata contradicts observed bytes at node_modules/node-pty/prebuilds/win32-x64/conpty.node; the observed bytes are untrusted."
      ]
    }
  ],
  "handlers": [
    {
      "channel": "ListMcpServers",
      "file": "index.chunk-DL8fZzVo.js",
      "api": "handle (ผ่าน sns)",
      "check": "ok",
      "note": "ตรวจ senderFrame: top frame + host allowlist (b4o)"
    },
    {
      "channel": "ConnectToMcpServer",
      "file": "index.chunk-DL8fZzVo.js",
      "api": "handle (ผ่าน sns)",
      "check": "ok",
      "note": "ตรวจ senderFrame + sender ต้องเป็น webContents ของหน้าหลัก"
    },
    {
      "channel": "RequestOpenMcpSettings",
      "file": "index.chunk-DL8fZzVo.js",
      "api": "handle",
      "check": "ok",
      "note": "ตรวจ senderFrame ด้วย b4o"
    },
    {
      "channel": "servesPage",
      "file": "index.chunk-Bj6yHbbm.js",
      "api": "on",
      "check": "ok",
      "note": "senderFrame ต้องเป็น sender.mainFrame + URL ผ่านการตรวจ"
    },
    {
      "channel": "web-store answer",
      "file": "index.chunk-Bj6yHbbm.js",
      "api": "handle",
      "check": "ok",
      "note": "method answer() เรียก ax(): top frame, origin ของ Chrome Web Store, session"
    },
    {
      "channel": "start, scope, envelope, structured-log, metric, status",
      "file": "index.pre.js",
      "api": "on (Sentry SDK) x6",
      "check": "none",
      "note": "ไม่มีการตรวจ senderFrame ใกล้จุดลงทะเบียน แต่ฟังก์ชันที่เรียกไม่มีสิทธิ์ใช้งานระบบ: เขียนข้อมูลเข้า Sentry เท่านั้น"
    }
  ],
  "verdict": "handler ที่มีสิทธิ์จริง (MCP, settings, web-store, servesPage) ตรวจ sender แล้ว ส่วน telemetry 6 ตัวไม่ตรวจแต่ไม่มีอำนาจ ยังไม่ได้วิเคราะห์ไฟล์ 7.5 MB ทั้งไฟล์ด้วย REA (heap หมด)"
};
