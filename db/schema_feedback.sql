-- Run this once against SQL Server to add the feedback table.
-- match_id is nullable (no FK) so feedback survives --regen runs of 04_match_documents.py.

CREATE TABLE match_feedback (
    feedback_id         INT IDENTITY(1,1) PRIMARY KEY,
    match_id            INT            NULL,
    document_id         INT            NOT NULL REFERENCES documents(document_id),
    document_type       NVARCHAR(255)  NOT NULL,
    confidence_score    FLOAT          NOT NULL,
    matched_sample_id   INT            NOT NULL REFERENCES sample_documents(sample_id),
    matched_sample_page INT            NOT NULL,
    page_number_start   INT            NOT NULL,
    page_number_end     INT            NOT NULL,
    feedback_note       NVARCHAR(500)  NULL,
    created_at          DATETIME2      NOT NULL DEFAULT GETUTCDATE()
);
CREATE INDEX IX_match_feedback_document_type ON match_feedback (document_type);
CREATE INDEX IX_match_feedback_sample_page   ON match_feedback (matched_sample_id, matched_sample_page);
