FROM node:20-alpine

WORKDIR /srv

COPY apps/web /srv/apps/web
WORKDIR /srv/apps/web
RUN npm install && npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
