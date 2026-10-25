"""Inicia o MVP local com os checkouts e dados persistentes do projeto."""

import argparse
import ast
import base64
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


INFRA = Path(__file__).resolve().parents[1]
RAIZ = INFRA.parent
EXECUCAO = INFRA / ".execucao"
API = RAIZ / "icarus-platform"
MOBILE = RAIZ / "icarus-mobile"
IA = RAIZ / "icarus-ai"
COMPOSE = ["docker", "compose", "-f", str(INFRA / "compose.yaml")]
COMPOSE_BANCO = ["docker", "compose", "-f", str(API / "docker-compose.yml")]
PORTA_API = 5138
PORTA_EXPO = 8082


def informar(texto):
    print(texto, flush=True)


def executar(comando, *, ambiente=None, capturar=False, pasta=INFRA):
    return subprocess.run(
        comando, cwd=pasta, env=ambiente, check=True, text=True,
        stdout=subprocess.PIPE if capturar else None,
        stderr=subprocess.PIPE if capturar else None,
    ).stdout


def ler_env(caminho):
    valores = {}
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        nome, valor = linha.split("=", 1)
        valor = valor.strip()
        valores[nome.strip()] = ast.literal_eval(valor) if valor.startswith(("'", '"')) else valor
    return valores


def inicio_processo(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


def parar_processo(nome):
    arquivo = EXECUCAO / f"{nome}.pid.json"
    if not arquivo.exists():
        return
    estado = json.loads(arquivo.read_text())
    pid = estado["pid"]
    if inicio_processo(pid) == estado["inicio"]:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            arquivo.unlink(missing_ok=True)
            return
        for _ in range(50):
            if inicio_processo(pid) != estado["inicio"]:
                break
            time.sleep(0.1)
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    arquivo.unlink(missing_ok=True)


def iniciar_processo(nome, comando, pasta, ambiente=None):
    with (EXECUCAO / f"{nome}.log").open("a") as registro:
        processo = subprocess.Popen(
            comando, cwd=pasta, env=ambiente, stdout=registro,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    (EXECUCAO / f"{nome}.pid.json").write_text(json.dumps({
        "pid": processo.pid, "inicio": inicio_processo(processo.pid),
    }))
    return processo


def aguardar(verificar, descricao, segundos=90):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            if verificar():
                return
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    raise RuntimeError(f"{descricao} não ficou pronto. Consulte {EXECUCAO}.")


def http_pronto(url):
    with urlopen(url, timeout=3) as resposta:
        return resposta.status == 200


def dados_container(compose, servico):
    identificador = executar(compose + ["ps", "-q", servico], capturar=True).strip()
    if not identificador:
        raise RuntimeError(f"Contêiner {servico} não encontrado.")
    aguardar(lambda: json.loads(executar(
        ["docker", "inspect", identificador], capturar=True,
    ))[0]["State"].get("Health", {}).get("Status") == "healthy", servico)
    return json.loads(executar(["docker", "inspect", identificador], capturar=True))[0]


def ambiente_container(dados):
    return dict(valor.split("=", 1) for valor in dados["Config"]["Env"] if "=" in valor)


def porta_container(dados, porta):
    return dados["NetworkSettings"]["Ports"][f"{porta}/tcp"][0]["HostPort"]


def configurar_api(postgres, rabbit, minio):
    pg, mq = ambiente_container(postgres), ambiente_container(rabbit)
    armazenamento = ambiente_container(minio)
    usuario = pg.get("POSTGRES_USER", "postgres")
    banco = pg.get("POSTGRES_DB", "icarus")
    psql = ["docker", "exec", postgres["Id"], "psql", "-U", usuario, "-d", "postgres", "-tAc"]
    nome_sql = banco.replace("'", "''")
    if not executar(psql + [f"SELECT 1 FROM pg_database WHERE datname='{nome_sql}'"], capturar=True).strip():
        executar(["docker", "exec", postgres["Id"], "createdb", "-U", usuario, banco])
    arquivo = EXECUCAO / "ambiente-api.json"
    anterior = json.loads(arquivo.read_text()) if arquivo.exists() else {}
    ambiente = os.environ.copy()
    ambiente.update({
        "ASPNETCORE_ENVIRONMENT": "Development",
        "ASPNETCORE_URLS": f"http://0.0.0.0:{PORTA_API}",
        "ConnectionStrings__DefaultConnection": (
            f"Host=127.0.0.1;Port={porta_container(postgres, 5432)};Database={banco};"
            f"Username={usuario};Password={pg.get('POSTGRES_PASSWORD', '')}"
        ),
        "Jwt__ChaveSecreta": anterior.get("Jwt__ChaveSecreta") or secrets.token_urlsafe(48),
        "Jwt__Emissor": anterior.get("Jwt__Emissor") or "icarus-local",
        "Jwt__Audiencia": "icarus-mobile",
        "RabbitMq__Host": "127.0.0.1", "RabbitMq__Porta": porta_container(rabbit, 5672),
        "RabbitMq__Usuario": mq["RABBITMQ_DEFAULT_USER"],
        "RabbitMq__Senha": mq["RABBITMQ_DEFAULT_PASS"],
        "Minio__Endpoint": f"127.0.0.1:{porta_container(minio, 9000)}",
        "Minio__AccessKey": armazenamento["MINIO_ROOT_USER"],
        "Minio__SecretKey": armazenamento["MINIO_ROOT_PASSWORD"],
    })
    arquivo.write_text(json.dumps({k: v for k, v in ambiente.items() if k.startswith((
        "ASPNETCORE_", "ConnectionStrings__", "Jwt__", "RabbitMq__", "Minio__",
    ))}))
    arquivo.chmod(0o600)
    return ambiente


def preparar_api(ambiente):
    import xml.etree.ElementTree as xml

    versao = next(p.attrib["Version"] for p in xml.parse(API / "Directory.Packages.props").iter(
        "PackageVersion",
    ) if p.attrib["Include"] == "Microsoft.EntityFrameworkCore.Design")
    ferramentas = EXECUCAO / "ferramentas"
    executaveis = list(ferramentas.glob(f".store/dotnet-ef/{versao}/**/dotnet-ef.dll"))
    if not executaveis:
        acao = "update" if (ferramentas / "dotnet-ef").exists() else "install"
        executar(["dotnet", "tool", acao, "dotnet-ef", "--tool-path", str(ferramentas), "--version", versao], pasta=API)
        executaveis = list(ferramentas.glob(f".store/dotnet-ef/{versao}/**/dotnet-ef.dll"))
    executar(["dotnet", "build", str(API / "src/Icarus.Api"), "--nologo"], pasta=API)
    executar(["dotnet", str(executaveis[0]), "database", "update", "--project",
              str(API / "src/Icarus.Infrastructure"), "--startup-project",
              str(API / "src/Icarus.Api"), "--no-build"], ambiente=ambiente, pasta=API)


def preparar_mobile():
    resumo = hashlib.sha256(b"".join((MOBILE / nome).read_bytes() for nome in [
        "package.json", "package-lock.json",
    ])).hexdigest()
    marcador = EXECUCAO / "dependencias-mobile.sha256"
    if (MOBILE / "node_modules/.bin/expo").exists() and marcador.exists() and marcador.read_text() == resumo:
        return
    executar(["npm", "ci", "--no-audit", "--no-fund"], pasta=MOBILE)
    marcador.write_text(resumo)


def celular_usb():
    if not shutil.which("adb"):
        return None
    linhas = executar(["adb", "devices"], capturar=True).splitlines()[1:]
    celulares = [linha.split()[0] for linha in linhas if len(linha.split()) >= 2
                 and linha.split()[1] == "device" and not linha.startswith("emulator-")]
    return celulares[0] if len(celulares) == 1 else None


def ip_local():
    if os.environ.get("ICARUS_IP_LOCAL"):
        return os.environ["ICARUS_IP_LOCAL"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
        conexao.connect(("8.8.8.8", 80))
        return conexao.getsockname()[0]


def gerar_qr(endereco):
    bibliotecas = EXECUCAO / "bibliotecas"
    if not (bibliotecas / "qrcode").exists():
        executar([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                  "--target", str(bibliotecas), "qrcode[pil]==8.2"])
    sys.path.insert(0, str(bibliotecas))
    import qrcode

    arquivo = EXECUCAO / "qr-expo.png"
    qrcode.make(endereco).save(arquivo)
    configuracao = Path.home() / ".config/user-dirs.dirs"
    area = Path.home() / "Desktop"
    if configuracao.exists():
        correspondencia = re.search(r'^XDG_DESKTOP_DIR="(.*)"$', configuracao.read_text(), re.MULTILINE)
        if correspondencia:
            area = Path(os.path.expandvars(correspondencia.group(1)))
    if area.is_dir():
        arquivo = Path(shutil.copyfile(arquivo, area / "qr-code-icarus.png"))
    informar(f"QR do Expo: {arquivo}")


def espelhar(serial):
    executavel = shutil.which("scrcpy")
    if executavel:
        versao = executar([executavel, "--version"], capturar=True)
        correspondencia = re.search(r"scrcpy (\d+)", versao)
        if not correspondencia or int(correspondencia.group(1)) < 5:
            executavel = None
    if not executavel:
        if platform.machine() != "x86_64":
            informar("Para espelhar, instale um scrcpy atual para esta arquitetura.")
            return
        pasta = EXECUCAO / "scrcpy"
        executavel = pasta / "scrcpy-linux-x86_64-v5.0.1/scrcpy"
        if not executavel.exists():
            informar("Baixando scrcpy 5.0.1 para compatibilidade com Android 16.")
            with urlopen("https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/"
                         "scrcpy-linux-x86_64-v5.0.1.tar.gz", timeout=60) as resposta:
                conteudo = resposta.read()
            if hashlib.sha256(conteudo).hexdigest() != "9f969d30cc574816077edecda65719c1c70b0aee1df1ba5fa00779ac07b8fd6e":
                raise RuntimeError("SHA-256 divergente no pacote do scrcpy.")
            import io

            pasta.mkdir(exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(conteudo)) as pacote:
                for membro in pacote.getmembers():
                    if not (pasta / membro.name).resolve().is_relative_to(pasta.resolve()):
                        raise RuntimeError("Caminho inválido no pacote do scrcpy.")
                pacote.extractall(pasta)
    parar_processo("espelhamento")
    processo = iniciar_processo("espelhamento", [str(executavel), "--serial", serial,
        "--window-title", "Icarus — tela do celular", "--max-size", "1280", "--no-audio"], INFRA)
    time.sleep(1)
    informar("Espelhamento iniciado." if processo.poll() is None else
             "Espelhamento indisponível; consulte .execucao/espelhamento.log.")


def iniciar():
    for comando in ["docker", "dotnet", "npm", "git"]:
        if not shutil.which(comando):
            raise RuntimeError(f"Instale {comando} antes de iniciar o projeto.")
    for repositorio in [API, MOBILE, IA]:
        if not (repositorio / ".git").exists():
            raise RuntimeError(f"Checkout necessário: {repositorio}.")
        ramo = executar(["git", "branch", "--show-current"], pasta=repositorio, capturar=True).strip()
        informar(f"{repositorio.name}: {ramo}")
    if not (IA / ".env").exists():
        shutil.copyfile(IA / ".env.example", IA / ".env")
        (IA / ".env").chmod(0o600)
        raise RuntimeError("Preencha icarus-ai/.env com o provedor/modelo e execute novamente.")
    configuracao_ia = ler_env(IA / ".env")
    if configuracao_ia.get("ICARUS_PROVIDER") == "openai" and not configuracao_ia.get("ICARUS_LLM_API_KEY"):
        raise RuntimeError("Preencha ICARUS_LLM_API_KEY no icarus-ai/.env.")
    for nome in ["expo", "api"]:
        parar_processo(nome)
    for porta in [PORTA_API, PORTA_EXPO]:
        with socket.socket() as conexao:
            if conexao.connect_ex(("127.0.0.1", porta)) == 0:
                raise RuntimeError(f"Porta {porta} ocupada por outro processo; encerre-o antes de iniciar.")
    informar("Iniciando PostgreSQL, RabbitMQ e MinIO.")
    executar(COMPOSE_BANCO + ["up", "-d", "postgres"])
    executar(COMPOSE + ["up", "-d", "rabbitmq", "minio"])
    postgres = dados_container(COMPOSE_BANCO, "postgres")
    rabbit = dados_container(COMPOSE, "rabbitmq")
    identificador_minio = executar(COMPOSE + ["ps", "-q", "minio"], capturar=True).strip()
    minio = json.loads(executar(["docker", "inspect", identificador_minio], capturar=True))[0]
    aguardar(lambda: http_pronto(
        f"http://127.0.0.1:{porta_container(minio, 9000)}/minio/health/live"), "MinIO")
    ambiente = configurar_api(postgres, rabbit, minio)
    informar(f"Compilando a API e aplicando migrations no banco {ambiente_container(postgres).get('POSTGRES_DB', 'icarus')}.")
    preparar_api(ambiente)
    iniciar_processo("api", ["dotnet", "run", "--project", str(API / "src/Icarus.Api"),
                     "--no-build", "--no-launch-profile"], API, ambiente)
    aguardar(lambda: http_pronto(f"http://127.0.0.1:{PORTA_API}/health"), "API")
    mq = ambiente_container(rabbit)
    ambiente_worker = os.environ.copy()
    ambiente_worker["ICARUS_RABBITMQ_URL"] = (
        f"amqp://{quote(mq['RABBITMQ_DEFAULT_USER'], safe='')}:"
        f"{quote(mq['RABBITMQ_DEFAULT_PASS'], safe='')}@127.0.0.1:{porta_container(rabbit, 5672)}/"
    )
    informar("Iniciando o worker de IA com Python 3.13.")
    executar(COMPOSE + ["--profile", "mvp", "up", "-d", "--build", "worker"], ambiente=ambiente_worker)
    autorizacao = base64.b64encode(f"{mq['RABBITMQ_DEFAULT_USER']}:{mq['RABBITMQ_DEFAULT_PASS']}".encode()).decode()

    def worker_pronto():
        for fila in ["icarus.onboarding", "icarus.relatorio.semanal.v1"]:
            pedido = Request(f"http://127.0.0.1:{porta_container(rabbit, 15672)}/api/queues/%2F/{fila}",
                             headers={"Authorization": "Basic " + autorizacao})
            with urlopen(pedido, timeout=3) as resposta:
                if json.load(resposta).get("consumers", 0) == 0:
                    return False
        return True

    aguardar(worker_pronto, "Worker de IA")
    informar("Preparando o Expo Go.")
    preparar_mobile()
    serial = celular_usb()
    endereco = "127.0.0.1" if serial else ip_local()
    ambiente_mobile = os.environ.copy()
    ambiente_mobile["EXPO_PUBLIC_API_URL"] = f"http://{endereco}:{PORTA_API}"
    iniciar_processo("expo", [str(MOBILE / "node_modules/.bin/expo"), "start", "--go",
                     "--localhost" if serial else "--lan", "--port", str(PORTA_EXPO)], MOBILE, ambiente_mobile)
    aguardar(lambda: http_pronto(f"http://127.0.0.1:{PORTA_EXPO}/status"), "Expo")
    url_expo = f"exp://{endereco}:{PORTA_EXPO}"
    gerar_qr(url_expo)
    if serial:
        for porta in [PORTA_API, PORTA_EXPO]:
            executar(["adb", "-s", serial, "reverse", f"tcp:{porta}", f"tcp:{porta}"])
        executar(["adb", "-s", serial, "shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
                  "-d", url_expo, "-p", "host.exp.exponent"])
        try:
            espelhar(serial)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as erro:
            informar(f"App iniciado; espelhamento opcional indisponível: {erro}")
    else:
        informar("Abra o QR no Expo Go, na mesma rede Wi-Fi. Para USB, autorize a depuração e execute novamente.")
    informar(f"MVP local iniciado: {url_expo} | API: http://127.0.0.1:{PORTA_API}/swagger")
    informar(f"Logs: {EXECUCAO}; worker: docker compose logs -f worker")


def principal():
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument("--parar", action="store_true", help="Encerra API, Expo, worker e espelhamento do MVP local.")
    opcoes = argumentos.parse_args()
    if sys.platform != "linux":
        raise RuntimeError("Este iniciador foi preparado para Linux.")
    os.umask(0o077)
    EXECUCAO.mkdir(mode=0o700, exist_ok=True)
    if opcoes.parar:
        for nome in ["espelhamento", "expo", "api"]:
            parar_processo(nome)
        executar(COMPOSE + ["--profile", "mvp", "stop", "worker"])
        informar("MVP local encerrado. PostgreSQL, RabbitMQ, MinIO e seus dados continuam disponíveis.")
    else:
        iniciar()


if __name__ == "__main__":
    try:
        principal()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as erro:
        informar(f"Não foi possível iniciar o projeto: {erro}")
        sys.exit(1)
