import secrets
import hashlib
import sys
from database import SessionLocal, engine, Base
from models import ApiKeyDB

# Ensure tables exist
Base.metadata.create_all(bind=engine)


def create_api_key(user_name, user_id):
    # 1. Generate a secure random key
    # Format: sk_live_<24_random_hex_chars>
    raw_key = f"sk_live_{secrets.token_hex(12)}"

    # 2. Hash it (SHA-256 is fine for API keys)
    # We add a static "salt" if you want, but simple SHA256 is standard for high-entropy keys
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()

    # 3. Store in DB
    db = SessionLocal()
    try:
        new_key = ApiKeyDB(
            key_hash=hashed_key,
            user_id=user_id,
            owner_name=user_name
        )
        db.add(new_key)
        db.commit()

        print("\n" + "="*50)
        print(f"✅ Key Created for {user_name}")
        print(f"🔑 API KEY: {raw_key}")
        print("⚠️  COPY THIS NOW. It will never be shown again.")
        print("="*50 + "\n")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python admin_create_key.py <Name> <UserID>")
    else:
        create_api_key(sys.argv[1], sys.argv[2])
