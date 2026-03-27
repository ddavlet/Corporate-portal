FROM node:22-slim

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Create app directory for the webhook server
WORKDIR /webhook

# Copy and install webhook server dependencies
COPY package.json .
RUN npm install

COPY server.js .

EXPOSE 3001

CMD ["node", "server.js"]
