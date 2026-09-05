# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS frontend

WORKDIR /build
COPY control-ui/package.json control-ui/package-lock.json ./
RUN npm ci
COPY control-ui/index.html control-ui/vite.config.js ./
COPY control-ui/src ./src
RUN npm run build

FROM docker:28-cli AS runtime

RUN apk add --no-cache nodejs

WORKDIR /opt/omegaclaw-control
COPY control-ui/server.mjs ./server.mjs
COPY --from=frontend /build/dist ./dist
COPY compose.yaml /opt/omegaclaw/compose.yaml

ENV NODE_ENV=production \
    PORT=3210 \
    COMPOSE_FILE=/opt/omegaclaw/compose.yaml \
    COMPOSE_PROJECT_NAME=omegaclaw

EXPOSE 3210

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3210/api/health >/dev/null || exit 1

ENTRYPOINT ["node", "server.mjs"]
