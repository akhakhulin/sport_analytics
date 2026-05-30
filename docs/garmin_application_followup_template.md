# Garmin Developer Program — заявка и follow-up

Этот документ — справочник для подачи и сопровождения заявки в **Garmin Connect
Developer Program** (получение OAuth-доступа к Health API + Activity API).

## Куда подавать

https://developer.garmin.com/gc-developer-program/overview/ → «Get Started»

Срок рассмотрения: **3-5 рабочих дней** (по их FAQ).

## Краткое описание (для поля Application Description)

```
BeatMetrics is a web-based training analytics platform for endurance athletes
(running, cycling, cross-country skiing) and their coaches. It transforms
Garmin Connect activity, heart-rate, sleep, HRV, and recovery data into
actionable visualizations: weekly training load, heart-rate zone distribution,
plan vs. actual comparison, recovery trends, and seasonal periodization
analysis.

Use case:
  1. Athletes connect their Garmin Connect account via OAuth (read-only).
  2. The Garmin Health API pushes new activities and daily summaries to our
     webhook within seconds of the athlete syncing their device.
  3. Activities are analyzed against the athlete's planned training schedule
     and personal heart-rate zones (LT2, HRmax) to compute compliance and
     fatigue metrics.
  4. The athlete sees a personal dashboard. With explicit consent, their
     designated coach also receives access.

Data handling:
  - Read-only access. We do not modify, upload, or delete any data in the
     athlete's Garmin Connect account.
  - Data is stored encrypted at rest in our own database.
  - No third-party sharing. Data is never sold or used for advertising.
  - The athlete can revoke access and request full data deletion at any
     time from in-app settings.
  - We comply with GDPR and Russian Federal Law 152-FZ on personal data.

Initial scope: small private beta (5-20 athletes coached by the founder).
Public launch planned mid-2026 after Garmin approval and full UX polish.

The founder is a KMS-level cross-country skier and runner who built this
to analyze his own training; expanding to coach a small group of fellow
amateur and semi-pro athletes.
```

## Короткий вариант (если поле лимитировано)

```
Multi-tenant training analytics dashboard for endurance athletes and their
coaches. Read-only Garmin Connect integration via Health + Activity APIs.
Visualizes training load, HR zones, recovery, plan compliance.
Initial scale: 5-50 athletes, coached privately by the founder.
```

## Follow-up email template (если Garmin запросит уточнения)

```
Subject: Re: Garmin Developer Program application — BeatMetrics

Dear Garmin Developer Relations team,

Thank you for reviewing my application for the Garmin Connect Developer
Program. I'm happy to provide any additional information needed.

To clarify the questions raised:

[пункт 1 — ответ на их вопрос]
[пункт 2 — ответ на их вопрос]

To recap the project briefly:
- BeatMetrics is a personal-scale training analytics platform for endurance
  athletes. The founder (myself) is a competitive cross-country skier and
  runner; the platform was built to analyze my own training and is now being
  extended to a small group of fellow athletes (5-20) whom I coach privately.
- We request the Health API and Activity API to access activity files,
  heart-rate streams, sleep, HRV, recovery, and Body Battery data — strictly
  read-only.
- All access is via OAuth, with athletes giving explicit consent. We do not
  store Garmin credentials; only OAuth refresh tokens (encrypted).
- We are a small private beta currently; no commercial offering is planned
  before mid-2026.

Please let me know if you need anything else to move the application forward.

Best regards,
Artem Khakhulin
a.khakhulin89@gmail.com
```

## Поля заявки — что куда

| Поле формы | Значение |
|---|---|
| First Name | Artem |
| Last Name | Khakhulin |
| Email | a.khakhulin89@gmail.com |
| Country | Russia |
| Company / Organization | BeatMetrics (individual developer, planning to incorporate) |
| Company website | https://beatmetrics.ru |
| Application Name | BeatMetrics |
| Application Type | Web application |
| Platform | Web / Backend |
| APIs requested | **Health API** + **Activity API** (обе галочки) |
| Estimated user count (year 1) | 50-200 |
| Estimated user count (year 3) | 1000-5000 |
| Privacy Policy URL | https://beatmetrics.ru/privacy |
| Terms of Service URL | https://beatmetrics.ru/terms |

## Что делать после получения approval

1. В Garmin Connect Developer Portal получаешь **Consumer Key** и **Consumer Secret** (OAuth 1.0a в случае Garmin Health legacy, либо OAuth 2.0 client_id/secret в новой версии).
2. Регистрируешь callback URL: `https://beatmetrics.ru/oauth/garmin/callback` (потребует HTTPS — должны быть готовы Phase C: nginx + TLS).
3. Регистрируешь Webhook URL для push-данных: `https://beatmetrics.ru/webhooks/garmin`.
4. Тестируешь в sandbox.
5. Переключаешь в production.
