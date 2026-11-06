-- Apply once with a database owner, before deploying the matching API.
-- No browser role may read the new tables or execute these functions.
begin;

create table if not exists public.aluno_preferencias_jogos (
  aluno_id bigint primary key references public.alunos(id) on delete cascade,
  preferencias jsonb not null default '{"pieceCount":null,"showHints":true,"memoryPreviewSeconds":5,"advanceDelaySeconds":1}'::jsonb,
  atualizado_em timestamptz not null default now(),
  constraint game_preferences_object check (jsonb_typeof(preferencias) = 'object')
);
create table if not exists public.roar_progress_requests (
  aluno_id bigint not null references public.alunos(id) on delete cascade,
  id_tentativa uuid not null,
  atividade_id bigint not null references public.atividades(id) on delete cascade,
  resposta jsonb not null,
  criado_em timestamptz not null default now(),
  primary key (aluno_id, id_tentativa)
);
create table if not exists public.aluno_palavras_pratica (
  aluno_id bigint not null references public.alunos(id) on delete cascade,
  id_tentativa uuid not null,
  atividade_id bigint not null references public.atividades(id) on delete cascade,
  palavra text not null check (length(palavra) between 1 and 100),
  acertos integer not null check (acertos between 0 and 10000),
  erros integer not null check (erros between 0 and 10000),
  ajudas integer not null check (ajudas between 0 and 10000),
  registro_ordem bigint generated always as identity unique,
  praticado_em timestamptz not null default clock_timestamp(),
  primary key (aluno_id, id_tentativa, palavra)
);
alter table public.aluno_palavras_pratica add column if not exists registro_ordem bigint generated always as identity;
alter table public.aluno_palavras_pratica alter column praticado_em set default clock_timestamp();
create index if not exists aluno_palavras_pratica_report on public.aluno_palavras_pratica(aluno_id, praticado_em desc);
alter table public.aluno_preferencias_jogos enable row level security;
alter table public.roar_progress_requests enable row level security;
alter table public.aluno_palavras_pratica enable row level security;
revoke all on public.aluno_preferencias_jogos, public.roar_progress_requests, public.aluno_palavras_pratica from public, anon, authenticated;
grant all on public.aluno_preferencias_jogos, public.roar_progress_requests, public.aluno_palavras_pratica to service_role;

create or replace function public.roar_save_game_preferences(p_aluno_id bigint, p_professor_id bigint, p_preferencias jsonb)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare result jsonb;
begin
  perform 1 from public.alunos where id = p_aluno_id and professor_id = p_professor_id and ativo = true for update;
  if not found then return jsonb_build_object('erro','Acesso não autorizado a este aluno.','code','FORBIDDEN','status',403); end if;
  if p_preferencias is null or jsonb_typeof(p_preferencias) <> 'object' or exists (
    select 1 from jsonb_object_keys(p_preferencias) key where key not in ('pieceCount','showHints','memoryPreviewSeconds','advanceDelaySeconds')
  ) then raise exception 'Invalid preferences'; end if;
  insert into public.aluno_preferencias_jogos(aluno_id) values(p_aluno_id) on conflict do nothing;
  select preferencias || p_preferencias into result from public.aluno_preferencias_jogos where aluno_id = p_aluno_id;
  if result->'pieceCount' not in ('null'::jsonb,'2'::jsonb,'4'::jsonb,'6'::jsonb)
    or jsonb_typeof(result->'showHints') <> 'boolean'
    or result->'memoryPreviewSeconds' not in ('3'::jsonb,'5'::jsonb,'8'::jsonb,'10'::jsonb)
    or result->'advanceDelaySeconds' not in ('1'::jsonb,'2'::jsonb,'3'::jsonb,'5'::jsonb)
  then raise exception 'Invalid preferences'; end if;
  update public.aluno_preferencias_jogos set preferencias=result, atualizado_em=now() where aluno_id=p_aluno_id;
  return result;
end $$;

