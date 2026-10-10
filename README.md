# Webhook Integration Hub for Odoo 17 & 18/19

[![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20%7C%2018.0%20%7C%2019.0-714B67?logo=odoo)](https://www.odoo.com/)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)

A production-grade inbound webhook ingestion engine for Odoo. Designed to connect external platforms (Salesforce Outbound Messages / Platform Events, Stripe, ChargeOver, Shopify, or custom microservices) reliably and defensively.

---

## Key Features

1. **Enterprise Security & Signature Verification**
   - **HMAC-SHA256**: Constant-time comparison (`hmac.compare_digest`) preventing timing attacks. Compatible with Stripe, GitHub, and Shopify signature schemes.
   - **Bearer Token / API Key**: For standard microservice authentication.
   - Configurable signature header names.

2. **Guaranteed At-Most-Once Delivery (Idempotency)**
   - Deduplication by HTTP Header (`X-Idempotency-Key`) or dot-notation JSON body field (`event_id`, `id`).
   - Database-level unique constraint (`unique(endpoint_id, idempotency_key)`). Duplicate payloads return `200 OK (duplicate_ignored)` without duplicate side-effects.

3. **Resilience & Dead Letter Queue (DLQ)**
   - Sync or Async ingestion modes: Synchronous for immediate feedback, or Asynchronous (`202 Accepted`) queued for background cron workers.
   - Automatic retry scheduling with **exponential backoff** (`2^retry_count * 60s`).
   - Events reaching `max_retries` automatically transition to `dead_letter` status for manual intervention.

4. **Complete Audit Logging & Observability**
   - Logs client IP, HTTP headers, raw payload, execution time in milliseconds, HTTP response codes, and Python exception tracebacks.
   - Native Odoo UI views with status badges, filters, and manual "Retry Now" actions.

---

## Architecture Overview

```
External System (Salesforce / Stripe / etc.)
        │
        ▼ POST /api/v1/webhook/<endpoint_slug>
┌────────────────────────────────────────────────────────┐
│ WebhookReceiverController                             │
│  ├─ 1. Authenticate (HMAC-SHA256 / Bearer)            │
│  ├─ 2. Extract Idempotency Key                        │
│  └─ 3. Deduplicate check                              │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ webhook.event (Audit Record created)                   │
├────────────────────────────────────────────────────────┤
│ If Sync:                                               │
│   ├─ Dispatch to Target Model Handler Method           │
│   └─ On error: calculate backoff, schedule retry       │
│ If Async:                                              │
│   ├─ Return HTTP 202 Accepted immediately              │
│   └─ Processed by ir.cron worker                       │
└────────────────────────────────────────────────────────┘
```

---

## Installation & Setup

1. Copy the `webhook_hub` folder into your Odoo addons path.
2. Update the Apps list in Odoo Developer Mode (`Settings > Update Apps List`).
3. Search for **Webhook Integration Hub** (`webhook_hub`) and click **Install**.

---

## Example: Connecting Salesforce to Odoo

### 1. Configure the Endpoint in Odoo
Navigate to **Webhook Hub > Configuration > Endpoints** and create an endpoint:
* **Name**: `Salesforce Contact Outbound`
* **Slug**: `salesforce-contacts`
* **Auth Method**: `HMAC-SHA256` (or `Bearer Token`)
* **Secret Key**: `your_shared_secret_key`
* **Target Model**: `res.partner`
* **Handler Method**: `process_salesforce_webhook`
* **Processing Mode**: `Synchronous` (or `Asynchronous`)

The endpoint is now live at:
```text
https://your-odoo-domain.com/api/v1/webhook/salesforce-contacts
```

### 2. Implement the Handler Method in Your Custom Addon
In your custom addon, add the method to the target model:

```python
from odoo import models
import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def process_salesforce_webhook(self, event):
        """Called automatically by webhook_hub upon receiving an event."""
        payload = event.get_parsed_payload()
        sf_id = payload.get('Id')
        name = payload.get('Name')
        email = payload.get('Email')

        existing = self.search([('ref', '=', sf_id)], limit=1)
        if existing:
            existing.write({'name': name, 'email': email})
        else:
            self.create({'name': name, 'email': email, 'ref': sf_id})
```

---

## Testing with cURL

### Send a Valid Webhook with HMAC-SHA256:
```bash
BODY='{"id": "evt_1001", "name": "Acme Corp", "email": "contact@acme.com"}'
SECRET="your_shared_secret_key"
SIGNATURE=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')

curl -X POST https://your-odoo-domain.com/api/v1/webhook/salesforce-contacts \
  -H "Content-Type: application/json" \
  -H "X-Signature-SHA256: $SIGNATURE" \
  -H "X-Idempotency-Key: evt_1001" \
  -d "$BODY"
```

---

## Running Unit Tests

Execute the test suite using standard Odoo test runners:

```bash
odoo-bin -c /etc/odoo.conf -d test_db -u webhook_hub --test-enable --stop-after-init
```

---

## Author

**Raouf Ben Hassine**  
Salesforce & Python / Odoo Developer  
Website: [rbenhassine.com](https://rbenhassine.com) · [LinkedIn](https://www.linkedin.com/in/rbenhassine/) · [GitHub](https://github.com/rbenhassine2)
