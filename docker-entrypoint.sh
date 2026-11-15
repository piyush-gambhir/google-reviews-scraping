#!/bin/sh








set -e

case "${GRS_HEADED}" in
    1|true|TRUE|yes|YES)
        : "${DISPLAY:=:99}"
        export DISPLAY
        echo "entrypoint: starting Xvfb on ${DISPLAY}" >&2
        Xvfb "${DISPLAY}" -screen 0 1280x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
        xvfb_pid=$!



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
