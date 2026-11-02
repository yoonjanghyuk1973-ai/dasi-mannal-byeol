FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk fontconfig && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.py ./
COPY static ./static
COPY fonts ./fonts
RUN mkdir -p uploads videos orig
ENV PORT=10000
CMD ["python","server.py"]
