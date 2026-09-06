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
- senha local padrão: `icarus-desenvolvimento`.

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
- senha local padrão: `icarus-desenvolvimento`.

As credenciais padrão servem somente ao desenvolvimento local. Para alterá-las,
defina `ICARUS_RABBITMQ_USUARIO` e `ICARUS_RABBITMQ_SENHA`.
As portas publicadas também podem ser alteradas com `ICARUS_RABBITMQ_PORTA` e
`ICARUS_RABBITMQ_PORTA_MANAGEMENT`.

Assim como o MinIO, as portas ficam publicadas somente em `127.0.0.1` — não são
expostas fora do host (seção 10.3 da arquitetura). O console administrativo é
uma ferramenta de desenvolvimento; não deve ser habilitado/exposto em produção.

Consumidores (API em `icarus-platform`, trabalhador em `icarus-data`) hoje
rodam fora de container e se conectam por `localhost:5672` com as portas
publicadas acima. Quando esses processos forem containerizados, será preciso
uma rede Docker compartilhada entre os repositórios para a comunicação
acontecer pelo nome do serviço em vez de portas publicadas no host.

## Pendências

**Estratégia de versionamento das imagens Docker.** Hoje cada serviço usa uma
convenção diferente, sem termos parado para decidir isso de propósito:

- `minio/minio:RELEASE.2025-09-07T16-13-09Z` (aqui) — tag de release imutável, 100% fixada.
- `rabbitmq:4.0-management` (aqui) — major.minor fixados, patch "flutua" a cada `pull`.
- `postgres:16` (`icarus-platform/docker-compose.yml`) — só a major fixada; minor/patch "flutuam".

O trade-off: tag flutuante pega correção de segurança automaticamente mas não
é 100% reprodutível entre execuções/máquinas diferentes; tag imutável é
reprodutível mas exige atualização manual periódica (e checar CVEs
manualmente). Precisamos decidir **uma convenção única** para todos os
serviços (provável candidato: tag imutável/digest para todos, seguindo o
exemplo do MinIO) e aplicá-la de forma consistente. Não decidido ainda —
discutir antes de adicionar novos serviços (ex.: trabalhador Python, Nginx).
