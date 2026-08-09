#!/bin/sh
# Headed Chromium needs a display. Rather than ship a second image, start a
# virtual framebuffer only when GRS_HEADED is set, so the same image covers
# both modes and a deployment can A/B them with one env var.
#
# Xvfb is started directly rather than via `xvfb-run`: that wrapper writes an
# X authority file under $HOME and hangs indefinitely when HOME is not
# writable, which is exactly what happened on Cloud Run — the container
# produced no output at all until it was killed.
set -e

case "${GRS_HEADED}" in
    1|true|TRUE|yes|YES)
        : "${DISPLAY:=:99}"
        export DISPLAY
        echo "entrypoint: starting Xvfb on ${DISPLAY}" >&2
        Xvfb "${DISPLAY}" -screen 0 1280x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
        xvfb_pid=$!

        # Wait for the display socket rather than sleeping blindly, and fail
        # loudly if it never appears — a silent hang is the worst outcome.
        i=0
        while [ "$i" -lt 30 ]; do
            if [ -e "/tmp/.X11-unix/X${DISPLAY#:}" ]; then
                break
            fi
            if ! kill -0 "$xvfb_pid" 2>/dev/null; then
                echo "entrypoint: Xvfb died on startup:" >&2
                cat /tmp/xvfb.log >&2 || true
                exit 1
            fi
            i=$((i + 1))
            sleep 0.5
        done
        if [ ! -e "/tmp/.X11-unix/X${DISPLAY#:}" ]; then
            echo "entrypoint: Xvfb did not come up within 15s" >&2
            cat /tmp/xvfb.log >&2 || true
            exit 1
        fi
        echo "entrypoint: Xvfb ready" >&2
        ;;
esac

exec grscraper "$@"
