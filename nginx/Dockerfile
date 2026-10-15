FROM node:20-alpine AS frontend-builder

WORKDIR /app/dashboard

# Use the repo's lockfile and install dependencies before copying the whole app.
# This keeps Docker cache warm and avoids re-resolving packages on every code change.
COPY dashboard/package.json dashboard/pnpm-lock.yaml ./
RUN corepack enable \
    && corepack prepare pnpm@9 --activate \
    && pnpm install --frozen-lockfile --prefer-offline

COPY dashboard/ ./
RUN pnpm run build

FROM nginx:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-builder /app/dashboard/dist/ /usr/share/nginx/html/
EXPOSE 80
