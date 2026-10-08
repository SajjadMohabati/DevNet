#!/bin/sh
# DevNet — privileged setup. Run once:  sudo ./install.sh
# (DevNet runs this for you from “Enable Passwordless Mode”.)
#
#  • /usr/local/libexec/devnet-dns  root-owned DNS helper (live DNS override, even while a VPN sets its own)
#  • /etc/sudoers.d/devnet          lets you change routes and DNS without a password prompt;
#                                   only route add/delete, DNS settings and cache flush — nothing else.
#
# Uninstall:  sudo ./install.sh --uninstall
#
# Created by Sajjad Mohabati — https://github.com/SajjadMohabati/DevNet
set -e

if [ -t 1 ]; then B=$(printf '\033[1m'); D=$(printf '\033[2m'); G=$(printf '\033[32m'); C=$(printf '\033[36m'); R=$(printf '\033[31m'); N=$(printf '\033[0m'); fi
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
fail() { printf '  %s✗ %s%s\n' "$R" "$1" "$N"; exit 1; }

printf '\n  %s%sDevNet%s %s— route around your VPN%s\n' "$B" "$C" "$N" "$D" "$N"
printf '  %sby Sajjad Mohabati · github.com/SajjadMohabati/DevNet%s\n\n' "$D" "$N"

[ "$(id -u)" = 0 ] || fail "Run with sudo: sudo $0"
cd "$(dirname "$0")"

if [ "$1" = "--uninstall" ]; then
  rm -f /etc/sudoers.d/devnet /usr/local/libexec/devnet-dns
  ok "Removed sudoers rule and DNS helper"
  printf '\n'
  exit 0
fi

USER_NAME=${1:-$SUDO_USER}
[ -n "$USER_NAME" ] && id "$USER_NAME" >/dev/null 2>&1 || fail "Unknown user. Usage: sudo $0 [username]"

install -d -m 755 -o root -g wheel /usr/local/libexec
install -m 755 -o root -g wheel helper/devnet-dns /usr/local/libexec/devnet-dns
ok "DNS helper     → /usr/local/libexec/devnet-dns"

TMP=$(mktemp)
sed "s/USERNAME/$USER_NAME/g" sudoers/devnet > "$TMP"
visudo -c -f "$TMP" >/dev/null || { rm -f "$TMP"; fail "sudoers validation failed — nothing changed"; }
install -m 440 -o root -g wheel "$TMP" /etc/sudoers.d/devnet
rm -f "$TMP"
ok "Sudoers rule   → /etc/sudoers.d/devnet ($USER_NAME)"

printf '\n  %sDone.%s Routes and DNS now switch instantly, no password needed.\n\n' "$B" "$N"
