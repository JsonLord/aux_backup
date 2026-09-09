FROM node:24-slim
WORKDIR /app
COPY services/eyeson-worker/node/package*.json ./
RUN npm install --omit=dev
COPY services/eyeson-worker/node/src ./src
RUN npm run check
CMD ["npm", "start"]
