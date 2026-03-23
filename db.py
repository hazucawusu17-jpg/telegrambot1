import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()


class Database:
    def __init__(self):
        uri = os.getenv("MONGO_URI")
        self.client = MongoClient(uri)
        db_name = os.getenv("MONGO_DB_NAME", "telegram_mail_bot")
        self.db = self.client[db_name]

        self.users = self.db["users"]
        self.emails = self.db["registered_emails"]
        self.admins = self.db["admins"]

        self._seed_admins()

    # ─────────────────────────────────────────────
    # Seed admins from env
    # ─────────────────────────────────────────────

    def _seed_admins(self):
        """
        Pre-load admin Telegram IDs from the ADMIN_IDS env variable.
        ADMIN_IDS should be a comma-separated list of Telegram user IDs.
        Example: ADMIN_IDS=123456789,987654321
        """
        raw = os.getenv("ADMIN_IDS", "")
        for id_str in raw.split(","):
            id_str = id_str.strip()
            if id_str.isdigit():
                tid = int(id_str)
                self.admins.update_one(
                    {"telegram_id": tid},
                    {"$setOnInsert": {"telegram_id": tid}},
                    upsert=True,
                )

    # ─────────────────────────────────────────────
    # Admin helpers
    # ─────────────────────────────────────────────

    def is_admin(self, telegram_id: int) -> bool:
        return self.admins.find_one({"telegram_id": telegram_id}) is not None

    # ─────────────────────────────────────────────
    # User helpers
    # ─────────────────────────────────────────────

    def register_user(self, telegram_id: int, username: str):
        """Insert user if not already present."""
        self.users.update_one(
            {"telegram_id": telegram_id},
            {
                "$setOnInsert": {
                    "telegram_id": telegram_id,
                    "username": username,
                    "blocked": False,
                }
            },
            upsert=True,
        )

    def list_users(self) -> list[dict]:
        return list(self.users.find({}, {"_id": 0}))

    def is_user_blocked(self, telegram_id: int) -> bool:
        user = self.users.find_one({"telegram_id": telegram_id})
        if user is None:
            return False
        return user.get("blocked", False)

    def set_user_blocked(self, telegram_id: int, blocked: bool):
        self.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"blocked": blocked}},
            upsert=True,
        )

    # ─────────────────────────────────────────────
    # Email registry helpers
    # ─────────────────────────────────────────────

    def is_email_registered(self, email: str) -> bool:
        return self.emails.find_one({"email": email.lower()}) is not None

    def add_email(self, email: str, added_by: int):
        self.emails.update_one(
            {"email": email.lower()},
            {"$setOnInsert": {"email": email.lower(), "added_by": added_by}},
            upsert=True,
        )

    def remove_email(self, email: str):
        self.emails.delete_one({"email": email.lower()})

    def list_emails(self) -> list[dict]:
        return list(self.emails.find({}, {"_id": 0}))
