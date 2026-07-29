#!/bin/bash
# bwrap invocation template (Linux)
#
# This is a template; the actual invocation is constructed at runtime
# by backend/src/agentos/sandbox/bwrap.py with the workspace path
# substituted in.
#
# Usage: bwrap_defaults.sh <workspace> <command>

WORKSPACE="${1:?Usage: bwrap_defaults.sh <workspace> <command>}"
COMMAND="${2:?Usage: bwrap_defaults.sh <workspace> <command>}"

bwrap \
  --clearenv \
  --setenv PATH /usr/bin:/bin \
  --setenv HOME /workspace \
  --ro-bind /usr /usr \
  --ro-bind /bin /bin \
  --ro-bind /lib /lib \
  --ro-bind /lib64 /lib64 \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --bind "$WORKSPACE" /workspace \
  --chdir /workspace \
  --unshare-all \
  --die-with-parent \
  --new-session \
  /bin/sh -c "$COMMAND"
