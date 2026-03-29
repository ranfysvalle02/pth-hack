FROM node:20-slim AS tailwind
WORKDIR /build
RUN npm install tailwindcss@3
COPY tailwind.config.js .
COPY static/ static/
RUN npx tailwindcss -i static/css/input.css -o static/css/tailwind.css --minify

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ static/
COPY --from=tailwind /build/static/css/tailwind.css static/css/tailwind.css

RUN mkdir -p static/fonts && \
    curl -sL "https://fonts.gstatic.com/s/inter/v18/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1ZL7.woff2" -o static/fonts/inter-400.woff2 && \
    curl -sL "https://fonts.gstatic.com/s/inter/v18/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa2JL7.woff2" -o static/fonts/inter-500.woff2 && \
    curl -sL "https://fonts.gstatic.com/s/inter/v18/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1pL7.woff2" -o static/fonts/inter-600.woff2 && \
    curl -sL "https://fonts.gstatic.com/s/inter/v18/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa25L7.woff2" -o static/fonts/inter-700.woff2 && \
    curl -sL "https://fonts.gstatic.com/s/inter/v18/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa0ZL7.woff2" -o static/fonts/inter-900.woff2 && \
    curl -sL "https://fonts.gstatic.com/s/jetbrainsmono/v21/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjPVmUsaaDhw.woff2" -o static/fonts/jetbrains-mono-400.woff2 && \
    curl -sL "https://fonts.gstatic.com/s/jetbrainsmono/v21/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjDlmUsaaDhw.woff2" -o static/fonts/jetbrains-mono-700.woff2

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
