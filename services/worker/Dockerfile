# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# SPECTRA worker image.
#
# The worker is the API image with a different entrypoint - same Python
# environment, same system dependencies, same non-root user.  Building it as a
# derivative keeps the two images byte-identical below the final layer, which
# halves both bundle size (shared layers in `docker save`) and the surface that
# has to be re-verified after a patch.
#
#   docker build -f services/api/Dockerfile -t spectra-api:1.0.0 .
#   docker build -f services/worker/Dockerfile \
#       --build-arg SPECTRA_API_IMAGE=spectra-api:1.0.0 \
#       -t spectra-worker:1.0.0 .
#
# `scripts/package-release.sh` and `scripts/package-patch.sh` always build the
# API image first and pass SPECTRA_API_IMAGE.  The developer compose stack
# instead uses `services/api/Dockerfile --target worker`, which produces the same
# image without requiring a particular build order.
# ---------------------------------------------------------------------------

ARG SPECTRA_API_IMAGE=spectra-api:dev

FROM ${SPECTRA_API_IMAGE} AS runtime

ENV SPECTRA_ROLE=worker

# Inherited from the API image: WORKDIR /app, USER spectra, /opt/venv on PATH.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD pgrep -f spectra_worker >/dev/null || exit 1

CMD ["python", "-m", "spectra_worker"]
