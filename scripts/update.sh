#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

[[ $EUID -ne 0 ]] && log_error "Запусти с sudo или от root"

set -a
source "${PROJECT_DIR}/.env"
set +a

SERVICE_USER="${SERVICE_USER:-$(logname 2>/dev/null || echo $SUDO_USER)}"

# ============================================================
log_info "Обновление MediaFlow..."
echo -e "${BLUE}$(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo ""

# Git pull
log_info "Получаем обновления..."
su - "${SERVICE_USER}" -c "cd ${PROJECT_DIR} && git pull origin main"
log_success "Код обновлён"

# Зависимости
log_info "Обновляем зависимости..."
su - "${SERVICE_USER}" -c "cd ${PROJECT_DIR} && .venv/bin/uv sync"
log_success "Зависимости обновлены"

# Миграции
log_info "Применяем миграции..."
su - "${SERVICE_USER}" -c "cd ${PROJECT_DIR} && .venv/bin/alembic upgrade head"
log_success "Миграции применены"

# Обновляем unit файлы если изменились
log_info "Обновляем systemd unit файлы..."
SYSTEMD_DIR="${PROJECT_DIR}/deploy/systemd"
SYSTEMD_SYSTEM="/etc/systemd/system"

SERVICES=("telegram-bot-api" "mediaflow-web" "mediaflow-worker" "mediaflow-scheduler")
APP_WORKERS="${APP_WORKERS:-4}"

for SERVICE in "${SERVICES[@]}"; do
    SRC="${SYSTEMD_DIR}/${SERVICE}.service"
    DST="${SYSTEMD_SYSTEM}/${SERVICE}.service"
    if [[ -f "${SRC}" ]]; then
        envsubst '${PROJECT_DIR} ${SERVICE_USER} ${DOMAIN} ${APP_WORKERS} ${TELEGRAM_API_ID} ${TELEGRAM_API_HASH}' \
            < "${SRC}" > "${DST}"
    fi
done

systemctl daemon-reload

# Restart сервисов (кроме telegram-bot-api — он долго стартует)
log_info "Перезапускаем сервисы..."

systemctl restart mediaflow-scheduler
log_success "mediaflow-scheduler перезапущен"

systemctl restart mediaflow-worker
log_success "mediaflow-worker перезапущен"

# Web — zero downtime через reload
systemctl reload-or-restart mediaflow-web
log_success "mediaflow-web перезапущен"

# ============================================================
echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Обновление завершено!${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

for SERVICE in "${SERVICES[@]}"; do
    STATUS=$(systemctl is-active "${SERVICE}" 2>/dev/null || echo "not-found")
    if [[ "${STATUS}" == "active" ]]; then
        echo -e "  ${GREEN}●${NC} ${SERVICE}: ${GREEN}${STATUS}${NC}"
    else
        echo -e "  \033[0;31m●${NC} ${SERVICE}: \033[0;31m${STATUS}${NC}"
    fi
done

echo ""
echo -e "  Логи: ${YELLOW}journalctl -u mediaflow-web -f${NC}"
echo ""
