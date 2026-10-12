#!/usr/bin/env bash
# One-off move of a docker compose project from the syrop VPS to kolberg.
# Run from a workstation that has ssh aliases `syrop` and `kolberg`.
#
#   ./edge/migrate-from-syrop.sh prepare  <project>   # no downtime
#   ./edge/migrate-from-syrop.sh cutover  <project>   # downtime starts here
#   (switch the domain's A record to 85.9.200.143)
#   ./edge/migrate-from-syrop.sh start    <project>   # up on kolberg + TLS check
#   ./edge/migrate-from-syrop.sh rollback <project>   # back to syrop
#
# prepare  copies the whole project directory (.git, .env, untracked files;
#          not node_modules/__pycache__) to the same path on kolberg, switches
#          the compose files from syrop's cert resolver `letsencrypt` to
#          kolberg's `mytlschallenge` (left uncommitted in the working tree)
#          and builds the images there.
# cutover  stops the project on syrop and streams every named volume to
#          kolberg. Volumes are created with compose labels before any
#          container exists, so images can't seed them; an existing volume on
#          kolberg aborts the run. File count and total bytes are compared.
# start    starts the project on kolberg. Run it after the DNS switch, so the
#          edge Traefik's TLS-ALPN challenge reaches kolberg on the first try.
#
# The network name `traefik-public` is the same on both hosts. syrop keeps
# its own unchanged copy, stopped containers and volumes for rollback.
set -euo pipefail

KOLBERG_IP=85.9.200.143
SYROP_IP=94.237.84.234
ALL="horeca-demo bubbleking about-muse-warehouse marketing_signage recipebook"

usage() { sed -n '2,9p' "$0" >&2; echo "projects: $ALL" >&2; exit 2; }
[[ $# -eq 2 ]] || usage
cmd=$1 project=$2

# dir | compose args | named volumes | domain
case $project in
  horeca-demo)          spec="barbaza|--env-file .env.demo -f docker/docker-compose.demo.yml|horeca-demo_db_data horeca-demo_media_data|barbaza.botiq.uz" ;;
  bubbleking)           spec="bubbleking|-f docker-compose.yml|bubbleking_pg_data bubbleking_uploads|bubbleking.kolberg.uz" ;;
  about-muse-warehouse) spec="about-muse-warehouse|-f docker-compose.yml -f docker-compose.prod.yml|about-muse-warehouse_pg_data|sklad.about-muse.uz" ;;
  marketing_signage)    spec="marketing_signage|-f docker-compose.yml|marketing_signage_postgres_data marketing_signage_media_files|signage.kolberg.uz" ;;
  recipebook)           spec="recipebook|-f docker-compose.prod.yml|recipebook_postgres_data recipebook_uploads|syrop-recipebook.botiq.uz" ;;
  *) usage ;;
esac
IFS='|' read -r dir compose_args volumes domain <<<"$spec"

syrop_compose()   { ssh syrop   "cd ~/$dir && sudo docker compose $compose_args $*"; }
kolberg_compose() { ssh kolberg "cd ~/$dir && docker compose $compose_args $*"; }
docker_on()       { if [[ $1 == syrop ]]; then echo "sudo docker"; else echo docker; fi; }

running_on() {
  ssh "$1" "$(docker_on "$1") ps -q --filter label=com.docker.compose.project=$project | wc -l"
}

# "<files> <bytes>" of a volume; equal on both hosts means a full copy.
volume_stats() {
  ssh "$1" "$(docker_on "$1") run --rm -i -v $2:/v:ro alpine sh -s" <<'EOF'
echo "$(find /v -type f | wc -l) $(find /v -type f -exec stat -c %s {} + | awk '{s+=$1} END{print s+0}')"
EOF
}

