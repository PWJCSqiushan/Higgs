ARG NODE_IMAGE
FROM ${NODE_IMAGE}

WORKDIR /opt/higgs-official-qq

COPY package.json package-lock.json ./
RUN npm ci --omit=optional --ignore-scripts \
    && npm cache clean --force

COPY src ./src

USER 10001:10001

CMD ["node", "src/index.mjs"]
