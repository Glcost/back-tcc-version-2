import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Carrega as variáveis do arquivo .env
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise EnvironmentError("SUPABASE_URL e SUPABASE_KEY devem ser definidas no .env")

# Cria a conexão oficial (chave publishable/anon) usada pelas rotas normais da API
supabase: Client = create_client(url, key)


# ==========================================================
# CLIENTE ADMINISTRATIVO (SERVICE ROLE / SECRET KEY)
# ==========================================================
# Usado exclusivamente pelo módulo de Relatórios (BI), que precisa
# ler dados agregados de várias tabelas/professores sem ficar
# restrito pelas políticas de RLS (Row Level Security).
#
# IMPORTANTE:
# - A SUPABASE_SECRET_KEY NUNCA deve ser exposta ao frontend.
# - Ela só deve existir como variável de ambiente no servidor
#   (arquivo .env local, ou variável de ambiente na Vercel),
#   nunca hardcoded no código ou em commits.
secret_key: str = os.environ.get("SUPABASE_SECRET_KEY")

supabase_admin: Client = create_client(url, secret_key) if secret_key else None
