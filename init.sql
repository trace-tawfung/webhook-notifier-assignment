CREATE TABLE webhooks (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid(),
    post_url TEXT NOT NULL,
    events TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO webhooks (id, post_url, events)
VALUES ('wh1', 'http://example.com/webhook', ARRAY['subscriber_created']);