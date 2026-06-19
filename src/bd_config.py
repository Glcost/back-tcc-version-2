import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Carrega as variáveis do arquivo .env
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise EnvironmentError("SUPABASE_URL e SUPABASE_KEY devem ser definidas no .env")

# Cria a conexão oficial
supabase: Client = create_client(url, key)

