create or replace function public.roar_shop_transaction(p_aluno_id bigint, p_acao text, p_skin_id bigint default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare student public.alunos%rowtype; skin public.skins_lex%rowtype; owned boolean; balance bigint;
begin
  -- All balance mutations use this same student lock, including activity rewards.
  select * into student from public.alunos where id=p_aluno_id and ativo=true for update;
  if not found then return jsonb_build_object('erro','Aluno não encontrado.','code','STUDENT_NOT_FOUND','status',404); end if;
  balance := coalesce(student.xp_total,0);
  if p_acao='consultar' then return jsonb_build_object('xp_atual',balance); end if;
  if p_acao is null or p_acao not in ('comprar','equipar') or p_skin_id is null then
    return jsonb_build_object('erro','Ação inválida.','code','INVALID_SHOP_ACTION','status',400);
  end if;
  select * into skin from public.skins_lex where id=p_skin_id;
  if not found then return jsonb_build_object('erro','Dino não encontrado.','code','SKIN_NOT_FOUND','status',404); end if;
  select exists(select 1 from public.aluno_skins_lex where aluno_id=p_aluno_id and skin_id=p_skin_id) into owned;
  -- The default mascot is owned from account creation even on older accounts.
  owned := owned or (p_skin_id=1 and coalesce(skin.preco_xp,0)=0);
  if p_acao='equipar' then
    if not owned then return jsonb_build_object('erro','Adquira este Dino antes de equipar.','code','SKIN_NOT_OWNED','status',403); end if;
  elsif owned then
    return jsonb_build_object('mensagem','Este Dino já está no seu inventário.','code','SKIN_ALREADY_OWNED','xp_restante',balance,'status',200);
  else
    if skin.preco_xp is null or skin.preco_xp < 0 then raise exception 'Invalid catalog price'; end if;
    if balance < skin.preco_xp then return jsonb_build_object('erro','XP insuficiente para este Dino.','code','INSUFFICIENT_XP','status',400); end if;
    balance := balance-skin.preco_xp;
    insert into public.aluno_skins_lex(aluno_id,skin_id) values(p_aluno_id,p_skin_id);
  end if;
  update public.alunos set xp_total=balance,skin_ativa_id=p_skin_id where id=p_aluno_id;
  return jsonb_build_object('mensagem','Dino equipado com sucesso!','xp_restante',balance,'skin_ativa_id',p_skin_id,'status',200);
end $$;

create or replace function public.roar_register_progress(
 p_aluno_id bigint,p_atividade_id bigint,p_quantidade_erros integer,p_tempo_segundos integer,
 p_concluido boolean,p_id_tentativa uuid,p_palavras jsonb default '[]'::jsonb)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare student public.alunos%rowtype; saved jsonb; response jsonb; previous_completion boolean; reward integer:=0; word jsonb; status_code integer:=201;
begin
  select * into student from public.alunos where id=p_aluno_id and ativo=true for update;
  if not found then return jsonb_build_object('erro','Aluno não encontrado.','code','STUDENT_NOT_FOUND','status',404); end if;
  select resposta into saved from public.roar_progress_requests where aluno_id=p_aluno_id and id_tentativa=p_id_tentativa;
  if found then
    if (saved->'data'->>'atividade_id')::bigint <> p_atividade_id then
      return jsonb_build_object('erro','A tentativa já pertence a outra atividade.','code','ATTEMPT_ACTIVITY_MISMATCH','status',409);
    end if;
    return saved || jsonb_build_object('status',200);
  end if;
  if p_id_tentativa is null or p_quantidade_erros is null or p_tempo_segundos is null or p_concluido is null
    or p_quantidade_erros not between 0 and 1000 or p_tempo_segundos not between 0 and 86400
    or p_palavras is null or jsonb_typeof(p_palavras)<>'array' or jsonb_array_length(p_palavras)>128 then raise exception 'Invalid progress data'; end if;
  perform 1 from public.atividades a join public.variacoes_atividades v on v.atividade_id=a.id
    where a.id=p_atividade_id and v.modo_alvo=student.modo_aprendizagem;
  if not found then return jsonb_build_object('erro','Atividade indisponível para este aluno.','code','ACTIVITY_NOT_AVAILABLE_FOR_MODE','status',403); end if;
  select exists(select 1 from public.historico_desempenho where aluno_id=p_aluno_id and atividade_id=p_atividade_id and concluido=true) into previous_completion;
  if p_concluido and previous_completion then
    status_code:=200;
  else
    insert into public.historico_desempenho(aluno_id,atividade_id,modo_utilizado,quantidade_erros,tempo_segundos,concluido)
      values(p_aluno_id,p_atividade_id,student.modo_aprendizagem,p_quantidade_erros,p_tempo_segundos,p_concluido);
    if p_concluido then reward:=greatest(10,50-p_quantidade_erros*5); end if;
  end if;
  -- Evidence records actual attempts, including later reviews, but a retry of the
  -- same UUID cannot duplicate evidence or rewards. No old history is invented.
  for word in select value from jsonb_array_elements(p_palavras) loop
    if jsonb_typeof(word)<>'object' or not (word ?& array['palavra','acertos','erros','ajudas'])
      or jsonb_typeof(word->'palavra')<>'string' or jsonb_typeof(word->'acertos')<>'number'
      or jsonb_typeof(word->'erros')<>'number' or jsonb_typeof(word->'ajudas')<>'number' or length(btrim(word->>'palavra')) not between 1 and 100
      or (word->>'acertos')::integer not between 0 and 10000 or (word->>'erros')::integer not between 0 and 10000
      or (word->>'ajudas')::integer not between 0 and 10000 then raise exception 'Invalid word evidence'; end if;
    insert into public.aluno_palavras_pratica(aluno_id,id_tentativa,atividade_id,palavra,acertos,erros,ajudas)
      values(p_aluno_id,p_id_tentativa,p_atividade_id,upper(btrim(word->>'palavra')),(word->>'acertos')::integer,(word->>'erros')::integer,(word->>'ajudas')::integer);
  end loop;
  update public.alunos set xp_total=coalesce(xp_total,0)+reward where id=p_aluno_id returning * into student;
  response:=jsonb_build_object('mensagem',case when p_concluido and previous_completion then 'Atividade já concluída; revisão registrada sem XP adicional.' else 'Progresso registrado com sucesso.' end,
    'code',case when p_concluido and previous_completion then 'ACTIVITY_ALREADY_COMPLETED' else 'PROGRESS_REGISTERED' end,
    'status',status_code,'data',jsonb_build_object('aluno_id',p_aluno_id,'atividade_id',p_atividade_id,'concluido',p_concluido,
      'primeira_conclusao',p_concluido and not previous_completion,'xp_ganho',reward,'xp_total',student.xp_total));
  insert into public.roar_progress_requests(aluno_id,id_tentativa,atividade_id,resposta) values(p_aluno_id,p_id_tentativa,p_atividade_id,response);
  return response;
end $$;

create or replace function public.roar_student_word_report(p_aluno_id bigint)
returns jsonb language sql security definer set search_path=public,pg_temp as $$
  with totals as (
    select palavra,sum(acertos)::bigint acertos,sum(erros)::bigint erros,sum(ajudas)::bigint ajudas,
      count(*)::integer tentativas,max(praticado_em) ultima_pratica
    from public.aluno_palavras_pratica where aluno_id=p_aluno_id group by palavra
  ), latest as (
    select distinct on (palavra) palavra,(erros>0 or ajudas>0 or acertos=0) precisa_revisao
    from public.aluno_palavras_pratica where aluno_id=p_aluno_id
    order by palavra,praticado_em desc,registro_ordem desc
  )
  select jsonb_build_object('palavras',coalesce(jsonb_agg(to_jsonb(words) order by precisa_revisao desc,palavra),'[]'::jsonb)) from (
    select totals.*,latest.precisa_revisao from totals join latest using(palavra)
  ) words;
$$;

revoke all on function public.roar_save_game_preferences(bigint,bigint,jsonb) from public,anon,authenticated;
revoke all on function public.roar_shop_transaction(bigint,text,bigint) from public,anon,authenticated;
revoke all on function public.roar_register_progress(bigint,bigint,integer,integer,boolean,uuid,jsonb) from public,anon,authenticated;
revoke all on function public.roar_student_word_report(bigint) from public,anon,authenticated;
grant execute on function public.roar_save_game_preferences(bigint,bigint,jsonb) to service_role;
grant execute on function public.roar_shop_transaction(bigint,text,bigint) to service_role;
grant execute on function public.roar_register_progress(bigint,bigint,integer,integer,boolean,uuid,jsonb) to service_role;
grant execute on function public.roar_student_word_report(bigint) to service_role;

commit;
