FROM docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
LABEL org.opencontainers.image.title="kataAI fixed Python runner" \
      org.opencontainers.image.version="0.1.1"
# Numeric UID/GID require no passwd database modifications or build-time RUN.
# COPY applies chmod to created directories too: keep non-root traversal bits.
COPY --chown=0:0 --chmod=0555 __init__.py contract.py validation.py staging.py report.py scratch.py supervisor.py /opt/kataai/runnerlib/
COPY --chown=0:0 --chmod=0555 entrypoint.py /opt/kataai/runner.py
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["python3", "-I", "-B", "/opt/kataai/runner.py"]
