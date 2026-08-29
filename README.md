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
