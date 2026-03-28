FROM node:22-slim

# Install Claude Code globally (pinned for runtime stability in headless Docker)
RUN npm install -g @anthropic-ai/claude-code@2.0.88

# Create app directory for the webhook server
WORKDIR /webhook

# Copy and install webhook server dependencies
COPY package.json .
RUN npm install

COPY server.js .
RUN chown -R node:node /webhook && chmod -R u+rwX,go+rX /webhook

EXPOSE 3001

USER node

CMD ["node", "server.js"]
