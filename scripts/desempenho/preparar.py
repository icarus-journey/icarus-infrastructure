import csv
import json
import os
from pathlib import Path
import secrets
import socket
import shutil
import subprocess
import time
import urllib.request
import uuid

RAIZ = Path(__file__).resolve().parents[3]
PASTA = Path(
    os.environ.get(
        "ICARUS_CARGA_SAIDA", RAIZ / "icarus-infrastructure/.execucao/carga-api"
    )
).resolve()
if not PASTA.is_relative_to(RAIZ / "icarus-infrastructure/.execucao"):
    raise ValueError("A saída deve permanecer na pasta privada .execucao.")
PASTA.mkdir(mode=0o700, parents=True, exist_ok=True)
PID_ORIGEM = json.loads(
    (RAIZ / "icarus-infrastructure/.execucao/api.pid.json").read_text()
)["pid"]
AMBIENTE = dict(
    x.split("=", 1)
    for x in Path(f"/proc/{PID_ORIGEM}/environ").read_text().split("\0")
    if "=" in x
)
INSPECAO = json.loads(
    subprocess.check_output(["docker", "inspect", "icarus-postgres"])
)[0]
PG = dict(x.split("=", 1) for x in INSPECAO["Config"]["Env"] if "=" in x)
BASE = "icarus_carga_mvp26_base"
VHOST = "icarus-carga-mvp26"