case $cmd in
  prepare)
    if ssh kolberg "test -e ~/$dir"; then
      echo "kolberg:~/$dir already exists, not overwriting" >&2; exit 1
    fi
    echo "== copy ~/$dir syrop -> kolberg"
    ssh syrop "cd ~ && sudo tar -cf - --exclude=node_modules --exclude=__pycache__ $dir | gzip -1" \
      | ssh kolberg "cd ~ && gzip -d | tar -xf - --no-same-owner"
    ssh kolberg "du -sh ~/$dir"
    echo "== certresolver letsencrypt -> mytlschallenge"
    files=$(awk '{for (i = 1; i < NF; i++) if ($i == "-f") print $(i + 1)}' <<<"$compose_args" | tr '\n' ' ')
    ssh kolberg "cd ~/$dir && sed -i -E 's/(certresolver[=:] *)letsencrypt\b/\1mytlschallenge/' $files"
    kolberg_compose config | grep -E 'certresolver|docker.network' | sort | uniq -c
    if kolberg_compose config | grep -q 'certresolver: letsencrypt'; then
      echo "letsencrypt resolver still referenced, stop" >&2; exit 1
    fi
    echo "== build on kolberg"
    kolberg_compose build
    ;;

  cutover)
    [[ $(running_on kolberg) -eq 0 ]] || { echo "$project already runs on kolberg" >&2; exit 1; }
    for vol in $volumes; do
      if ssh kolberg "docker volume inspect $vol >/dev/null 2>&1"; then
        echo "volume $vol already exists on kolberg, stop" >&2; exit 1
      fi
    done
    echo "== stop on syrop (downtime starts)"
    syrop_compose stop
    [[ $(running_on syrop) -eq 0 ]] || { echo "$project still running on syrop" >&2; exit 1; }
    for vol in $volumes; do
      echo "== copy volume $vol"
      ssh kolberg "docker volume create \
        --label com.docker.compose.project=$project \
        --label com.docker.compose.volume=${vol#"${project}"_} $vol >/dev/null"
      ssh syrop "sudo docker run --rm -v $vol:/v:ro alpine sh -c 'tar -C /v -cf - . | gzip -1'" \
        | ssh kolberg "docker run --rm -i -v $vol:/v alpine sh -c 'gzip -d | tar -C /v -xf -'"
      src=$(volume_stats syrop "$vol")
      dst=$(volume_stats kolberg "$vol")
      echo "   files bytes  syrop: $src  kolberg: $dst"
      [[ "$src" == "$dst" ]] || { echo "volume $vol differs, stop" >&2; exit 1; }
    done
    echo "== volumes copied. Switch the A record of $domain to $KOLBERG_IP, then: $0 start $project"
    ;;

  start)
    [[ $(running_on syrop) -eq 0 ]] || { echo "$project is running on syrop, stop it first" >&2; exit 1; }
    current=$(dig +short "$domain" @1.1.1.1 | tail -1)
    [[ "$current" == "$KOLBERG_IP" ]] \
      || echo "warning: $domain resolves to $current; TLS will fail until it points at kolberg" >&2
    kolberg_compose up -d --no-build
    echo "== waiting for a valid certificate on https://$domain"
    out="-"
    for _ in $(seq 1 24); do
      out=$(curl -sS -o /dev/null --max-time 10 --resolve "$domain:443:$KOLBERG_IP" \
        -w '%{http_code} %{ssl_verify_result}' "https://$domain/" 2>/dev/null) || out="ERR -"
      read -r code tls <<<"$out"
      if [[ "$tls" == "0" ]]; then echo "   $code tls-ok"; kolberg_compose ps; exit 0; fi
      sleep 5
    done
    echo "no valid certificate after 2 minutes (last: $out)." >&2
    echo "Check: ssh kolberg 'docker logs traefik --since 5m 2>&1 | grep -i acme'." >&2
    echo "If DNS changed after start: stop the web container, wait 15s, start it" >&2
    echo "(a plain restart is merged away by the provider throttle and issues nothing)." >&2
    exit 1
    ;;

  rollback)
    echo "== stop on kolberg (data written there since start is NOT copied back)"
    kolberg_compose stop
    echo "== start on syrop"
    syrop_compose start
    echo "== switch the A record of $domain back to $SYROP_IP"
    ;;

  *) usage ;;
esac
