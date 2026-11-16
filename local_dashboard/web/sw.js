/*
 * Service worker บางมาก: ไม่ดัก fetch และไม่ใช้ Cache API
 * เพื่อไม่เขียนแคชลง HDD ของเครื่อง i5-7400
 */
self.addEventListener("install", function () {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});
