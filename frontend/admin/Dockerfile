FROM node:20-alpine

ENV TZ=Asia/Taipei
RUN apk add --no-cache tzdata nginx supervisor
WORKDIR /app

COPY package*.json ./
RUN npm install

COPY nginx/ /etc/nginx/http.d/
COPY supervisord.conf /etc/supervisord.conf

EXPOSE 80 5173

CMD ["supervisord", "-c", "/etc/supervisord.conf"]
