FROM node:20-alpine

WORKDIR /srv/apps/web

COPY apps/web/package.json apps/web/package-lock.json ./

RUN npm ci --no-audit --no-fund

COPY apps/web .

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
