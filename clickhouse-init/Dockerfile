FROM curlimages/curl:8.7.1

USER root
RUN apk add --no-cache bash
USER 1000:1000

WORKDIR /app

COPY . .

ENV SQL_DIR=/app/clickhouse_scripts

ENTRYPOINT ["/bin/bash", "./init-clickhouse.sh"]