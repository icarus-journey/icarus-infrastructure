# Icarus Infrastructure

Reúne a configuração dos ambientes, a integração dos serviços e os recursos
necessários para executar e operar o Icarus.

## Ambiente de dados

Inicie o armazenamento de arquivos brutos:

```bash
docker compose up -d minio
```

- API S3: `http://localhost:9100`;
- console administrativo: `http://localhost:9101`;
- usuário local padrão: `icarus`;
- senha local padrão: `urubu@100`.

As credenciais padrão servem somente ao desenvolvimento local. Para alterá-las,
defina `ICARUS_MINIO_USUARIO` e `ICARUS_MINIO_SENHA`.
As portas publicadas também podem ser alteradas com
`ICARUS_MINIO_PORTA_API` e `ICARUS_MINIO_PORTA_CONSOLE`.

O ETL também pode ser construído e executado como contêiner:

```bash
docker compose --profile dados run --rm etl ingerir-bronze
```

O MinIO e o DuckDB usam volumes Docker distintos. O serviço `etl` é executado
sob demanda e não permanece ativo após a carga.

## Mensageria

Inicie o RabbitMQ 

```bash
docker compose up -d rabbitmq
```

- protocolo AMQP: `localhost:5672`;
- console administrativo: `http://localhost:15672`;
- usuário local padrão: `icarus`;
- senha local padrão: `urubu@100`.

As credenciais padrão servem somente ao desenvolvimento local. Para alterá-las,
defina `ICARUS_RABBITMQ_USUARIO` e `ICARUS_RABBITMQ_SENHA`.
As portas publicadas também podem ser alteradas com `ICARUS_RABBITMQ_PORTA` e
`ICARUS_RABBITMQ_PORTA_MANAGEMENT`.

Assim como o MinIO, as portas ficam publicadas somente em `127.0.0.1` — não são
expostas fora do host (seção 10.3 da arquitetura). O console administrativo é
uma ferramenta de desenvolvimento; não deve ser habilitado/exposto em produção.

A API roda no host e o trabalhador atual pertence a `icarus-ai`, executado em
contêiner com rede do host no iniciador Linux. Ambos usam o RabbitMQ local;
`icarus-data` executa o ETL sob demanda. O relatório semanal usa o volume
`worker_operacional:/estado` para SQLite e saúde transacional, sem credenciais
do PostgreSQL no trabalhador. Não remova esse volume para reiniciar o app.

## Aplicativo mobile no Expo Go

O Metro pode ser executado como serviço local. A branch `development` do
mobile usa Expo SDK 57 e abre no Expo Go; ditado e `react-native-keychain`
ficam na branch `feature/recursos-nativos`, que exige uma build própria.

```bash
docker compose up -d --build mobile
docker compose logs -f mobile
```

Abra a URL `exp://` exibida nos logs pelo Expo Go. No iPhone físico, a CLI e o
Expo Go precisam usar a mesma conta Expo. O túnel só transporta o Metro: para
testes fora da rede, configure um endereço HTTPS público da API em
`EXPO_PUBLIC_API_URL`; na rede local, use `http://IP_DA_MAQUINA:5138`. O código do
checkout de `icarus-mobile` é montado no contêiner, preservando a atualização
automática durante o desenvolvimento.

## Observabilidade

Grafana, Tempo (traces), Prometheus (métricas) e Loki (logs) — seção 11 do
`01-arquitetura-da-solucao.md` no `icarus-context`. Os logs continuam
também em JSON no stdout de cada processo (exigência da mesma seção) — o
Loki é um destino *a mais*, não substitui o stdout.

```bash
docker compose up -d tempo prometheus loki grafana
```

