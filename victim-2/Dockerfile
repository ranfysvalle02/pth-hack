FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client nodejs npm && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn[standard] requests cryptography

WORKDIR /root
COPY fake-home/ /root/
COPY server.py /app/server.py

ENV HOME=/root

EXPOSE 8001
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--app-dir", "/app"]
