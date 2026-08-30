FROM node:20-alpine

WORKDIR /srv/apps/web

RUN chown node:node /srv/apps/web

USER node

COPY --chown=node:node apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY --chown=node:node apps/web .

RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
