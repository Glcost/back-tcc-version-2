BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.solicitacoes_dados (
    id uuid PRIMARY KEY,
    ordem bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    aluno_id integer NOT NULL REFERENCES public.alunos(id),
    professor_abertura_id integer NOT NULL REFERENCES public.professores(id),
    atendido_por_id integer NOT NULL REFERENCES public.professores(id),
    tipo text NOT NULL CHECK (tipo IN ('correcao', 'exclusao')),
    descricao text NOT NULL CHECK (char_length(btrim(descricao)) BETWEEN 10 AND 2000),
    solicitante text NOT NULL CHECK (solicitante IN ('titular', 'responsavel')),
    verificacao_confirmada boolean NOT NULL CHECK (verificacao_confirmada),
    status text NOT NULL DEFAULT 'recebida' CHECK (status IN ('recebida', 'em_analise', 'respondida')),
    resposta text NOT NULL DEFAULT '' CHECK (char_length(resposta) <= 2000),
    versao integer NOT NULL DEFAULT 1 CHECK (versao > 0),
    criado_em timestamptz NOT NULL DEFAULT clock_timestamp(),
    atualizado_em timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (status <> 'respondida' OR char_length(btrim(resposta)) >= 10)
);
CREATE INDEX solicitacoes_dados_aluno_ordem_idx ON public.solicitacoes_dados(aluno_id, ordem DESC);
CREATE INDEX solicitacoes_dados_abertura_idx ON public.solicitacoes_dados(professor_abertura_id);
CREATE INDEX solicitacoes_dados_atendente_idx ON public.solicitacoes_dados(atendido_por_id);

CREATE TABLE public.solicitacoes_dados_eventos (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    solicitacao_id uuid NOT NULL REFERENCES public.solicitacoes_dados(id),
    versao integer NOT NULL,
    status text NOT NULL CHECK (status IN ('recebida', 'em_analise', 'respondida')),
    resposta text NOT NULL,
    professor_id integer NOT NULL REFERENCES public.professores(id),
    nome_professor text NOT NULL,
    criado_em timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(solicitacao_id, versao)
);
CREATE INDEX solicitacoes_dados_eventos_professor_idx ON public.solicitacoes_dados_eventos(professor_id);

CREATE SCHEMA IF NOT EXISTS roar_private;
REVOKE ALL ON SCHEMA roar_private FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA roar_private TO service_role;

-- The event is written in the same transaction as the request. The server may
-- not edit or delete audit rows, and browser roles have no access to either table.
CREATE FUNCTION roar_private.audit_privacy_request() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE actor_name text;
BEGIN
    PERFORM 1 FROM public.alunos
        WHERE id = NEW.aluno_id AND professor_id = NEW.atendido_por_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Student is not assigned to this teacher' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.versao <> 1 OR NEW.status <> 'recebida' OR NEW.resposta <> ''
            OR NEW.professor_abertura_id <> NEW.atendido_por_id THEN
            RAISE EXCEPTION 'Invalid initial request' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF ROW(NEW.id, NEW.ordem, NEW.aluno_id, NEW.professor_abertura_id, NEW.tipo,
               NEW.descricao, NEW.solicitante, NEW.verificacao_confirmada, NEW.criado_em)
           IS DISTINCT FROM
           ROW(OLD.id, OLD.ordem, OLD.aluno_id, OLD.professor_abertura_id, OLD.tipo,
               OLD.descricao, OLD.solicitante, OLD.verificacao_confirmada, OLD.criado_em)
           OR NEW.versao <> OLD.versao + 1 OR OLD.status = 'respondida'
           OR NOT ((OLD.status = 'recebida' AND NEW.status IN ('em_analise', 'respondida'))
                   OR (OLD.status = 'em_analise' AND NEW.status = 'respondida'))
           OR (NEW.status <> 'respondida' AND NEW.resposta <> '') THEN
            RAISE EXCEPTION 'Invalid request transition' USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT nome INTO STRICT actor_name FROM public.professores WHERE id = NEW.atendido_por_id;
    INSERT INTO public.solicitacoes_dados_eventos
        (solicitacao_id, versao, status, resposta, professor_id, nome_professor)
        VALUES (NEW.id, NEW.versao, NEW.status, NEW.resposta, NEW.atendido_por_id, actor_name);
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION roar_private.audit_privacy_request() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION roar_private.audit_privacy_request() TO service_role;
CREATE TRIGGER audit_privacy_request AFTER INSERT OR UPDATE ON public.solicitacoes_dados
    FOR EACH ROW EXECUTE FUNCTION roar_private.audit_privacy_request();

ALTER TABLE public.solicitacoes_dados ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.solicitacoes_dados_eventos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.solicitacoes_dados, public.solicitacoes_dados_eventos
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.solicitacoes_dados TO service_role;
GRANT SELECT, INSERT ON public.solicitacoes_dados_eventos TO service_role;
REVOKE ALL ON SEQUENCE public.solicitacoes_dados_ordem_seq, public.solicitacoes_dados_eventos_id_seq
    FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.solicitacoes_dados_ordem_seq, public.solicitacoes_dados_eventos_id_seq
    TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
