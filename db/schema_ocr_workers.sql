-- Run this against existing databases to enable multi-worker safe operation.
ALTER TABLE documents ADD worker_id NVARCHAR(255) NULL;
