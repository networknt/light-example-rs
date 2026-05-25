# syntax=docker/dockerfile:1
FROM rust:1.94.1-bookworm AS builder

ARG APP_NAME
ARG APP_DIR

RUN apt-get update && \
    apt-get install -y --no-install-recommends musl-tools pkg-config && \
    rm -rf /var/lib/apt/lists/* && \
    rustup target add x86_64-unknown-linux-musl

WORKDIR /usr/src

COPY light-fabric/ light-fabric/
COPY light-example-rs/ light-example-rs/

WORKDIR /usr/src/light-example-rs

RUN cargo build --locked --release --target x86_64-unknown-linux-musl --bin "${APP_NAME}" && \
    cp "target/x86_64-unknown-linux-musl/release/${APP_NAME}" /tmp/service && \
    mkdir -p /tmp/config && \
    cp -R "${APP_DIR}/config/." /tmp/config/

FROM debian:bookworm-slim

ARG PORT=8080

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    groupadd --system app && \
    useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app && \
    mkdir -p /app/config /app/config-cache && \
    chown -R app:app /app && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder --chown=app:app /tmp/service /app/service
COPY --from=builder --chown=app:app /tmp/config/ /app/config/

ENV CUSTOMER_PROFILE_CONFIG_DIR=/app/config
ENV CUSTOMER_PROFILE_EXTERNAL_CONFIG_DIR=/app/config-cache
ENV OFFER_DECISION_CONFIG_DIR=/app/config
ENV OFFER_DECISION_EXTERNAL_CONFIG_DIR=/app/config-cache

EXPOSE ${PORT}

USER app:app
CMD ["/app/service"]
