-- migrations/001_init.sql —— PRD 4.2 完整 DDL
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE conversations (
    id          TEXT PRIMARY KEY,               -- UUIDv7 字符串
    title       TEXT NOT NULL DEFAULT '新对话',
    model       TEXT NOT NULL DEFAULT 'qwen-plus',
    created_at  TEXT NOT NULL,                  -- ISO8601 UTC
    updated_at  TEXT NOT NULL,
    deleted     INTEGER NOT NULL DEFAULT 0      -- 软删除标记
);

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,           -- UUIDv7
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content         TEXT NOT NULL DEFAULT '',
    tokens          INTEGER,                    -- 该消息估算 token 数
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('streaming','done','error','cancelled'))
);

CREATE TABLE tool_calls (
    id              TEXT PRIMARY KEY,           -- UUIDv7
    message_id      TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tool_name       TEXT NOT NULL,              -- shell / file_read / file_write / file_delete / gsettings_set
    arguments_json  TEXT NOT NULL,              -- 见 PRD 4.3
    decision        TEXT NOT NULL CHECK (decision IN ('pending','confirmed','denied_by_user','denied_by_guard','executed','failed','timeout')),
    result_json     TEXT,                       -- 执行结果（stdout/stderr/exit_code 或文件 diff）
    created_at      TEXT NOT NULL,
    executed_at     TEXT
);

CREATE TABLE settings (                          -- 单例表, 固定 id=1
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    provider        TEXT NOT NULL DEFAULT 'dashscope',   -- dashscope / openai / custom
    base_url        TEXT NOT NULL DEFAULT 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model           TEXT NOT NULL DEFAULT 'qwen-plus',
    temperature     REAL NOT NULL DEFAULT 0.7 CHECK (temperature BETWEEN 0 AND 2),
    max_tokens      INTEGER NOT NULL DEFAULT 4096,
    context_window  INTEGER NOT NULL DEFAULT 30000,      -- 上下文裁剪阈值(token 估算)
    tools_enabled   INTEGER NOT NULL DEFAULT 1,
    theme           TEXT NOT NULL DEFAULT 'system' CHECK (theme IN ('light','dark','system')),
    updated_at      TEXT NOT NULL
);
-- 注意: API Key 不入库, 存 gnome-keyring(schema: com.lingos.assistant, item: api-key)

CREATE TABLE audit_logs (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'assistant',   -- assistant / user
    action      TEXT NOT NULL,                       -- tool_executed / tool_denied / key_written / settings_changed ...
    detail_json TEXT,
    tool_call_id TEXT REFERENCES tool_calls(id) ON DELETE SET NULL  -- 删会话不删审计
);

CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX idx_toolcalls_conv ON tool_calls(conversation_id, created_at);
CREATE INDEX idx_audit_ts ON audit_logs(ts);
CREATE INDEX idx_conversations_updated ON conversations(updated_at DESC) WHERE deleted = 0;
