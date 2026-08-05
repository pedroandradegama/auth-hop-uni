-- =============================================================================
-- Migration NOVA (nao editar a aplicada 20260630203905_...): Unimed Intercambio
-- RASCUNHO DE REFERENCIA — Codex valida contra o corpo REAL de
-- fn_autorizacao_enfileirar antes de aplicar. Onde nao temos o corpo, ha
-- marcadores >>> COLE/AJUSTE <<<.
-- =============================================================================

-- 1) Persistir o CRM do solicitante (a tabela hoje so tem medico_solicitante text)
alter table public.autorizacoes
  add column if not exists medico_solicitante_crm text;
comment on column public.autorizacoes.medico_solicitante_crm is
  'CRM do medico solicitante. Exigido por unimed_intercambio (CONNECTA).';

-- 2) Recriar fn_autorizacao_enfileirar com 3 correcoes + tratamento requer_humano.
--    >>> IMPORTANTE: copie o corpo ATUAL da funcao (migration 20260630203905) e
--    aplique SOMENTE as mudancas marcadas abaixo. Assinatura mantida.
create or replace function public.fn_autorizacao_enfileirar(
  p_org_id uuid, p_sessao_id uuid, p_contexto jsonb
) returns public.autorizacoes
language plpgsql security definer as $$
declare
  v_convenio_slug text;
  v_exames jsonb;
  -- >>> COLE AQUI as demais declaracoes do corpo atual <<<
begin
  v_convenio_slug := coalesce(p_contexto->>'convenio_slug', 'unimed_recife');

  -- >>> COLE AQUI: dedup por idempotency_key (retorno da linha existente), como no
  --     corpo atual. NOTA: por isso re-"Go" NAO conserta linha antiga (auditar). <<<

  -- (A) MODALIDADE — incluir unimed_intercambio no ramo "qualquer modalidade":
  if v_convenio_slug in ('sassepe','sulamerica','unimed_intercambio') then
    -- aceita qualquer modalidade; (B) preservar quantidade com cast defensivo:
    select coalesce(jsonb_agg(jsonb_build_object(
             'codigo_tuss', e->>'codigo_tuss',
             'nome',        e->>'nome',
             'quantidade',
               case when coalesce(e->>'quantidade','') ~ '^[1-9][0-9]*$'
                    then (e->>'quantidade')::int else 1 end
             -- >>> mantenha os demais campos do jsonb_build_object atual <<<
           )), '[]'::jsonb)
      into v_exames
      from jsonb_array_elements(coalesce(p_contexto->'exames','[]'::jsonb)) e;
  else
    -- unimed_recife: mantem filtro RM/TC do corpo atual, MAS tambem preservar
    -- quantidade defensiva no jsonb_build_object:
    select coalesce(jsonb_agg(jsonb_build_object(
             'codigo_tuss', e->>'codigo_tuss',
             'sub_tipo',    upper(e->>'modalidade'),
             'nome',        e->>'nome',
             'quantidade',
               case when coalesce(e->>'quantidade','') ~ '^[1-9][0-9]*$'
                    then (e->>'quantidade')::int else 1 end
           )), '[]'::jsonb)
      into v_exames
      from jsonb_array_elements(coalesce(p_contexto->'exames','[]'::jsonb)) e
     where upper(e->>'modalidade') in ('TC','RM');
  end if;

  -- (C) CRM — incluir a coluna no INSERT e nos VALUES:
  insert into public.autorizacoes (
    org_id, sessao_id, convenio, carteirinha, cpf,
    medico_solicitante, medico_solicitante_crm, exames, anexos_paths, status
    -- >>> mantenha as demais colunas do INSERT atual <<<
  ) values (
    p_org_id, p_sessao_id, v_convenio_slug,
    p_contexto->>'carteirinha', p_contexto->>'cpf',
    coalesce(p_contexto->>'medico_solicitante', p_contexto#>>'{medico_solicitante,nome}'),
    coalesce(p_contexto->>'crm', p_contexto#>>'{medico_solicitante,crm}'),
    v_exames,
    coalesce(p_contexto->'pedido_medico_storage_paths','[]'::jsonb),
    'pendente'
    -- >>> mantenha os demais valores do INSERT atual <<<
  )
  -- >>> mantenha o ON CONFLICT / RETURNING do corpo atual <<<
  returning * into strict "..."; -- ajustar ao padrao atual

  -- (D) requer_humano vindo do callback da VPS (Pendencia 1):
  --     garantir que o receive-autorizacao / RPC de gravacao de resultado saiba
  --     persistir status='requer_humano' + motivo/evidencias + sinalizar operador
  --     e NAO re-enfileirar. (Isto normalmente vive no receive-autorizacao, nao
  --     nesta fn de enfileirar — ajustar no lugar correto.)

  return "..."; -- ajustar ao retorno atual
end;
$$;

-- 3) Regenerar src/integrations/supabase/types.ts apos aplicar (novo campo).
