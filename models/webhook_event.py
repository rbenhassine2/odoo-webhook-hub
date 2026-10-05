import datetime
import json
import logging
import traceback

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WebhookEvent(models.Model):
    _name = 'webhook.event'
    _description = 'Inbound Webhook Event Audit Log and Queue'
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    endpoint_id = fields.Many2one(
        'webhook.endpoint',
        string='Endpoint',
        required=True,
        ondelete='cascade',
        index=True,
    )
    idempotency_key = fields.Char(
        string='Idempotency Key',
        index=True,
        copy=False,
        help="Unique key to ensure at-most-once/idempotent processing.",
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending / Queued'),
            ('processing', 'Processing'),
            ('done', 'Completed'),
            ('failed', 'Failed (Retryable)'),
            ('dead_letter', 'Dead Letter (Exhausted / Unprocessable)'),
            ('ignored', 'Ignored (Duplicate)'),
        ],
        string='Status',
        default='pending',
        required=True,
        index=True,
    )

    # Request data
    http_method = fields.Char(string='HTTP Method', default='POST')
    remote_ip = fields.Char(string='Client IP')
    headers_json = fields.Text(string='Request Headers (JSON)')
    payload_raw = fields.Text(string='Raw Payload', required=True)

    # Processing metadata
    response_code = fields.Integer(string='HTTP Response Code')
    execution_time_ms = fields.Float(string='Execution Time (ms)')
    error_message = fields.Text(string='Last Error Message')
    error_traceback = fields.Text(string='Stack Trace')

    retry_count = fields.Integer(string='Retry Count', default=0)
    next_retry_time = fields.Datetime(
        string='Next Retry Scheduled',
        index=True,
        help="Next scheduled execution timestamp calculated with exponential backoff.",
    )

    processed_date = fields.Datetime(string='Processed Timestamp')
    display_name = fields.Char(string='Name', compute='_compute_display_name', store=True)

    _sql_constraints = [
        (
            'endpoint_idempotency_unique',
            'unique(endpoint_id, idempotency_key)',
            'An event with this idempotency key already exists for this endpoint.',
        ),
    ]

    @api.depends('endpoint_id.name', 'idempotency_key', 'create_date')
    def _compute_display_name(self):
        for record in self:
            date_str = record.create_date.strftime('%Y-%m-%d %H:%M:%S') if record.create_date else ''
            key = record.idempotency_key or f"#{record.id}"
            endpoint_name = record.endpoint_id.name if record.endpoint_id else 'Unknown'
            record.display_name = f"[{endpoint_name}] {key} ({date_str})"

    def get_parsed_payload(self):
        """Helper to parse the raw json payload safely."""
        self.ensure_one()
        if not self.payload_raw:
            return {}
        try:
            return json.loads(self.payload_raw)
        except (ValueError, TypeError):
            return {}

    def action_retry_now(self):
        """Manual trigger from the UI to retry processing immediately."""
        for record in self:
            record.process_event()

    def action_mark_dead_letter(self):
        for record in self:
            record.write({'state': 'dead_letter'})

    def action_mark_done(self):
        for record in self:
            record.write({'state': 'done', 'error_message': False, 'error_traceback': False})

    def _dispatch_handler(self, endpoint):
        """Helper to locate and invoke target handler."""
        if not (endpoint.target_model_id and endpoint.handler_method):
            _logger.info("No handler configured for endpoint %s; event marked as completed.", endpoint.code)
            return

        model_name = endpoint.target_model_id.model
        if model_name not in self.env:
            raise UserError(f"Model '{model_name}' is not found in the environment registry.")

        handler_model = self.env[model_name]
        if not hasattr(handler_model, endpoint.handler_method):
            raise UserError(
                f"Target model '{model_name}' does not implement method '{endpoint.handler_method}'.",
            )

        handler_func = getattr(handler_model, endpoint.handler_method)
        handler_func(self)

    def process_event(self):
        """Core execution logic with error catching, timing and state transition."""
        self.ensure_one()
        start_time = datetime.datetime.now()
        endpoint = self.endpoint_id

        self.write(
            {
                'state': 'processing',
                'retry_count': self.retry_count + 1,
            },
        )

        try:
            self._dispatch_handler(endpoint)
            duration = (datetime.datetime.now() - start_time).total_seconds() * 1000.0
            self.write(
                {
                    'state': 'done',
                    'execution_time_ms': duration,
                    'processed_date': fields.Datetime.now(),
                    'error_message': False,
                    'error_traceback': False,
                    'next_retry_time': False,
                },
            )
            return True

        except Exception as exc:
            duration = (datetime.datetime.now() - start_time).total_seconds() * 1000.0
            tb = traceback.format_exc()
            _logger.exception("Failed processing webhook event %s on endpoint %s", self.id, endpoint.code)

            new_state = 'failed'
            next_retry = False

            if self.retry_count >= endpoint.max_retries:
                new_state = 'dead_letter'
            else:
                # Exponential backoff: 2^retry_count * 60 seconds (2m, 4m, 8m, 16m...)
                backoff_seconds = (2**self.retry_count) * 60
                next_retry = fields.Datetime.now() + datetime.timedelta(seconds=backoff_seconds)

            self.write(
                {
                    'state': new_state,
                    'execution_time_ms': duration,
                    'error_message': str(exc),
                    'error_traceback': tb,
                    'next_retry_time': next_retry,
                },
            )
            return False

    @api.model
    def cron_process_pending_and_retries(self, batch_size=50):
        """Scheduled action to process queued async events and scheduled retries."""
        now = fields.Datetime.now()
        domain = [
            '|',
            '&',
            ('state', '=', 'pending'),
            ('endpoint_id.process_mode', '=', 'async'),
            '&',
            ('state', '=', 'failed'),
            ('next_retry_time', '<=', now),
        ]
        records = self.search(domain, order='create_date asc', limit=batch_size)
        _logger.info("Cron found %s webhook events to process/retry.", len(records))

        for rec in records:
            # Using savepoint to ensure one event failure does not rollback the whole cron transaction
            try:
                with self.env.cr.savepoint():
                    rec.process_event()
            except Exception as e:  # ruff: ignore[blind-except]
                _logger.error("Unhandled exception during cron batch processing of event %s: %s", rec.id, e)
