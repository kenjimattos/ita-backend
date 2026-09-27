# ita-backend

Backend do **ITA**, assistente financeiro do time 01 no hackathon Itaú. É uma API em FastAPI que lê o extrato dos clientes no BigQuery e usa o Gemini (Vertex AI) para responder perguntas sobre esses dados. Roda no Cloud Run, e o deploy é automático a cada push na `main`.

- **URL de produção:** https://ita-backend-540082622758.us-central1.run.app
- **Documentação interativa (Swagger):** https://ita-backend-540082622758.us-central1.run.app/docs

---

## Arquitetura

```
Cliente / front
      │  HTTPS
      ▼
Cloud Run: ita-backend  (FastAPI, roda como squad-agent-sa)
      │                         │
      │ SQL parametrizado        │ generate_content
      ▼                         ▼
BigQuery                     Vertex AI
hackathon_dados.             gemini-3.8-flash
extrato_sintetico            (location "global")
```

O agente não acessa o banco diretamente. O backend busca as transações com uma query controlada e parametrizada e manda só esse recorte para o Gemini.

## Estrutura do repositório

| Arquivo | Para que serve |
|---|---|
| `app.py` | A API: endpoints, acesso ao BigQuery e chamada ao Gemini. |
| `requirements.txt` | Dependências Python da imagem. |
| `Dockerfile` | Imagem do Cloud Run (Python 3.12 + uvicorn na porta `$PORT`). |
| `.gcloudignore` | O que **não** sobe para o Cloud Build (`.env`, `.gemini.json`, venv…). |
| `.github/workflows/deploy.yml` | Pipeline de deploy. |
| `.env` | Variáveis locais. **Não versionado.** |
| `package.json` | Sobra de um começo em Node. Não é usado pelo backend. |

## Rodando localmente

