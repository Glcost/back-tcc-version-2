import os
import base64
import json
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

def _is_private_key(value):
    if value.startswith('sb_secret_') and len(value) > len('sb_secret_'):
        return True
    # Recognize legacy service-role keys only to reject a mistakenly configured
    # anon key. Supabase still validates the key's real signature.
    try:
        parts = value.split('.')
        if len(parts) != 3:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        return isinstance(payload, dict) and payload.get('role') == 'service_role'
    except (ValueError, TypeError):
        return False


url: str = os.environ.get('SUPABASE_URL', '').strip()
secret_key: str = os.environ.get('SUPABASE_SECRET_KEY', '').strip()
if not url or not _is_private_key(secret_key):
    raise EnvironmentError('Configure SUPABASE_URL e uma SUPABASE_SECRET_KEY privada no servidor.')

# This API uses its own JWT authentication. All database access stays on the
# trusted server; every route must authorize the acting user before querying.
# Never initialize an anon/publishable fallback or forward a user's JWT here.
supabase_admin: Client = create_client(url, secret_key)
supabase: Client = supabase_admin  # Compatibility name for existing routes.
