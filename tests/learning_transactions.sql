do $$
declare result jsonb; initial_balance bigint; before_count bigint;
begin
  -- No browser role can bypass the API's ownership checks.
  assert not has_function_privilege('anon','public.roar_shop_transaction(bigint,text,bigint)','execute');
  assert not has_function_privilege('authenticated','public.roar_register_progress(bigint,bigint,integer,integer,boolean,uuid,jsonb)','execute');
  assert not has_table_privilege('anon','public.aluno_palavras_pratica','select');
  assert not has_table_privilege('authenticated','public.aluno_preferencias_jogos','update');
  assert (select relrowsecurity from pg_class where oid='public.aluno_palavras_pratica'::regclass);
  result:=roar_shop_transaction(17,'equipar',2);
  assert result->>'code'='SKIN_NOT_OWNED';
  result:=roar_shop_transaction(17,'comprar',3);
  assert result->>'code'='INSUFFICIENT_XP';
  assert (select xp_total from alunos where id=17)=500;
  result:=roar_shop_transaction(17,'comprar',2);
  assert (result->>'xp_restante')::integer=400;
  result:=roar_shop_transaction(17,'comprar',2);
  assert result->>'code'='SKIN_ALREADY_OWNED';
  assert (select xp_total from alunos where id=17)=400;
  assert (select count(*) from aluno_skins_lex where aluno_id=17)=1;
  result:=roar_shop_transaction(17,'equipar',1);
  assert (result->>'status')::integer=200;
  result:=roar_save_game_preferences(17,6,'{"pieceCount":2}');
  assert result->>'code'='FORBIDDEN';
  assert not exists(select 1 from aluno_preferencias_jogos where aluno_id=17);
  result:=roar_save_game_preferences(17,5,'{"pieceCount":2}');
  assert (result->>'pieceCount')::integer=2;
  result:=roar_save_game_preferences(17,5,'{"showHints":false}');
  assert (result->>'pieceCount')::integer=2 and (result->>'showHints')::boolean=false;
  -- Atomic completion awards exactly once. Retry returns original response.
  result:=roar_register_progress(17,1,1,12,true,'00000000-0000-4000-8000-000000000001','[{"palavra":"HEAD","acertos":1,"erros":1,"ajudas":0}]');
  assert (result->'data'->>'xp_ganho')::integer=45;
  result:=roar_register_progress(17,1,1,12,true,'00000000-0000-4000-8000-000000000001','[{"palavra":"HEAD","acertos":1,"erros":1,"ajudas":0}]');
  assert (select count(*) from historico_desempenho where aluno_id=17)=1;
  assert (select count(*) from aluno_palavras_pratica where aluno_id=17)=1;
  assert (select xp_total from alunos where id=17)=445;
  -- A new review records fresh evidence, without a second activity reward.
  result:=roar_register_progress(17,1,0,8,true,'00000000-0000-4000-8000-000000000002','[{"palavra":"HEAD","acertos":1,"erros":0,"ajudas":1}]');
  assert (result->'data'->>'xp_ganho')::integer=0;
  assert (select count(*) from historico_desempenho where aluno_id=17)=1;
  assert (select count(*) from aluno_palavras_pratica where aluno_id=17)=2;
  result:=roar_student_word_report(17);
  assert (result->'palavras'->0->>'acertos')::integer=2;
  assert (result->'palavras'->0->>'tentativas')::integer=2;
  assert (result->'palavras'->0->>'precisa_revisao')::boolean=true;
  -- A later independent success clears the suggestion, without erasing history.
  result:=roar_register_progress(17,1,0,8,true,'00000000-0000-4000-8000-000000000005','[{"palavra":"HEAD","acertos":1,"erros":0,"ajudas":0}]');
  assert (result->'data'->>'xp_ganho')::integer=0;
  result:=roar_student_word_report(17);
  assert (result->'palavras'->0->>'precisa_revisao')::boolean=false;
  assert (result->'palavras'->0->>'acertos')::integer=3;
  assert (result->'palavras'->0->>'erros')::integer=1;
  assert (result->'palavras'->0->>'ajudas')::integer=1;
  assert (result->'palavras'->0->>'tentativas')::integer=3;
  assert (select xp_total from alunos where id=17)=445;
  assert (select count(*) from historico_desempenho where aluno_id=17)=1;
  -- Reusing a request for another activity is rejected, not silently accepted.
  result:=roar_register_progress(17,2,0,1,true,'00000000-0000-4000-8000-000000000001','[]');
  assert result->>'code'='ATTEMPT_ACTIVITY_MISMATCH';
end $$;

-- Inject a database failure after history is written; both changes must roll back.
create function test_block_reward() returns trigger language plpgsql as $$ begin
  if new.xp_total>old.xp_total then raise exception 'injected reward failure'; end if;
  return new;
end $$;
create trigger test_reward_failure before update on alunos for each row execute function test_block_reward();
do $$ begin
  begin
    perform roar_register_progress(17,2,0,2,true,'00000000-0000-4000-8000-000000000003','[{"palavra":"FOOT","acertos":1,"erros":0,"ajudas":0}]');
    raise exception 'Expected reward failure';
  exception when others then
    if sqlerrm <> 'injected reward failure' then raise; end if;
  end;
  assert not exists(select 1 from historico_desempenho where atividade_id=2);
  assert not exists(select 1 from aluno_palavras_pratica where palavra='FOOT');
  assert not exists(select 1 from roar_progress_requests where id_tentativa='00000000-0000-4000-8000-000000000003');
  assert (select xp_total from alunos where id=17)=445;
end $$;
drop trigger test_reward_failure on alunos;
drop function test_block_reward();

-- Inject delivery failure; no XP can be deducted without granting ownership.
update alunos set xp_total=500 where id=18;
create function test_block_delivery() returns trigger language plpgsql as $$ begin raise exception 'injected delivery failure'; end $$;
create trigger test_delivery_failure before insert on aluno_skins_lex for each row execute function test_block_delivery();
do $$ begin
  begin
    perform roar_shop_transaction(18,'comprar',2);
    raise exception 'Expected delivery failure';
  exception when others then
    if sqlerrm <> 'injected delivery failure' then raise; end if;
  end;
  assert (select xp_total from alunos where id=18)=500;
  assert not exists(select 1 from aluno_skins_lex where aluno_id=18);
end $$;
drop trigger test_delivery_failure on aluno_skins_lex;
drop function test_block_delivery();

-- Missing/null values are rejected before they can cause partial writes.
do $$ begin
  begin
    perform roar_register_progress(17,3,null,1,true,'00000000-0000-4000-8000-000000000004','[]');
    raise exception 'Expected null validation';
  exception when others then
    if sqlerrm <> 'Invalid progress data' then raise; end if;
  end;
  begin
    perform roar_register_progress(17,3,0,1,true,'00000000-0000-4000-8000-000000000004','[{"palavra":"FOOT"}]');
    raise exception 'Expected word validation';
  exception when others then
    if sqlerrm <> 'Invalid word evidence' then raise; end if;
  end;
  assert not exists(select 1 from historico_desempenho where atividade_id=3);
  assert (roar_shop_transaction(17,null,3)->>'code')='INVALID_SHOP_ACTION';
end $$;
