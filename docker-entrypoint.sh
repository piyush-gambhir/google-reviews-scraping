#!/bin/sh
# Headed Chromium needs a display. Rather than ship a second image, wrap the
# CLI in a virtual framebuffer only when GRS_HEADED is set, so the same image
# covers both modes and a deployment can A/B them with one env var.
set -e

case "${GRS_HEADED}" in
    1|true|TRUE|yes|YES)
        exec xvfb-run -a --server-args="-screen 0 1280x900x24" grscraper "$@"
        ;;
esac

exec grscraper "$@"
