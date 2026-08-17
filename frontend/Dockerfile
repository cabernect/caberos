# CaberOS frontend — multi-stage: build with Node, serve with nginx
# Build from repo root:  docker build -f frontend/Dockerfile -t caberos-frontend .

# Stage 1: Build the React app
FROM node:22-slim AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Build the frontend — VITE_API_BASE_URL is empty so the frontend uses
# same-origin requests (nginx proxies /api and /health to the backend)
RUN npm run build

# Stage 2: Serve static files with nginx
FROM nginx:alpine

# Copy built static assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
