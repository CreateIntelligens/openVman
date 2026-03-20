FROM node:20-alpine

RUN apk add --no-cache nginx supervisor
WORKDIR /app

COPY package*.json ./
RUN npm install

COPY nginx/ /etc/nginx/conf.d/
COPY supervisord.conf /etc/supervisord.conf

EXPOSE 80 5173

CMD ["supervisord", "-c", "/etc/supervisord.conf"]
