FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
# 127.0.0.1, not localhost: nginx listens IPv4-only (see nginx.conf), but
# this image's wget resolves "localhost" to ::1 first and never falls back,
# so a hostname-based check reports unhealthy despite the server working
# fine (confirmed live: the exact same request succeeds against 127.0.0.1
# and fails with "connection refused" against localhost, from inside this
# same container).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000/ || exit 1
