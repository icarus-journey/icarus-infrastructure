#!/usr/bin/env python3
"""Verifica a integração local com contas temporárias e provedor real.

Cria registros de teste somente nessas contas e remove-as ao terminar.
Não modifica o snapshot público nem o histórico das contas existentes.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def banco(sql):
    resultado = subprocess.run(
        ["docker", "exec", "-i", "icarus-postgres", "psql", "-U", "postgres",
         "-d", "icarus", "-At", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, check=True,
    )
    return resultado.stdout.strip()


def executar(api, destino):
    contas = []
    evidencia = {"executadoEm": dt.datetime.now(dt.timezone.utc).isoformat()}

    def requisitar(rota, corpo=None, token=None, esperado=200):
        cabecalhos = {"Content-Type": "application/json"}
        if token:
            cabecalhos["Authorization"] = f"Bearer {token}"
        entrada = urllib.request.Request(
            api + rota, data=json.dumps(corpo).encode() if corpo is not None else None,
            headers=cabecalhos,
        )
        try:
            with urllib.request.urlopen(entrada, timeout=30) as resposta:
                codigo, carga = resposta.status, resposta.read()
        except urllib.error.HTTPError as erro:
            codigo, carga = erro.code, erro.read()
        assert codigo in ([esperado] if isinstance(esperado, int) else esperado), f"HTTP inesperado: {codigo} em {rota.split('?')[0]}"
        return json.loads(carga) if carga else None

    def criar(idade):
        hoje = dt.date.today()
        nascimento = hoje.replace(year=hoje.year - idade)
        email = f"teste-analitico-{uuid.uuid4().hex}@example.com"
        senha = secrets.token_urlsafe(24) + "aA1!"
        conta = requisitar("/api/auth/cadastro", {
            "nome": "Conta temporária de verificação", "email": email,
            "senha": senha, "dataNascimento": nascimento.isoformat(),
        }, esperado=201)
        identificador = str(uuid.UUID(conta["usuarioId"]))
        contas.append(identificador)
        token = requisitar("/api/auth/login", {"email": email, "senha": senha})["accessToken"]
        # PUT tem corpo, mas não deve usar o POST implícito do auxiliar.
        entrada = urllib.request.Request(
            api + f"/api/usuarios/{identificador}/fuso", method="PUT",
            data=json.dumps({"fusoHorario": "America/Sao_Paulo"}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(entrada, timeout=30) as resposta:
            assert resposta.status == 200
        return identificador, token

    try:
        adulto, token = criar(25)
        adolescente, token_menor = criar(17)
        crianca, token_crianca = criar(14)
        rota = f"/api/usuarios/{adulto}"
        gold = requisitar(rota + "/referencias-publicas?areaDaVida=SONO_E_RECUPERACAO", token=token)
        assert gold["estado"] == "disponivel"
        fontes = sorted({r["dados"]["fonte"] for r in gold["referencias"]})
        assert {"ATUS", "VIGITEL"} == {f.upper() for f in fontes}, fontes
        assert len(gold["referencias"]) <= 4
        for referencia in gold["referencias"]:
            dados = referencia["dados"]
            assert dados["edicao"] == 2024 and dados["denominador"] and dados["populacao"]
            assert dados["limitacoes"] and referencia["origens"]
            assert all(o["urlFonte"].startswith("https://") and len(o["sha256"]) == 64 for o in referencia["origens"])
            assert "suporte" not in dados
        menor = requisitar(f"/api/usuarios/{adolescente}/referencias-publicas?areaDaVida=SONO_E_RECUPERACAO", token=token_menor)
        assert menor["referencias"] and all(r["dados"]["fonte"].upper() == "ATUS" for r in menor["referencias"])
        infantil = requisitar(f"/api/usuarios/{crianca}/referencias-publicas?areaDaVida=SONO_E_RECUPERACAO", token=token_crianca)
        assert not infantil["referencias"]
        requisitar(rota + "/referencias-publicas?areaDaVida=SONO_E_RECUPERACAO", token=token_menor, esperado=404)
        requisitar(rota + "/progresso", esperado=401)
        requisitar(rota + "/referencias-publicas?areaDaVida=invalida", token=token, esperado=400)
        sem_mapa = requisitar(rota + "/referencias-publicas?areaDaVida=FINANCAS", token=token)
        assert not sem_mapa["referencias"]
        progresso = requisitar(rota + "/progresso", token=token)
        assert progresso["indicadores"]["concluidas"] is None
        vazio = requisitar(rota + "/relatorios/semanais", {}, token)
        assert vazio["estado"] == "historico_insuficiente"
        periodo = progresso["periodo"]
        inicio = dt.date.fromisoformat(periodo["inicio"])
        # Massa explícita de teste, jamais retroalimentação de contas reais.
        for dia in (inicio, inicio + dt.timedelta(days=2)):
            banco(f"""WITH nova AS (
              INSERT INTO missao(usuario_id,titulo,pontuacao,horario,status,dificuldade,criado_em,atualizado_em)
              VALUES ('{adulto}','Registro isolado de teste',30,'{dia}T15:00:00Z','Ativa','Facil',now(),now()) RETURNING id
            ) INSERT INTO ocorrencia(missao_id,data_prevista,status,realizada_em,concluida_em,criado_em,atualizado_em)
              SELECT id,'{dia}','Concluida','{dia}T15:00:00Z','{dia}T15:00:00Z',now(),now() FROM nova;""")
        primeiro = requisitar(rota + "/relatorios/semanais", {}, token, [200, 202])
        assert primeiro["estado"] == "processando"
        limite = time.monotonic() + 310
        resultado = primeiro
        while resultado["estado"] == "processando" and time.monotonic() < limite:
            time.sleep(2)
            resultado = requisitar(rota + "/relatorios/semanais/atual", token=token)
        assert resultado["estado"] == "disponivel", f"Relatório terminou em {resultado['estado']}"
        relatorio = resultado["relatorio"]
        assert relatorio["texto"]["resumo"] and relatorio["indicadores"]["concluidas"] == 2
        assert relatorio["indicadores"]["previstas"] is None
        repetido = requisitar(rota + "/relatorios/semanais", {}, token)
        assert repetido["relatorio"]["id"] == relatorio["id"]
        assert banco(f"SELECT count(*) FROM relatorio WHERE usuario_id='{adulto}';") == "1"
        evidencia.update({
            "versaoGold": gold["versaoGold"], "fontesAdulto": fontes,
            "referenciasAdulto": len(gold["referencias"]),
            "menorSemVigitel": True, "criancaSemFonteIncompativel": True,
            "isolamentoHttp": True, "metadadosPreservados": True,
            "relatorioRealPersistido": True, "idempotencia": True,
            "geracao": relatorio["geracao"], "origemIndicadores": "massa isolada de teste",
        })
    finally:
        for conta in contas:
            banco(f"DELETE FROM usuario WHERE id='{conta}';")
        evidencia["contasTemporariasRemovidas"] = len(contas)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidencia, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument("--api", default="http://127.0.0.1:5138")
    argumentos.add_argument("--evidencia", type=Path, default=Path(__file__).resolve().parents[1] / ".execucao/evidencias/consumo-analitico.json")
    opcoes = argumentos.parse_args()
    executar(opcoes.api.rstrip("/"), opcoes.evidencia)