def executar(args, entrada=None):
    r = subprocess.run(
        args, input=entrada, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace")[:1500])
    return r.stdout


def sql(banco, texto):
    assert banco == "postgres" or banco.startswith("icarus_carga_mvp26")
    return executar(
        [
            "docker",
            "exec",
            "-i",
            "icarus-postgres",
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            PG["POSTGRES_USER"],
            "-d",
            banco,
            "-At",
        ],
        texto.encode(),
    )


def http(rota, corpo=None, token=None):
    cabecalhos = {"Content-Type": "application/json"}
    if token:
        cabecalhos["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        "http://127.0.0.1:5139" + rota,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers=cabecalhos,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def ambiente_api(banco):
    assert banco.startswith("icarus_carga_mvp26")
    e = AMBIENTE.copy()
    partes = e["ConnectionStrings__DefaultConnection"].split(";")
    e["ConnectionStrings__DefaultConnection"] = ";".join(
        ("Database=" + banco) if p.lower().startswith("database=") else p
        for p in partes
    )
    e.update(
        {
            "ASPNETCORE_URLS": "http://127.0.0.1:5139",
            "RabbitMq__Vhost": VHOST,
            "Serilog__MinimumLevel__Default": "Warning",
            "Serilog__MinimumLevel__Override__Microsoft.EntityFrameworkCore.Database.Command": "Warning",
            "DOTNET_PROCESSOR_COUNT": "2",
        }
    )
    return e


def iniciar(banco, etapa):
    with socket.socket() as teste:
        if teste.connect_ex(("127.0.0.1", 5139)) == 0:
            raise RuntimeError(
                "Porta 5139 ocupada; encerre apenas o processo de carga anterior."
            )
    log = (PASTA / f"api-{etapa}.log").open("ab")
    p = subprocess.Popen(
        ["dotnet", str(PASTA / f"api-{etapa}/Icarus.Api.dll")],
        cwd=RAIZ / "icarus-platform",
        env=ambiente_api(banco),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(100):
        if p.poll() is not None:
            raise RuntimeError("API de carga encerrou; consulte log privado")
        try:
            urllib.request.urlopen("http://127.0.0.1:5139/health", timeout=1).close()
            return p
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("API de carga não ficou pronta")


def parar(p):
    p.terminate()
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()


def preparar():
    if (PASTA / "ambiente.json").exists():
        raise RuntimeError(
            "Ambiente já preparado; use executar.py ou limpe a execução anterior."
        )
    shutil.copytree(
        RAIZ / "icarus-platform/src/Icarus.Api/bin/Release/net10.0",
        PASTA / "api-antes",
        dirs_exist_ok=True,
    )
    sql("postgres", f'CREATE DATABASE "{BASE}";')
    sql(BASE, "DROP SCHEMA public CASCADE;")
    for argumentos in [
        ["--schema-only", "--schema=public"],
        ["--data-only", '--table=public."__EFMigrationsHistory"'],
        ["--schema=dados_publicos"],
    ]:
        dados = executar(
            [
                "docker",
                "exec",
                "icarus-postgres",
                "pg_dump",
                "-U",
                PG["POSTGRES_USER"],
                "-d",
                PG["POSTGRES_DB"],
                *argumentos,
            ]
        )
        sql(BASE, dados.decode())
    executar(["docker", "exec", "icarus-rabbitmq-1", "rabbitmqctl", "add_vhost", VHOST])
    executar(
        [
            "docker",
            "exec",
            "icarus-rabbitmq-1",
            "rabbitmqctl",
            "set_permissions",
            "-p",
            VHOST,
            AMBIENTE["RabbitMq__Usuario"],
            ".*",
            ".*",
            ".*",
        ]
    )
    senha = secrets.token_urlsafe(24)
    api = iniciar(BASE, "antes")
    try:
        id_inicial = http(
            "/api/auth/cadastro",
            {
                "nome": "Pessoa de carga 1",
                "email": "carga-1@teste.local",
                "senha": senha,
                "dataNascimento": "1995-01-01",
            },
        )["usuarioId"]
    finally:
        parar(api)
    pessoas = [id_inicial] + [str(uuid.uuid4()) for _ in range(49)]
    valores = ",".join(f"({i},'{id}'::uuid)" for i, id in enumerate(pessoas, 1))
    s = f"""
    CREATE TABLE carga_pessoa(numero integer PRIMARY KEY, usuario_id uuid NOT NULL);
    INSERT INTO carga_pessoa VALUES {valores};
    INSERT INTO usuario(id,nome,email,data_nascimento,saldo_pontos,criado_em,atualizado_em,senha_hash,fuso_horario,planejamento_versionado_desde,protecao_ativada_em)
      SELECT p.usuario_id,'Pessoa de carga '||p.numero,'carga-'||p.numero||'@teste.local','1995-01-01',50000,now()-interval '181 days',now()-interval '181 days',u.senha_hash,'UTC',now()-interval '181 days',now()
      FROM carga_pessoa p CROSS JOIN usuario u WHERE u.id='{id_inicial}' AND p.numero>1;
    UPDATE usuario SET criado_em=now()-interval '181 days',planejamento_versionado_desde=now()-interval '181 days',fuso_horario='UTC';
    INSERT INTO epico(id,usuario_id,titulo,area_da_vida,pontuacao,dificuldade,prazo_inicio,prazo_fim,estado,criado_em,atualizado_em)
      SELECT p.numero*1000+n,p.usuario_id,'Objetivo de carga '||n,'EstudosEAprendizado',100,'Media',current_date-180,current_date+90,'EmAndamento',now()-interval '180 days',now() FROM carga_pessoa p CROSS JOIN generate_series(1,8) n;
    INSERT INTO campanha(id,epico_id,titulo,area_da_vida,pontuacao,dificuldade,prazo_inicio,prazo_fim,valor_mensurado,unidade,valor_atual,estado,criado_em,atualizado_em)
      SELECT p.numero*1000+n,p.numero*1000+((n-1)%8)+1,'Campanha de carga '||n,'EstudosEAprendizado',100,'Media',current_date-180,current_date+90,20,'modulos',12,'EmAndamento',now()-interval '180 days',now() FROM carga_pessoa p CROSS JOIN generate_series(1,11) n;
    INSERT INTO missao(id,usuario_id,campanha_id,titulo,pontuacao,data_limite,horario,status,criado_em,atualizado_em,dificuldade)
      SELECT p.numero*100000+n,p.usuario_id,CASE WHEN n<=24 THEN p.numero*1000+((n-1)%11)+1 END,'Missao de carga '||n,30,current_date-((n*5)%179),(current_date-180)::timestamptz+interval '12 hours','Ativa',now()-interval '180 days',now(),'Facil' FROM carga_pessoa p CROSS JOIN generate_series(1,29) n;
    INSERT INTO recorrencia(missao_id,tipo,data_inicio,regra,criado_em,atualizado_em)
      SELECT p.numero*100000+n,'Diaria',current_date-180,'{{}}'::jsonb,now()-interval '180 days',now() FROM carga_pessoa p CROSS JOIN generate_series(1,3) n;
    INSERT INTO ocorrencia(missao_id,data_prevista,status,realizada_em,concluida_em,criado_em,atualizado_em,fuso_horario_realizacao)
      SELECT m.id,current_date-d,CASE WHEN d%5<3 THEN 'Concluida' WHEN d%5=3 THEN 'ConcluidaComAtraso' ELSE 'Atrasada' END,
      CASE WHEN d%5<4 THEN (current_date-d)::timestamptz+interval '12 hours'+CASE WHEN d%5=3 THEN interval '1 day' ELSE interval '0 days' END END,
      CASE WHEN d%5<4 THEN (current_date-d)::timestamptz+interval '12 hours'+CASE WHEN d%5=3 THEN interval '1 day' ELSE interval '0 days' END END,
      now()-interval '180 days',now(),CASE WHEN d%5<4 THEN 'UTC' END FROM missao m JOIN recorrencia r ON r.missao_id=m.id CROSS JOIN generate_series(1,180) d;
    INSERT INTO ocorrencia(missao_id,data_prevista,status,criado_em,atualizado_em)
      SELECT m.id,m.data_limite,'Atrasada',now()-interval '180 days',now() FROM missao m WHERE NOT EXISTS(SELECT 1 FROM recorrencia r WHERE r.missao_id=m.id);
    INSERT INTO registro_planejamento_ocorrencia(ocorrencia_id,data_prevista,ativa,registrado_em)
      SELECT id,data_prevista,true,now()-interval '180 days' FROM ocorrencia;
    INSERT INTO diario(usuario_id,data_registro,texto,criado_em,atualizado_em,tipo)
      SELECT p.usuario_id,current_date-n*3,'Reflexao de carga '||n,now()-n*interval '3 days',now()-n*interval '3 days','Reflexao' FROM carga_pessoa p CROSS JOIN generate_series(1,54) n;
    INSERT INTO item(id,usuario_id,nome,valor,controla_app,criado_em,atualizado_em,estado)
      SELECT p.numero*1000+n,p.usuario_id,'Recompensa de carga '||n,35,'Nao',now()-interval '180 days',now(),'Disponivel' FROM carga_pessoa p CROSS JOIN generate_series(1,18) n;
    INSERT INTO medicao_campanha(campanha_id,valor_anterior,valor_atual,valor_mensurado,unidade,registrada_em,fuso_horario,operacao_id)
      SELECT c.id,n*2-2,n*2,20,'modulos',now()-(7*(7-n))*interval '1 day','UTC',md5(c.id||'-'||n)::uuid FROM campanha c CROSS JOIN generate_series(1,6) n;
    INSERT INTO movimentacao_pontos(usuario_id,tipo,quantidade,criado_em,saldo_resultante,titulo_origem)
      SELECT usuario_id,'Bonus',50000,now()-interval '181 days',50000,'Saldo inicial de carga' FROM carga_pessoa;
    INSERT INTO movimentacao_pontos(usuario_id,ocorrencia_id,tipo,quantidade,criado_em,titulo_origem)
      SELECT m.usuario_id,o.id,'GanhoMissao',30,o.realizada_em,'Missao de carga' FROM ocorrencia o JOIN missao m ON m.id=o.missao_id WHERE o.realizada_em IS NOT NULL;
    UPDATE usuario u SET saldo_pontos=(SELECT sum(quantidade) FROM movimentacao_pontos m WHERE m.usuario_id=u.id);
    DO $$ DECLARE t text; s text; v bigint; BEGIN FOREACH t IN ARRAY ARRAY['epico','campanha','missao','item'] LOOP s:=pg_get_serial_sequence(t,'id'); EXECUTE format('SELECT max(id) FROM %I',t) INTO v; IF s IS NOT NULL AND v IS NOT NULL THEN PERFORM setval(s,v); END IF; END LOOP; END $$;
    ANALYZE;
    """
    sql(BASE, s)
    with (PASTA / "pessoas.csv").open("w") as f:
        w = csv.writer(f)
        w.writerow(["usuario", "email", "senha", "item", "outro"])
        for i, id in enumerate(pessoas, 1):
            w.writerow(
                [id, f"carga-{i}@teste.local", senha, i * 1000 + 1, pessoas[i % 50]]
            )
    (PASTA / "pessoas.csv").chmod(0o600)
    (PASTA / "ambiente.json").write_text(
        json.dumps({"base": BASE, "vhost": VHOST, "porta": 5139, "usuarios": 50})
    )
    print(
        "Ambiente sintético criado: 50 usuários; banco de apresentação intacto.",
        flush=True,
    )


def limpar():
    import signal

    dados = json.loads((PASTA / "ambiente.json").read_text())
    if dados["base"] != BASE or dados["vhost"] != VHOST:
        raise RuntimeError("Manifesto não corresponde ao ambiente de carga.")
    pid = PASTA / "api-carga.pid"
    if pid.exists():
        processo = int(pid.read_text())
        argumentos = Path(f"/proc/{processo}/cmdline")
        if argumentos.exists() and str(PASTA).encode() in argumentos.read_bytes():
            os.kill(processo, signal.SIGTERM)
            time.sleep(2)
    for sufixo in ["antes", "depois", "smoke", "plano", "equivalencia", "base"]:
        banco = "icarus_carga_mvp26_" + sufixo
        sql("postgres", f'DROP DATABASE IF EXISTS "{banco}" WITH (FORCE);')
    executar(
        ["docker", "exec", "icarus-rabbitmq-1", "rabbitmqctl", "delete_vhost", VHOST]
    )
    (PASTA / "pessoas.csv").unlink(missing_ok=True)
    (PASTA / "ambiente.json").unlink()
    print("Bancos e vhost de carga removidos; resultados preservados.")


if __name__ == "__main__":
    import argparse

    argumentos = argparse.ArgumentParser(
        description="Prepara contas sintéticas em banco exclusivo para JMeter."
    )
    argumentos.add_argument("--limpar", action="store_true")
    argumentos.add_argument("--verificar", action="store_true")
    opcoes = argumentos.parse_args()
    if opcoes.verificar:
        print("Configuração local disponível; alvo de carga exclusivo na porta 5139.")
    elif opcoes.limpar:
        limpar()
    else:
        preparar()
