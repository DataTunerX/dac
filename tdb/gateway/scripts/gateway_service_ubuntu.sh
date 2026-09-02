#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TDB_ROOT="$(cd "$GATEWAY_DIR/.." && pwd)"

SERVICE_NAME="${TDB_GATEWAY_SERVICE_NAME:-tdb-gateway}"
SERVICE_USER="${TDB_GATEWAY_SERVICE_USER:-${SUDO_USER:-$USER}}"
INSTALL_DIR="${TDB_GATEWAY_INSTALL_DIR:-$GATEWAY_DIR}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

usage() {
  cat <<EOF
Usage:
  $0 install    [--user USER] [--name SERVICE_NAME] [--dir GATEWAY_DIR] [--build]
  $0 start      [--name SERVICE_NAME]
  $0 stop       [--name SERVICE_NAME]
  $0 restart    [--name SERVICE_NAME]
  $0 status     [--name SERVICE_NAME]
  $0 logs       [--name SERVICE_NAME]
  $0 uninstall  [--name SERVICE_NAME]

Examples:
  ./tdb/gateway/scripts/gateway_service_ubuntu.sh install --build
  ./tdb/gateway/scripts/gateway_service_ubuntu.sh start
  ./tdb/gateway/scripts/gateway_service_ubuntu.sh stop
  ./tdb/gateway/scripts/gateway_service_ubuntu.sh logs

Environment overrides:
  TDB_GATEWAY_SERVICE_NAME
  TDB_GATEWAY_SERVICE_USER
  TDB_GATEWAY_INSTALL_DIR
EOF
}

BUILD_BEFORE_INSTALL=0

parse_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --user)
        SERVICE_USER="${2:?missing value for --user}"
        shift 2
        ;;
      --name)
        SERVICE_NAME="${2:?missing value for --name}"
        UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
        shift 2
        ;;
      --dir)
        INSTALL_DIR="$(cd "${2:?missing value for --dir}" && pwd)"
        shift 2
        ;;
      --build)
        BUILD_BEFORE_INSTALL=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown option: $1" >&2
        usage
        exit 2
        ;;
    esac
  done
}

require_systemd() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl not found. This script is intended for Ubuntu/systemd hosts." >&2
    exit 1
  fi
}

require_root_command() {
  if ! command -v sudo >/dev/null 2>&1 && [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "sudo is required unless you run this script as root." >&2
    exit 1
  fi
}

run_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

service_home() {
  getent passwd "$SERVICE_USER" | cut -d: -f6
}

build_gateway() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm not found. Install Node.js 20+ and npm first." >&2
    exit 1
  fi
  echo "Building gateway in $INSTALL_DIR"
  (cd "$INSTALL_DIR" && npm run build)
}

install_service() {
  require_systemd
  require_root_command

  if [[ ! -f "$INSTALL_DIR/package.json" ]]; then
    echo "Gateway package.json not found under: $INSTALL_DIR" >&2
    exit 1
  fi

  if [[ "$BUILD_BEFORE_INSTALL" == "1" ]]; then
    build_gateway
  fi

  if [[ ! -f "$INSTALL_DIR/dist/src/index.js" ]]; then
    echo "Gateway build output not found: $INSTALL_DIR/dist/src/index.js" >&2
    echo "Run: cd $INSTALL_DIR && npm install && npm run build" >&2
    echo "Or install with: $0 install --build" >&2
    exit 1
  fi

  local env_file="$TDB_ROOT/.env"
  if [[ ! -f "$env_file" ]]; then
    echo "Warning: $env_file not found. The gateway will use config/default values."
  fi

  local home_dir
  home_dir="$(service_home)"
  if [[ -z "$home_dir" ]]; then
    echo "Could not determine home directory for service user: $SERVICE_USER" >&2
    exit 1
  fi

  local unit_tmp
  unit_tmp="$(mktemp)"
  cat > "$unit_tmp" <<EOF
[Unit]
Description=TDB Gateway Node App
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment=HOME=$home_dir
Environment=NODE_ENV=production
Environment=TDB_ENV_PATH=$TDB_ROOT/.env
Environment=PATH=$home_dir/.nvm/versions/node/current/bin:$home_dir/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/bin/env node dist/src/index.js
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

  run_root install -m 0644 "$unit_tmp" "$UNIT_PATH"
  rm -f "$unit_tmp"

  run_root systemctl daemon-reload
  run_root systemctl enable "$SERVICE_NAME"

  echo "Installed systemd service: $SERVICE_NAME"
  echo "Unit file: $UNIT_PATH"
  echo "Start with: $0 start --name $SERVICE_NAME"
}

start_service() {
  require_systemd
  run_root systemctl start "$SERVICE_NAME"
  run_root systemctl status "$SERVICE_NAME" --no-pager
}

stop_service() {
  require_systemd
  run_root systemctl stop "$SERVICE_NAME"
}

restart_service() {
  require_systemd
  run_root systemctl restart "$SERVICE_NAME"
  run_root systemctl status "$SERVICE_NAME" --no-pager
}

status_service() {
  require_systemd
  systemctl status "$SERVICE_NAME" --no-pager
}

logs_service() {
  require_systemd
  journalctl -u "$SERVICE_NAME" -f
}

uninstall_service() {
  require_systemd
  require_root_command
  run_root systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  run_root systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
  run_root rm -f "$UNIT_PATH"
  run_root systemctl daemon-reload
  echo "Uninstalled systemd service: $SERVICE_NAME"
}

main() {
  local command="${1:-}"
  if [[ -z "$command" || "$command" == "-h" || "$command" == "--help" ]]; then
    usage
    exit 0
  fi
  shift
  parse_flags "$@"

  case "$command" in
    install) install_service ;;
    start) start_service ;;
    stop) stop_service ;;
    restart) restart_service ;;
    status) status_service ;;
    logs) logs_service ;;
    uninstall) uninstall_service ;;
    *)
      echo "Unknown command: $command" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
