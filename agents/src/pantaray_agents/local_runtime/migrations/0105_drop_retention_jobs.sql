-- retention_jobs は 0006 で作られて以降、読み手も書き手も存在しない。
-- screenshot artifact の保持は Electron 側 (capture_manager.js) が担う。
DROP TABLE retention_jobs;
