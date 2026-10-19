"""Auth DB schema: SQL for each migration and the ordered migration list.

AuthDatabase in database.py applies these; keeping the statements here keeps
the runner small enough to read.
"""

from __future__ import annotations

_INITIAL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        username_normalized TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
        disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
        token_version INTEGER NOT NULL DEFAULT 0 CHECK (token_version >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_users_role_disabled
    ON users(role, disabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS resources (
        resource_type TEXT NOT NULL CHECK (
            resource_type IN (
                'project',
                'avatar_character',
                'avatar_background',
                'avatar_mascot',
                'custom_voice',
                'asr_engine'
            )
        ),
        resource_id TEXT NOT NULL,
        owner_user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
        visibility TEXT NOT NULL CHECK (
            visibility IN ('private', 'system_public', 'project')
        ),
        created_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        owner_project_id TEXT NULL,
        PRIMARY KEY (resource_type, resource_id),
        CHECK (
            (visibility = 'private' AND owner_user_id IS NOT NULL AND owner_project_id IS NULL)
            OR (visibility = 'system_public' AND owner_user_id IS NULL AND owner_project_id IS NULL)
            OR (visibility = 'project' AND owner_user_id IS NULL)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resources_owner_visibility_type
    ON resources(owner_user_id, visibility, resource_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resources_owner_project
    ON resources(owner_project_id, resource_type)
    """,
)

_TEMPORARY_ACCOUNT_STATEMENTS = (
    """
    ALTER TABLE users
    ADD COLUMN account_type TEXT NOT NULL DEFAULT 'formal'
    CHECK (account_type IN ('formal', 'temporary'))
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_users_account_type_disabled
    ON users(account_type, disabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS temporary_account_batches (
        id TEXT PRIMARY KEY,
        created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS temporary_credentials (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        batch_id TEXT NOT NULL REFERENCES temporary_account_batches(id)
            ON DELETE CASCADE,
        code_locator TEXT NOT NULL UNIQUE,
        first_used_at TEXT,
        expires_at TEXT,
        duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0),
        CHECK (
            (first_used_at IS NULL AND expires_at IS NULL)
            OR (first_used_at IS NOT NULL AND expires_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_temporary_credentials_batch
    ON temporary_credentials(batch_id, user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_grants (
        grantee_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        granted_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (grantee_user_id, resource_type, resource_id),
        FOREIGN KEY (resource_type, resource_id)
            REFERENCES resources(resource_type, resource_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_grants_resource
    ON resource_grants(resource_type, resource_id, grantee_user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS account_defaults (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        voice_provider TEXT NOT NULL,
        voice_id TEXT NOT NULL,
        mascot_id TEXT NOT NULL DEFAULT '',
        background_id TEXT NOT NULL DEFAULT '',
        asr_provider TEXT NOT NULL DEFAULT ''
    )
    """,
)

_ACCOUNT_DEFAULTS_MASCOT_BACKGROUND_STATEMENTS = (
    """
    ALTER TABLE account_defaults
    ADD COLUMN mascot_id TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE account_defaults
    ADD COLUMN background_id TEXT NOT NULL DEFAULT ''
    """,
)

_ACCOUNT_ASR_PROVIDER_SCHEMA_VERSION = 12
_ACCOUNT_ASR_PROVIDER_MIGRATION_NAME = "account_defaults_asr_provider"
# 空字串代表「沒選過」，用部署設定的 ASR_PROVIDER。用空字串而不是 NULL，跟這張表其他
# 欄位一致，讀取端也不必到處判斷 None。
_ACCOUNT_ASR_PROVIDER_STATEMENTS = (
    """
    ALTER TABLE account_defaults
    ADD COLUMN asr_provider TEXT NOT NULL DEFAULT ''
    """,
)

_ASR_ENGINE_RESOURCE_SCHEMA_VERSION = 13
_ASR_ENGINE_RESOURCE_MIGRATION_NAME = "resources_allow_asr_engine"
_ASR_ENGINE_RESOURCES_TABLE = """
    CREATE TABLE resources_rebuilt (
        resource_type TEXT NOT NULL CHECK (
            resource_type IN (
                'project',
                'avatar_character',
                'avatar_background',
                'avatar_mascot',
                'custom_voice',
                'asr_engine'
            )
        ),
        resource_id TEXT NOT NULL,
        owner_user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
        visibility TEXT NOT NULL CHECK (
            visibility IN ('private', 'system_public')
        ),
        created_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (resource_type, resource_id),
        CHECK (
            (visibility = 'private' AND owner_user_id IS NOT NULL)
            OR (visibility = 'system_public' AND owner_user_id IS NULL)
        )
    )
"""

_EMBED_KEY_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS embed_keys (
        key_id TEXT PRIMARY KEY,
        label TEXT NOT NULL DEFAULT '',
        project_id TEXT NOT NULL,
        allowed_origins_json TEXT NOT NULL DEFAULT '[]',
        default_character_id TEXT NOT NULL DEFAULT '',
        allowed_character_ids_json TEXT NOT NULL DEFAULT '[]',
        default_persona_id TEXT NOT NULL DEFAULT '',
        default_tts_provider TEXT NOT NULL DEFAULT '',
        default_tts_voice TEXT NOT NULL DEFAULT '',
        rate_limit_per_minute INTEGER NOT NULL DEFAULT 60
            CHECK (rate_limit_per_minute >= 1),
        daily_request_quota INTEGER NOT NULL DEFAULT 1000
            CHECK (daily_request_quota >= 1),
        disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_used_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_embed_keys_project
    ON embed_keys(project_id, disabled)
    """,
    """
    CREATE TABLE IF NOT EXISTS embed_key_daily_usage (
        key_id TEXT NOT NULL REFERENCES embed_keys(key_id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        requests INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
        PRIMARY KEY (key_id, day)
    )
    """,
)

_ROOT_ACCOUNT_SCHEMA_VERSION = 4
_ROOT_ACCOUNT_MIGRATION_NAME = "root_account_role_and_auth_audit"
# v5 的 WHERE 條件拿小寫化的 username_normalized 去比對保留原始大小寫的
# locator，永遠不成立，於是被標記完成卻沒遷移到任何一列。改用 v6 重跑。
_TEMPORARY_USERNAME_SCHEMA_VERSION = 6
_TEMPORARY_USERNAME_MIGRATION_NAME = "redact_temporary_credential_locators_v2"
_ADMIN_PORTAL_ACCESS_SCHEMA_VERSION = 7
_ADMIN_PORTAL_ACCESS_MIGRATION_NAME = "add_admin_portal_access"
_KIOSK_SCHEMA_VERSION = 16
_KIOSK_MIGRATION_NAME = "add_users_kiosk"
# 後台要判斷哪些帳號已經沒人用；升級前沒有紀錄，所以既有帳號一律從 NULL 開始。
_LAST_LOGIN_SCHEMA_VERSION = 22
_LAST_LOGIN_MIGRATION_NAME = "add_users_last_login_at"
_EMBED_KEY_SCHEMA_VERSION = 8
_EMBED_KEY_MIGRATION_NAME = "embed_keys_and_daily_usage"

_ADMIN_SCOPE_SCHEMA_VERSION = 9
_ADMIN_SCOPE_MIGRATION_NAME = "admin_resource_scopes"
# ROOT 指派給 admin 的可分配資源池。刻意不重用 resource_grants：那張表與
# account_defaults 綁在一起（必須含 project/voice/角色，且 defaults 要落在
# grants 內），而 admin 的池子沒有「預設值」的概念。分開存也讓「這個 admin
# 有沒有被設限」是一個可直接查詢的事實，而不用從 grant 內容反推。
_ADMIN_SCOPE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS admin_resource_scopes (
        admin_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        granted_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (admin_user_id, resource_type, resource_id),
        FOREIGN KEY (resource_type, resource_id)
            REFERENCES resources(resource_type, resource_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_admin_scopes_resource
    ON admin_resource_scopes(resource_type, resource_id, admin_user_id)
    """,
    # 一個 admin 是否受限，是「有沒有任何一列」的問題。單獨記一列旗標，
    # 才能表達「ROOT 設了範圍，但某個資源類型刻意給空」——沒有這張表就
    # 無法和「完全沒設限」區分開。
    """
    CREATE TABLE IF NOT EXISTS admin_scope_state (
        admin_user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        scoped INTEGER NOT NULL DEFAULT 0,
        updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL
    )
    """,
)

_SYSTEM_SETTINGS_SCHEMA_VERSION = 11
_SYSTEM_SETTINGS_MIGRATION_NAME = "system_settings"
# 營運時可改的全站設定。環境變數仍是預設值來源：這張表只存「被人改過」的
# 項目，沒有紀錄就回退到 .env，所以新部署不必先寫一輪設定才能啟動。
# 存 updated_by 與 updated_at 是因為這些設定會影響每一個使用者，出事時要
# 查得到是誰在什麼時候動的。
_SYSTEM_SETTINGS_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL
    )
    """,
)

_DECISION_PROVIDER_SETTINGS_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS decision_provider_settings (
        setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
        order_json TEXT NOT NULL,
        enabled_json TEXT NOT NULL,
        updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_provider_secrets (
        provider_id TEXT PRIMARY KEY,
        ciphertext TEXT NOT NULL,
        updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL
    )
    """,
)

# 決策以外的模型（主對話 LLM…）也要能在後台排順序、存金鑰，改成每類一列設定。
# 金鑰改按廠商存而不是按決策 hop：同一把 OpenAI key 同時給決策與主對話用。
# 舊的 decision_provider_* 兩張表只複製、不刪，見 _MIGRATIONS 之前的說明。
_MODEL_PROVIDER_SETTINGS_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS model_provider_settings (
        category TEXT PRIMARY KEY,
        order_json TEXT NOT NULL,
        enabled_json TEXT NOT NULL,
        models_json TEXT NOT NULL DEFAULT '{}',
        updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_provider_secrets (
        credential_id TEXT PRIMARY KEY,
        ciphertext TEXT NOT NULL,
        updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    INSERT OR IGNORE INTO model_provider_settings(
        category, order_json, enabled_json, models_json, updated_by, updated_at
    )
    SELECT 'decision', order_json, enabled_json, '{}', updated_by, updated_at
    FROM decision_provider_settings
    """,
    """
    INSERT OR IGNORE INTO model_provider_secrets(credential_id, ciphertext, updated_by, updated_at)
    SELECT provider_id, ciphertext, updated_by, updated_at FROM decision_provider_secrets
    """,
)
# 舊的兩張決策表刻意保留（只複製不刪）：部署後若把程式退回舊版，舊版還讀得到
# 升級當下的決策設定。新版確定不會退回後，再用之後的 migration 刪掉。

# 專案層的語音限制：帳號授權決定「這個人能用什麼」，這張表決定「這個專案肯用什麼」，
# 請求實際能用的是兩者交集。另開一張表而不是塞進 resources.metadata_json：那份
# metadata 是專案的顯示資訊，沒有欄位型別也沒有變更紀錄；限制要記錄誰改的、何時
# 改的，也要能被外鍵跟著專案一起刪掉。resource_type 固定是 'project'，只為了能用複合外鍵
# 指向 resources。清單存 JSON：引擎與聲音被移除時不會連動刪掉，讀取端照原樣當作
# 限制（寧可擋下也不要因為清單變空而變成「不限制」）。
_PROJECT_POLICY_SCHEMA_VERSION = 20
_PROJECT_POLICY_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS project_policies (
        project_id TEXT PRIMARY KEY,
        resource_type TEXT NOT NULL DEFAULT 'project'
            CHECK (resource_type = 'project'),
        allowed_asr_engines_json TEXT NOT NULL DEFAULT '[]',
        default_asr_engine TEXT,
        taiwanese_asr_engine TEXT,
        allowed_tts_voices_json TEXT NOT NULL DEFAULT '[]',
        default_tts_voice TEXT,
        allowed_characters_json TEXT NOT NULL DEFAULT '[]',
        default_character_id TEXT,
        allowed_backgrounds_json TEXT NOT NULL DEFAULT '[]',
        default_background_id TEXT,
        allowed_mascots_json TEXT NOT NULL DEFAULT '[]',
        default_mascot_id TEXT,
        tts_engine_order_json TEXT NOT NULL DEFAULT '[]',
        asr_engine_order_json TEXT NOT NULL DEFAULT '[]',
        updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (resource_type, project_id)
            REFERENCES resources(resource_type, resource_id) ON DELETE CASCADE
    )
    """,
)

# 開放 CORS 後，外部網站的前端可以直接呼叫 API；依「來源網域 × 哪把 key／哪個帳號」
# 彙總記錄，才知道誰在用、從哪裡用。不設外鍵：key 撤銷或帳號刪除後仍要留著紀錄。
_REQUEST_ORIGIN_SCHEMA_VERSION = 21
_REQUEST_ORIGIN_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS request_origins (
        origin TEXT NOT NULL,
        principal_type TEXT NOT NULL,
        principal_id TEXT NOT NULL DEFAULT '',
        user_id TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        last_path TEXT NOT NULL DEFAULT '',
        request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
        PRIMARY KEY (origin, principal_type, principal_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_request_origins_last_seen
    ON request_origins(last_seen_at)
    """,
)

_PROJECT_RESOURCE_SCOPE_SCHEMA_VERSION = 23
_PROJECT_RESOURCE_SCOPE_MIGRATION_NAME = "project_resource_scope"

_PROJECT_RESOURCE_SCOPE_RESOURCES_TABLE = """
    CREATE TABLE resources_rebuilt (
        resource_type TEXT NOT NULL CHECK (
            resource_type IN (
                'project',
                'avatar_character',
                'avatar_background',
                'avatar_mascot',
                'custom_voice',
                'asr_engine'
            )
        ),
        resource_id TEXT NOT NULL,
        owner_user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
        visibility TEXT NOT NULL CHECK (
            visibility IN ('private', 'system_public', 'project')
        ),
        created_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        owner_project_id TEXT NULL,
        PRIMARY KEY (resource_type, resource_id),
        CHECK (
            (visibility = 'private' AND owner_user_id IS NOT NULL AND owner_project_id IS NULL)
            OR (visibility = 'system_public' AND owner_user_id IS NULL AND owner_project_id IS NULL)
            OR (visibility = 'project' AND owner_user_id IS NULL)
        )
    )
"""

_PROJECT_RESOURCE_ASSIGNMENTS_TABLE = """
    CREATE TABLE IF NOT EXISTS project_resource_assignments (
        project_id TEXT NOT NULL,
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        assigned_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        assigned_at TEXT NOT NULL,
        project_resource_type TEXT NOT NULL DEFAULT 'project'
            CHECK (project_resource_type = 'project'),
        PRIMARY KEY (project_id, resource_type, resource_id),
        FOREIGN KEY (project_resource_type, project_id)
            REFERENCES resources(resource_type, resource_id) ON DELETE CASCADE,
        FOREIGN KEY (resource_type, resource_id)
            REFERENCES resources(resource_type, resource_id) ON DELETE CASCADE
    )
"""

_MIGRATIONS = (
    (1, "initial_accounts_and_resources", _INITIAL_SCHEMA_STATEMENTS),
    (2, "temporary_accounts_grants_and_defaults", _TEMPORARY_ACCOUNT_STATEMENTS),
    (
        3,
        "account_defaults_mascot_and_background",
        _ACCOUNT_DEFAULTS_MASCOT_BACKGROUND_STATEMENTS,
    ),
    (_EMBED_KEY_SCHEMA_VERSION, _EMBED_KEY_MIGRATION_NAME, _EMBED_KEY_STATEMENTS),
    (
        _ADMIN_SCOPE_SCHEMA_VERSION,
        _ADMIN_SCOPE_MIGRATION_NAME,
        _ADMIN_SCOPE_STATEMENTS,
    ),
    (
        10,
        "encrypted_temporary_passwords",
        ("ALTER TABLE temporary_credentials ADD COLUMN password_ciphertext TEXT",),
    ),
    (
        _SYSTEM_SETTINGS_SCHEMA_VERSION,
        _SYSTEM_SETTINGS_MIGRATION_NAME,
        _SYSTEM_SETTINGS_STATEMENTS,
    ),
    (
        _ACCOUNT_ASR_PROVIDER_SCHEMA_VERSION,
        _ACCOUNT_ASR_PROVIDER_MIGRATION_NAME,
        _ACCOUNT_ASR_PROVIDER_STATEMENTS,
    ),
    # 後台的「全站預設 ASR 引擎」拔掉了（2026-09-24），沒選過的人一律用部署設定的
    # ASR_PROVIDER。留著這筆不會有程式讀，但會讓看資料庫的人以為它還有作用。
    (
        14,
        "drop_site_asr_provider_setting",
        ("DELETE FROM system_settings WHERE key = 'asr_provider'",),
    ),
    # 前台設定（專案、人設、聲音、背景…）原本只存在瀏覽器，換電腦就沒了；改跟著帳號走。
    # 存 JSON 而不是一欄一個：前台加欄位時不必每次加 migration，白名單在 API 那層把關。
    (
        15,
        "account_preferences",
        (
            """
            CREATE TABLE IF NOT EXISTS account_preferences (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                preferences_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
            """,
        ),
    ),
    (17, "decision_provider_settings", _DECISION_PROVIDER_SETTINGS_STATEMENTS),
    (
        18,
        "account_api_keys",
        (
            """
            CREATE TABLE IF NOT EXISTS account_api_keys (
                key_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                credential_digest TEXT NOT NULL,
                issued_role TEXT NOT NULL,
                issued_token_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                revoked_at TEXT,
                last_used_at TEXT,
                request_count INTEGER NOT NULL DEFAULT 0
                    CHECK (request_count >= 0)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_account_api_keys_user
            ON account_api_keys(user_id, created_at)
            """,
        ),
    ),
    (19, "model_provider_settings", _MODEL_PROVIDER_SETTINGS_STATEMENTS),
    (
        _PROJECT_POLICY_SCHEMA_VERSION,
        "project_policies",
        _PROJECT_POLICY_STATEMENTS,
    ),
    (
        _REQUEST_ORIGIN_SCHEMA_VERSION,
        "request_origins",
        _REQUEST_ORIGIN_STATEMENTS,
    ),
    (
        24,
        "project_gemini_credentials",
        (
            """
            CREATE TABLE IF NOT EXISTS project_gemini_credentials (
                project_id TEXT PRIMARY KEY,
                credential_id TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                ciphertext TEXT NOT NULL,
                updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                updated_at TEXT NOT NULL,
                project_resource_type TEXT NOT NULL DEFAULT 'project'
                    CHECK (project_resource_type = 'project'),
                FOREIGN KEY (project_resource_type, project_id)
                    REFERENCES resources(resource_type, resource_id)
                    ON DELETE CASCADE
            )
            """,
        ),
    ),
)
