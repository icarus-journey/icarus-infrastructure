#!/usr/bin/env bash

set -euo pipefail

RAMO_ORIGEM="development"
DIRETORIO_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIRETORIO_REPOSITORIO="$(cd -- "${DIRETORIO_SCRIPT}/.." && pwd)"
DIRETORIO_DESTINO="${ICARUS_DIRETORIO_DEPLOYMENT:-${DIRETORIO_REPOSITORIO}/.deployment/${RAMO_ORIGEM}}"

if [[ "$(git -C "${DIRETORIO_REPOSITORIO}" branch --show-current)" != "development" ]]; then
    echo "Execute este script a partir da branch development do icarus-infrastructure." >&2
    exit 1
fi

if ! command -v docker >/dev/null; then
    echo "Docker não encontrado no PATH." >&2
    exit 1
fi

if ! docker compose version >/dev/null; then
    echo "Docker Compose não está disponível." >&2
    exit 1
fi

atualizar_repositorio() {
    local nome="$1"
    local endereco="$2"
    local destino="${DIRETORIO_DESTINO}/${nome}"

    if [[ ! -d "${destino}/.git" ]]; then
        git clone --branch "${RAMO_ORIGEM}" --single-branch "${endereco}" "${destino}"
    else
        if ! git -C "${destino}" diff --quiet || ! git -C "${destino}" diff --cached --quiet; then
            echo "O checkout de deployment ${destino} possui alterações locais." >&2
            echo "Resolva-as antes de executar novamente." >&2
            exit 1
        fi

        git -C "${destino}" fetch origin "${RAMO_ORIGEM}"
        git -C "${destino}" checkout --detach "origin/${RAMO_ORIGEM}"
    fi

    printf '%s: %s\n' "${nome}" "$(git -C "${destino}" rev-parse --short HEAD)"
}

mkdir -p "${DIRETORIO_DESTINO}"

echo "Sincronizando os repositórios na branch ${RAMO_ORIGEM}:"
atualizar_repositorio "icarus-mobile" "https://github.com/icarus-journey/icarus-mobile.git"
atualizar_repositorio "icarus-platform" "https://github.com/icarus-journey/icarus-platform.git"
atualizar_repositorio "icarus-data" "https://github.com/icarus-journey/icarus-data.git"
atualizar_repositorio "icarus-infrastructure" "https://github.com/icarus-journey/icarus-infrastructure.git"

echo "Iniciando PostgreSQL, MinIO, RabbitMQ e o Expo Mobile:"
docker compose -f "${DIRETORIO_DESTINO}/icarus-platform/docker-compose.yml" up -d postgres
docker compose -f "${DIRETORIO_DESTINO}/icarus-infrastructure/compose.yaml" up -d --build minio rabbitmq mobile

echo "Deployment local inicializado em ${DIRETORIO_DESTINO}."
echo "Acompanhe a URL do Expo Go com:"
echo "docker compose -f \"${DIRETORIO_DESTINO}/icarus-infrastructure/compose.yaml\" logs -f mobile"
echo "A API ainda não é iniciada por este script."