**Pré-requisitos:** Python 3.9 ou mais recente e o [gcloud](https://cloud.google.com/sdk/docs/install) instalado.

1. **Autentique no Google Cloud.** As bibliotecas usam as *Application Default Credentials* (ADC), então nenhuma chave vai no código.
   ```bash
   gcloud auth login
   gcloud config set project batalha-time-01-97zr
   gcloud auth application-default login
   gcloud auth application-default set-quota-project batalha-time-01-97zr
   ```
   Use nos dois logins a mesma conta com acesso ao projeto. Se a ADC ficar em outra conta, aparece o erro `serviceusage.services.use`.

2. **Crie o `.env`:**
   ```bash
   TABLE_NAME=batalha-time-01-97zr.hackathon_dados.extrato_sintetico
   ```

3. **Instale e rode:**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app:app --reload --env-file .env
   ```
   Depois abra http://127.0.0.1:8000/docs.

Localmente, o BigQuery e o Gemini são chamados **com a sua conta**. No Cloud Run, com a conta de serviço do serviço (veja [Identidades](#identidades-e-permissões)).

---

## Deploy

### Fluxo automático

Todo push na `main` dispara o workflow [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml):

```
push na main
   │
   ▼
GitHub Actions (environment "production")
   │ 1. checkout do código
   │ 2. instala o gcloud
   │ 3. autentica: troca o secret GCP_CREDENTIALS por um access token de 1h
   │ 4. Cloud Build: gcloud builds submit
   │       → imagem .../agentes/ita-backend:<sha do commit>
   │ 5. Cloud Run: gcloud run deploy ita-backend
   │       → nova revisão recebe 100% do tráfego
   │ 6. apaga o token do runner
   ▼
https://ita-backend-540082622758.us-central1.run.app
```

- **Tag da imagem = SHA do commit.** Cada revisão no Cloud Run aponta para um commit exato, o que facilita rastrear e voltar versões.
- **Um deploy por vez.** O `concurrency` do workflow enfileira pushes seguidos, em vez de rodá-los em paralelo.
- **Disparo manual:** na aba **Actions → Deploy ita-backend → Run workflow** (`workflow_dispatch`).
- **Tempo típico:** cerca de 2 a 3 minutos do push até o serviço atualizado.

### Identidades e permissões

O fluxo usa **duas identidades diferentes**:

| Momento | Identidade | Precisa de |
|---|---|---|
| **Deploy** (GitHub Actions) | credencial de usuário do dono do repositório (secret `GCP_CREDENTIALS`) | Cloud Build, Artifact Registry, Cloud Run Admin, `iam.serviceAccountUser` na conta de runtime |
| **Execução** (Cloud Run) | `squad-agent-sa@batalha-time-01-97zr.iam.gserviceaccount.com` | BigQuery (Job User e acesso à tabela) e Vertex AI User. Todos já concedidos pela organização |

**Por que o deploy usa uma credencial de usuário:** o jeito recomendado seria Workload Identity Federation ou uma conta de serviço dedicada ao deploy. Nenhum dos dois é possível neste projeto. A criação de chaves de conta de serviço está bloqueada pela política da organização (`iam.disableServiceAccountKeyCreation`), e o time não tem permissão para criar pools de identidade nem contas de serviço. Veja [Segurança e pendências](#segurança-e-pendências).

**Por que o serviço não usa a conta padrão:** a conta padrão do Compute (`540082622758-compute@developer.gserviceaccount.com`) não tem acesso ao BigQuery nem ao Vertex AI. O `--service-account` no workflow é obrigatório. Sem ele, os endpoints voltam a dar erro 403.

### Secrets e configuração

**Secret do GitHub** (Settings → Environments → `production`):

| Secret | Conteúdo |
|---|---|
| `GCP_CREDENTIALS` | O JSON de `~/.config/gcloud/application_default_credentials.json` (tipo `authorized_user`) |

Só a branch `main` pode usar o environment `production`. Para atualizar a credencial:

```bash
gh secret set GCP_CREDENTIALS --env production --repo kenjimattos/ita-backend \
  < ~/.config/gcloud/application_default_credentials.json
```

**Variáveis de ambiente do serviço**, definidas no `env:` do workflow e aplicadas com `--set-env-vars`:

| Variável | Valor | Uso |
|---|---|---|
| `TABLE_NAME` | `batalha-time-01-97zr.hackathon_dados.extrato_sintetico` | Tabela consultada |
| `GOOGLE_CLOUD_PROJECT` | `batalha-time-01-97zr` | Projeto do BigQuery e do Vertex AI |
| `GEMINI_MODEL` (opcional) | padrão `gemini-3.8-flash` | Modelo do agente |
| `GEMINI_LOCATION` (opcional) | padrão `global` | Location do Vertex AI |

O `--set-env-vars` **substitui todas** as variáveis do serviço a cada deploy. Variáveis novas devem entrar no workflow, não ser configuradas à mão no console, senão o próximo deploy as apaga.

Nenhuma chave de API é necessária no Cloud Run. O Gemini é chamado pelo Vertex AI usando a conta de serviço. Se um dia precisar de um segredo em tempo de execução, use o Secret Manager com `--set-secrets` (a `squad-agent-sa` já tem `secretAccessor`) e troque o `--clear-secrets` do workflow.

### Como fazer um deploy

A `main` tem uma regra que **exige pull request com 1 aprovação**:

1. Crie uma branch, faça as mudanças e abra um PR para a `main`.
2. Depois da aprovação, faça o merge. O merge é um push na `main`, então o deploy dispara sozinho.
3. Acompanhe na aba **Actions** ou pelo terminal:
   ```bash
   gh run watch
   ```

Admins do repositório conseguem dar push direto na `main` (o GitHub avisa `Bypassed rule violations`). Evite isso fora de emergências.

### Verificar um deploy

```bash
# Revisão ativa e imagem (a tag deve ser o SHA do último commit)
gcloud run services describe ita-backend --region=us-central1 \
  --format="value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)"

# Teste rápido
curl -s -o /dev/null -w "%{http_code}\n" \
  https://ita-backend-540082622758.us-central1.run.app/usuarios/001221d1-3626-45c1-807a-990502adf808/extrato

# Erros recentes
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="ita-backend" AND severity>=ERROR' \
  --freshness=1h --limit=20 --format="value(timestamp,textPayload)"
```

### Rollback

Cada deploy cria uma revisão nova, e as anteriores continuam disponíveis. Para voltar o tráfego para uma delas:

```bash
# Listar revisões
gcloud run revisions list --service=ita-backend --region=us-central1

# Mandar 100% do tráfego para uma revisão anterior
gcloud run services update-traffic ita-backend --region=us-central1 \
  --to-revisions=ita-backend-0000X-xxx=100
```

O rollback é temporário: **o próximo push na `main` faz deploy de novo**. Para desfazer de vez, reverta o commit (`git revert`) e faça merge.

### Deploy manual (sem GitHub Actions)

Útil se o GitHub Actions estiver fora do ar ou a credencial expirar. Usa a sua sessão local do gcloud:

```bash
SHA=$(git rev-parse HEAD)
IMAGE=us-central1-docker.pkg.dev/batalha-time-01-97zr/agentes/ita-backend:$SHA

gcloud builds submit --tag=$IMAGE

gcloud run deploy ita-backend \
  --image=$IMAGE \
  --region=us-central1 \
  --allow-unauthenticated \
  --max-instances=5 \
  --service-account=squad-agent-sa@batalha-time-01-97zr.iam.gserviceaccount.com \
  --set-env-vars=TABLE_NAME=batalha-time-01-97zr.hackathon_dados.extrato_sintetico,GOOGLE_CLOUD_PROJECT=batalha-time-01-97zr
```

Mantenha estes parâmetros iguais aos do workflow. O que for diferente vale só até o próximo deploy automático.

---

## Problemas conhecidos e soluções

| Sintoma | Causa | Solução |
|---|---|---|
| `403 ... bigquery.jobs.create permission` no Cloud Run | O serviço está rodando com a conta padrão do Compute | Faça o deploy com `--service-account=squad-agent-sa@...` |
| `404 Publisher model gemini-3.8-flash was not found` | Location `us-central1`. Os modelos Gemini 3.x só estão em `global` | `GEMINI_LOCATION=global` (já é o padrão). O `.gemini.json` ainda diz `us-central1` |
| `set-quota-project`: falta `serviceusage.services.use` | A ADC local está logada numa conta sem acesso ao projeto | Rode `gcloud auth application-default login` de novo com a conta certa |
| `KeyError: 'TABLE_NAME'` ao rodar localmente | O `.env` não foi carregado | `uvicorn app:app --env-file .env` |
| Workflow falha no passo "Autenticar" | A credencial do secret foi revogada ou expirou | Refaça o login da ADC e [atualize o secret](#secrets-e-configuração) |
| Primeira chamada alguns segundos mais lenta | Cold start (~2,7 s) depois de ~15 min sem uso | Faça uma chamada de aquecimento antes de demonstrar, ou use `--min-instances=1` |

## Latência

Medições reais do `POST /agente` no Cloud Run: **cerca de 10 s por chamada**, dos quais ~0,6 s são do BigQuery e ~90% do tempo é do Gemini. Decompondo uma chamada ao Gemini com o prompt real:

| Parte | Tempo | Origem |
|---|---|---|
| Rede, fila e leitura do prompt | ~1,4 s | Infraestrutura (mínimo) |
| Modelo pensando (~660 tokens) | ~4,7 s | Configuração (raciocínio no padrão) |
| Modelo escrevendo (~400 tokens) | ~2,8 s | Prompt (sem limite de tamanho) |

Limitando o raciocínio (`thinking_budget`) e pedindo respostas curtas, a mesma chamada caiu para **~2,7 s** em teste. Carga concorrente (10 chamadas simultâneas) não degradou o serviço de forma relevante. O limite prático é a cota de requisições do Gemini no projeto, que é compartilhada com os outros serviços do time.

## Segurança e pendências

- **O deploy depende de uma credencial pessoal.** O secret `GCP_CREDENTIALS` tem acesso a tudo que o dono dessa credencial acessa no Google Cloud, não só a este projeto. Mitigações: repositório privado, environment `production` restrito à `main` e token de curta duração no runner.
  - **Ao fim do hackathon:** revogue com `gcloud auth application-default revoke` e apague o secret no GitHub.
  - **Pendência:** pedir aos organizadores Workload Identity Federation para o GitHub e uma conta de serviço de deploy (`run.admin`, `artifactregistry.writer`, `cloudbuild.builds.editor`, `iam.serviceAccountUser`). Depois disso, basta trocar o passo "Autenticar" por `google-github-actions/auth`.
- **O endpoint é público e não tem autenticação.** Qualquer pessoa com a URL consulta o extrato de qualquer `id_usuario`, e cada chamada ao `/agente` gasta cota do Gemini. Isso é aceitável para a demonstração com dados sintéticos, mas não para dados reais.
- O segredo `ita-backend-gcp-credentials` no Secret Manager não é usado pelo `ita-backend`. Ele existe para outro serviço do time.
