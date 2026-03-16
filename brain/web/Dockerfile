FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

EXPOSE 5173

CMD ["sh", "-c", "if [ ! -d node_modules/tailwindcss ]; then npm install; fi && npx vite --host"]
