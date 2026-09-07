FROM node:24-alpine AS build
RUN corepack enable
WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/contracts ./packages/contracts
COPY apps/web ./apps/web
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @lifereel/web build

FROM nginx:1.27-alpine
COPY apps/web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /workspace/apps/web/dist /usr/share/nginx/html
EXPOSE 80
