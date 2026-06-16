#!/bin/bash

set -e

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    COMPOSE="docker compose"
fi

log "Building and starting master-podbora: React on 10111, Django on 10112..."
$COMPOSE up --build -d

log "Waiting for healthcheck..."
for attempt in $(seq 1 30); do
    if curl -fsS http://localhost:10112/health >/dev/null 2>&1; then
        log "master-podbora React is available: http://localhost:10111"
        log "master-podbora Django is available: http://localhost:10112"
        exit 0
    fi
    sleep 2
done

log "Healthcheck failed. Recent logs:"
$COMPOSE logs --tail=80
exit 1
