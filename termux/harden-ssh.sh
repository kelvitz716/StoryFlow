#!/data/data/com.termux/files/usr/bin/sh
# StoryFlow Termux SSH Hardening Script
# Enforces key-only authentication and secure defaults for OpenSSH.
#
# Usage:
#   sh termux/harden-ssh.sh [--dry-run] [--listen <ipv4>]

set -e
umask 077

# Overridable variables for testing and configuration
SSHD_CONFIG="${SSHD_CONFIG:-${PREFIX:-/data/data/com.termux/files/usr}/etc/ssh/sshd_config}"
AUTH_KEYS="${AUTH_KEYS:-$HOME/.ssh/authorized_keys}"
SSHD_BIN="${SSHD_BIN:-sshd}"
PIDFILE="${PIDFILE:-${PREFIX:-/data/data/com.termux/files/usr}/var/run/sshd.pid}"
RELOAD="${RELOAD:-1}"

DRY_RUN=0
LISTEN_IP=""

# Parse flags
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --listen)
      if [ $# -lt 2 ]; then
        echo "Error: --listen requires an IPv4 address" >&2
        exit 1
      fi
      LISTEN_IP="$2"
      shift 2
      ;;
    --listen=*)
      LISTEN_IP="${1#*=}"
      shift
      ;;
    *)
      echo "Error: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# Validate --listen IPv4 address if specified
if [ -n "$LISTEN_IP" ]; then
  if ! echo "$LISTEN_IP" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' >/dev/null 2>&1; then
    echo "Error: Invalid IPv4 address for --listen: $LISTEN_IP" >&2
    exit 1
  fi
fi

# Ensure SSH configuration file exists
if [ ! -f "$SSHD_CONFIG" ]; then
  echo "Error: SSH configuration file not found at $SSHD_CONFIG" >&2
  exit 1
fi

# 1. Lockout protection: refuse to disable passwords unless $AUTH_KEYS has at least one valid key
if [ ! -f "$AUTH_KEYS" ] || ! grep -v '^[[:space:]]*#' "$AUTH_KEYS" 2>/dev/null | grep -E '(^|[[:space:]])(ssh-|ecdsa-|sk-)' >/dev/null 2>&1; then
  echo "Error: Lockout protection: No authorized SSH keys found in $AUTH_KEYS." >&2
  echo "To install your laptop's public key to your phone, run from your laptop:" >&2
  echo "  ssh-copy-id -p 8022 <user>@<phone-ip>" >&2
  exit 1
fi

CURRENT_USER="$(id -un)"

# Prepare target settings list
SETTINGS_TMP=$(mktemp)
cat <<EOF > "$SETTINGS_TMP"
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
PermitEmptyPasswords no
MaxAuthTries 3
LoginGraceTime 20
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 60
ClientAliveCountMax 3
AllowUsers $CURRENT_USER
EOF

if [ -n "$LISTEN_IP" ]; then
  echo "ListenAddress $LISTEN_IP" >> "$SETTINGS_TMP"
fi

# Generate updated config using POSIX awk:
# Replaces existing occurrences of directives or inserts them before the first Match line.
NEW_CONFIG_TMP=$(mktemp)
awk '
NR == FNR {
    key = $1
    order[++num_keys] = key
    target[key] = $0
    next
}
NF == 0 || $1 ~ /^#/ {
    print $0
    next
}
in_match {
    print $0
    next
}
{
    first = $1
    sub(/=.*$/, "", first)
    if (tolower(first) == "match") {
        if (!first_match_seen) {
            first_match_seen = 1
            for (i = 1; i <= num_keys; i++) {
                k = order[i]
                if (!seen_global[k]) {
                    print target[k]
                    seen_global[k] = 1
                }
            }
        }
        in_match = 1
        print $0
        next
    }
    matched = ""
    for (i = 1; i <= num_keys; i++) {
        k = order[i]
        if (tolower(first) == tolower(k)) {
            matched = k
            break
        }
    }
    if (matched != "") {
        if (!seen_global[matched]) {
            print target[matched]
            seen_global[matched] = 1
        }
        next
    }
    print $0
}
END {
    if (!first_match_seen) {
        for (i = 1; i <= num_keys; i++) {
            k = order[i]
            if (!seen_global[k]) {
                print target[k]
            }
        }
    }
}
' "$SETTINGS_TMP" "$SSHD_CONFIG" > "$NEW_CONFIG_TMP"

# Handle --dry-run
if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== SSH Hardening Dry Run ==="
  echo "Proposed changes for $SSHD_CONFIG:"
  diff -u "$SSHD_CONFIG" "$NEW_CONFIG_TMP" || true
  rm -f "$SETTINGS_TMP" "$NEW_CONFIG_TMP"
  exit 0
fi

# 2. Back up the config to ${SSHD_CONFIG}.bak.<timestamp> with mode 600
TIMESTAMP=$(date +%s)
BACKUP="${SSHD_CONFIG}.bak.${TIMESTAMP}"
if [ -e "$BACKUP" ]; then
  COUNT=1
  while [ -e "${BACKUP}.${COUNT}" ]; do
    COUNT=$((COUNT + 1))
  done
  BACKUP="${BACKUP}.${COUNT}"
fi
cp "$SSHD_CONFIG" "$BACKUP"
chmod 600 "$BACKUP"
echo "Backed up $SSHD_CONFIG to $BACKUP"

# Write new config
cp "$NEW_CONFIG_TMP" "$SSHD_CONFIG"
chmod 600 "$SSHD_CONFIG"
rm -f "$SETTINGS_TMP" "$NEW_CONFIG_TMP"

# 4. Validate with $SSHD_BIN -t -f "$SSHD_CONFIG"
echo "Validating SSH configuration with $SSHD_BIN -t -f \"$SSHD_CONFIG\"..."
if ! "$SSHD_BIN" -t -f "$SSHD_CONFIG"; then
  echo "Error: Validation failed. Restoring backup from $BACKUP..." >&2
  cp "$BACKUP" "$SSHD_CONFIG"
  exit 1
fi

# 5. Reload without dropping existing sessions
if [ "$RELOAD" = "1" ]; then
  if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null || true)"
    kill -HUP "$PID" 2>/dev/null || true
    sleep 2
    if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
      echo "sshd is not running. Start it from the Termux app with: sshd" >&2
      exit 1
    fi
    echo "sshd reloaded successfully."
  else
    echo "Warning: PID file $PIDFILE not found. Start sshd manually." >&2
  fi
else
  echo "Skipping sshd reload (RELOAD=$RELOAD)."
fi

# 6. Print effective settings and reminder
echo ""
echo "=== Effective SSH Hardening Settings ==="
echo "  PasswordAuthentication no"
echo "  KbdInteractiveAuthentication no"
echo "  PubkeyAuthentication yes"
echo "  PermitRootLogin no"
echo "  PermitEmptyPasswords no"
echo "  MaxAuthTries 3"
echo "  LoginGraceTime 20"
echo "  X11Forwarding no"
echo "  AllowAgentForwarding no"
echo "  ClientAliveInterval 60"
echo "  ClientAliveCountMax 3"
echo "  AllowUsers $CURRENT_USER"
if [ -n "$LISTEN_IP" ]; then
  echo "  ListenAddress $LISTEN_IP"
fi
echo ""
echo "IMPORTANT: Open a second SSH session to test before closing the first."
