/* =====================================================================
 *  parking-cx-monitor — Cloud Run 서버
 *  @socar.kr Google 로그인 뒤에서 docs/ 정적 사이트(CSAT 리포트·GAZETTE)를 서빙.
 *  GitHub Pages(공개)를 대체하는 서버측 접근통제판.
 *
 *  인증: 서버측 OAuth + hd===socar.kr 검증(클라이언트 우회 불가).
 *  정적 파일은 로그인 세션 없으면 절대 안 나감.
 *
 *  ── 환경변수 (Cloud Run) ──────────────────────────────
 *    GOOGLE_CLIENT_ID       OAuth 클라이언트 ID
 *    GOOGLE_CLIENT_SECRET   OAuth 클라이언트 보안 비밀 (Secret Manager 권장)
 *    OAUTH_REDIRECT_URL     https://<run주소>/auth/callback
 *    SESSION_SECRET         임의 랜덤 문자열 (Secret Manager 권장)
 *    PORT                   Cloud Run이 자동 주입
 * ===================================================================== */
'use strict';

const path = require('path');
const express = require('express');
const cookieSession = require('cookie-session');
const { OAuth2Client } = require('google-auth-library');

const app = express();
app.set('trust proxy', 1); // Cloud Run 프록시 뒤 → secure 쿠키 인식

const ALLOWED_DOMAIN = 'socar.kr';
const DOCS_DIR = path.join(__dirname, 'docs'); // 이미지에 복사된 정적 사이트

const CLIENT_ID = process.env.GOOGLE_CLIENT_ID || '';
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET || '';
const REDIRECT_URL = process.env.OAUTH_REDIRECT_URL || '';
const oauthConfigured = !!(CLIENT_ID && CLIENT_SECRET && REDIRECT_URL);
const oauth = oauthConfigured
  ? new OAuth2Client(CLIENT_ID, CLIENT_SECRET, REDIRECT_URL)
  : null;

// 헬스체크(인증 없이) — Cloud Run 기동 확인용
app.get('/healthz', (_req, res) => res.status(200).send('ok'));

app.use(cookieSession({
  name: 'modu_sess',
  secret: process.env.SESSION_SECRET || 'change-me-please',
  httpOnly: true,
  sameSite: 'lax',
  secure: true,
  maxAge: 12 * 60 * 60 * 1000, // 12시간
}));

// ── 로그인 시작 ──────────────────────────────────────
app.get('/auth/login', (req, res) => {
  if (!oauthConfigured) {
    return res.status(503).send(
      'OAuth 미설정: GOOGLE_CLIENT_ID/SECRET/OAUTH_REDIRECT_URL 환경변수를 설정해야 합니다.');
  }
  const url = oauth.generateAuthUrl({
    scope: ['openid', 'email', 'profile'],
    hd: ALLOWED_DOMAIN,
    prompt: 'select_account',
  });
  res.redirect(url);
});

// ── 콜백: 토큰 검증 + @socar.kr 강제 ─────────────────
app.get('/auth/callback', async (req, res) => {
  if (!oauthConfigured) return res.status(503).send('OAuth 미설정');
  try {
    const { tokens } = await oauth.getToken(req.query.code);
    const ticket = await oauth.verifyIdToken({
      idToken: tokens.id_token,
      audience: CLIENT_ID,
    });
    const p = ticket.getPayload();
    const ok = p && p.email_verified && p.hd === ALLOWED_DOMAIN
      && p.email && p.email.endsWith('@' + ALLOWED_DOMAIN);
    if (!ok) {
      return res.status(403).send('접근 권한이 없습니다. @socar.kr 계정으로만 접근 가능합니다.');
    }
    req.session.user = { email: p.email, name: p.name };
    res.redirect('/');
  } catch (e) {
    res.status(401).send('로그인 실패: ' + e.message);
  }
});

app.get('/auth/logout', (req, res) => { req.session = null; res.redirect('/auth/login'); });

// ── 보호 미들웨어 (정적 서빙보다 반드시 위) ──────────
app.use((req, res, next) => {
  if (req.path === '/healthz' || req.path.startsWith('/auth/')) return next();
  const u = req.session && req.session.user;
  if (u && u.email && u.email.endsWith('@' + ALLOWED_DOMAIN)) return next();
  return res.redirect('/auth/login');
});

// ── 인증 통과 후 정적 사이트 서빙 ────────────────────
app.use(express.static(DOCS_DIR, { extensions: ['html'] }));
// 루트 → CSAT 리포트로 (원하면 GAZETTE 대시보드 index로 변경 가능)
app.get('/', (_req, res) => res.redirect('/csat/'));

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => console.log(`parking-cx-monitor cloudrun listening on ${PORT}`));
