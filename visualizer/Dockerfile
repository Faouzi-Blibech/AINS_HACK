# Cassette Visualizer - frontend image (multi-stage build)
# Stage 1: build the Vite app.
# Stage 2: serve the static output with nginx on port 80.

# --- Build stage ---
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

# VITE_API_URL is baked in at build time by Vite.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL

COPY . .

RUN npm run build

# --- Serve stage ---
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
