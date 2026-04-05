#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  MediaFlow — Install Script
#  Использование: ./deploy/scripts/install.sh
# ============================================================

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ============================================================
# Определяем пути
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEPLOY_DIR="${PROJECT_DIR}/deploy"
SYSTEMD_DIR="${DEPLOY_DIR}/systemd"
SYSTEMD_SYSTEM="/etc/systemd/system"

# ============================================================
# Проверки
# ============================================================
log_info "Проверяем систему..."

[[ $EUID -ne 0 ]] && log_error "Запусти с sudo или от root"
[[ ! -f "${PROJECT_DIR}/.env" ]] && log_error ".env файл не найден в ${PROJECT_DIR}"
command -v systemctl >/dev/null 2>&1 || log_error "systemd не найден"
command -v nginx >/dev/null 2>&1 || log_warn "nginx не установлен — пропускаем конфиг"

log_success "Система OK"

# ============================================================
# Читаем .env
# ============================================================
log_info "Читаем конфигурацию..."
set -a
source "${PROJECT_DIR}/.env"
set +a

# Дефолты если не задано в .env
SERVICE_USER="${SERVICE_USER:-$(logname 2>/dev/null || echo $SUDO_USER)}"
DOMAIN="${DOMAIN:-localhost}"
APP_WORKERS="${APP_WORKERS:-4}"

log_info "PROJECT_DIR  = ${PROJECT_DIR}"
log_info "SERVICE_USER = ${SERVICE_USER}"
log_info "DOMAIN       = ${DOMAIN}"

# ============================================================
# Создаём директории
# ============================================================
log_info "Создаём директории..."

mkdir -p "${PROJECT_DIR}/storage/logs"
mkdir -p "${PROJECT_DIR}/storage/temp"
mkdir -p "${PROJECT_DIR}/storage/telegram-bot-api"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PROJECT_DIR}/storage"

log_success "Директории созданы"

# ============================================================
# Устанавливаем Python зависимости
# ============================================================
log_info "Устанавливаем зависимости..."

if [[ ! -f "${PROJECT_DIR}/.venv/bin/python" ]]; then
    su - "${SERVICE_USER}" -c "cd ${PROJECT_DIR} && python -m venv .venv"
fi

su - "${SERVICE_USER}" -c "cd ${PROJECT_DIR} && .venv/bin/pip install uv -q"
su - "${SERVICE_USER}" -c "cd ${PROJECT_DIR} && .venv/bin/uv sync"

log_success "Зависимости установлены"

# ============================================================
# Миграции
# ============================================================
log_info "Запускаем миграции..."
su - "${SERVICE_USER}" -c "cd ${PROJECT_DIR} && .venv/bin/alembic upgrade head"
log_success "Миграции применены"

# ============================================================
# Копируем и настраиваем systemd unit файлы
# ============================================================
log_info "Устанавливаем systemd сервисы..."

SERVICES=(
    "telegram-bot-api"
    "mediaflow-web"
    "mediaflow-worker"
    "mediaflow-scheduler"
)

for SERVICE in "${SERVICES[@]}"; do
    SRC="${SYSTEMD_DIR}/${SERVICE}.service"
    DST="${SYSTEMD_SYSTEM}/${SERVICE}.service"

    if [[ ! -f "${SRC}" ]]; then
        log_warn "Файл ${SRC} не найден — пропускаем"
        continue
    fi

    # Подставляем переменные через envsubst
    envsubst '${PROJECT_DIR} ${SERVICE_USER} ${DOMAIN} ${APP_WORKERS} ${TELEGRAM_API_ID} ${TELEGRAM_API_HASH}' \
        < "${SRC}" > "${DST}"

    chmod 644 "${DST}"
    log_success "Установлен ${SERVICE}.service"
done

# ============================================================
# Nginx конфиг
# ============================================================
if command -v nginx >/dev/null 2>&1; then
    log_info "Настраиваем nginx..."
    NGINX_SRC="${DEPLOY_DIR}/nginx/mediaflow.conf"
    NGINX_DST="/etc/nginx/sites-available/mediaflow.conf"
    NGINX_ENABLED="/etc/nginx/sites-enabled/mediaflow.conf"

    envsubst '${PROJECT_DIR} ${DOMAIN}' < "${NGINX_SRC}" > "${NGINX_DST}"
    ln -sf "${NGINX_DST}" "${NGINX_ENABLED}"

    nginx -t && systemctl reload nginx
    log_success "Nginx настроен"
fi

# ============================================================
# Включаем и запускаем сервисы
# ============================================================
log_info "Перезагружаем systemd..."
systemctl daemon-reload

log_info "Запускаем сервисы в правильном порядке..."

# Telegram Bot API первым
if [[ -f "${SYSTEMD_SYSTEM}/telegram-bot-api.service" ]]; then
    systemctl enable telegram-bot-api
    systemctl start telegram-bot-api
    sleep 3
    log_success "telegram-bot-api запущен"
fi

# Веб сервер
systemctl enable mediaflow-web
systemctl start mediaflow-web
sleep 2
log_success "mediaflow-web запущен"

# Воркер
systemctl enable mediaflow-worker
systemctl start mediaflow-worker
sleep 1
log_success "mediaflow-worker запущен"

# Scheduler
systemctl enable mediaflow-scheduler
systemctl start mediaflow-scheduler
log_success "mediaflow-scheduler запущен"

# ============================================================
# Статус
# ============================================================
echo ""
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}  MediaFlow успешно установлен!${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo ""

for SERVICE in "${SERVICES[@]}"; do
    STATUS=$(systemctl is-active "${SERVICE}" 2>/dev/null || echo "not-found")
    if [[ "${STATUS}" == "active" ]]; then
        echo -e "  ${GREEN}●${NC} ${SERVICE}: ${GREEN}${STATUS}${NC}"
    else
        echo -e "  ${RED}●${NC} ${SERVICE}: ${RED}${STATUS}${NC}"
    fi
done

echo ""
echo -e "  Логи:    ${YELLOW}journalctl -u mediaflow-web -f${NC}"
echo -e "  Статус:  ${YELLOW}systemctl status mediaflow-web${NC}"
echo -e "  URL:     ${YELLOW}http://${DOMAIN}${NC}"
echo ""