- Grafana: `http://localhost:3000` (usuário/senha padrão: `icarus`/`icarus-desenvolvimento`);
- Tempo: recebe traces via OTLP/HTTP em `localhost:4318`; API de consulta em `localhost:3200` (a mesma que o Grafana usa internamente — publicada também no host para depuração via `curl`);
- Prometheus: `http://localhost:9090`, com o **recebedor OTLP habilitado** (`--web.enable-otlp-receiver`) — a API empurra métricas direto, sem *scrape*;
- Loki: recebe logs via API de push em `localhost:3100` — a API empurra logs direto, sem agente coletor (ex.: Promtail) no meio. Retenção de **1 semana** (`compactor.retention_enabled: true` em `observabilidade/loki-config.yaml` — sem isso, `retention_period` sozinho não apaga nada).

As credenciais padrão do Grafana servem só ao desenvolvimento local. Para
alterá-las, defina `ICARUS_GRAFANA_USUARIO` e `ICARUS_GRAFANA_SENHA`. Portas
alteráveis via `ICARUS_TEMPO_PORTA_OTLP`, `ICARUS_TEMPO_PORTA_QUERY`,
`ICARUS_PROMETHEUS_PORTA`, `ICARUS_LOKI_PORTA` e `ICARUS_GRAFANA_PORTA`.

Tempo, Prometheus e Loki já vêm pré-configurados como fontes de dados no
Grafana (`observabilidade/grafana-datasources.yml`) — abrir o Grafana já é
suficiente para explorar logs, traces e métricas, sem configuração manual.
O Tempo também já vem ligado ao Loki (um clique num trace abre os logs
daquela requisição) e vice-versa (um clique numa linha de log com `TraceId`
abre o trace correspondente) — a correlação usa o `TraceId` **dentro do
texto** da linha de log, não como *label* do Loki (`TraceId` é alta
cardinalidade — um valor novo a cada requisição — e nunca deve virar label,
sob pena de degradar a performance do Loki).

Consumidores hoje rodam fora de container (mesma situação do RabbitMQ, ver
seção acima) e se conectam pelas portas publicadas em `localhost`.

## Iniciar o MVP local

Em Linux, com Docker/Compose, Python ≥3.10 com pip, Node.js 22 e o SDK .NET
indicado no `global.json` da plataforma:

```bash
./scripts/iniciar-projeto.sh
```

Usa os checkouts atuais, lado a lado no workspace. Enquanto a integração do
onboarding não estiver em `development`, use:

| Repositório | Branch |
| --- | --- |
| `icarus-platform` | `feature/onboarding-integrado` |
| `icarus-mobile` | `feature/onboarding-e-auth` |
| `icarus-ai` | `feature/onboarding-integrado` |

Preencha uma vez `icarus-ai/.env` com o provedor, modelo, endpoint e chave de
IA. O script usa o RabbitMQ local também no worker. A chave permanece nesse
arquivo ignorado pelo Git; ela não vai para o aplicativo.

Antes de iniciar a API, aguarda a saúde do MinIO e fornece sua configuração
para a foto de perfil. As credenciais ficam somente no ambiente da API e em
`.execucao/ambiente-api.json`, ignorado pelo Git, com permissão `0600`.

O comando inicia PostgreSQL, RabbitMQ e MinIO, aplica migrations no banco do
projeto (`POSTGRES_DB`, por padrão `icarus`), inicia a API em 5138, o worker com Python 3.13 em
contêiner e o Expo Go em 8082. Dependências são preparadas na primeira execução;
o código dos três repositórios continua nos seus próprios checkouts. Contas,
épicos, campanhas e missões persistidos pela API permanecem no banco entre
execuções; o iniciador não cria usuários, dados fictícios ou cenários de teste.

Com um Android autorizado no `adb`, configura o acesso por USB, abre o Expo Go
e espelha a tela. Requer Expo Go instalado, depuração USB autorizada e sessão
gráfica no notebook; em Linux x86_64 baixa o scrcpy 5.0.1 quando necessário.
Sem celular autorizado, publica o Expo na rede local; abra pelo mesmo Wi-Fi.
Use `ICARUS_IP_LOCAL` se a detecção escolher a interface errada.

