FROM node:22-alpine AS build
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /web
COPY apps/web-dashboard/package.json apps/web-dashboard/package-lock.json ./
RUN npm ci --registry="${NPM_REGISTRY}"
COPY apps/web-dashboard ./
RUN npm run build

FROM nginx:1.27-alpine
COPY deployment/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD wget -q -O - http://127.0.0.1/healthz || exit 1
