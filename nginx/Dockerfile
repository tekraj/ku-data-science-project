FROM node:20-alpine AS frontend-builder

WORKDIR /app/dashboard
COPY dashboard/package.json ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-builder /app/dashboard/dist/ /usr/share/nginx/html/
EXPOSE 80