O QR fica em `.execucao/qr-expo.png` e também na Área de Trabalho, se existir.
O ditado exige build nativa e fica indisponível no Expo Go. Configurações,
PIDs e logs locais ficam em `.execucao/`; logs da IA: `docker compose logs -f
worker`. Cada execução reinicia API e Expo gerenciados pelo script;
mantém o espelhamento durante a preparação e reabre sua janela ao final.
Após atualizar uma branch, execute o mesmo comando novamente.

Para encerrar API, worker, Expo e espelhamento, mantendo os serviços de dados:

```bash
./scripts/iniciar-projeto.sh --parar
```

## Deployment local de development

A branch `development` contém o script inicial de deployment local. Ele cria
ou atualiza checkouts isolados das branches remotas `development` de mobile,
platform, dados e infraestrutura; depois inicia PostgreSQL, MinIO, RabbitMQ e
o Expo Mobile em túnel.
As cópias de trabalho da equipe não são trocadas nem atualizadas pelo script.

```bash
git switch development
./scripts/implantar-development.sh
```

Por padrão, os checkouts ficam em `.deployment/development/`. Para usar outro
local, defina `ICARUS_DIRETORIO_DEPLOYMENT`. A API ainda não é iniciada nem
recebe migrations; o mobile é iniciado como Expo em túnel a partir da revisão
de `development`.

## Pendências

**Estratégia de versionamento das imagens Docker.** Hoje cada serviço usa uma
convenção diferente, sem termos parado para decidir isso de propósito:

- `minio/minio:RELEASE.2025-09-07T16-13-09Z` (aqui) — tag de release imutável, 100% fixada.
- `rabbitmq:4.0-management` (aqui) — major.minor fixados, patch "flutua" a cada `pull`.
- `grafana/tempo:2.6.1`, `prom/prometheus:v3.0.1`, `grafana/grafana:11.3.0`, `grafana/loki:3.3.0` (aqui) — major.minor.patch fixados, mas sem revisão periódica combinada.
- `postgres:16` (`icarus-platform/docker-compose.yml`) — só a major fixada; minor/patch "flutuam".

O trade-off: tag flutuante pega correção de segurança automaticamente mas não
é 100% reprodutível entre execuções/máquinas diferentes; tag imutável é
reprodutível mas exige atualização manual periódica (e checar CVEs
manualmente). Precisamos decidir **uma convenção única** para todos os
serviços (provável candidato: tag imutável/digest para todos, seguindo o
exemplo do MinIO) e aplicá-la de forma consistente. Não decidido ainda —
discutir antes de adicionar novos serviços (ex.: trabalhador Python, Nginx).

## Verificar a integração analítica local

Com o projeto iniciado e a Gold publicada pelo procedimento de Dados:

```bash
python3 icarus-infrastructure/scripts/verificar-consumo-analitico.py
```

Execute da raiz do workspace. O comando cria três contas temporárias pela API,
verifica seleção pública por idade, linhagem, autenticação e isolamento. Insere
conclusões de teste somente na conta temporária adulta, solicita uma geração
real ao provedor configurado e verifica persistência/idempotência. Isso pode
consumir uma chamada do provedor. Remove as contas ao terminar, inclusive após
falha, e salva evidência sem tokens em
`.execucao/evidencias/consumo-analitico.json`. Não adiciona histórico a contas
existentes nem publica novamente a Gold. O teste exige Docker/psql local,
banco `icarus` e API 5138; `--api` altera somente o endereço HTTP.

API, mobile e trabalhador devem usar as features de onboarding desta sessão;
Gold vem de `icarus-data/feature/camada-silver`. Contratos HTTP e de mensagens
estão no [contexto analítico](../icarus-context/docs/implementation-design/platform/06-consumo-analitico-mobile-api.md).
