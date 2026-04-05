#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()    { echo -e "\033[0;34m[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

[[ $EUID -ne 0 ]] && log_error "Запусти с sudo или от root"

SERVICES=(
    "mediaflow-scheduler"
    "mediaflow-worker"
    "mediaflow-web"
    "telegram-bot-api"
)

log_info "Останавливаем сервисы..."
for SERVICE in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "${SERVICE}" 2>/dev/null; then
        systemctl stop "${SERVICE}"
        log_success "Остановлен ${SERVICE}"
    fi

    if systemctl is-enabled --quiet "${SERVICE}" 2>/dev/null; then
        systemctl disable "${SERVICE}"
        log_success "Отключён ${SERVICE}"
    fi

    if [[ -f "/etc/systemd/system/${SERVICE}.service" ]]; then
        rm -f "/etc/systemd/system/${SERVICE}.service"
        log_success "Удалён ${SERVICE}.service"
    fi
done

systemctl daemon-reload
log_success "systemd перезагружен"

# Nginx
if [[ -f "/etc/nginx/sites-enabled/mediaflow.conf" ]]; then
    rm -f "/etc/nginx/sites-enabled/mediaflow.conf"
    rm -f "/etc/nginx/sites-available/mediaflow.conf"
    nginx -t && systemctl reload nginx
    log_success "Nginx конфиг удалён"
fi

echo ""
echo -e "${GREEN}MediaFlow удалён${NC}"
echo -e "${YELLOW}Данные в storage/ и .env сохранены${NC}"
echo ""
