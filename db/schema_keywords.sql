CREATE TABLE type_keywords (
    keyword_id    INT IDENTITY(1,1) PRIMARY KEY,
    document_type NVARCHAR(255) NOT NULL,
    keyword       NVARCHAR(255) NOT NULL,
    weight        FLOAT         NOT NULL,   -- positive = boost, negative = penalty
    created_at    DATETIME2     NOT NULL DEFAULT GETUTCDATE(),
    CONSTRAINT UQ_type_keyword UNIQUE (document_type, keyword)
);
CREATE INDEX IX_type_keywords_document_type ON type_keywords (document_type);
