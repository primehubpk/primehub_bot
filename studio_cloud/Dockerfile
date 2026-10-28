FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.py ./server.py
RUN useradd -m -u 10001 app && mkdir -p /tmp/primehub-film-studio && chown -R app:app /tmp/primehub-film-studio /app
USER app
ENV PYTHONUNBUFFERED=1 PORT=10000
EXPOSE 10000
CMD ["python","server.py"]
