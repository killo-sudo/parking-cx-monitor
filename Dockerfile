# parking-cx-monitor — Cloud Run 이미지 (@socar.kr 로그인 게이트 + docs/ 정적 서빙)
# 빌드 컨텍스트 = 레포 루트 (docs/ 포함 위해). 배포: gcloud run deploy --source .
FROM node:20-slim

WORKDIR /app

# 의존성 먼저 (레이어 캐시)
COPY cloudrun/package.json ./package.json
RUN npm install --omit=dev

# 서버 + 정적 사이트
COPY cloudrun/server.js ./server.js
COPY docs ./docs

ENV PORT=8080
EXPOSE 8080
CMD ["node", "server.js"]
