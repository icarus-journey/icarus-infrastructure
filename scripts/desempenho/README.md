# Carga local da API — MVP-26

JMeter 5.6.3 em modo CLI, Python 3.10+, Java, .NET 10 e Docker. Execute da raiz
do workspace, com API iniciada pelo inicializador oficial, PostgreSQL e RabbitMQ
ativos. A porta 5139 deve estar livre. Não execute compilação, testes ou ETL
durante as janelas medidas.

O preparador lê a configuração do processo gerenciado, sem gravar seus segredos.
Copia somente a estrutura operacional, migrations e os dados **públicos** Gold;
gera 50 contas `carga-*@teste.local`, seis meses de planejamento, realizações,
medições, Diário, saldo e recompensas em `icarus_carga_mvp26_*`. O vhost
`icarus-carga-mvp26` é exclusivo, sem trabalhador de IA. Não copia perfis, fotos
ou registros pessoais e não escreve no banco `icarus`.

## Executar

Compile a revisão anterior em Release antes de preparar: o binário é congelado
em `.execucao/carga-api/api-antes/`. Use a estrutura/migrations correspondentes
a essa revisão no banco de origem. Não use o resultado como comparação entre
revisões se a origem e o binário não corresponderem.

```bash
dotnet build icarus-platform/src/Icarus.Api -c Release --nologo
python3 icarus-infrastructure/scripts/desempenho/preparar.py --verificar
python3 icarus-infrastructure/scripts/desempenho/preparar.py
python3 icarus-infrastructure/scripts/desempenho/executar.py antes
```

Após implementar a mudança, recompile a API em Release e execute `depois`.
Cada etapa parte de um clone novo da mesma fixture; `depois` aplica as migrations
atuais somente ao banco exclusivo. A ferramenta EF da versão do projeto deve
estar instalada pelo inicializador. Para diagnóstico curto, existe a etapa
`smoke` (`--duracao 15 --usuarios 1 --rampa 1 --intervalo 100`).

```bash
dotnet build icarus-platform/src/Icarus.Api -c Release --nologo
python3 icarus-infrastructure/scripts/desempenho/executar.py depois
python3 icarus-infrastructure/scripts/desempenho/analisar.py \
  icarus-infrastructure/.execucao/carga-api/antes.jtl \
  --saida icarus-infrastructure/.execucao/carga-api/metricas-antes.json
python3 icarus-infrastructure/scripts/desempenho/analisar.py \
  icarus-infrastructure/.execucao/carga-api/depois.jtl \
  --saida icarus-infrastructure/.execucao/carga-api/metricas-depois.json
python3 icarus-infrastructure/scripts/desempenho/preparar.py --limpar
```

O padrão é 675 segundos, rampa de 30 segundos, 50 usuários e intervalo de um
segundo por ação; o analisador usa a janela de 45 a 645 segundos. Verifica
600 segundos completos, 50 threads durante toda a janela, presença das operações,
p95 por operação até 2 s e erro inferior a 1%. Exibe também os resultados globais,
incluindo login. O `404` de acesso a outro titular é esperado e validado.

O ciclo cobre perfil, planejamento, avulsas, jornada, Diário, loja, três períodos
de progresso, Gold, relatório salvo, históricos, criação/conclusão de missão e
resgate/estorno. O relatório é solicitado uma vez por pessoa; o ensaio mede a
API e a publicação assíncrona, **não** a geração externa por IA ou o ETL.
`DOTNET_PROCESSOR_COUNT=2` configura o runtime da API de carga; não reserva CPUs.

## Resultados e limites

`ICARUS_CARGA_SAIDA` permite outra pasta dentro de `.execucao/`. Não rode dois
ensaios simultâneos: banco, vhost e porta são fixos. A repetição recusa resultados
e bancos existentes; preserve os artefatos e limpe o ambiente antes de recomeçar.
O CSV de contas contém senha sintética e recebe permissão 600. Não publique esse
CSV nem logs privados. O JTL não grava corpos, tokens ou cabeçalhos.
`--limpar` remove somente os bancos/vhost de carga conhecidos e o CSV, preservando
os resultados; execute enquanto a API gerenciada original ainda estiver ativa.

O cenário permite reproduzir a medição local; não comprova capacidade de produção,
latência de rede móvel, geração por IA, contenção entre dispositivos do mesmo
usuário ou cobertura integral de todos os endpoints. As transações concorrentes
e a idempotência também são verificadas pelos testes PostgreSQL da Plataforma.
Os resultados e as ressalvas do MVP-26 estão no [contexto](../../../icarus-context/docs/implementation-design/platform/14-desempenho-api.md).
