-- Run this once against SQL Server to create the pipeline tables.

CREATE TABLE documents (
    document_id      INT IDENTITY(1,1) PRIMARY KEY,
    file_path        NVARCHAR(1000) NOT NULL UNIQUE,
    file_name        NVARCHAR(255)  NOT NULL,
    file_type        NVARCHAR(10)   NOT NULL,
    file_size_bytes  BIGINT         NOT NULL,
    date_discovered  DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
    ocr_status       NVARCHAR(20)   NOT NULL DEFAULT 'pending',
    ocr_started_at   DATETIME2      NULL,
    ocr_completed_at DATETIME2      NULL,
    ocr_error        NVARCHAR(MAX)  NULL,
    page_count       INT            NULL
);
CREATE INDEX IX_documents_ocr_status ON documents (ocr_status);

CREATE TABLE document_pages (
    page_id        INT IDENTITY(1,1) PRIMARY KEY,
    document_id    INT           NOT NULL REFERENCES documents(document_id),
    page_number    INT           NOT NULL,
    extracted_text NVARCHAR(MAX) NULL,
    ocr_confidence FLOAT         NULL,
    word_count     INT           NULL,
    CONSTRAINT UQ_doc_page UNIQUE (document_id, page_number)
);
CREATE INDEX IX_document_pages_document_id ON document_pages (document_id);

CREATE TABLE sample_documents (
    sample_id     INT IDENTITY(1,1) PRIMARY KEY,
    document_type NVARCHAR(255)  NOT NULL,
    file_path     NVARCHAR(1000) NOT NULL UNIQUE,
    file_name     NVARCHAR(255)  NOT NULL,
    page_count    INT            NULL,
    date_ingested DATETIME2      NOT NULL DEFAULT GETUTCDATE()
);
CREATE INDEX IX_sample_documents_document_type ON sample_documents (document_type);

CREATE TABLE sample_pages (
    sample_page_id INT IDENTITY(1,1) PRIMARY KEY,
    sample_id      INT           NOT NULL REFERENCES sample_documents(sample_id),
    document_type  NVARCHAR(255) NOT NULL,
    page_number    INT           NOT NULL,
    extracted_text NVARCHAR(MAX) NULL,
    ocr_confidence FLOAT         NULL,
    CONSTRAINT UQ_sample_page UNIQUE (sample_id, page_number)
);
CREATE INDEX IX_sample_pages_document_type ON sample_pages (document_type);

CREATE TABLE document_matches (
    match_id            INT IDENTITY(1,1) PRIMARY KEY,
    document_id         INT           NOT NULL REFERENCES documents(document_id),
    document_type       NVARCHAR(255) NOT NULL,
    confidence_score    FLOAT         NOT NULL,
    matched_sample_id   INT           NOT NULL REFERENCES sample_documents(sample_id),
    matched_sample_page INT           NOT NULL,
    page_number_start   INT           NOT NULL,
    page_number_end     INT           NOT NULL,
    match_created_at    DATETIME2     NOT NULL DEFAULT GETUTCDATE()
);
CREATE INDEX IX_document_matches_document_id   ON document_matches (document_id);
CREATE INDEX IX_document_matches_document_type ON document_matches (document_type);
CREATE INDEX IX_document_matches_confidence    ON document_matches (confidence_score DESC);
