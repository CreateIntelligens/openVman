from app.auth.models import AccountRole
from app.auth.runtime import get_auth_runtime


def test_web_search_migration_preserves_existing_internal_accounts_and_embed_keys():
    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    staff = runtime.users.create(
        username="staff", password_hash="unused", role=AccountRole.ADMIN, created_by=root.id,
    )
    vendor = runtime.users.create(
        username="vendor", password_hash="unused", role=AccountRole.USER,
        created_by=root.id, vendor_name="甲商",
    )
    embed = runtime.embed_keys.create(
        label="既有嵌入", project_id="default", allowed_origins=["https://partner.example"],
    )

    with runtime.database.transaction(write=True) as connection:
        connection.execute("ALTER TABLE users DROP COLUMN web_search_access")
        connection.execute("ALTER TABLE embed_keys DROP COLUMN web_search_access")
        connection.execute("DELETE FROM schema_migrations WHERE version = 29")

    runtime.database.initialize()
    assert runtime.users.get_by_id(root.id).web_search_access is True
    assert runtime.users.get_by_id(staff.id).web_search_access is True
    assert runtime.users.get_by_id(vendor.id).web_search_access is False
    assert runtime.embed_keys.get(embed.key_id).web_search_access is True

    new_account = runtime.users.create(
        username="new-staff", password_hash="unused", role=AccountRole.ADMIN, created_by=root.id,
    )
    new_embed = runtime.embed_keys.create(
        label="新嵌入", project_id="default", allowed_origins=["https://partner.example"],
    )
    runtime.database.initialize()
    assert runtime.users.get_by_id(new_account.id).web_search_access is False
    assert runtime.embed_keys.get(new_embed.key_id).web_search_access is False
