FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn[standard] requests cryptography

WORKDIR /root
COPY fake-home/ /root/
COPY server.py /app/server.py

ENV HOME=/root

EXPOSE 8002
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8002", "--app-dir", "/app"]
