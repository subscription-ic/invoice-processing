# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Frontend image — Vite/React build served by nginx.
# Build context = frontend/  ->  docker build -f frontend/Dockerfile -t <tag> ./frontend
#
# VITE_API_URL is baked in at BUILD time (Vite inlines import.meta.env.*).
# Pass the backend's public URL, e.g.:
#   --build-arg VITE_API_URL=https://invoice-backend.<region>.azurecontainerapps.io
# Leave empty for same-origin (only works if something proxies /api to the backend).
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- Runtime: nginx serving the static SPA ----
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
