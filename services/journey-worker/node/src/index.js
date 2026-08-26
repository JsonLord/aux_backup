/** PLACEHOLDER worker process until JourneyTest hooks are integrated in Stage 4. */
const http = require("node:http");
const server = http.createServer((request, response) => {
  response.setHeader("content-type", "application/json");
  response.end(JSON.stringify({ service: "journey-worker", status: "placeholder", journeyTestIntegrated: false }));
});
server.listen(Number(process.env.PORT || 8080), "0.0.0.0");
