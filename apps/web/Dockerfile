FROM node:20-alpine

WORKDIR /app

COPY apps/web/package*.json /app/

RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY apps/web /app

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
