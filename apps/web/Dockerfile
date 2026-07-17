FROM node:22.17.1-alpine AS build
ARG MAX_UPLOAD_BYTES=104857600
ENV VITE_MAX_UPLOAD_BYTES=$MAX_UPLOAD_BYTES
RUN corepack enable && corepack prepare pnpm@10.33.2 --activate
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/api-client/package.json ./packages/api-client/package.json
RUN pnpm install --frozen-lockfile --filter @novel-platform/web...
COPY apps/web ./apps/web
COPY packages/api-client ./packages/api-client
WORKDIR /workspace/apps/web
RUN pnpm build

FROM nginx:1.27.5-alpine
ARG MAX_UPLOAD_BYTES=104857600
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
RUN case "$MAX_UPLOAD_BYTES" in ''|*[!0-9]*) exit 1 ;; esac \
    && test "$MAX_UPLOAD_BYTES" -ge 1 \
    && test "$MAX_UPLOAD_BYTES" -le 2147483647 \
    && client_max_body_size=$((MAX_UPLOAD_BYTES + 1048576)) \
    && sed -i "s/__MAX_UPLOAD_BODY_BYTES__/${client_max_body_size}/" \
        /etc/nginx/conf.d/default.conf \
    && ! grep -q '__MAX_UPLOAD_BODY_BYTES__' /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/web/dist /usr/share/nginx/html
EXPOSE 80
