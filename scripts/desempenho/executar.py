import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

SCRIPTS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("ambiente", SCRIPTS / "preparar.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
PASTA = h.PASTA
a = argparse.ArgumentParser()
a.add_argument("etapa", choices=["antes", "depois", "smoke"])
a.add_argument("--duracao", type=int, default=675)
a.add_argument("--usuarios", type=int, default=50)
a.add_argument("--rampa", type=int, default=30)
a.add_argument("--intervalo", type=int, default=1000)
op = a.parse_args()
if not 1 <= op.usuarios <= 50 or min(op.duracao, op.rampa, op.intervalo) <= 0:
    raise ValueError("Use de 1 a 50 usuários e tempos positivos.")
if (PASTA / f"{op.etapa}.jtl").exists():
    raise RuntimeError("Resultado já existe; preserve-o antes de repetir a etapa.")
banco = "icarus_carga_mvp26_" + op.etapa
for pessoa in csv.DictReader((PASTA / "pessoas.csv").open()):
    if not pessoa["email"].startswith("carga-") or not pessoa["email"].endswith(
        "@teste.local"
    ):
        raise ValueError("Use somente pessoas sintéticas geradas pelo preparador.")
h.sql("postgres", f'CREATE DATABASE "{banco}" TEMPLATE "{h.BASE}";')
if op.etapa == "depois":
    shutil.copytree(
        h.RAIZ / "icarus-platform/src/Icarus.Api/bin/Release/net10.0",
        PASTA / "api-depois",
    )
if op.etapa == "depois":
    import xml.etree.ElementTree as xml

    versao = next(
        p.attrib["Version"]
        for p in xml.parse(h.RAIZ / "icarus-platform/Directory.Packages.props").iter(
            "PackageVersion"
        )
        if p.attrib["Include"] == "Microsoft.EntityFrameworkCore.Design"
    )
    ef = next(
        (h.RAIZ / "icarus-infrastructure/.execucao/ferramentas/.store/dotnet-ef").glob(
            f"{versao}/**/dotnet-ef.dll"
        )
    )
    with (PASTA / "migracao-carga.log").open("w") as log:
        subprocess.run(
            [
                "dotnet",
                str(ef),
                "database",
                "update",
                "--project",
                "src/Icarus.Infrastructure",
                "--startup-project",
                "src/Icarus.Api",
                "--configuration",
                "Release",
                "--no-build",
            ],
            cwd=h.RAIZ / "icarus-platform",
            env=h.ambiente_api(banco),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
etapa_api = "antes" if op.etapa == "smoke" else op.etapa
api = h.iniciar(banco, etapa_api)
(PASTA / "api-carga.pid").write_text(str(api.pid))
env = os.environ.copy()
env["HEAP"] = "-Xms128m -Xmx512m -XX:MaxMetaspaceSize=256m"
inicio = time.time()
try:
    cmd = [
        "jmeter",
        "-n",
        "-t",
        str(SCRIPTS / "carga.jmx"),
        "-l",
        str(PASTA / f"{op.etapa}.jtl"),
        "-j",
        str(PASTA / f"jmeter-{op.etapa}.log"),
        f"-Jpessoas={PASTA / 'pessoas.csv'}",
        f"-Jduracao={op.duracao}",
        f"-Jusuarios={op.usuarios}",
        f"-Jrampa={op.rampa}",
        f"-Jintervalo={op.intervalo}",
        "-Jjmeter.save.saveservice.url=false",
        "-Jjmeter.save.saveservice.response_data=false",
        "-Jjmeter.save.saveservice.samplerData=false",
        "-Jjmeter.save.saveservice.requestHeaders=false",
        "-Jjmeter.save.saveservice.responseHeaders=false",
    ]
    with (PASTA / f"saida-{op.etapa}.log").open("w") as log:
        subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
finally:
    h.parar(api)
    (PASTA / f"tempo-{op.etapa}.json").write_text(
        json.dumps(
            {
                "inicio": inicio,
                "rampa_segundos": op.rampa,
                "fim": time.time(),
                "usuarios": op.usuarios,
                "duracao_configurada": op.duracao,
            }
        )
    )
print("Etapa concluída:", op.etapa, flush=True)
