CREATE TABLE IF NOT EXISTS entries (
    id            text PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('ask', 'post')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    engine        text,
    model         text,
    session_id    text,
    cwd           text,
    project       text,
    script        text,
    priority      text NOT NULL CHECK (priority IN ('urgent', 'normal', 'low')),
    mode          text CHECK (mode IN ('wait', 'resume')),
    title         text NOT NULL,
    summary       text,
    detail        text,
    html          text,
    control       jsonb,
    source        jsonb,
    expires_at    timestamptz,
    state         text NOT NULL CHECK (state IN (
                      'open', 'answered', 'delivered', 'expired', 'withdrawn', 'superseded', 'undelivered',
                      'unread', 'read', 'archived')),
    answer        jsonb,
    waiter_pid    integer,
    delivery      jsonb NOT NULL DEFAULT '{}'::jsonb,
    superseded_by text REFERENCES entries (id)
);

CREATE INDEX IF NOT EXISTS entries_state ON entries (state);
CREATE INDEX IF NOT EXISTS entries_project ON entries (project);
CREATE INDEX IF NOT EXISTS entries_session ON entries (session_id);

CREATE TABLE IF NOT EXISTS events (
    seq      bigserial PRIMARY KEY,
    entry_id text NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    at       timestamptz NOT NULL DEFAULT now(),
    type     text NOT NULL CHECK (type IN ('answer', 'followup', 'reply', 'revise', 'state')),
    via      text,
    body     jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS events_entry ON events (entry_id, seq);

-- One channel for every change. TG_ARGV[0] names the column holding the entry id,
-- so one function serves both tables without referencing a field the row lacks.
CREATE OR REPLACE FUNCTION agent_inbox_notify() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify(
        'agent_inbox',
        json_build_object('table', TG_TABLE_NAME, 'id', to_jsonb(NEW) ->> TG_ARGV[0])::text
    );
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER entries_notify AFTER INSERT OR UPDATE ON entries
    FOR EACH ROW EXECUTE FUNCTION agent_inbox_notify('id');

CREATE OR REPLACE TRIGGER events_notify AFTER INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION agent_inbox_notify('entry_id');

CREATE TABLE IF NOT EXISTS ops (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);
