FROM python:3.11-slim AS builder

WORKDIR /build
COPY malicious-package/ .
RUN pip install --no-cache-dir setuptools wheel \
    && python setup.py bdist_wheel -d /wheels

FROM pypiserver/pypiserver:latest
COPY --from=builder /wheels/ /data/packages/
CMD ["run", "-p", "8080", "/data/packages", "--disable-fallback"]
