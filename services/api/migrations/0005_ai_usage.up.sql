-- Conservative reservations, not actual provider bills. No student FK: reservation
-- uses a separate transaction while consultation may still be creating that student.
CREATE TABLE ai_daily_usage (
    usage_day DATE NOT NULL,
    scope_key TEXT NOT NULL CHECK (scope_key = 'global' OR scope_key ~ '^student:[0-9a-f-]{36}$'),
    attempts BIGINT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    reserved_usd NUMERIC(20, 8) NOT NULL DEFAULT 0 CHECK (reserved_usd >= 0),
    PRIMARY KEY (usage_day, scope_key)
);
