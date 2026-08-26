FROM node:24-slim
WORKDIR /app
COPY services/journey-worker/node/package*.json ./
COPY services/journey-worker/node/src ./src
RUN npm run check
CMD ["npm", "start"]
