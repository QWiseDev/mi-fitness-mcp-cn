"""让 stdio MCP 通过 keyring 接口读取已有扫码账号，不另存一份凭据。"""

import sqlite3

from keyring.backend import KeyringBackend
from keyring.errors import NoKeyringError, PasswordSetError

DATABASE = "/var/lib/mi-fitness-mcp/data/mi-fitness-mcp/mi_fitness.db"
FIELDS = {
    "mi_fitness_auth_user_id": "user_id",
    "mi_fitness_auth_pass_token": "pass_token",
}


class SQLiteKeyring(KeyringBackend):
    priority = 1

    def get_password(self, service, username):
        if service != "mi-fitness-mcp" or username not in FIELDS:
            return None
        with sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            accounts = connection.execute(
                "SELECT user_id,pass_token FROM api_keys WHERE revoked=0 "
                "ORDER BY created_at DESC"
            ).fetchall()
        if not accounts or len({row["user_id"] for row in accounts}) != 1:
            raise NoKeyringError("MCP 需要唯一有效的扫码账号")
        return accounts[0][FIELDS[username]]

    def set_password(self, service, username, password):
        raise PasswordSetError("此后端只读，请通过 Mi Fitness 网页管理扫码账号")
