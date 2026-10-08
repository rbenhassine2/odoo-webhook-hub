import hashlib
import hmac
import json

from odoo.tests.common import HttpCase


class TestWebhookController(HttpCase):
    def setUp(self):
        super().setUp()
        self.secret = 'super_secret_hmac_key_999'
        self.endpoint = self.env['webhook.endpoint'].create(
            {
                'name': 'Stripe Charge Webhook',
                'code': 'stripe-charges',
                'auth_type': 'hmac_sha256',
                'secret_key': self.secret,
                'signature_header': 'X-Signature-SHA256',
                'idempotency_header': 'X-Idempotency-Key',
                'process_mode': 'sync',
            },
        )

    def test_01_missing_signature_rejected(self):
        response = self.url_open(
            '/api/v1/webhook/stripe-charges',
            data=b'{"charge_id": "ch_123"}',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 401)
        res_json = response.json()
        self.assertIn('Missing signature header', res_json.get('error', ''))

    def test_02_valid_hmac_and_idempotency_dedup(self):
        payload = json.dumps({"charge_id": "ch_123", "amount": 5000}).encode('utf-8')
        signature = hmac.new(self.secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()

        headers = {
            'Content-Type': 'application/json',
            'X-Signature-SHA256': signature,
            'X-Idempotency-Key': 'idemp_txn_456',
        }

        # First request -> Successful (200)
        res1 = self.url_open('/api/v1/webhook/stripe-charges', data=payload, headers=headers)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json().get('status'), 'success')

        # Duplicate request with same idempotency key -> Ignored duplicate (200 with notice)
        res2 = self.url_open('/api/v1/webhook/stripe-charges', data=payload, headers=headers)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json().get('status'), 'duplicate_ignored')
