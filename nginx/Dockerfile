FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx git fcgiwrap \
    && rm -rf /var/lib/apt/lists/*
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["sh", "-c", "fcgiwrap -s unix:/var/run/fcgiwrap.socket & sleep 1 && nginx -g 'daemon off;'"]
