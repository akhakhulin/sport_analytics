# Google Sign-In: получение OAuth credentials

Код для Google Sign-In готов (`signup_service/auth_google.py`), но **выключен**
пока в `.env` не положены `GOOGLE_CLIENT_ID` и `GOOGLE_CLIENT_SECRET`. Пока их
нет, кнопка «Продолжить с Google» не отображается на /signup и /login
(контролируется через `auth_google.is_configured()`).

## Шаги для получения credentials (15 минут)

1. **Google Cloud Console** → https://console.cloud.google.com/
   - Войти gmail-аккаунтом (любым, рекомендую тот что для BeatMetrics)
   - Создать новый проект: «BeatMetrics Auth» (или использовать существующий)

2. **OAuth Consent Screen** (если ещё не настроен)
   - APIs & Services → OAuth consent screen
   - User type: **External**
   - App name: `BeatMetrics`
   - User support email: `a.khakhulin89@gmail.com`
   - App logo: загрузить `docs/Beatmetrics_logo/icon-1024.png`
   - Authorized domain: `beatmetrics.ru`
   - Developer contact: `a.khakhulin89@gmail.com`
   - Scopes (стандартные, оставить по умолчанию): `openid`, `email`, `profile`
   - Test users: добавить свой email пока в Testing-режиме
   - Когда готов к production — нажать «Publish app» (требует app verification
     при scope чтении/записи Drive/Gmail; для openid+email+profile не нужна)

3. **Создать OAuth Client ID**
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: **Web application**
   - Name: `BeatMetrics Web Client`
   - **Authorized JavaScript origins**:
     - `https://app.beatmetrics.ru`
     - `http://127.0.0.1:8502` (для локального dev — необязательно)
   - **Authorized redirect URIs**:
     - `https://app.beatmetrics.ru/auth/google/callback`
     - `http://127.0.0.1:8502/auth/google/callback` (для локального dev)
   - Create → получишь `Client ID` (длинный с `.apps.googleusercontent.com`)
     и `Client Secret` (начинается на `GOCSPX-`)

4. **Положить в `.env`** (файл `c:\Claude_Projects\garmin_analytics\.env`)
   ```
   GOOGLE_CLIENT_ID=123456789012-abc...xyz.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-...
   ```
   (Если нужно переопределить redirect base — добавить
   `GOOGLE_REDIRECT_BASE=https://app.beatmetrics.ru`; обычно не требуется,
   код берёт из `request.base_url`.)

5. **Перезапустить signup_service**
   ```
   schtasks /End /TN GarminAtomik-SignupService
   schtasks /Run /TN GarminAtomik-SignupService
   ```

После этого:
- На `https://app.beatmetrics.ru/signup` и `/login` появится кнопка
  «Продолжить с Google» сверху формы
- Клик → редирект на Google consent → callback `/auth/google/callback`
- Если email уже есть в `users` — log in
- Если нет — создаётся новый user (role=athlete, email_verified_at=now,
  password — рандомный, для входа не используется)

## Что код уже умеет

- `signup_service/auth_google.py` — OAuth flow через `authlib`
- `signup_service/main.py` — подключён `SessionMiddleware` (нужен authlib)
  + `app.include_router(auth_google.router)`
- `signup_service/templates/{signup,login}.html` — кнопки с SVG-лого Google,
  divider «или email» под ней
- Граничные случаи обработаны: `email_not_verified`, `state_mismatch`,
  `no_code`, `token_exchange:*` — все идут на `/login?google_error=...`

## Что НЕ сделано (вне scope)

- Apple Sign-In: требует Apple Developer Account ($99/год) и JWT-подписи —
  отложено в P2
- Привязка существующего email-аккаунта к Google (account linking):
  сейчас если пользователь регался через email/password, а потом пришёл
  через Google с тем же email — он залогинится, но password останется
  старым. Можно потом добавить «You can also log in via Google» в Settings.
