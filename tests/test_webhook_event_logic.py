from odoo.tests.common import TransactionCase


class TestWebhookEventLogic(TransactionCase):
    def setUp(self):
        super().setUp()
        self.endpoint = self.env['webhook.endpoint'].create(
            {
                'name': 'Test Outbound Salesforce',
                'code': 'sf-test-sync',
                'auth_type': 'bearer',
                'secret_key': 'secret_token_123',
                'process_mode': 'sync',
                'max_retries': 3,
            },
        )

    def test_01_event_creation_and_naming(self):
        event = self.env['webhook.event'].create(
            {
                'endpoint_id': self.endpoint.id,
                'idempotency_key': 'msg_001',
                'payload_raw': '{"event": "lead_created", "lead_id": 99}',
            },
        )
        self.assertIn('sf-test-sync', event.display_name)
        self.assertIn('msg_001', event.display_name)
        self.assertEqual(event.state, 'pending')

    def test_02_idempotency_uniqueness_constraint(self):
        self.env['webhook.event'].create(
            {
                'endpoint_id': self.endpoint.id,
                'idempotency_key': 'idemp_key_unique',
                'payload_raw': '{"data": 1}',
            },
        )
        with self.assertRaises(Exception):  # ruff: ignore[BLE001]
            # Duplicate key on same endpoint must raise an integrity error
            self.env['webhook.event'].create(
                {
                    'endpoint_id': self.endpoint.id,
                    'idempotency_key': 'idemp_key_unique',
                    'payload_raw': '{"data": 2}',
                },
            )

    def test_03_retry_exponential_backoff(self):
        # Configure endpoint pointing to nonexistent method to simulate failure
        ir_model_partner = self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
        self.endpoint.write(
            {
                'target_model_id': ir_model_partner.id,
                'handler_method': 'non_existent_handler_function_test',
                'max_retries': 2,
            },
        )

        event = self.env['webhook.event'].create(
            {
                'endpoint_id': self.endpoint.id,
                'idempotency_key': 'retry_test_01',
                'payload_raw': '{"account": "Acme Corp"}',
            },
        )

        # 1st attempt failure
        event.process_event()
        self.assertEqual(event.state, 'failed')
        self.assertEqual(event.retry_count, 1)
        self.assertTrue(event.next_retry_time)
        self.assertTrue(event.error_message)

        # 2nd attempt failure -> reaches max_retries
        event.process_event()
        self.assertEqual(event.state, 'dead_letter')
        self.assertEqual(event.retry_count, 2)
